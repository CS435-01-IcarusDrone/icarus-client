from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import config
from app_services import connect_to_pi_api, ensure_directory, get_pi_status, update_config_values, upload_pi_config


class ConfigTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "DroneManagerApp") -> None:
        super().__init__(master, padding=16)
        self.app = app

        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Image Quality").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.quality_var = tk.StringVar(value=str(config.IMAGE_QUALITY))
        ttk.Entry(self, textvariable=self.quality_var, width=12).grid(row=0, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Image Directory").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.directory_var = tk.StringVar(value=config.IMAGE_DIRECTORY)
        ttk.Entry(self, textvariable=self.directory_var).grid(row=1, column=1, sticky="ew", pady=(0, 10))
        ttk.Button(self, text="Browse", command=self.choose_directory).grid(row=1, column=2, padx=(12, 0), pady=(0, 10))

        ttk.Separator(self, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 12))

        ttk.Label(self, text="Pi API Base URL").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_base_url_var = tk.StringVar(value=config.PI_API_BASE_URL)
        ttk.Entry(self, textvariable=self.pi_api_base_url_var).grid(row=3, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Config Endpoint").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_config_endpoint_var = tk.StringVar(value=config.PI_API_CONFIG_ENDPOINT)
        ttk.Entry(self, textvariable=self.pi_api_config_endpoint_var).grid(row=4, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Capture Endpoint").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_capture_endpoint_var = tk.StringVar(value=config.PI_API_CAPTURE_ENDPOINT)
        ttk.Entry(self, textvariable=self.pi_api_capture_endpoint_var).grid(row=5, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Activate Endpoint").grid(row=6, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_activate_endpoint_var = tk.StringVar(value=config.PI_API_ACTIVATE_ENDPOINT)
        ttk.Entry(self, textvariable=self.pi_api_activate_endpoint_var).grid(row=6, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Set Mode Endpoint").grid(row=7, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_set_mode_endpoint_var = tk.StringVar(value=config.PI_API_SET_MODE_ENDPOINT)
        ttk.Entry(self, textvariable=self.pi_api_set_mode_endpoint_var).grid(row=7, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Status Endpoint").grid(row=8, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_status_endpoint_var = tk.StringVar(value=config.PI_API_STATUS_ENDPOINT)
        ttk.Entry(self, textvariable=self.pi_api_status_endpoint_var).grid(row=8, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="API Timeout (s)").grid(row=9, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.pi_api_timeout_var = tk.StringVar(value=str(config.PI_API_TIMEOUT_SECONDS))
        ttk.Entry(self, textvariable=self.pi_api_timeout_var, width=12).grid(row=9, column=1, sticky="ew", pady=(0, 10))

        ttk.Button(self, text="Save Local Config", command=self.save_config).grid(row=10, column=0, sticky="w", pady=(8, 0))
        ttk.Button(self, text="Save + Upload To Pi", command=self.save_and_upload_config).grid(row=10, column=1, sticky="w", pady=(8, 0))
        ttk.Button(self, text="Connect", command=self.connect).grid(row=10, column=2, sticky="w", pady=(8, 0))
        ttk.Button(self, text="Status", command=self.status).grid(row=10, column=3, sticky="w", pady=(8, 0))

        self.status_var = tk.StringVar(value="Config loaded.")
        ttk.Label(self, textvariable=self.status_var).grid(row=11, column=0, columnspan=4, sticky="w", pady=(16, 0))

    def choose_directory(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(Path(self.directory_var.get()).expanduser()))
        if selected:
            self.directory_var.set(selected)

    def save_config(self) -> None:
        saved = self._persist_config_values()
        if saved:
            self.status_var.set("Config saved locally to config.json.")

    def save_and_upload_config(self) -> None:
        saved = self._persist_config_values()
        if not saved:
            return

        try:
            message = upload_pi_config()
        except Exception as exc:
            messagebox.showerror("Upload failed", str(exc))
            self.status_var.set("Local config saved, but Pi upload failed.")
            return

        self.app.mark_pi_config_uploaded()
        self.status_var.set(f"Config saved locally and uploaded to the Raspberry Pi API. {message}")

    def connect(self) -> None:
        saved = self._persist_config_values()
        if not saved:
            return

        try:
            message = connect_to_pi_api()
        except Exception as exc:
            messagebox.showerror("Connection failed", str(exc))
            self.status_var.set("Could not connect to the Raspberry Pi API.")
            return

        self.status_var.set(message)

    def status(self) -> None:
        saved = self._persist_config_values()
        if not saved:
            return

        try:
            message = get_pi_status()
        except Exception as exc:
            messagebox.showerror("Status failed", str(exc))
            self.status_var.set("Could not fetch Raspberry Pi status.")
            return

        self.status_var.set(message)

    def _persist_config_values(self) -> bool:
        try:
            quality = int(self.quality_var.get())
        except ValueError:
            messagebox.showerror("Invalid quality", "Image quality must be an integer.")
            return False

        if quality < 1 or quality > 100:
            messagebox.showerror("Invalid quality", "Image quality must be between 1 and 100.")
            return False

        directory = self.directory_var.get().strip()
        if not directory:
            messagebox.showerror("Invalid directory", "Image directory cannot be empty.")
            return False

        try:
            timeout_seconds = float(self.pi_api_timeout_var.get())
        except ValueError:
            messagebox.showerror("Invalid timeout", "API timeout must be a number.")
            return False

        if timeout_seconds <= 0:
            messagebox.showerror("Invalid timeout", "API timeout must be greater than zero.")
            return False

        pi_api_base_url = self.pi_api_base_url_var.get().strip()
        pi_api_config_endpoint = self.pi_api_config_endpoint_var.get().strip()
        pi_api_capture_endpoint = self.pi_api_capture_endpoint_var.get().strip()
        pi_api_activate_endpoint = self.pi_api_activate_endpoint_var.get().strip()
        pi_api_set_mode_endpoint = self.pi_api_set_mode_endpoint_var.get().strip()
        pi_api_status_endpoint = self.pi_api_status_endpoint_var.get().strip()
        if not pi_api_base_url or not pi_api_config_endpoint or not pi_api_capture_endpoint or not pi_api_activate_endpoint or not pi_api_set_mode_endpoint or not pi_api_status_endpoint:
            messagebox.showerror("Invalid API config", "Pi API base URL and endpoints are required.")
            return False

        resolved_directory = str(ensure_directory(directory))
        update_config_values({
            "IMAGE_QUALITY": quality,
            "IMAGE_DIRECTORY": resolved_directory,
            "PI_API_BASE_URL": pi_api_base_url,
            "PI_API_CONFIG_ENDPOINT": pi_api_config_endpoint,
            "PI_API_CAPTURE_ENDPOINT": pi_api_capture_endpoint,
            "PI_API_ACTIVATE_ENDPOINT": pi_api_activate_endpoint,
            "PI_API_SET_MODE_ENDPOINT": pi_api_set_mode_endpoint,
            "PI_API_STATUS_ENDPOINT": pi_api_status_endpoint,
            "PI_API_TIMEOUT_SECONDS": timeout_seconds,
        })

        self.quality_var.set(str(config.IMAGE_QUALITY))
        self.directory_var.set(config.IMAGE_DIRECTORY)
        self.pi_api_base_url_var.set(config.PI_API_BASE_URL)
        self.pi_api_config_endpoint_var.set(config.PI_API_CONFIG_ENDPOINT)
        self.pi_api_capture_endpoint_var.set(config.PI_API_CAPTURE_ENDPOINT)
        self.pi_api_activate_endpoint_var.set(config.PI_API_ACTIVATE_ENDPOINT)
        self.pi_api_set_mode_endpoint_var.set(config.PI_API_SET_MODE_ENDPOINT)
        self.pi_api_status_endpoint_var.set(config.PI_API_STATUS_ENDPOINT)
        self.pi_api_timeout_var.set(str(config.PI_API_TIMEOUT_SECONDS))
        self.app.refresh_from_config()
        return True
