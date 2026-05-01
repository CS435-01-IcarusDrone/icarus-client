from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import config
from app_services import (
    MODEL_PIPELINES,
    SUPPORTED_IMAGE_SUFFIXES,
    activate_remote_camera,
    ensure_directory,
    get_pi_status,
    get_wifi_signal_status,
    sanitize_pipeline_name,
    set_remote_camera_mode,
    trigger_remote_capture,
)

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


class ImagesTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "DroneManagerApp") -> None:
        super().__init__(master, padding=16)
        self.app = app
        self.preview_image = None
        self.last_seen_image: Path | None = None
        self.displayed_image_path: Path | None = None
        self.detection_counts: dict[tuple[str, str], tuple[int, int]] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(1, weight=1)
        toolbar.columnconfigure(2, weight=0)
        toolbar.columnconfigure(3, weight=0)
        toolbar.columnconfigure(4, weight=0)
        toolbar.columnconfigure(5, weight=0)
        toolbar.columnconfigure(6, weight=0)
        toolbar.columnconfigure(7, weight=0)

        ttk.Button(toolbar, text="Refresh", command=self.refresh_images).grid(row=0, column=0, padx=(0, 12))
        self.directory_var = tk.StringVar(value=config.IMAGE_DIRECTORY)
        ttk.Label(toolbar, textvariable=self.directory_var).grid(row=0, column=1, sticky="w")
        self.signal_var = tk.StringVar(value=get_wifi_signal_status())
        ttk.Label(toolbar, textvariable=self.signal_var).grid(row=0, column=2, padx=(12, 12), sticky="e")
        self.camera_mode_var = tk.StringVar(value="image")
        ttk.OptionMenu(
            toolbar,
            self.camera_mode_var,
            self.camera_mode_var.get(),
            "image",
            "video",
        ).grid(row=0, column=3, padx=(0, 12), sticky="e")
        self.set_mode_button = ttk.Button(toolbar, text="Set Mode", command=self.set_camera_mode)
        self.set_mode_button.grid(row=0, column=4, padx=(0, 12), sticky="e")
        self.status_button = ttk.Button(toolbar, text="Status", command=self.fetch_status)
        self.status_button.grid(row=0, column=5, padx=(0, 12), sticky="e")
        self.activate_button = ttk.Button(toolbar, text="Activate Camera", command=self.activate_camera)
        self.activate_button.grid(row=0, column=6, padx=(0, 12), sticky="e")
        self.capture_button = ttk.Button(toolbar, text="Capture Image", command=self.capture_image)
        self.capture_button.grid(row=0, column=7, sticky="e")

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Processing").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.pipeline_var = tk.StringVar(value="Original")
        ttk.OptionMenu(controls, self.pipeline_var, self.pipeline_var.get(), *MODEL_PIPELINES.keys(), command=self._on_pipeline_change).grid(row=0, column=1, sticky="w")
        ttk.Button(controls, text="Process Selected", command=self.process_selected_image).grid(row=0, column=2, padx=(12, 0))
        ttk.Button(controls, text="Process All", command=self.process_all_images).grid(row=0, column=3, sticky="w", padx=(12, 0))

        content = ttk.Frame(self)
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        self.image_list = tk.Listbox(content, height=18, exportselection=False)
        self.image_list.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.image_list.bind("<<ListboxSelect>>", self._on_select)

        preview_panel = ttk.Frame(content)
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)

        self.counts_var = tk.StringVar(value="Vehicles: --    People: --")
        ttk.Label(preview_panel, textvariable=self.counts_var, anchor="center").grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.preview_label = ttk.Label(preview_panel, text="No images found.", anchor="center")
        self.preview_label.grid(row=1, column=0, sticky="nsew")

        self.status_var = tk.StringVar(value="Waiting for images.")
        ttk.Label(self, textvariable=self.status_var).grid(row=3, column=0, sticky="w", pady=(12, 0))

    def current_directory(self) -> Path:
        return ensure_directory(config.IMAGE_DIRECTORY)

    def refresh_directory_label(self) -> None:
        self.directory_var.set(config.IMAGE_DIRECTORY)

    def processed_directory(self) -> Path:
        return self.current_directory() / "processed" / sanitize_pipeline_name(self.pipeline_var.get())

    def _counts_key(self, image_path: Path, pipeline_name: str | None = None) -> tuple[str, str]:
        return (pipeline_name or self.pipeline_var.get(), image_path.name)

    def _set_detection_counts(self, vehicle_count: int | None = None, person_count: int | None = None) -> None:
        if vehicle_count is None or person_count is None:
            self.counts_var.set("Vehicles: --    People: --")
            return

        self.counts_var.set(f"Vehicles: {vehicle_count}    People: {person_count}")

    def _store_detection_counts(self, image_path: Path, pipeline_name: str, vehicle_count: int, person_count: int) -> None:
        self.detection_counts[self._counts_key(image_path, pipeline_name)] = (vehicle_count, person_count)

    def _show_stored_detection_counts(self, image_path: Path) -> None:
        counts = self.detection_counts.get(self._counts_key(image_path))
        if counts is None:
            self._set_detection_counts()
        else:
            self._set_detection_counts(*counts)

    def refresh_images(self, select_path: Path | None = None) -> None:
        self.signal_var.set(get_wifi_signal_status())
        directory = self.current_directory()
        images = sorted(
            [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

        selected_name = select_path.name if select_path else None
        if selected_name is None:
            current_selection = self.image_list.curselection()
            if current_selection:
                selected_name = self.image_list.get(current_selection[0])
            elif self.displayed_image_path is not None:
                selected_name = self.displayed_image_path.name

        self.image_list.delete(0, tk.END)
        for image_path in images:
            self.image_list.insert(tk.END, image_path.name)

        if not images:
            self.last_seen_image = None
            self.preview_image = None
            self.preview_label.configure(text="No images found.", image="")
            self._set_detection_counts()
            self.status_var.set("Waiting for images.")
            return

        latest_image = images[0]
        if latest_image != self.last_seen_image:
            self.status_var.set(f"Latest image received: {latest_image.name}")
            self.last_seen_image = latest_image

        target_name = selected_name or latest_image.name
        try:
            target_index = [image.name for image in images].index(target_name)
        except ValueError:
            target_index = 0

        self.image_list.selection_clear(0, tk.END)
        self.image_list.selection_set(target_index)
        self.image_list.activate(target_index)
        self.show_image_for_pipeline(images[target_index])

    def show_image(self, image_path: Path) -> None:
        if Image is None or ImageTk is None:
            self.preview_label.configure(
                text=f"Pillow is required to preview JPG images.\nFound: {image_path.name}",
                image="",
            )
            self.preview_image = None
            return

        image = Image.open(image_path)
        image.thumbnail((800, 600))
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image, text="")
        self.displayed_image_path = image_path

    def show_image_for_pipeline(self, image_path: Path) -> None:
        pipeline_name = self.pipeline_var.get()
        if pipeline_name == "Original":
            self.show_image(image_path)
            self._set_detection_counts()
            return

        processed_path = self.processed_directory() / image_path.name
        if processed_path.exists():
            self.show_image(processed_path)
            self._show_stored_detection_counts(image_path)
            self.status_var.set(f"Showing processed image: {processed_path.name}")
        else:
            self.show_image(image_path)
            self._set_detection_counts()
            self.status_var.set(f"No processed image yet for {pipeline_name}.")

    def _on_select(self, _event: object) -> None:
        selection = self.image_list.curselection()
        if not selection:
            return

        image_name = self.image_list.get(selection[0])
        image_path = self.current_directory() / image_name
        if image_path.exists():
            self.show_image_for_pipeline(image_path)

    def _on_pipeline_change(self, _selected: str | None = None) -> None:
        selection = self.image_list.curselection()
        if not selection:
            return

        image_name = self.image_list.get(selection[0])
        image_path = self.current_directory() / image_name
        if image_path.exists():
            self.show_image_for_pipeline(image_path)

    def _selected_source_image(self) -> Path | None:
        selection = self.image_list.curselection()
        if not selection:
            return None

        image_name = self.image_list.get(selection[0])
        image_path = self.current_directory() / image_name
        return image_path if image_path.exists() else None

    def process_selected_image(self) -> None:
        image_path = self._selected_source_image()
        if image_path is None:
            messagebox.showerror("No image selected", "Select an image to process.")
            return

        try:
            result = self.app.model_processor.process_image(
                image_path,
                self.pipeline_var.get(),
                self.processed_directory(),
            )
        except Exception as exc:
            messagebox.showerror("Processing failed", str(exc))
            return

        self._store_detection_counts(image_path, self.pipeline_var.get(), result.vehicle_count, result.person_count)
        self.show_image(result.output_path if self.pipeline_var.get() != "Original" else image_path)
        self._set_detection_counts(result.vehicle_count, result.person_count)
        self.status_var.set(
            f"Processed {image_path.name} with {self.pipeline_var.get()}: "
            f"{result.vehicle_count} vehicles, {result.person_count} people."
        )

    def process_all_images(self) -> None:
        images = [
            self.current_directory() / self.image_list.get(index)
            for index in range(self.image_list.size())
        ]
        if not images:
            messagebox.showerror("No images found", "There are no images in the image directory.")
            return

        processed_count = 0
        total_vehicles = 0
        total_people = 0
        for image_path in images:
            if not image_path.exists():
                continue

            try:
                result = self.app.model_processor.process_image(
                    image_path,
                    self.pipeline_var.get(),
                    self.processed_directory(),
                )
            except Exception as exc:
                messagebox.showerror("Processing failed", f"{image_path.name}: {exc}")
                return
            processed_count += 1
            self._store_detection_counts(image_path, self.pipeline_var.get(), result.vehicle_count, result.person_count)
            total_vehicles += result.vehicle_count
            total_people += result.person_count

        if processed_count == 0:
            messagebox.showerror("Processing failed", "No images were processed.")
            return

        selected_image = self._selected_source_image()
        if selected_image is not None:
            self.show_image_for_pipeline(selected_image)
        self.status_var.set(
            f"Processed {processed_count} images with {self.pipeline_var.get()}: "
            f"{total_vehicles} vehicles, {total_people} people."
        )

    def capture_image(self) -> None:
        try:
            image_path = trigger_remote_capture()
        except Exception as exc:
            messagebox.showerror("Capture failed", str(exc))
            return

        self.refresh_images(select_path=image_path)
        self.status_var.set(f"Captured {image_path.name}.")

    def set_camera_mode(self) -> None:
        try:
            message = set_remote_camera_mode(self.camera_mode_var.get())
        except Exception as exc:
            messagebox.showerror("Set mode failed", str(exc))
            return

        self.status_var.set(message)

    def fetch_status(self) -> None:
        try:
            message = get_pi_status()
        except Exception as exc:
            messagebox.showerror("Status failed", str(exc))
            return

        self.status_var.set(message)

    def activate_camera(self) -> None:
        try:
            message = activate_remote_camera()
        except Exception as exc:
            messagebox.showerror("Activate failed", str(exc))
            return

        self.status_var.set(message)
