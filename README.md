# CS435DroneManager

Imported model assets live in:
- `models/v4_vehicle_model/`
- `models/yolov8m/`

Files:
- `models/v4_vehicle_model/vehicle_type_v4.pt`
- `models/v4_vehicle_model/metadata.yaml`
- `models/yolov8m/yolov8m.pt`

Minimal usage example:

```python
from ultralytics import YOLO

model = YOLO("models/v4_vehicle_model/vehicle_type_v4.pt")
results = model("path/to/image.jpg")
```

Standard Ultralytics model example:

```python
from ultralytics import YOLO

model = YOLO("models/yolov8m/yolov8m.pt")
results = model("path/to/image.jpg")
```

Raspberry Pi camera UI:

```python
.venv/bin/python drone_manager_app.py
```

The UI lets you update `IMAGE_QUALITY` and `IMAGE_DIRECTORY` in `config.json`, upload config or selected image files through the Raspberry Pi Flask API, and monitor the image directory from the `Images` tab. Launch it with the project `.venv` so `ultralytics` and `Pillow` are available.

The `Config` tab also includes Raspberry Pi Flask API settings:
- `Pi API Base URL`
- `Config Endpoint`
- `Capture Endpoint`
- `Latest Image Endpoint`
- `API Timeout (s)`

Use `Save Local Config` to update this app's `config.json`, or `Save + Upload To Pi` to also POST the Pi-side JSON config file to the Flask API using multipart upload style. The remote payload uses the lowercase keys expected by your Raspberry Pi capture script.

Use `Connect` in the `Config` tab to test the configured Pi API base URL and confirm the desktop app can reach the Raspberry Pi.

The `Capture Image` button in the `Images` tab now POSTs to `/capture`. The Pi captures an image, waits one second, finds the newest file in its image directory, returns that filename, and the desktop client immediately downloads the newest file from `/latest-image` into the local `IMAGE_DIRECTORY`.

The `Images` tab also shows a best-effort Wi-Fi signal readout. On macOS this uses the local machine's current RSSI/noise values, which is useful when this machine is connected to the Raspberry Pi hotspot.

Script purposes:
- `drone_manager_app.py`: main desktop launcher that builds the Tkinter window, tabs, and image polling loop
- `app_services.py`: shared service layer for model execution, Pi API calls, local file handling, and Wi-Fi signal reads
- `config.py`: config loader that exposes values from `config.json`
- `ui/config_tab.py`: `Config` tab UI for editing local settings and calling Pi API config/status actions
- `ui/images_tab.py`: `Images` tab UI for capture, preview, mode switching, and image processing actions
- `test.py`: minimal ad hoc API test script for a direct `/capture` request

Default API routes expected by the desktop app:
- `GET /`
- `POST /upload`
- `POST /capture`
- `GET /latest-image`

The `Images` tab also lets you switch processing between `Original`, `YOLOv8m`, `Vehicle v1`, and `YOLOv8m + Vehicle v1`, then process either the selected image or the full image folder. In the combined mode, `YOLOv8m` detects the base objects first and only `car` detections are refined through the v1 model, with one final label drawn per detection. Processed outputs are saved under `IMAGE_DIRECTORY/processed/...`.
