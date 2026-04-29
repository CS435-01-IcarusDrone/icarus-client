from __future__ import annotations

import importlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
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
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


CONFIG_PATH = Path(__file__).with_name("config.json")
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
MODEL_PIPELINES = {
    "Original": (),
    "YOLOv8m": ("yolov8m",),
    "Vehicle v4": ("vehicle_v4",),
    "YOLOv8m + Vehicle v4": ("yolov8m", "vehicle_v4"),
}
MODEL_PATHS = {
    "yolov8m": Path(__file__).with_name("models") / "yolov8m" / "yolov8m.pt",
    "vehicle_v4": Path(__file__).with_name("models") / "v4_vehicle_model" / "vehicle_type_v4.pt",
}


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

def _capture_filename_from_response(response: "requests.Response") -> str:
    header = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^"]+)"?', header)
    if match:
        return Path(match.group(1)).name

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = ".jpg"
    content_type = response.headers.get("Content-Type", "").lower()
    if "png" in content_type:
        suffix = ".png"
    return f"capture_{timestamp}{suffix}"


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
        vehicle_model = self.ensure_model("vehicle_v4")
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

    def _draw_combined_pipeline(self, image_path: Path, output_path: Path) -> Path:
        if Image is None or ImageDraw is None:
            raise RuntimeError("Pillow is required to build the combined model preview.")

        yolov8m_model = self.ensure_model("yolov8m")
        result = yolov8m_model.predict(source=str(image_path), verbose=False)[0]
        source_image = Image.open(image_path).convert("RGB")
        annotated_image = source_image.copy()
        draw = ImageDraw.Draw(annotated_image)

        if getattr(result, "boxes", None) is None:
            annotated_image.save(output_path)
            return output_path

        for box in result.boxes:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            if x2 <= x1 or y2 <= y1:
                continue

            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            base_label = result.names[class_id]
            label = f"{base_label} {confidence:.2f}"
            color = "lime"

            if base_label == "car":
                crop = source_image.crop((x1, y1, x2, y2))
                refinement = self._refine_car_label(crop)
                if refinement is not None:
                    refined_label, refined_confidence = refinement
                    label = f"{refined_label} {refined_confidence:.2f}"
                    color = "cyan"

            draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
            text_bbox = draw.textbbox((x1, y1), label)
            text_bottom = text_bbox[3]
            text_right = text_bbox[2]
            text_top = max(0, y1 - (text_bottom - text_bbox[1]) - 6)
            draw.rectangle((x1, text_top, text_right + 8, text_top + (text_bottom - text_bbox[1]) + 6), fill=color)
            draw.text((x1 + 4, text_top + 3), label, fill="black")

        annotated_image.save(output_path)
        return output_path

    def process_image(self, image_path: Path, pipeline_name: str, output_directory: Path) -> Path:
        pipeline = MODEL_PIPELINES[pipeline_name]
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / image_path.name

        if not pipeline:
            shutil.copy2(image_path, output_path)
            return output_path

        if pipeline_name == "YOLOv8m + Vehicle v4":
            return self._draw_combined_pipeline(image_path, output_path)

        with tempfile.TemporaryDirectory() as temp_dir_name:
            current_source = image_path
            temp_dir = Path(temp_dir_name)

            for index, model_key in enumerate(pipeline):
                model = self.ensure_model(model_key)
                results = model.predict(source=str(current_source), verbose=False)
                result = results[0]

                stage_output = output_path if index == len(pipeline) - 1 else temp_dir / f"stage_{index}_{image_path.name}"
                result.save(filename=str(stage_output))
                current_source = stage_output

            return output_path


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
