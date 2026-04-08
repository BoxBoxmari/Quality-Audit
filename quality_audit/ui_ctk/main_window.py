from __future__ import annotations

import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk

from quality_audit.ui_ctk.file_dialogs import (
    ask_open_docx_folder,
    ask_open_docx_paths,
    ask_output_directory,
)
from quality_audit.ui_ctk.runtime_contract import (
    RunSpec,
    discover_docx,
    file_key_for,
    run_spec,
)


class CTKAuditApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Quality Audit")
        self.geometry("1120x760")
        self.minsize(920, 620)

        self.input_source_type: str = "folder"
        self.input_source_path: Optional[Path] = None
        self.selected_files: List[Path] = []
        self.discovered_files: List[Path] = []
        self.base_path: Optional[Path] = None

        self.output_dir_var = ctk.StringVar(value=str(Path.cwd() / "results"))
        self.input_path_var = ctk.StringVar(value="")
        self.tax_mode_var = ctk.StringVar(value="all")
        self.tax_all_rate_var = ctk.StringVar(value="15")
        self.tax_default_rate_var = ctk.StringVar(value="15")

        self.tax_row_vars: Dict[str, ctk.StringVar] = {}
        self._worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._running = False
        self._state = "idle"
        self._current_run_started_at: Optional[datetime] = None
        self._progress_processed = 0
        self._progress_total = 0
        self._failed_file_paths: List[Path] = []

        self._disable_when_running: List[ctk.CTkBaseClass] = []

        self._build_ui()
        self._set_state("idle", "Ready")
        self.after(100, self._poll_worker_queue)

    def _build_ui(self) -> None:
        root = ctk.CTkFrame(self)
        root.pack(fill="both", expand=True, padx=14, pady=14)

        # Global scroll container for small screens
        content = ctk.CTkScrollableFrame(root)
        content.pack(fill="both", expand=True)

        ctk.CTkLabel(
            content,
            text="Quality Audit",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 14))

        self._build_input_panel(content)
        self._build_tax_panel(content)
        self._build_output_panel(content)
        self._build_run_panel(content)

        self.log_box = ctk.CTkTextbox(content, height=220, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self._append_log("UI initialized. Runtime uses canonical CLI/batch contracts.")

    def _build_input_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent)
        panel.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(panel, text="Input Source").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self.input_path_entry = ctk.CTkEntry(
            panel,
            textvariable=self.input_path_var,
            placeholder_text="Folder path or DOCX file path",
        )
        self.input_path_entry.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

        btn_row = ctk.CTkFrame(panel)
        btn_row.grid(row=1, column=1, sticky="e", padx=8, pady=(0, 8))

        self.browse_folder_btn = ctk.CTkButton(
            btn_row, text="Browse Folder", width=120, command=self._on_browse_folder
        )
        self.browse_folder_btn.pack(side="left", padx=(0, 6))

        self.browse_multi_btn = ctk.CTkButton(
            btn_row, text="Select Files", width=120, command=self._on_select_files
        )
        self.browse_multi_btn.pack(side="left", padx=(0, 6))

        self.rescan_btn = ctk.CTkButton(
            btn_row, text="Scan", width=90, command=self._on_rescan
        )
        self.rescan_btn.pack(side="left")

        panel.grid_columnconfigure(0, weight=1)

        self.discovery_label = ctk.CTkLabel(panel, text="Files Found: 0", anchor="w")
        self.discovery_label.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 6)
        )

        self.files_listbox = ctk.CTkTextbox(panel, height=120, wrap="none")
        self.files_listbox.grid(
            row=3, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 10)
        )
        self.files_listbox.configure(state="disabled")

        panel.grid_rowconfigure(3, weight=1)

        self._disable_when_running.extend(
            [
                self.input_path_entry,
                self.browse_folder_btn,
                self.browse_multi_btn,
                self.rescan_btn,
            ]
        )

    def _build_tax_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent)
        panel.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(panel, text="Tax Mode").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self.tax_mode_option = ctk.CTkOptionMenu(
            panel,
            values=["all", "individual"],
            variable=self.tax_mode_var,
            command=lambda _v: self._refresh_tax_mode_ui(),
        )
        self.tax_mode_option.grid(row=0, column=1, sticky="w", padx=8, pady=(8, 4))

        self.tax_mode_help = ctk.CTkLabel(
            panel,
            text="All: one rate for all files | Individual: per-file rates",
            anchor="w",
        )
        self.tax_mode_help.grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6)
        )

        # Use a dedicated container for mode-specific frames to avoid
        # mixing grid/pack in the same parent widget.
        self.tax_mode_content = ctk.CTkFrame(panel)
        self.tax_mode_content.grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8)
        )
        self.tax_mode_content.grid_columnconfigure(0, weight=1)

        self.tax_all_frame = ctk.CTkFrame(self.tax_mode_content)
        ctk.CTkLabel(self.tax_all_frame, text="Tax Rate (%)", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(8, 8), pady=8
        )
        self.tax_all_entry = ctk.CTkEntry(
            self.tax_all_frame,
            width=100,
            textvariable=self.tax_all_rate_var,
            placeholder_text="For example: 15",
        )
        self.tax_all_entry.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=8)
        self.tax_all_frame.grid_columnconfigure(2, weight=1)

        self.tax_individual_frame = ctk.CTkFrame(self.tax_mode_content)
        ind_hdr = ctk.CTkFrame(self.tax_individual_frame)
        ind_hdr.pack(fill="x", padx=8, pady=(10, 4))
        ctk.CTkLabel(ind_hdr, text="Default Rate (%)", anchor="w").pack(
            side="left", padx=(0, 8)
        )
        self.tax_default_entry = ctk.CTkEntry(
            ind_hdr,
            width=100,
            textvariable=self.tax_default_rate_var,
            placeholder_text="For example: 15",
        )
        self.tax_default_entry.pack(side="left", padx=(0, 8))
        self.apply_bulk_btn = ctk.CTkButton(
            ind_hdr,
            text="Apply to All",
            width=110,
            command=self._apply_bulk_rate,
        )
        self.apply_bulk_btn.pack(side="left")

        self.individual_rows_frame = ctk.CTkScrollableFrame(
            self.tax_individual_frame,
            height=140,
            label_text="Per-file Rates",
        )
        self.individual_rows_frame.pack(fill="x", padx=8, pady=(4, 8))

        panel.grid_columnconfigure(2, weight=1)
        self._disable_when_running.extend(
            [
                self.tax_mode_option,
                self.tax_all_entry,
                self.tax_default_entry,
                self.apply_bulk_btn,
            ]
        )
        self._refresh_tax_mode_ui()

    def _build_output_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent)
        panel.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(panel, text="Output Folder").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self.output_entry = ctk.CTkEntry(panel, textvariable=self.output_dir_var)
        self.output_entry.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.pick_output_btn = ctk.CTkButton(
            panel, text="Browse Output Folder", command=self._on_pick_output
        )
        self.pick_output_btn.grid(row=1, column=1, sticky="e", padx=8, pady=(0, 8))
        panel.grid_columnconfigure(0, weight=1)

        self._disable_when_running.extend([self.output_entry, self.pick_output_btn])

    def _build_run_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent)
        panel.pack(fill="x", padx=12, pady=(6, 8))

        self.run_btn = ctk.CTkButton(panel, text="Run Audit", command=self._on_run)
        self.run_btn.pack(side="left", padx=(8, 6), pady=8)
        self.retry_failed_btn = ctk.CTkButton(
            panel, text="Retry Failed", width=120, command=self._on_retry_failed
        )
        self.retry_failed_btn.pack(side="left", padx=(0, 6), pady=8)
        self.open_output_btn = ctk.CTkButton(
            panel,
            text="Open Output Folder",
            width=150,
            command=self._on_open_output_folder,
        )
        self.open_output_btn.pack(side="left", padx=(0, 8), pady=8)
        self.status_label = ctk.CTkLabel(panel, text="Ready", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=(10, 8))
        self.progress_label = ctk.CTkLabel(panel, text="Progress: 0/0", anchor="e")
        self.progress_label.pack(side="right", padx=(8, 8))
        self._disable_when_running.extend(
            [self.run_btn, self.open_output_btn, self.retry_failed_btn]
        )

    def _append_log(self, text: str) -> None:
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")

    def _set_state(self, state: str, message: str) -> None:
        self._state = state
        self.status_label.configure(text=message)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._disable_when_running:
            widget.configure(state=state)
        for child in self.individual_rows_frame.winfo_children():
            if isinstance(child, ctk.CTkEntry):
                child.configure(state=state)

    def _on_browse_folder(self) -> None:
        selected = ask_open_docx_folder(parent=self)
        if not selected:
            return
        self.input_source_type = "folder"
        self.input_source_path = Path(selected)
        self.selected_files = []
        self.input_path_var.set(selected)
        self._on_rescan()

    def _on_select_files(self) -> None:
        paths = ask_open_docx_paths(parent=self)
        if not paths:
            return
        self.input_source_type = "multi_files"
        self.selected_files = [Path(p).resolve() for p in paths]
        self.input_source_path = None
        first = self.selected_files[0]
        self.input_path_var.set(f"{first} (+{len(self.selected_files)-1} more)")
        self._on_rescan()

    def _on_pick_output(self) -> None:
        selected = ask_output_directory(
            initial_dir=self.output_dir_var.get(), parent=self
        )
        if not selected:
            return
        self.output_dir_var.set(selected)
        self._append_log(f"Output folder selected: {selected}")

    def _on_open_output_folder(self) -> None:
        raw_output_dir = (self.output_dir_var.get() or "").strip()
        if not raw_output_dir:
            self._append_log("Output folder is empty.")
            self._set_state("error", "Output Folder Required")
            return

        try:
            output_dir = Path(raw_output_dir).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            if not output_dir.is_dir():
                self._append_log("Output path is not a folder.")
                self._set_state("error", "Invalid Output Folder")
                return

            if sys.platform.startswith("win"):
                import os

                os.startfile(str(output_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(output_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(output_dir)], check=False)

            self._append_log(f"Opened output folder: {output_dir}")
        except Exception as e:
            self._append_log(f"Failed to open output folder: {e}")
            self._set_state("error", "Open Output Folder Failed")

    def _detect_source_from_path_entry(self) -> None:
        if self.input_source_type == "multi_files":
            return
        raw = (self.input_path_var.get() or "").strip()
        if not raw:
            self.input_source_path = None
            return
        p = Path(raw)
        self.input_source_path = p
        if p.exists():
            if p.is_dir():
                self.input_source_type = "folder"
            elif p.is_file():
                self.input_source_type = "file"

    def _on_rescan(self) -> None:
        self._detect_source_from_path_entry()
        discovered, base_path = discover_docx(
            self.input_source_type, self.input_source_path, self.selected_files
        )
        self.discovered_files = discovered
        self.base_path = base_path
        self._refresh_discovery_view()
        self._rebuild_individual_tax_rows()
        self._append_log(
            f"Scan complete: source={self.input_source_type}, found={len(discovered)}"
        )

    def _refresh_discovery_view(self) -> None:
        self.discovery_label.configure(
            text=f"Files Found: {len(self.discovered_files)}"
        )
        self.files_listbox.configure(state="normal")
        self.files_listbox.delete("1.0", "end")
        if not self.discovered_files:
            self.files_listbox.insert("end", "No files found.\n")
        for p in self.discovered_files:
            self.files_listbox.insert("end", f"{file_key_for(p, self.base_path)}\n")
        self.files_listbox.configure(state="disabled")

    def _refresh_tax_mode_ui(self) -> None:
        self.tax_all_frame.pack_forget()
        self.tax_individual_frame.pack_forget()
        mode = self.tax_mode_var.get()
        if mode == "all":
            self.tax_all_frame.pack(fill="x", padx=8, pady=(6, 8))
        else:
            self.tax_individual_frame.pack(fill="x", padx=8, pady=(6, 8))

    def _rebuild_individual_tax_rows(self) -> None:
        current_values = {k: v.get() for k, v in self.tax_row_vars.items()}
        self.tax_row_vars.clear()
        for w in self.individual_rows_frame.winfo_children():
            w.destroy()

        default_text = self.tax_default_rate_var.get() or "15"
        for i, p in enumerate(self.discovered_files):
            key = file_key_for(p, self.base_path)
            ctk.CTkLabel(self.individual_rows_frame, text=key, anchor="w").grid(
                row=i, column=0, sticky="ew", padx=(8, 8), pady=2
            )
            rate_var = ctk.StringVar(value=current_values.get(key, default_text))
            entry = ctk.CTkEntry(
                self.individual_rows_frame, width=90, textvariable=rate_var
            )
            entry.grid(row=i, column=1, sticky="e", padx=(0, 8), pady=2)
            self.tax_row_vars[key] = rate_var
        self.individual_rows_frame.grid_columnconfigure(0, weight=1)

    def _apply_bulk_rate(self) -> None:
        bulk = (self.tax_default_rate_var.get() or "").strip()
        value = self._parse_rate_percent(bulk, field_name="Default/Bulk rate")
        if value is None:
            return
        for var in self.tax_row_vars.values():
            var.set(str(value))
        self._append_log("Default rate applied to all files.")

    def _parse_rate_percent(self, raw: str, field_name: str) -> Optional[float]:
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            self._append_log(f"Invalid {field_name}: enter a numeric value.")
            self._set_state("error", f"Invalid {field_name}")
            return None
        if not (0.0 <= value <= 100.0):
            self._append_log(f"Invalid {field_name}: must be between 0 and 100.")
            self._set_state("error", f"Invalid {field_name}")
            return None
        return value

    def _build_run_spec(self) -> Optional[RunSpec]:
        if not self.discovered_files:
            self._append_log("No DOCX files found to process.")
            self._set_state("error", "Input Files Required")
            return None

        raw_output_dir = (self.output_dir_var.get() or "").strip()
        if not raw_output_dir:
            self._append_log("Please select an output folder.")
            self._set_state("error", "Output Folder Required")
            return None
        output_dir = Path(raw_output_dir)

        mode = self.tax_mode_var.get()
        all_rate: Optional[float] = None
        default_rate: Optional[float] = None
        per_file_rates: Dict[str, float] = {}

        if mode == "all":
            all_rate = self._parse_rate_percent(self.tax_all_rate_var.get(), "Tax rate")
            if all_rate is None:
                return None
        elif mode == "individual":
            default_rate = self._parse_rate_percent(
                self.tax_default_rate_var.get(), "Default/Bulk rate"
            )
            if default_rate is None:
                return None
            for key, rate_var in self.tax_row_vars.items():
                val = self._parse_rate_percent(rate_var.get(), f"Tax rate for {key}")
                if val is None:
                    return None
                per_file_rates[key] = val

        snapshot = RunSpec(
            input_source_type=self.input_source_type,  # type: ignore[arg-type]
            input_source_path=(
                self.input_source_path.resolve() if self.input_source_path else None
            ),
            selected_files=tuple(p.resolve() for p in self.selected_files),
            discovered_files=tuple(p.resolve() for p in self.discovered_files),
            base_path=self.base_path.resolve() if self.base_path else None,
            output_dir=output_dir.resolve(),
            tax_mode=mode,  # type: ignore[arg-type]
            all_rate_percent=all_rate,
            default_rate_percent=default_rate,
            per_file_rates_percent=per_file_rates,
            cache_size=1000,
            log_level="INFO",
            previous_output=None,
        )
        return snapshot

    def _on_run(self) -> None:
        if self._running:
            return
        self._set_state("idle", "Validating...")
        run_snapshot = self._build_run_spec()
        if run_snapshot is None:
            return

        self._running = True
        self._current_run_started_at = datetime.now()
        self._progress_processed = 0
        self._progress_total = len(run_snapshot.discovered_files)
        self.progress_label.configure(
            text=f"Progress: {self._progress_processed}/{self._progress_total}"
        )
        self._failed_file_paths = []
        self.retry_failed_btn.configure(state="disabled")
        self._set_state("running", "Running...")
        self.run_btn.configure(text="Running...")
        self._set_controls_enabled(False)
        self._append_log("Audit started.")

        thread = threading.Thread(
            target=self._run_worker,
            args=(run_snapshot,),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, snapshot: RunSpec) -> None:
        try:
            exit_code = run_spec(
                snapshot,
                lambda msg: self._worker_queue.put(("log", msg)),
                progress=lambda p: self._worker_queue.put(("progress", p)),
            )
            self._worker_queue.put(("done", exit_code))
        except Exception as e:
            self._worker_queue.put(("error", str(e)))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self._worker_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "progress" and isinstance(payload, dict):
                    self._on_progress(payload)
                elif kind == "done":
                    self._on_run_complete(int(payload), None)
                elif kind == "error":
                    self._on_run_complete(1, str(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll_worker_queue)

    def _on_run_complete(self, exit_code: int, error_message: Optional[str]) -> None:
        self._running = False
        elapsed = None
        if self._current_run_started_at is not None:
            elapsed = datetime.now() - self._current_run_started_at
        self._current_run_started_at = None
        self._set_controls_enabled(True)

        if error_message:
            self._set_state("error", "Execution Error")
            self._append_log(f"Error: {error_message}")
        elif exit_code == 0:
            done_msg = "Completed"
            if elapsed is not None:
                total_seconds = int(elapsed.total_seconds())
                done_msg += f" ({total_seconds // 60:02d}:{total_seconds % 60:02d})"
            self._set_state("done", done_msg)
            self._append_log("Audit completed successfully.")
            self.after(2500, lambda: self._set_state("idle", "Ready"))
        else:
            self._set_state("error", "Execution Failed")
            self._append_log("Audit finished with failures. See log output above.")
            if self._failed_file_paths:
                self.retry_failed_btn.configure(state="normal")
        self.run_btn.configure(text="Run Audit")
        if self._progress_total == 0:
            self.progress_label.configure(text="Progress: 0/0")

    def _on_progress(self, payload: Dict[str, object]) -> None:
        processed = int(payload.get("processed", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        current_file = str(payload.get("current_file", "") or "")
        success = bool(payload.get("success", False))
        error = str(payload.get("error", "") or "")
        error_code = str(payload.get("error_code", "") or "")
        stage = str(payload.get("stage", "") or "")

        self._progress_processed = processed
        self._progress_total = total
        self.progress_label.configure(text=f"Progress: {processed}/{total}")

        if current_file:
            self.status_label.configure(
                text=f"Running {processed}/{total}: {current_file}"
            )

        if not success and current_file:
            failed = next(
                (p for p in self.discovered_files if p.name == current_file),
                None,
            )
            if failed is not None and failed not in self._failed_file_paths:
                self._failed_file_paths.append(failed)
            if error:
                code_part = f" [{error_code}]" if error_code else ""
                stage_part = f" ({stage})" if stage else ""
                self._append_log(
                    f"FAILED{code_part}{stage_part} {current_file}: {error}"
                )

    def _on_retry_failed(self) -> None:
        if self._running or not self._failed_file_paths:
            return
        self.input_source_type = "multi_files"
        self.selected_files = [p.resolve() for p in self._failed_file_paths]
        self.input_source_path = None
        first = self.selected_files[0]
        self.input_path_var.set(f"{first} (+{len(self.selected_files)-1} more)")
        self._on_rescan()
        self._append_log(
            f"Retry mode: selected {len(self.selected_files)} failed file(s) from previous run."
        )
        self._on_run()


def launch_ctk() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = CTKAuditApp()
    app.mainloop()
