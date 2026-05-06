from __future__ import annotations

import importlib
import io
import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import config

try:
    import requests
except ImportError:
    requests = None

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

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


CONFIG_PATH = Path(__file__).with_name("config.json")
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
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


def ensure_directory(path_text: str) -> Path:
    image_dir = Path(path_text).expanduser()
    image_dir.mkdir(parents=True, exist_ok=True)
    return image_dir


def update_config_values(updates: dict[str, object]) -> None:
    current_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    current_config.update(updates)
    CONFIG_PATH.write_text(json.dumps(current_config, indent=2) + "\n", encoding="utf-8")
    importlib.reload(config)


def build_pi_config_payload() -> dict[str, object]:
    return {
        "client_ip": config.CLIENT_IP,
        "client_username": config.CLIENT_USERNAME,
        "image_quality": int(config.IMAGE_QUALITY),
        "image_directory": config.IMAGE_DIRECTORY,
        "image_capture_gpio_pin": config.IMAGE_CAPTURE_GPIO_PIN,
    }


def _build_pi_api_url(endpoint: str) -> str:
    base_url = config.PI_API_BASE_URL.rstrip("/") + "/"
    return urljoin(base_url, endpoint.lstrip("/"))


def _response_message(response: "requests.Response", default: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if not text:
            return default
        if "text/html" in response.headers.get("Content-Type", "").lower():
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        return text or default

    if isinstance(payload, dict):
        for key in ("message", "error", "mode"):
            value = payload.get(key)
            if value:
                return str(value)

    return default


def connect_to_pi_api() -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.get(
        config.PI_API_BASE_URL,
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    return f"Connected to Pi API at {config.PI_API_BASE_URL}."


def register_with_pi_api() -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.post(
        _build_pi_api_url(config.PI_API_REGISTER_ENDPOINT),
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Registration failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    return _response_message(response, "Registered with Pi image sender.")


def get_pi_status() -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.get(
        _build_pi_api_url(config.PI_API_STATUS_ENDPOINT),
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Status request failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            return text
        raise RuntimeError("Status endpoint did not return valid JSON.")

    camera_status = payload.get("camera_status")
    camera_mode = payload.get("camera_mode")
    image_directory = payload.get("image_directory")
    if camera_status is not None or camera_mode is not None or image_directory is not None:
        return (
            f"Camera: {camera_status or 'unknown'} | "
            f"Mode: {camera_mode or 'unknown'} | "
            f"Directory: {image_directory or 'unknown'}"
        )

    if isinstance(payload, dict) and payload:
        return " | ".join(f"{key}: {value}" for key, value in payload.items())

    return "Status retrieved."


def upload_pi_config() -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    pi_config = json.dumps(build_pi_config_payload(), indent=2).encode("utf-8")
    response = requests.post(
        _build_pi_api_url(config.PI_API_CONFIG_ENDPOINT),
        files={"file": ("received.json", io.BytesIO(pi_config), "application/json")},
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Config upload failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            upload_message = text
        else:
            upload_message = "Remote config upload complete."
    else:
        upload_message = payload.get("message", "Remote config upload complete.")

    response = requests.post(
        _build_pi_api_url(config.PI_API_SETTINGS_ENDPOINT),
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Settings update failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    settings_message = _response_message(response, "Settings updated.")
    return f"{upload_message} {settings_message}"


def upload_file_to_pi(file_path: Path) -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    if not file_path.exists():
        raise RuntimeError(f"File not found: {file_path}")

    with file_path.open("rb") as upload_file:
        response = requests.post(
            _build_pi_api_url(config.PI_API_CONFIG_ENDPOINT),
            files={"file": (file_path.name, upload_file, "application/octet-stream")},
            timeout=float(config.PI_API_TIMEOUT_SECONDS),
        )
    response.raise_for_status()
    payload = response.json()
    return payload.get("message", f"Uploaded {file_path.name}.")


def trigger_remote_capture() -> Path:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.post(
        _build_pi_api_url(config.PI_API_CAPTURE_ENDPOINT),
        stream=True,
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Capture request failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    content_type = response.headers.get("Content-Type", "").lower()
    if "application/json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("Capture endpoint returned invalid JSON.")
        raise RuntimeError(payload.get("message") or payload.get("error") or "Capture failed.")

    destination = ensure_directory(config.IMAGE_DIRECTORY) / _capture_filename_from_response(response)
    with destination.open("wb") as output_file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                output_file.write(chunk)
    return destination


def get_latest_remote_image() -> Path:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.get(
        _build_pi_api_url(config.PI_API_LATEST_IMAGE_ENDPOINT),
        stream=True,
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Latest image request failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    content_type = response.headers.get("Content-Type", "").lower()
    if "application/json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("Latest image endpoint returned invalid JSON.")
        raise RuntimeError(payload.get("message") or payload.get("error") or "Latest image request failed.")

    destination = ensure_directory(config.IMAGE_DIRECTORY) / _capture_filename_from_response(response, "latest")
    with destination.open("wb") as output_file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                output_file.write(chunk)
    return destination


def activate_remote_camera() -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    response = requests.post(
        _build_pi_api_url(config.PI_API_ACTIVATE_ENDPOINT),
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Activate request failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            return text
        return "Camera activated."

    return payload.get("message", "Camera activated.")


def set_remote_camera_mode(mode: str) -> str:
    if requests is None:
        raise RuntimeError("requests is not installed in this environment.")

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"image", "video"}:
        raise RuntimeError(f"Unsupported camera mode: {mode}")

    response = requests.post(
        _build_pi_api_url(config.PI_API_SET_MODE_ENDPOINT),
        json={"mode": normalized_mode},
        timeout=float(config.PI_API_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
    except Exception:
        message = _response_message(response, f"Set mode request failed with HTTP {response.status_code}.")
        raise RuntimeError(message)

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            return text
        raise RuntimeError("Set mode endpoint did not return valid JSON.")

    return payload.get("message", f"Camera mode set to {normalized_mode}.")

def _capture_filename_from_response(response: "requests.Response", prefix: str = "capture") -> str:
    header = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^"]+)"?', header)
    if match:
        return Path(match.group(1)).name

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = ".jpg"
    content_type = response.headers.get("Content-Type", "").lower()
    if "png" in content_type:
        suffix = ".png"
    return f"{prefix}_{timestamp}{suffix}"


def build_socket_image_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    return ensure_directory(config.IMAGE_DIRECTORY) / f"socket_capture_{timestamp}.jpg"


class ImageSocketReceiver:
    def __init__(
        self,
        on_image_received: Callable[[Path], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.on_image_received = on_image_received
        self.on_status = on_status
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, name="ImageSocketReceiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _emit_status(self, message: str) -> None:
        if self.on_status is not None:
            self.on_status(message)

    def _emit_image_received(self, image_path: Path) -> None:
        if self.on_image_received is not None:
            self.on_image_received(image_path)

    def _listen(self) -> None:
        host = str(config.IMAGE_SOCKET_HOST)
        port = int(config.IMAGE_SOCKET_PORT)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
                self._server_socket = server_socket
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.bind((host, port))
                server_socket.listen(5)
                server_socket.settimeout(1)
                self._emit_status(f"Image socket listening on {host}:{port}.")

                while not self._stop_event.is_set():
                    try:
                        connection, address = server_socket.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        if not self._stop_event.is_set():
                            self._emit_status("Image socket stopped unexpectedly.")
                        break

                    with connection:
                        self._receive_image(connection, address)
        except OSError as exc:
            self._emit_status(f"Image socket failed: {exc}")
        finally:
            self._server_socket = None

    def _receive_image(self, connection: socket.socket, address: tuple[str, int]) -> None:
        image_path = build_socket_image_path()
        bytes_received = 0
        try:
            with image_path.open("wb") as output_file:
                while True:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    bytes_received += len(chunk)
                    output_file.write(chunk)
        except OSError as exc:
            image_path.unlink(missing_ok=True)
            self._emit_status(f"Image socket receive failed from {address[0]}: {exc}")
            return

        if bytes_received == 0:
            image_path.unlink(missing_ok=True)
            self._emit_status(f"Image socket received an empty transfer from {address[0]}.")
            return

        self._emit_status(f"Received image from {address[0]}: {image_path.name}.")
        self._emit_image_received(image_path)


def get_wifi_signal_status() -> str:
    airport_path = Path("/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport")
    if not airport_path.exists():
        return "Signal: unavailable"

    try:
        result = subprocess.run(
            [str(airport_path), "-I"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "Signal: unavailable"

    rssi = None
    noise = None
    for line in result.stdout.splitlines():
        if "agrCtlRSSI:" in line:
            rssi = line.split(":", 1)[1].strip()
        elif "agrCtlNoise:" in line:
            noise = line.split(":", 1)[1].strip()

    if rssi is None:
        return "Signal: unavailable"

    try:
        rssi_value = int(rssi)
    except ValueError:
        return f"Signal: {rssi}"

    if rssi_value >= -55:
        quality = "excellent"
    elif rssi_value >= -67:
        quality = "good"
    elif rssi_value >= -75:
        quality = "fair"
    else:
        quality = "weak"

    noise_suffix = f", noise {noise} dBm" if noise is not None else ""
    return f"Signal: {rssi_value} dBm ({quality}{noise_suffix})"


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


class CameraController:
    def __init__(self) -> None:
        self.camera = Picamera2() if Picamera2 else None
        self.is_active = False

    def available(self) -> bool:
        return self.camera is not None

    def activate(self, image_quality: int) -> None:
        if not self.camera:
            return

        if not self.is_active:
            self.camera.configure(self.camera.create_still_configuration())
            self.camera.start()
            self.is_active = True

        self.camera.options["quality"] = image_quality

    def capture_image(self, image_directory: str) -> Path:
        if not self.camera:
            raise RuntimeError("Picamera2 is not installed on this device.")

        self.activate(config.IMAGE_QUALITY)
        directory = ensure_directory(image_directory)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = directory / f"{timestamp}.jpg"
        self.camera.capture_file(str(filename))
        return filename
