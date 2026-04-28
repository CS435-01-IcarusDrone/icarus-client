from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import config
from app_services import CameraController, ModelProcessor, ensure_directory
from ui import ConfigTab, ImagesTab


class DroneManagerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Raspberry Pi Camera Manager")
        self.geometry("1100x720")

        self.camera_controller = CameraController()
        self.model_processor = ModelProcessor()
        self.pi_config_uploaded = False
        self.pi_mode_set = False
        self.pi_camera_activated = False

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.config_tab = ConfigTab(notebook, self)
        self.images_tab = ImagesTab(notebook, self)

        notebook.add(self.config_tab, text="Config")
        notebook.add(self.images_tab, text="Images")

        self.refresh_from_config()
        self.refresh_pi_workflow_controls()
        self.after(3000, self.poll_for_images)

    def refresh_from_config(self) -> None:
        ensure_directory(config.IMAGE_DIRECTORY)
        self.images_tab.refresh_directory_label()
        self.images_tab.refresh_images()

    def poll_for_images(self) -> None:
        self.images_tab.refresh_images()
        self.after(3000, self.poll_for_images)

    def refresh_pi_workflow_controls(self) -> None:
        self.images_tab.update_pi_workflow_controls(
            config_uploaded=self.pi_config_uploaded,
            mode_set=self.pi_mode_set,
            camera_activated=self.pi_camera_activated,
        )

    def mark_pi_config_uploaded(self) -> None:
        self.pi_config_uploaded = True
        self.pi_mode_set = False
        self.pi_camera_activated = False
        self.refresh_pi_workflow_controls()

    def mark_pi_mode_set(self) -> None:
        self.pi_mode_set = True
        self.pi_camera_activated = False
        self.refresh_pi_workflow_controls()

    def mark_pi_camera_activated(self) -> None:
        self.pi_camera_activated = True
        self.refresh_pi_workflow_controls()

    def reset_pi_mode_steps(self) -> None:
        self.pi_mode_set = False
        self.pi_camera_activated = False
        self.refresh_pi_workflow_controls()


def main() -> None:
    app = DroneManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
