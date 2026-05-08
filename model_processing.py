from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


MODEL_PIPELINES = {
    "Original": (),
    "YOLOv8m": ("yolov8m",),
    "Vehicle v1": ("vehicle_v1",),
    "YOLOv8m + Vehicle v1": ("yolov8m", "vehicle_v1"),
}
MODEL_PATHS = {
    "yolov8m": Path(__file__).with_name("models") / "yolov8m" / "yolov8m.pt",
    "vehicle_v1": Path(__file__).with_name("models") / "v4_vehicle_model" / "vehicle_type_v4.pt",
}
YOLO_VEHICLE_LABELS = {"car", "bus", "truck"}
YOLO_PERSON_LABELS = {"person"}
YOLO_FILTER_LABELS = YOLO_PERSON_LABELS | YOLO_VEHICLE_LABELS
YOLO_COCO_CLASS_IDS = [0, 2, 5, 7]
ANNOTATION_FONT_SIZE = 48
ANNOTATION_LABEL_PADDING_X = 18
ANNOTATION_LABEL_PADDING_Y = 12
ANNOTATION_BOX_WIDTH = 5
DETECTION_CONFIDENCE_THRESHOLD = 0.60


@dataclass(frozen=True)
class ProcessedImageResult:
    output_path: Path
    vehicle_count: int = 0
    person_count: int = 0


def sanitize_pipeline_name(pipeline_name: str) -> str:
    return pipeline_name.lower().replace(" ", "_").replace("+", "plus")


class ModelProcessor:
    def __init__(self) -> None:
        self.models: dict[str, object] = {}

    def ensure_model(self, model_key: str):
        if YOLO is None:
            raise RuntimeError("ultralytics is not installed on this device.")

        model_path = MODEL_PATHS[model_key]
        if not model_path.exists():
            raise RuntimeError(f"Model file not found: {model_path}")

        if model_key not in self.models:
            self.models[model_key] = YOLO(str(model_path))

        return self.models[model_key]

    def _refine_car_label(self, crop_image: Image.Image) -> tuple[str, float] | None:
        vehicle_model = self.ensure_model("vehicle_v1")
        results = vehicle_model.predict(source=crop_image, verbose=False)
        result = results[0]

        if getattr(result, "probs", None) is not None:
            top_index = int(result.probs.top1)
            confidence = float(result.probs.top1conf)
            label = result.names[top_index]
            return label, confidence

        if getattr(result, "boxes", None) is not None and len(result.boxes) > 0:
            best_index = int(result.boxes.conf.argmax().item())
            class_id = int(result.boxes.cls[best_index].item())
            confidence = float(result.boxes.conf[best_index].item())
            label = result.names[class_id]
            return label, confidence

        return None

    def _count_result_detections(self, result: object, model_key: str) -> tuple[int, int]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return 0, 0

        vehicle_count = 0
        person_count = 0
        for box in boxes:
            if model_key == "vehicle_v1":
                if float(box.conf.item()) < DETECTION_CONFIDENCE_THRESHOLD:
                    continue
                vehicle_count += 1
                continue

            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            if confidence < DETECTION_CONFIDENCE_THRESHOLD:
                continue

            label = str(result.names[class_id]).strip().lower()
            if label in YOLO_VEHICLE_LABELS:
                vehicle_count += 1
            elif label in YOLO_PERSON_LABELS:
                person_count += 1

        return vehicle_count, person_count

    def _predict_model(self, model_key: str, source: object) -> list[object]:
        model = self.ensure_model(model_key)
        if model_key == "yolov8m":
            return model.predict(source=source, classes=YOLO_COCO_CLASS_IDS, verbose=False)
        return model.predict(source=source, verbose=False)

    def _annotation_label_font(self):
        if ImageFont is None:
            return None

        try:
            return ImageFont.truetype("Arial.ttf", ANNOTATION_FONT_SIZE)
        except OSError:
            try:
                return ImageFont.load_default(size=ANNOTATION_FONT_SIZE)
            except TypeError:
                return ImageFont.load_default()

    def _draw_annotation(
        self,
        draw: ImageDraw.ImageDraw,
        box_coordinates: tuple[int, int, int, int],
        label: str,
        color: str,
        label_font: object,
    ) -> None:
        x1, y1, x2, y2 = box_coordinates
        draw.rectangle((x1, y1, x2, y2), outline=color, width=ANNOTATION_BOX_WIDTH)
        text_bbox = draw.textbbox((x1, y1), label, font=label_font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        box_height = text_height + (ANNOTATION_LABEL_PADDING_Y * 2)
        text_top = max(0, y1 - box_height)
        draw.rectangle(
            (
                x1,
                text_top,
                x1 + text_width + (ANNOTATION_LABEL_PADDING_X * 2),
                text_top + box_height,
            ),
            fill=color,
        )
        draw.text(
            (x1 + ANNOTATION_LABEL_PADDING_X, text_top + ANNOTATION_LABEL_PADDING_Y),
            label,
            fill="black",
            font=label_font,
        )

    def _draw_model_result(self, image_path: Path, result: object, output_path: Path, model_key: str) -> None:
        if Image is None or ImageDraw is None:
            result.save(filename=str(output_path))
            return

        source_image = Image.open(image_path).convert("RGB")
        annotated_image = source_image.copy()
        draw = ImageDraw.Draw(annotated_image)
        label_font = self._annotation_label_font()
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            annotated_image.save(output_path)
            return

        for box in boxes:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            if x2 <= x1 or y2 <= y1:
                continue

            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            if confidence < DETECTION_CONFIDENCE_THRESHOLD:
                continue

            label_name = str(result.names[class_id])
            normalized_label = label_name.strip().lower()
            if model_key == "yolov8m" and normalized_label not in YOLO_FILTER_LABELS:
                continue

            color = "lime" if model_key == "yolov8m" else "cyan"
            self._draw_annotation(
                draw,
                (x1, y1, x2, y2),
                f"{label_name} {confidence:.2f}",
                color,
                label_font,
            )

        annotated_image.save(output_path)

    def _draw_combined_pipeline(self, image_path: Path, output_path: Path) -> ProcessedImageResult:
        if Image is None or ImageDraw is None:
            raise RuntimeError("Pillow is required to build the combined model preview.")

        result = self._predict_model("yolov8m", str(image_path))[0]
        source_image = Image.open(image_path).convert("RGB")
        annotated_image = source_image.copy()
        draw = ImageDraw.Draw(annotated_image)
        label_font = self._annotation_label_font()

        if getattr(result, "boxes", None) is None:
            annotated_image.save(output_path)
            return ProcessedImageResult(output_path)

        vehicle_count = 0
        person_count = 0

        for box in result.boxes:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            if x2 <= x1 or y2 <= y1:
                continue

            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            if confidence < DETECTION_CONFIDENCE_THRESHOLD:
                continue

            base_label = result.names[class_id]
            label = f"{base_label} {confidence:.2f}"
            color = "lime"
            normalized_label = str(base_label).strip().lower()
            if normalized_label not in YOLO_FILTER_LABELS:
                continue

            if normalized_label in YOLO_VEHICLE_LABELS:
                vehicle_count += 1
            elif normalized_label in YOLO_PERSON_LABELS:
                person_count += 1

            if base_label == "car":
                crop = source_image.crop((x1, y1, x2, y2))
                refinement = self._refine_car_label(crop)
                if refinement is not None:
                    refined_label, refined_confidence = refinement
                    label = f"{refined_label} {refined_confidence:.2f}"
                    color = "cyan"

            self._draw_annotation(draw, (x1, y1, x2, y2), label, color, label_font)

        annotated_image.save(output_path)
        return ProcessedImageResult(output_path, vehicle_count, person_count)

    def process_image(self, image_path: Path, pipeline_name: str, output_directory: Path) -> ProcessedImageResult:
        pipeline = MODEL_PIPELINES[pipeline_name]
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / image_path.name

        if not pipeline:
            shutil.copy2(image_path, output_path)
            return ProcessedImageResult(output_path)

        if pipeline_name == "YOLOv8m + Vehicle v1":
            return self._draw_combined_pipeline(image_path, output_path)

        vehicle_count = 0
        person_count = 0
        with tempfile.TemporaryDirectory() as temp_dir_name:
            current_source = image_path
            temp_dir = Path(temp_dir_name)

            for index, model_key in enumerate(pipeline):
                results = self._predict_model(model_key, str(current_source))
                result = results[0]
                vehicle_count, person_count = self._count_result_detections(result, model_key)

                stage_output = output_path if index == len(pipeline) - 1 else temp_dir / f"stage_{index}_{image_path.name}"
                self._draw_model_result(current_source, result, stage_output, model_key)
                current_source = stage_output

            return ProcessedImageResult(output_path, vehicle_count, person_count)
