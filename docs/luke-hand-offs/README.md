# Hand-offs: Icarus drone and SkyPilot vision (Luke)

Dated session records for the Icarus drone work. Each one lets the next session
resume without re-discovering anything. New ones are written by the personal
`/icarus-handoff` Claude Code skill.

## Where the work lives

| Repo | Path on Luke's machine | Role |
|---|---|---|
| **SkyPilot** | `S:\GitHub\SkyPilot` (branch `ModelTraining`, remote `github.com/Elijahtab/SkyPilot`) | Vision model training and the two-stage pipeline. Supplies the v4 model; nothing else from it runs on the drone |
| **icarus-client** | this repo | Desktop drone manager (Tkinter). Runs the models on captured images |
| **icarus-pi** | `C:\Users\Administrator\Documents\CS433\PA_5\icarus-pi` | Raspberry Pi camera and Flask capture server (Pixhawk-triggered). `jetson/` (branch `jetson-v4-detector`): the v4 ROS 2 detector for the Jetson Orin Nano |

`models/v4_vehicle_model/vehicle_type_v4.pt` in this repo is byte-identical to
SkyPilot's `Vehicle_type_detection/runs/Vehicle_type_detection_v4/weights/best.pt`.

## Reading older hand-offs

The six hand-offs dated **2026-08-06 to 2026-09-22** were written in SkyPilot's
`docs/luke-hand-offs/`. They were moved here on 2026-09-28 unchanged. Every
repo path in them (`scripts/...`, `ros2_ws/...`, `docker/...`, `docs/*.md`)
is relative to `S:\GitHub\SkyPilot`, not to this repo. The exception is a
reference to another hand-off (`docs/luke-hand-offs/...`), which resolves here.
Their history before the move is in SkyPilot's git log.

Newer hand-offs say which repo each path belongs to. SkyPilot's `ros2_ws/`,
`docker/` and `.devcontainer/`, which the 2026-09-22 hand-off describes, were
removed on 2026-09-28. The Jetson work now lives in icarus-pi's `jetson/` folder.

## Index

| Date | Hand-off | Topic |
|---|---|---|
| 2026-08-06 | [vision-pipeline-reorg](2026-08-06-vision-pipeline-reorg.md) | Diagnosing v5–v7; reorganising the pipeline; CAR renamed to Vehicle |
| 2026-09-01 | [manual-labeler](2026-09-01-manual-labeler.md) | Manual vehicle-type labeler |
| 2026-09-08 | [v8-review-pool-training](2026-09-08-v8-review-pool-training.md) | v8 training on the hand-reviewed pool of crops 48px or larger |
| 2026-09-10 | [stopping-point](2026-09-10-stopping-point.md) | v8 reproduced; review pipeline restored |
| 2026-09-15 | [kaggle-train-split-assessment](2026-09-15-kaggle-train-split-assessment.md) | Should the Kaggle train split go into v8? Options A, B and C |
| 2026-09-22 | [jazzy-migration-jetson-bringup](2026-09-22-jazzy-migration-jetson-bringup.md) | ROS 2 Jazzy migration; Orin Nano on JetPack 7.2; v4 node |
