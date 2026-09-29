# Hand-off: v4 runs as a ROS 2 node on the Jetson; first accuracy on Icarus photos (2026-09-29)

## Goal

Pick up the 2026-09-22 bring-up and get the v4 detector running as a ROS 2
node on the Orin Nano. Along the way Luke restructured the project. The drone
side is now Icarus-only: only the v4 weights come from SkyPilot, the ROS work
moved into icarus-pi, and code reaches the board over SSH, never GitHub or USB.
Once the node worked, Luke hand-labelled the 85 Icarus drone photos, and v4
was scored against them. That gives v4's first accuracy number on Icarus
imagery.

## State

### Repos (all commits local-only unless noted)

| Repo | Branch / HEAD | This session | Pushed? |
|---|---|---|---|
| SkyPilot | `ModelTraining` @ `2da32c4` | `0a7e458` moved the hand-offs to icarus-client. `2da32c4` removed `ros2_ws/`, `docker/`, `.devcontainer/` | `0a7e458` yes; **`2da32c4` no** (1 ahead) |
| icarus-client | `LucasMW` @ `41689fb` (+ this hand-off) | `ca78b04` added the hand-offs. `41689fb` updated the index roles. This commit adds this hand-off | `ca78b04` yes; **`41689fb` + this no** |
| icarus-pi | **`jetson-v4-detector`** (new, from Kelby's `origin/main` `b20d47a`) @ `70eb098` | `e1ef420` node + scripts, `3709cf7` SSH deploy, `dece1a3` + `70eb098` smoke-test shutdown fixes, `fb9face` bundle all Test Pictures | **no** (5 ahead of `origin/main`, no upstream set). Local `main` untouched at `68400ba` |

- **SkyPilot untracked list, unchanged from 09-22, with two changes:**
  - `SkyPilot:ros2_ws/.../v4_detector_node.py` is gone. It was ported to icarus-pi, then deleted with `ros2_ws/`.
  - `SkyPilot:scripts/check_labeling_labels.py` is new. Luke created it on 09-24, outside any session; it is untracked and harmless.
- **The uncommitted Jazzy migration** (Dockerfiles, `ros2_ws/README.md`) was deliberately dropped with those folders. Its lessons are in `icarus-pi:jetson/README.md`.
- **icarus-client's working tree is dirty** as usual (`.idea/`, `__pycache__/`, `images/`, `evaluate_models.py`, `labeled/`). None of it is from this session except `Test Pictures/` (below).

### Outside git — this hand-off is the only record

**Jetson Orin Nano** (`ssh icarus-jetson`):

| Thing | Value |
|---|---|
| OS | JetPack **7.2.1** (L4T R39.2.1), Ubuntu 24.04.5, Python 3.12.3. Hostname `icarus`, user `icarus`, reachable as **`icarus.local`** |
| IP | DHCP; seen at .124, .135, .159, .165, .178 and .245 on `192.168.1.x`. Never hard-code it |
| Hardware | 7.3 GiB RAM, **0 swap**, 233 GB disk (~205 GB free), power mode **25W** |
| CUDA | **GPU driver only** (`nvidia-l4t-cuda` 39.2.1). No `/usr/local/cuda`, no `nvcc`, no `nvidia-jetpack`, no TensorRT |
| apt, added this session | `python3-pip`, `python3-wheel`, `ros-jazzy-vision-msgs`, `ros-jazzy-image-publisher` (+ `image-transport`, `camera-info-manager`, `camera-calibration-parsers`). Already present: `ros-jazzy-cv-bridge`, colcon |
| pip `--user` (`~/.local`, 4.7 GB) | torch **2.12.1+cu132**, torchvision 0.27.1+cu132, ultralytics 8.3.168, opencv-python 4.11.0.86. Also 2.9 GB of NVIDIA CUDA wheels (`nvidia-cublas`, `nvidia-cudnn-cu13`, …) and triton 3.7.1. numpy is apt's **1.26.4** |
| NVPL / cuDSS | the setup script's fallback did **not** trigger; torch imported without them |
| `~/icarus_ws` | deployed bundle, built. `models/vehicle_type_v4.pt` (md5 `5dd09e26…`) and all 85 test photos |
| Running | nothing. Detector is started by hand; no boot service |
| ROS env | `ROS_DOMAIN_ID` unset (0), Fast DDS, discovery range SUBNET, ufw inactive |
| Stray files | `/tmp/tA.log`, `/tmp/tB.log` from shutdown tests (harmless) |

**Windows PC:**
- **SSH:** `~/.ssh/config` defines `Host icarus-jetson` → `icarus.local`, user `icarus`, `HostKeyAlias icarus-jetson`, key `~/.ssh/icarus_jetson_ed25519`. The key has no passphrase and is installed in the board's `authorized_keys`.
- **Host keys:** `known_hosts` has the board's 3 host keys under the alias. They match the keys accepted for `.159` on 09-22.

**`icarus-client:Test Pictures/` — untracked, the only copy:**
- **Photos:** 85 drone photos, 4608×2592, dated 2026-05-04 and 2026-08-02 (395 MB).
- `labels/` — **Luke's hand labels**: 85 YOLO `.txt` files in the 7-class schema; **97 vehicles in 33 photos**, 52 photos empty. By type: Vehicle 32, Standard Car 31, SUV 23, Truck 9, Motorcycle 2. **Not backed up.**
- `preview/`: the labeller's drawn previews (85).
- `v4_vs_labels/`: 40 review images at 640 px. Green is Luke's label, yellow a matched v4 box, red an unmatched v4 box.

### Verified vs pending

| Thing | Status |
|---|---|
| `setup_jetson.sh` install → build → smoke test on the board | ✅ run by Luke with `ssh -t`; `--build-only` re-run by Claude |
| torch cu132 on Orin sm_87 | ✅ real GPU matmul; v4 on `device 0` |
| Node → node on the board (`image_publisher` → `v4_detector` → `ros2 topic echo`) | ✅ smoke test |
| Smoke test exits cleanly with no orphaned processes | ✅ after `70eb098`, with a tty (`ssh -tt`) and without one |
| v4 accuracy on Icarus photos | ✅ measured on Windows against Luke's labels (below) |
| ROS across machines | ❌ untested; no second ROS Jazzy machine exists |
| Real camera → `/camera/image_raw` | ❌ nothing publishes it yet |
| TensorRT engine | ❌ not attempted |
| 960 px / conf 0.35 on the board | ❌ recommended, **not applied**; the node still defaults to 640 / 0.25 |

## Key findings

### The node and its interface

`icarus-pi:jetson/` is a self-contained colcon workspace with package `icarus_vision`, node `/v4_detector`.

- **In:** `/camera/image_raw`, `sensor_msgs/Image`, best-effort depth 1.
- **Out:** `/detections`, `vision_msgs/Detection2DArray`, reliable depth 10. Optionally `/detections/image` (`publish_annotated:=true`).
- **Boxes** are centre and size in pixels of the incoming frame, and the header is copied from the image.
- **NMS** is class-agnostic.
- **No custom messages.** Luke chose `vision_msgs` over a renamed copy of SkyPilot's `VehicleArray`.
- **Weights path** is a parameter, so a `.engine` can replace the `.pt` with no code change.
- **`YOLO_AUTOINSTALL=false`** is set in the node, so ultralytics can't pip-install anything at run time.

Files, one line each: `icarus-pi:jetson/README.md` §"What a detection means". A folder-by-folder tour of the deployed `~/icarus_ws` was given in-session and isn't recorded elsewhere. Short version: `build/`, `install/` and `log/` are colcon output and safe to delete; `install/setup.bash` is what `run.sh` sources.

### Deploy and install path, all verified

1. **On the PC** (PowerShell, icarus-pi root): `.\jetson\make_bundle.ps1 -Deploy icarus-jetson`. It builds `dist\icarus_ws` (444 MB with photos) and copies it with scp; this took 44 s. `-SkipTestImages` gives a 50 MB code-only redeploy, and the board keeps its photos because scp never deletes.
2. **On the board:** `ssh -t icarus-jetson "bash ~/icarus_ws/setup_jetson.sh"`. The `-t` matters: sudo asks for Luke's password.
3. **Run:** `ssh -t icarus-jetson "bash ~/icarus_ws/run.sh"`.

### JetPack 7.2 torch facts (these correct the 09-22 hand-off)

- **`--pre` is no longer needed.** Stable aarch64 `cu132` wheels (torch 2.12 to 2.14) are on `download.pytorch.org/whl/cu132`.
- **A plain `pip install ultralytics` breaks the board.** A pip dry run for aarch64 showed it resolves numpy 2.5.3 (breaks `cv_bridge`), OpenCV 5.0, and PyPI's generic torch 2.14 (reported not to run on sm_87). The fix is `icarus-pi:jetson/constraints.txt`: `torch==2.12.1+cu132`, `torchvision==0.27.1+cu132`, `numpy<2` and `opencv*<4.12`. OpenCV 4.12+ requires numpy ≥2; 4.11.0.86 is the newest that accepts 1.26.
- **Why the install is ~3 GB this time** (Luke asked). The earlier latency tests ran inside `ultralytics/ultralytics:latest-jetson-jetpack5/6` Docker images, which bundle CUDA. The JetPack 7.2 ISO install ships only the driver, so the cu132 wheel pulls CUDA runtime libraries as pip dependencies. That is not the full toolkit: no compiler, no system install.
- **torch prints "Found GPU0 Orin … CC 8.7 … except {8.7}".** It is harmless: the matmul and v4 run. NVIDIA staff call it a known false warning.

### v4 on Icarus imagery — Luke's labels, 97 vehicles in 85 photos

| Setting | Recall | Precision | F1 |
|---|---|---|---|
| `diagnose_labels.py` (640, conf 0.25, no agnostic NMS) | 0.629 | 0.517 | — |
| **Deployed: 640, conf 0.25, agnostic** | **0.619** | **0.583** | 0.600 |
| 960, conf 0.25 | 0.763 | 0.627 | — |
| 1280, conf 0.25 | 0.629 | 0.513 | — |
| **960, conf 0.35** (recommended) | **0.722** | **0.700** | **0.711** |
| 960, conf 0.45 (precision option) | 0.639 | 0.785 | 0.705 |

For reference, v4 on SkyPilot base val scores recall 0.804 and precision 0.813.

- **Misses are smaller vehicles:** median long side 251 px, against 819 px for hits, at 640 input. 960 recovers 14 of them. 1280 is worse, because v4 was trained at 640.
- **False boxes at the deployed setting:** 37 are "not a vehicle" (22 of them in photos labelled empty) and 6 are stacked on a found vehicle.
  - **Luke reviewed `v4_vs_labels/` and confirmed** the red boxes are non-vehicles or duplicates stacked on a correct box. The labels are trustworthy.
  - **Confidence separates them:** true positives have a median 0.77, false positives 0.47.
  - **NMS IoU (0.7/0.5/0.3) and an overlap filter barely help:** they removed at most 1 box, because stacked boxes are few.
- **v4's type naming is unusable on Icarus photos:** class agreement 0.098 on matched boxes. Luke's SUV and Standard Car are mostly `CAR`, and his `Vehicle` is mostly `Truck`. Consumers of `/detections` must ignore `class_id`.
- **Caveat:** the thresholds were tuned on the same 85 photos they were scored on, so the numbers are optimistic. Validate on the next flight's photos.
- **Reproduce the standard number (Windows, SkyPilot root):**
  ```
  .\myenv\Scripts\python.exe scripts\evaluation\diagnose_labels.py "<icarus-client>\Test Pictures" "<icarus-client>\Test Pictures\labels"
  ```
  The deployment-matched and tuning scripts were **scratchpad-only and are lost**. They were short; rebuild them from the table above (greedy IoU ≥ 0.5 matching; agnostic NMS; conf applied after one low-conf pass).

### Jetson speed (`.pt`, GPU, 4608×2592 photos)

- **640:** a first 85-photo run gave a median of 58.8 ms inference and 73.3 ms for the whole `predict()`. A later run on 29 photos gave 36.2 / 45.9 ms.
- **960 (same later run):** 61.6 / 80.4 ms, about 12 photos per second.
- **Compare only within one run.** Clocks vary between runs, so the absolute numbers moved by a lot.
- **GPU memory** peaks at 197 MiB.

### Smoke-test orphan bug (fixed)

- **What happened:** `ros2 launch` exits on SIGTERM **without stopping its nodes**, and SIGINT never reaches a script's background jobs. A non-interactive `--build-only` run left the detector and `image_publisher` running **orphaned for 8.5 h**, holding 2.1 GB. Luke's interactive run was cleaned up by the SSH hang-up.
- **Fix (`70eb098`):** `setsid` the launch, send SIGTERM to the whole process group, then SIGKILL after 10 s. An EXIT trap does the same on failure or Ctrl+C.

### Labelling tool

- **Tool used:** `SkyPilot:scripts/labeling/manual_label.py` with `--source "<Test Pictures>" --out "<Test Pictures>\labels" --boxes detect --imgsz 1280 --view 2300 --no-dedupe`. Luke finished all 85 photos in about 7 minutes.
- **Its detector filter is hard-coded** to COCO ids `[2,3,5,7]`. With v4 as the proposer it would silently drop v4's CAR, Bus, Standard Car and Van boxes. Stock yolov8m was used instead. That was deliberate anyway: labels seeded from v4 would flatter v4 when scored against it.

### Pi → client image protocol (needed for the bridge node)

`icarus-pi:server.py` (Kelby, `b20d47a`):
- **Register:** the client registers with `POST http://<pi>:5000/client/register`; the Pi stores `request.remote_addr`.
- **Send:** on a Pixhawk RC_CHANNELS rising edge, the Pi captures a photo, connects to `client_ip:6000`, streams the raw JPEG bytes in 4 KB chunks, and closes the socket.
- **Framing:** one image per connection, delimited by EOF. There is no header.

## Gotchas

- **Piping a PowerShell here-string into `ssh` adds a UTF-8 BOM:** the first remote line fails with "command not found", even with `$OutputEncoding` set. Use Git Bash: `ssh icarus-jetson 'bash -s' <<'EOF' … EOF`.
- **`pgrep -f "<pattern>"` over SSH matches its own `bash -c` command line**, so the check reports processes that aren't there. Use bracket patterns: `ps -eo args | grep -E "[v]4_detector"`.
- **Git Bash mangles `origin/main:file` into a Windows path.** Prefix `MSYS_NO_PATHCONV=1`.
- **Windows backslash paths in Python heredocs** trigger escape warnings or mistakes. Use raw strings.
- **Both icarus repos have `core.autocrlf=true`.** `icarus-pi:jetson/.gitattributes` forces LF for `*.sh`, and `make_bundle.ps1` LF-normalises every text file anyway.
- **sudo on the board needs Luke's password**, so only the full `setup_jetson.sh` needs him. Claude can run `--build-only` over plain SSH.
- **A 36 MB raw test frame arrives slowly:** about 1 frame per 3 s over best-effort DDS. That is an `image_publisher` artefact; inference is ~60 ms.
- **The labels are the only copy**, in an untracked folder.

## Next steps

1. **Decide the node defaults.** Recommended: 960 / 0.35 (or 0.45 for fewer false alarms). Then:
   - Change the `imgsz` and `det_conf` defaults in `icarus-pi:jetson/src/icarus_vision/icarus_vision/v4_detector_node.py` **and** `…/launch/v4_detector.launch.py`. The launch default wins, and it does not currently pass `imgsz`.
   - PC: `.\jetson\make_bundle.ps1 -Deploy icarus-jetson -SkipTestImages`
   - Board: `ssh icarus-jetson "bash ~/icarus_ws/setup_jetson.sh --build-only"`
2. **Back up the labels.** Commit `icarus-client:Test Pictures/labels/` (73 KB), or copy it somewhere safe. Luke's call; the photos are 395 MB.
3. **Pi → ROS bridge node** in `icarus_vision`:
   - POST `/client/register` to the Pi.
   - Listen on TCP 6000 and read each connection to EOF.
   - Decode the JPEG and publish `/camera/image_raw`.
   This leaves `icarus-pi:server.py` unchanged. The alternative is ROS on the Pi, which means Ubuntu 24.04.
4. **Start on boot:** a systemd unit running `run.sh`, so other nodes can rely on `/detections`.
5. **TensorRT:**
   - Add swap first.
   - `sudo apt-get install -y python3-libnvinfer` (TensorRT 10.16.2 is in the configured r39.2 repo).
   - Then follow `icarus-pi:jetson/README.md` §"Faster: TensorRT".
6. **Non-vehicle false positives** (~24 even at 960/0.35) need model work in SkyPilot:
   - hard negatives from `v4_vs_labels/` red boxes, or
   - the "not a vehicle" stage-2 class (`SkyPilot:docs/two-stage-pipeline.md` §Next steps).
7. **Label the next flight's photos** to validate the tuned thresholds on unseen imagery.
8. **Push when ready:**
   - icarus-pi: `git push -u origin jetson-v4-detector`. Kelby's repo, so maybe open a PR.
   - SkyPilot: `2da32c4`. Removing `ros2_ws/` affects Elijah's view of the repo.
   - icarus-client: `41689fb` and this hand-off.
9. **Optional:** a higher power mode (`sudo nvpmodel -q --verbose` lists the modes).

## References

- `icarus-pi:jetson/README.md`: deploy, install, run, parameters, detection semantics, gotchas, status table.
- `icarus-pi:jetson/src/icarus_vision/`: the node and launch file.
- `icarus-pi:jetson/setup_jetson.sh`, `make_bundle.ps1`, `constraints.txt`, `run.sh`.
- `icarus-pi:server.py`: the Pi's capture and transfer protocol.
- `SkyPilot:scripts/labeling/manual_label.py`, `SkyPilot:scripts/evaluation/diagnose_labels.py`.
- `SkyPilot:docs/two-stage-pipeline.md`: v4 vs stock yolov8m, the traffic-signal defect, the type classifier.
- Prior hand-off: `2026-09-22-jazzy-migration-jetson-bringup.md`. Its torch steps and Docker path are superseded by this one.
- [NVIDIA forum: PyTorch on JetPack 7.2](https://forums.developer.nvidia.com/t/how-do-i-correctly-install-pytorch-on-jetpack-7-2/372773)
- [iuliaferoli/jetson-jp7.2-install](https://github.com/iuliaferoli/jetson-jp7.2-install)
- [vision_opencv#535 (cv_bridge and numpy 2)](https://github.com/ros-perception/vision_opencv/issues/535)
- [Isaac ROS 4.6 on Orin / JetPack 7.2](https://forums.developer.nvidia.com/t/roadmap-for-isaac-ros-jazzy-on-orin-devices/375982): a no-torch TensorRT alternative. `ros-jazzy-isaac-ros-yolov8` exists for arm64 noble; it publishes `Detection2DArray` in 640-px network coordinates.
