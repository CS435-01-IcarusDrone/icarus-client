from __future__ import annotations

import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import config
from app_services import (
    CameraController,
    ImageSocketReceiver,
    ModelProcessor,
    ensure_directory,
    register_with_pi_api,
)
from ui import ConfigTab, ImagesTab


class DroneManagerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Raspberry Pi Camera Manager")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")

        self.camera_controller = CameraController()
        self.model_processor = ModelProcessor()
        self.image_socket_receiver = ImageSocketReceiver(
            on_image_received=self._on_socket_image_received,
            on_status=self._on_socket_status,
        )
        self._image_socket_binding: tuple[str, int] | None = None

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.config_tab = ConfigTab(notebook, self)
        self.images_tab = ImagesTab(notebook, self)

        notebook.add(self.config_tab, text="Config")
        notebook.add(self.images_tab, text="Images")

        self.refresh_from_config()
        self.register_with_pi()
        self.after(3000, self.poll_for_images)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh_from_config(self) -> None:
        ensure_directory(config.IMAGE_DIRECTORY)
        self.images_tab.refresh_directory_label()
        self.images_tab.refresh_images()
        socket_binding = (str(config.IMAGE_SOCKET_HOST), int(config.IMAGE_SOCKET_PORT))
        if socket_binding != self._image_socket_binding:
            self.restart_image_socket_receiver(socket_binding)
        else:
            self.start_image_socket_receiver()

    def start_image_socket_receiver(self) -> None:
        self.image_socket_receiver.start()

    def restart_image_socket_receiver(self, socket_binding: tuple[str, int] | None = None) -> None:
        self.image_socket_receiver.stop()
        self._image_socket_binding = socket_binding or (str(config.IMAGE_SOCKET_HOST), int(config.IMAGE_SOCKET_PORT))
        self.image_socket_receiver.start()

    def register_with_pi(self) -> None:
        def register() -> None:
            try:
                message = register_with_pi_api()
            except Exception as exc:
                self.after(0, self.images_tab.status_var.set, f"Pi registration failed: {exc}")
                return

            self.after(0, self.images_tab.status_var.set, message)

        threading.Thread(target=register, name="PiRegistration", daemon=True).start()

    def _on_socket_image_received(self, image_path: Path) -> None:
        self.after(0, self.images_tab.refresh_images, image_path)

    def _on_socket_status(self, message: str) -> None:
        self.after(0, self.images_tab.status_var.set, message)

    def poll_for_images(self) -> None:
        self.images_tab.refresh_images()
        self.after(3000, self.poll_for_images)

    def on_close(self) -> None:
        self.image_socket_receiver.stop()
        self.destroy()


def main() -> None:
    app = DroneManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
