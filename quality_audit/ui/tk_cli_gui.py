import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from quality_audit.cli import main as cli_main
from quality_audit.ui.command_format import flatten_cmd, format_cmd_preview
from quality_audit.ui.settings_store import load_settings, save_settings
from quality_audit.ui.styles import (
    COLORS,
    FONTS,
    PADDING_SECTION,
    SPACING,
    apply_dark_theme,
)


class RedirectText:
    """Redirects stdout/stderr to a queue."""

    def __init__(self, queue_obj, tags=None):
        self.queue = queue_obj
        self.tags = tags or []

    def write(self, string):
        if string:
            self.queue.put((string, self.tags))

    def flush(self):
        pass


class QualityAuditGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Quality Audit — KPMG style")
        self.geometry("1280x780")
        self.minsize(1100, 700)

        # Apply Theme
        apply_dark_theme(self)
        self.configure(bg=COLORS["bg_primary"])

        # State
        try:
            # Assume we are in tool_root/quality_audit/ui or tool_root
            # Main entry usually from tool root
            self.tool_root = Path.cwd()
        except Exception:
            self.tool_root = Path(".")

        # Window/taskbar icon (E: commercial product feel) - after tool_root is set
        self._set_window_icon()

        self.discovered_files: List[Path] = []
        self.cancel_flag = False  # Not fully effective for CLI but flags UI state
        self.log_queue = queue.Queue()
        self.is_running = False
        self.ui_state = "idle"  # States: idle, scanning, ready, running, done, error

        # Load settings for banner preference
        settings = load_settings(self.tool_root)
        # banner_collapsed=True means expanded=False (inverted)
        banner_collapsed = settings.get("banner_collapsed", True)  # Default collapsed
        self.header_expanded = not banner_collapsed
        self.run_start_time: datetime | None = None
        self.elapsed_timer_id: str | None = None

        # Tax rate data model
        self.tax_rates: dict[str, float] = {}  # key = file path, value = rate
        self.default_tax_rate: float = 25.0  # from bulk_rate_var
        self.tax_rate_errors: dict[
            str, str
        ] = {}  # key = file path, value = error message
        self.tax_edit_entry: ttk.Entry | None = None  # current editing entry overlay
        self.tax_edit_item: str | None = None  # current editing item ID

        self._last_status_text = "Ready"
        self._last_error = (
            ""  # Persisted after messagebox.showerror for status bar / row
        )
        self._init_ui()
        self._on_rescan()  # Initial scan
        self._bind_cursor_for_buttons()
        self._bind_path_status_tooltips()
        self._bind_run_tooltip_and_input_tip()  # H: Run tooltip + first-time input tip
        self._init_help_menu()

        # Start log polling
        self._poll_log_queue()

        # Initialize state
        self.set_state("idle", "Ready")

        # G: First-run onboarding (Quick start once, "Don't show again")
        self.after(300, self._maybe_show_quick_start)

        # Check for debug environment variable
        if os.environ.get("QA_GUI_DEBUG_LAYOUT") == "1":
            self.after(500, self._debug_layout)

    def _init_ui(self):
        # Header - Collapsible
        header_container = ttk.Frame(self)
        header_container.pack(fill="x", padx=SPACING["base"], pady=SPACING["sm"])

        # Top bar (always visible)
        header_top = ttk.Frame(header_container)
        header_top.pack(fill="x")

        title_label = ttk.Label(
            header_top,
            text="Quality Audit — KPMG style",
            font=FONTS["ui"],
        )
        title_label.pack(side="left")

        self.header_toggle_btn = ttk.Button(
            header_top,
            text="[−] Banner",
            command=self._toggle_header,
            width=12,
        )
        self.header_toggle_btn.pack(side="right")

        # Collapsible banner frame
        self.banner_frame = ttk.Frame(header_container)
        self.banner_frame.pack(fill="x", pady=SPACING["sm"])

        banner = r"""
   ____                  _ _ _          _ _ _
  / __ \                | (_) |        | (_) |
 | |  | |_   _  __ _  __| |_| |_ _   _ | |_| |_
 | |  | | | | |/ _` |/ _` | | __| | | || | | __|
 | |__| | |_| | (_| | (_| | | |_| |_| || | | |_
  \___\_\\__,_|\__,_|\__,_|_|\__|\__,_||_|_|\__|
"""
        banner_lbl = tk.Label(
            self.banner_frame,
            text=banner,
            font=("Consolas", 9),  # Smaller font
            bg=COLORS["bg_primary"],
            fg=COLORS["accent"],
            justify="left",
        )
        banner_lbl.pack(side="left")

        # Apply initial banner state (collapsed by default)
        if not self.header_expanded:
            self.banner_frame.pack_forget()
            self.header_toggle_btn.config(text="[+] Banner")

        # Main Content
        main_paned = ttk.PanedWindow(self, orient="horizontal")
        main_paned.pack(
            fill="both", expand=True, padx=SPACING["base"], pady=SPACING["sm"]
        )

        # Left Panel (Inputs) — minsize so pane never shrinks below usable width at 1366x768
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)

        # Right Panel (Outputs)
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)

        # ttk::panedwindow only supports -weight per pane; no -minsize (unlike classic panedwindow).
        # Minimum widths (540 / 400) are enforced by _clamp_sash_position on sash drag and resize.

        # Store references for sash clamping
        self.main_paned = main_paned
        self.left_frame = left_frame
        self.right_frame = right_frame

        # Bind sash movement to clamp positions
        main_paned.bind("<ButtonRelease-1>", self._clamp_sash_position)
        main_paned.bind("<B1-Motion>", self._clamp_sash_position)
        # Clamp on resize so pane widths stay >= min when window is resized
        main_paned.bind(
            "<Configure>", lambda e: self.after_idle(self._clamp_sash_position)
        )

        self._init_left_panel(left_frame)
        self._init_right_panel(right_frame)

        # Enforce pane minimums after first layout (1366x768 and smaller)
        self.after(200, self._clamp_sash_position)

        # Status Bar
        self.status_bar_frame = ttk.Frame(self)
        self.status_bar_frame.pack(
            fill="x", side="bottom", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        # Left group: status dot, status text, elapsed time
        left_group = ttk.Frame(self.status_bar_frame)
        left_group.pack(side="left", fill="x", expand=True)

        # Colored status dot (using Label with background)
        self.status_dot = tk.Label(
            left_group,
            text="●",
            font=("Segoe UI", 12),
            bg=COLORS["bg_primary"],
            fg=COLORS["text_secondary"],
            width=2,
        )
        self.status_dot.pack(side="left", padx=(0, 5))

        self.status_label = ttk.Label(left_group, text="Ready")
        self.status_label.pack(side="left", padx=(0, 10))

        self.elapsed_label = ttk.Label(
            left_group,
            text="",
            foreground=COLORS["text_muted"],
            font=FONTS["ui"],
        )
        self.elapsed_label.pack(side="left")

        # Right group: progress bar
        right_group = ttk.Frame(self.status_bar_frame)
        right_group.pack(side="right", padx=10)

        self.progress_bar = ttk.Progressbar(
            right_group, mode="indeterminate", length=200
        )
        self.progress_bar.pack(side="right")

        # Last error row (shown after messagebox.showerror so user can copy / recall)
        self.last_error_frame = ttk.Frame(self)
        self._last_error_label = ttk.Label(
            self.last_error_frame,
            text="",
            foreground=COLORS["error"],
            font=FONTS["ui"],
        )
        self._last_error_label.pack(side="left", fill="x", expand=True)
        ttk.Button(
            self.last_error_frame,
            text="Clear",
            command=self._clear_last_error,
            width=6,
        ).pack(side="right", padx=(5, 0))

    def _set_last_error(self, msg: str):
        """Store last error and show it in the last-error row (graceful degradation)."""
        self._last_error = msg
        display = msg if len(msg) <= 80 else msg[:77] + "..."
        self._last_error_label.config(text=f"Last error: {display}")
        if not self.last_error_frame.winfo_ismapped():
            self.last_error_frame.pack(
                fill="x", side="bottom", padx=SPACING["sm"], pady=(0, SPACING["xs"])
            )

    def _clear_last_error(self):
        """Clear the last error and hide the row."""
        self._last_error = ""
        self._last_error_label.config(text="")
        if self.last_error_frame.winfo_ismapped():
            self.last_error_frame.pack_forget()

    def set_state(
        self,
        new_state: str,
        message: str | None = None,
        elapsed: timedelta | None = None,
    ):
        """
        Update UI state machine and control visibility/behavior.

        Args:
            new_state: One of idle, scanning, ready, running, done, error, cancel_requested
            message: Optional custom status message
            elapsed: Optional elapsed time to display
        """
        self.ui_state = new_state
        status_text = message or new_state.title()
        self._last_status_text = status_text
        self.status_label.config(text=status_text)

        # Update colored status dot
        if new_state in ("idle", "scanning", "ready"):
            self.status_dot.config(fg=COLORS["text_secondary"])
            self.status_label.config(foreground=COLORS["text_secondary"])
        elif new_state == "running":
            self.status_dot.config(fg=COLORS["accent"])
            self.status_label.config(foreground=COLORS["accent"])
            self.progress_bar.start(10)
        elif new_state == "done":
            self.status_dot.config(fg=COLORS["success"])
            self.status_label.config(foreground=COLORS["success"])
            self.progress_bar.stop()
        elif new_state in ("error", "failed"):
            self.status_dot.config(fg=COLORS["error"])
            self.status_label.config(foreground=COLORS["error"])
            self.progress_bar.stop()
        elif new_state == "cancel_requested":
            self.status_dot.config(fg=COLORS["warning"])
            self.status_label.config(foreground=COLORS["warning"])
            self.progress_bar.stop()

        # Update elapsed time display
        if elapsed is not None:
            total_seconds = int(elapsed.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            elapsed_str = f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.elapsed_label.config(text=elapsed_str)
        elif new_state not in ("running", "done"):
            self.elapsed_label.config(text="")

        # Enable/disable controls
        if new_state == "running":
            self.run_btn.config(state="disabled")
            # Disable input fields during running
            self._set_inputs_enabled(False)
        else:
            # Re-enable inputs
            self._set_inputs_enabled(True)
            # Update RUN button state using can_run_now()
            self._update_run_button_state()

    def _set_inputs_enabled(self, enabled: bool):
        """Enable or disable all input fields."""
        state = "normal" if enabled else "disabled"

        # Path inputs
        if hasattr(self, "input_path_entry"):
            self.input_path_entry.config(state=state)
        if hasattr(self, "output_dir_entry"):
            self.output_dir_entry.config(state=state)
        if hasattr(self, "prev_output_entry"):
            self.prev_output_entry.config(state=state)

        # Options inputs
        if hasattr(self, "cache_size_spinbox"):
            self.cache_size_spinbox.config(state=state)
        if hasattr(self, "log_level_combobox"):
            # Combobox readonly state should remain readonly, but we can disable it
            if state == "disabled":
                self.log_level_combobox.config(state="disabled")
            else:
                self.log_level_combobox.config(state="readonly")

        # Tax rate inputs
        if hasattr(self, "tax_rate_all_entry"):
            self.tax_rate_all_entry.config(state=state)
        if hasattr(self, "bulk_rate_entry"):
            self.bulk_rate_entry.config(state=state)

        # Browse buttons (disable during running)
        # Note: We keep rescan button enabled so user can still scan even while running
        # But we disable browse buttons to prevent path changes during run
        for widget in self.winfo_children():
            if isinstance(widget, ttk.Frame):
                self._disable_browse_buttons(widget, state)

    def _disable_browse_buttons(self, parent, state: str):
        """Recursively disable browse buttons in a frame."""
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Button):
                button_text = widget.cget("text")
                if "Browse" in button_text or button_text in ("Open", "X"):
                    widget.config(state=state)
            elif isinstance(widget, (ttk.Frame, tk.Frame)):
                self._disable_browse_buttons(widget, state)

    def _toggle_header(self):
        """Toggle header banner visibility."""
        self.header_expanded = not self.header_expanded
        if self.header_expanded:
            self.banner_frame.pack(fill="x", pady=SPACING["sm"])
            self.header_toggle_btn.config(text="[−] Banner")
        else:
            self.banner_frame.pack_forget()
            self.header_toggle_btn.config(text="[+] Banner")

        # Save preference (merge so other keys are preserved)
        s = load_settings(self.tool_root)
        s["banner_collapsed"] = not self.header_expanded
        save_settings(self.tool_root, s)
        # K: brief "Preferences saved" feedback
        prev = self._last_status_text
        self._last_status_text = "Preferences saved"
        self.status_label.config(text="Preferences saved")
        self.after(2000, lambda: self._restore_status_after_prefs(prev))

    def _restore_status_after_prefs(self, prev: str) -> None:
        self._last_status_text = prev
        self.status_label.config(text=prev)

    def _flash_done_feedback(self, elapsed: Optional[float] = None) -> None:
        """J: Brief success feedback when Run completes (1–2 s) then revert to Done message."""
        done_text = self._last_status_text  # e.g. "Done — N files"
        self.status_label.config(text="Run completed successfully")
        self.status_label.config(foreground=COLORS["success"])
        self.after(1500, lambda: self._restore_done_status(done_text))

    def _restore_done_status(self, done_text: str) -> None:
        self._last_status_text = done_text
        self.status_label.config(text=done_text)
        self.status_label.config(foreground=COLORS["success"])

    def _set_window_icon(self) -> None:
        """Set window and taskbar icon (E). Tries ui/icon.ico, tool_root/icon.ico, tool_root/assets/icon.ico."""
        bases = [Path(__file__).resolve().parent]
        if hasattr(self, "tool_root") and self.tool_root:
            bases.append(self.tool_root)
            bases.append(self.tool_root / "assets")
        for base in bases:
            ico = base / "icon.ico"
            if not ico.exists():
                continue
            try:
                self.iconbitmap(str(ico))
                return
            except Exception:
                try:
                    png = ico.with_suffix(".png")
                    if png.exists():
                        from tkinter import PhotoImage

                        self.iconphoto(True, PhotoImage(file=str(png)))
                except Exception:
                    pass
                return

    def _maybe_show_quick_start(self) -> None:
        """G: One-time Quick start (3 steps) with Don't show again."""
        if load_settings(self.tool_root).get("quick_start_seen"):
            return
        top = tk.Toplevel(self)
        top.title("Quick start")
        top.transient(self)
        top.geometry("420x220")
        apply_dark_theme(top)
        top.configure(bg=COLORS["bg_primary"])
        f = ttk.Frame(top, padding=PADDING_SECTION)
        f.pack(fill="both", expand=True)
        ttk.Label(
            f,
            text="Quick start",
            font=FONTS["heading_bold"],  # type: ignore[arg-type]
        ).pack(anchor="w")
        ttk.Label(f, text="1. Chọn thư mục Input và Output phía trên.").pack(
            anchor="w", pady=(8, 0)
        )
        ttk.Label(f, text="2. Kiểm tra Tax rate nếu cần.").pack(anchor="w")
        ttk.Label(f, text="3. Bấm Run (Ctrl+Enter).").pack(anchor="w")
        dont_show_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(f, text="Don't show again", variable=dont_show_var)
        cb.pack(anchor="w", pady=(12, 0))

        def on_ok():
            if dont_show_var.get():
                s = load_settings(self.tool_root)
                s["quick_start_seen"] = True
                save_settings(self.tool_root, s)
            top.destroy()

        btn = ttk.Button(f, text="OK", command=on_ok)
        btn.pack(pady=(12, 0))
        top.resizable(False, False)

    def _bind_run_tooltip_and_input_tip(self) -> None:
        """H: Run button tooltip in status bar; first-time tip on Input path focus."""

        def restore_status(*args):
            self.status_label.config(text=self._last_status_text)

        self.run_btn.bind(
            "<Enter>",
            lambda e: self.status_label.config(text="Run audit (Ctrl+Enter)"),
        )
        self.run_btn.bind("<Leave>", restore_status)

        def on_input_focus_in(e):
            if load_settings(self.tool_root).get("input_tip_shown"):
                return
            self.status_label.config(text="Tip: Ctrl+Enter = Run, F5 = Rescan")
            s = load_settings(self.tool_root)
            s["input_tip_shown"] = True
            save_settings(self.tool_root, s)

        self.input_path_entry.bind("<FocusIn>", on_input_focus_in, add="+")

    def _init_left_panel(self, parent):
        # Left panel: row 0 = scrollable content, row 1 = separator, row 2 = sticky Run/Cancel bar
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(
            2, weight=0, minsize=52
        )  # Reserve space so Run/Cancel never hidden
        parent.grid_columnconfigure(0, weight=1)

        # Scrollable area: canvas + scrollbar
        scroll_container = ttk.Frame(parent)
        scroll_container.grid(row=0, column=0, sticky="nsew")
        scroll_container.grid_rowconfigure(0, weight=1)
        scroll_container.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            scroll_container,
            highlightthickness=0,
            bg=COLORS["bg_primary"],
        )
        scrollbar = ttk.Scrollbar(scroll_container)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        scrollbar.config(command=canvas.yview)
        canvas.config(yscrollcommand=scrollbar.set)

        content_frame = ttk.Frame(canvas)
        self._left_canvas = canvas
        self._left_content = content_frame
        self._left_canvas_window = canvas.create_window(
            (0, 0), window=content_frame, anchor="nw"
        )

        def _on_canvas_configure(evt):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(self._left_canvas_window, width=evt.width)

        def _on_content_configure(evt):
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _on_canvas_configure)
        content_frame.bind("<Configure>", _on_content_configure)

        def _on_mousewheel(evt):
            canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")

        def _on_linux_scroll_up(evt):
            canvas.yview_scroll(-1, "units")

        def _on_linux_scroll_down(evt):
            canvas.yview_scroll(1, "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>", _on_linux_scroll_up)
        canvas.bind("<Button-5>", _on_linux_scroll_down)

        self._init_left_panel_content(content_frame)
        self._bind_mousewheel_to_scroll(content_frame, canvas, orient="y")

        # Separator above Run bar (hierarchy: config vs action)
        sep = ttk.Separator(parent, orient="horizontal")
        sep.grid(
            row=1, column=0, sticky="ew", padx=SPACING["sm"], pady=(SPACING["sm"], 4)
        )

        # Sticky Run/Cancel bar (always visible at 1366x768)
        ctrl_frame = ttk.Frame(parent)
        ctrl_frame.grid(
            row=2, column=0, sticky="ew", padx=SPACING["sm"], pady=SPACING["base"]
        )
        self.run_btn = ttk.Button(
            ctrl_frame,
            text="RUN (Ctrl+Enter)",
            command=self._on_run,
            style="Accent.TButton",
        )
        self.run_btn.pack(side="left", fill="x", expand=True, ipady=8)
        ttk.Button(ctrl_frame, text="Cancel", command=self._on_cancel).pack(
            side="right", padx=5
        )

    def _update_left_scroll_region(self):
        """Refresh left-panel canvas scroll region after content size changes (e.g. Individual tax list)."""
        if getattr(self, "_left_canvas", None):
            self._left_canvas.update_idletasks()
            self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all"))

    def _bind_mousewheel_to_scroll(self, widget, target, orient="y"):
        """Bind MouseWheel/Button-4/5 on widget and all descendants so scrolling over content scrolls target."""

        def yscroll(delta_units):
            if orient == "y" and hasattr(target, "yview_scroll"):
                target.yview_scroll(int(-1 * delta_units), "units")
            elif orient == "x" and hasattr(target, "xview_scroll"):
                target.xview_scroll(int(-1 * delta_units), "units")

        def _on_mousewheel(evt):
            yscroll(evt.delta / 120)

        def _on_linux_up(_evt):
            yscroll(-1)

        def _on_linux_down(_evt):
            yscroll(1)

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(
                seq,
                (
                    _on_mousewheel
                    if seq == "<MouseWheel>"
                    else (_on_linux_up if seq == "<Button-4>" else _on_linux_down)
                ),
            )
        for child in widget.winfo_children():
            self._bind_mousewheel_to_scroll(child, target, orient)

    def _init_left_panel_content(self, content):
        # Grid: 4 rows — Paths, Options, Tax Rate, Command Preview
        content.grid_rowconfigure(0, weight=0)
        content.grid_rowconfigure(1, weight=0)
        content.grid_rowconfigure(2, weight=1, minsize=220)
        content.grid_rowconfigure(3, weight=0, minsize=120)
        content.grid_columnconfigure(0, weight=1)

        # --- 1. Paths Section (Top) ---
        paths_frame = ttk.LabelFrame(content, text="1. Paths", padding=PADDING_SECTION)
        paths_frame.grid(
            row=0, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        # Input Path
        input_row = ttk.Frame(paths_frame)
        input_row.pack(fill="x", pady=2)
        ttk.Label(input_row, text="Input folder", width=12).pack(side="left")

        self.input_path_var = tk.StringVar(value=str(self.tool_root / "data"))
        self.input_path_var.trace_add(
            "write",
            lambda *args: (
                self._schedule_update_preview(),
                self._update_run_button_state(),
            ),
        )
        self.input_path_entry = ttk.Entry(input_row, textvariable=self.input_path_var)
        self.input_path_entry.pack(side="left", fill="x", expand=True, padx=8)

        ttk.Button(
            input_row,
            text="Browse Folder…",
            width=14,
            command=self._browse_input_folder,
        ).pack(side="left", padx=2)
        ttk.Button(
            input_row, text="Browse File…", width=14, command=self._browse_input_file
        ).pack(side="left", padx=2)
        ttk.Button(input_row, text="Rescan", width=8, command=self._on_rescan).pack(
            side="left", padx=2
        )

        self.discovery_label = ttk.Label(
            paths_frame,
            text="Found: 0 .docx",
            foreground=COLORS["text_secondary"],
            font=FONTS["ui"],
        )
        self.discovery_label.pack(anchor="w", padx=70)

        # Output Dir
        out_row = ttk.Frame(paths_frame)
        out_row.pack(fill="x", pady=2)
        ttk.Label(out_row, text="Output folder", width=12).pack(side="left")

        self.output_dir_var = tk.StringVar(value=str(self.tool_root / "results"))
        self.output_dir_var.trace_add(
            "write",
            lambda *args: (
                self._schedule_update_preview(),
                self._update_run_button_state(),
            ),
        )
        self.output_dir_entry = ttk.Entry(out_row, textvariable=self.output_dir_var)
        self.output_dir_entry.pack(side="left", fill="x", expand=True, padx=8)

        ttk.Button(
            out_row, text="Browse…", width=14, command=self._browse_output_dir
        ).pack(side="left", padx=2)
        ttk.Button(out_row, text="Open", width=14, command=self._open_output_dir).pack(
            side="left", padx=2
        )

        # Previous Output
        prev_row = ttk.Frame(paths_frame)
        prev_row.pack(fill="x", pady=2)
        ttk.Label(prev_row, text="Previous run", width=12).pack(side="left")

        self.prev_output_var = tk.StringVar()
        self.prev_output_var.trace_add(
            "write", lambda *args: self._schedule_update_preview()
        )
        self.prev_output_entry = ttk.Entry(prev_row, textvariable=self.prev_output_var)
        self.prev_output_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(
            prev_row, text="Browse…", width=14, command=self._browse_prev_output
        ).pack(side="left", padx=2)
        self.prev_clear_btn = ttk.Button(
            prev_row,
            text="Clear",
            width=5,
            command=lambda: self.prev_output_var.set(""),
        )
        self.prev_clear_btn.pack(side="left", padx=1)

        # --- 2. Options Section ---
        opts_frame = ttk.LabelFrame(content, text="2. Options", padding=PADDING_SECTION)
        opts_frame.grid(
            row=1, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        opts_grid = ttk.Frame(opts_frame)
        opts_grid.pack(fill="x")

        ttk.Label(opts_grid, text="Cache size").grid(row=0, column=0, padx=5)
        self.cache_size_var = tk.IntVar(value=1000)
        self.cache_size_spinbox = ttk.Spinbox(
            opts_grid,
            from_=100,
            to=100000,
            increment=100,
            textvariable=self.cache_size_var,
            width=8,
        )
        self.cache_size_spinbox.grid(row=0, column=1)

        ttk.Label(opts_grid, text="Log level").grid(row=0, column=2, padx=10)
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_level_combobox = ttk.Combobox(
            opts_grid,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            textvariable=self.log_level_var,
            width=8,
            state="readonly",
        )
        self.log_level_combobox.grid(row=0, column=3)

        # Auto-open toggle (Moved to grid column 4)
        self.auto_open_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts_grid, text="Auto-open output", variable=self.auto_open_var
        ).grid(row=0, column=4, padx=15, sticky="w")

        # --- 3. Tax Rate Section (Fill Middle) ---
        tax_frame = ttk.LabelFrame(content, text="3. Tax Rate", padding=PADDING_SECTION)
        tax_frame.grid(
            row=2, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        self.tax_mode_var = tk.StringVar(value="all")
        self.tax_mode_var.trace_add(
            "write",
            lambda *args: (self._update_tax_ui(), self._update_run_button_state()),
        )

        mode_row = tk.Frame(tax_frame, bg=COLORS["bg_primary"])
        # Grid mode_row at row 0
        mode_row.grid(row=0, column=0, sticky="ew", pady=2)

        # Configure tax_frame grid
        tax_frame.grid_rowconfigure(0, weight=0)  # Mode row (fixed)
        tax_frame.grid_rowconfigure(1, weight=0)  # Tax status line (fixed)
        tax_frame.grid_rowconfigure(2, weight=1)  # Content frame (expandable)
        tax_frame.grid_columnconfigure(0, weight=1)

        # Tax status line: always visible — "Tax rates valid" or "Tax rates invalid: N errors"
        self.tax_status_label = tk.Label(
            tax_frame,
            text="Tax rates valid",
            font=FONTS["caption"],
            fg=COLORS["success"],
            bg=COLORS["bg_primary"],
        )
        self.tax_status_label.grid(row=1, column=0, sticky="w", padx=5, pady=(0, 4))

        # Style props for tk.Radiobutton in dark mode
        rb_style = {
            "bg": COLORS["bg_primary"],
            "fg": COLORS["text_primary"],
            "selectcolor": COLORS["bg_secondary"],
            "activebackground": COLORS["bg_primary"],
            "activeforeground": COLORS["accent"],
            "font": FONTS["ui"],
            "highlightthickness": 0,
            "bd": 0,
        }

        tk.Radiobutton(
            mode_row,
            text="All Files",
            variable=self.tax_mode_var,
            value="all",
            **rb_style,
        ).pack(side="left", padx=5)

        tk.Radiobutton(
            mode_row,
            text="Individual",
            variable=self.tax_mode_var,
            value="individual",
            **rb_style,
        ).pack(side="left", padx=5)

        tk.Radiobutton(
            mode_row,
            text="Prompt",
            variable=self.tax_mode_var,
            value="prompt",
            **rb_style,
        ).pack(side="left", padx=5)

        # Container for dynamic tools (Set all loop, etc) in header
        self.tax_tools_area = tk.Frame(mode_row, bg=COLORS["bg_primary"])
        self.tax_tools_area.pack(side="right", fill="x", padx=5)

        self.tax_content_frame = ttk.Frame(tax_frame)
        # Configure tax_content_frame grid for child frames
        self.tax_content_frame.grid_rowconfigure(0, weight=1)
        self.tax_content_frame.grid_columnconfigure(0, weight=1)
        # Grid tax_content_frame into tax_frame (row 2, below mode + status)
        self.tax_content_frame.grid(row=2, column=0, sticky="nsew")

        # Will be populated by _update_tax_ui
        self._init_tax_panels()

        # --- 4. Command Preview ---
        cmd_frame = ttk.LabelFrame(
            content, text="4. Command Preview", padding=PADDING_SECTION
        )
        cmd_frame.grid(
            row=3, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        btn_row = ttk.Frame(cmd_frame)
        btn_row.pack(side="right", padx=5, anchor="n", fill="y")

        ttk.Button(btn_row, text="Copy one-line", command=self._copy_command).pack(
            side="top", pady=2
        )
        ttk.Button(
            btn_row, text="Copy multi-line", command=self._copy_command_multiline
        ).pack(side="top", pady=2)

        self.cmd_text = tk.Text(
            cmd_frame,
            height=5,
            font=FONTS["monospace"],
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_secondary"],
            relief="flat",
            wrap="char",
        )
        self.cmd_text.pack(fill="x", side="left", expand=True)

        # Microcopy
        microcopy = ttk.Label(
            cmd_frame,
            text="Copy uses CMD-safe quoting.",
            font=FONTS["ui"],
            foreground=COLORS["text_muted"],
        )
        microcopy.pack(side="bottom", anchor="w", padx=5)

    def _bind_cursor_for_buttons(self, parent=None):
        """Set hand2 cursor on Enter and arrow on Leave for all ttk.Button."""
        parent = parent or self
        top = self.winfo_toplevel()
        for w in parent.winfo_children():
            if isinstance(w, ttk.Button):
                w.bind(
                    "<Enter>",
                    lambda e, t=top: t.config(cursor="hand2"),
                )
                w.bind(
                    "<Leave>",
                    lambda e, t=top: t.config(cursor=""),
                )
            self._bind_cursor_for_buttons(w)

    def _bind_path_status_tooltips(self):
        """Show full path in status bar on path entry hover/focus."""

        def show_path(entry_var):
            path = entry_var.get().strip()
            self.status_label.config(
                text=path if path else "(empty)",
            )

        def restore_status(*args):
            self.status_label.config(text=self._last_status_text)

        for entry, var in [
            (self.input_path_entry, self.input_path_var),
            (self.output_dir_entry, self.output_dir_var),
            (self.prev_output_entry, self.prev_output_var),
        ]:
            entry.bind("<Enter>", lambda e, v=var: show_path(v))
            entry.bind("<Leave>", restore_status)
            entry.bind("<FocusIn>", lambda e, v=var: show_path(v))
            entry.bind("<FocusOut>", restore_status)

        # Tooltip for Clear (previous run): show in status bar (recognition over recall)
        self.prev_clear_btn.bind(
            "<Enter>",
            lambda e: self.status_label.config(text="Clear previous run"),
        )
        self.prev_clear_btn.bind("<Leave>", restore_status)

    def _init_help_menu(self):
        """Add Help menu with keyboard shortcuts and About."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(
            label="Keyboard shortcuts",
            command=self._show_shortcuts,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label="About Quality Audit",
            command=self._show_about,
        )

    def _show_about(self):
        """F: About dialog — version, docs note, settings saved automatically (K)."""
        try:
            from quality_audit import __version__

            version_str = __version__
        except Exception:
            version_str = "—"
        msg = (
            f"Quality Audit — KPMG style\n\n"
            f"Version: {version_str}\n\n"
            "Cài đặt (ví dụ thu gọn banner) được lưu tự động.\n\n"
            "Docs / support: xem README trong thư mục dự án."
        )
        messagebox.showinfo("About Quality Audit", msg)

    def _show_shortcuts(self):
        """Show keyboard shortcuts in a messagebox."""
        msg = (
            "Ctrl+Enter — Run audit\n"
            "F5 — Rescan input path\n"
            "Ctrl+L — Clear log\n"
            "Tab — Move focus (Paths → Options → Tax → Preview → Run)"
        )
        messagebox.showinfo("Keyboard shortcuts", msg)

    def _init_tax_panels(self):
        # All Mode Panel (Moved to Header self.tax_tools_area)
        self.all_header_tools = tk.Frame(self.tax_tools_area, bg=COLORS["bg_primary"])

        # We use tk.Label to ensure background matches the header container
        tk.Label(
            self.all_header_tools,
            text="Default rate (%):",
            bg=COLORS["bg_primary"],
            fg=COLORS["accent"],
            font=FONTS["ui"],
        ).pack(side="left")

        self.tax_rate_all_var = tk.DoubleVar(value=25.0)
        self.tax_rate_all_var.trace_add(
            "write",
            lambda *args: (
                self._schedule_update_preview(),
                self._update_run_button_state(),
            ),
        )
        self.tax_rate_all_entry = ttk.Entry(
            self.all_header_tools, textvariable=self.tax_rate_all_var, width=6
        )
        self.tax_rate_all_entry.pack(side="left", padx=5)
        ttk.Button(
            self.all_header_tools,
            text="Sets 25%",
            command=lambda: self.tax_rate_all_var.set(25.0),
        ).pack(side="left")

        # Individual Mode Panel
        self.tax_indiv_frame = ttk.Frame(self.tax_content_frame)

        # Tools row (Moved to Header self.tax_tools_area)
        self.indiv_header_tools = tk.Frame(self.tax_tools_area, bg=COLORS["bg_primary"])

        # We need custom labels because parent is tk.Frame (bg required)
        tk.Label(
            self.indiv_header_tools,
            text="Set all (%):",
            bg=COLORS["bg_primary"],
            fg=COLORS["accent"],
            font=FONTS["ui"],
        ).pack(side="left")

        self.bulk_rate_var = tk.DoubleVar(value=25.0)
        self.bulk_rate_entry = ttk.Entry(
            self.indiv_header_tools, textvariable=self.bulk_rate_var, width=6
        )
        self.bulk_rate_entry.pack(side="left", padx=2)
        ttk.Button(
            self.indiv_header_tools,
            text="Apply to all rows",
            command=self._apply_bulk_rate,
            width=14,
        ).pack(side="left")

        # Configure tax_indiv_frame grid
        self.tax_indiv_frame.grid_rowconfigure(0, weight=0)  # Help text row
        self.tax_indiv_frame.grid_rowconfigure(1, weight=0)  # Error label row
        self.tax_indiv_frame.grid_rowconfigure(
            2, weight=1, minsize=160
        )  # Treeview container (expandable)
        self.tax_indiv_frame.grid_columnconfigure(0, weight=1)

        # Help text
        help_label = tk.Label(
            self.tax_indiv_frame,
            text="Rates are percent (0–100). Example: 20 = 20%.",
            bg=COLORS["bg_primary"],
            fg=COLORS["text_muted"],
            font=FONTS["ui"],
        )
        help_label.grid(row=0, column=0, sticky="w", padx=5, pady=2)

        # Error label (initially hidden)
        self.tax_error_label = tk.Label(
            self.tax_indiv_frame,
            text="",
            bg=COLORS["bg_primary"],
            fg=COLORS["error"],
            font=FONTS["ui"],
        )
        self.tax_error_label.grid(row=1, column=0, sticky="w", padx=5, pady=2)

        # Treeview container frame
        tax_table_container = ttk.Frame(self.tax_indiv_frame)
        tax_table_container.grid(row=2, column=0, sticky="nsew")

        # Configure tax_table_container grid
        tax_table_container.grid_rowconfigure(0, weight=1)
        tax_table_container.grid_columnconfigure(0, weight=1)

        # Treeview
        cols = ("file", "rate", "override")
        self.tax_tree = ttk.Treeview(
            tax_table_container, columns=cols, show="headings", height=6
        )
        self.tax_tree.heading("file", text="File")
        self.tax_tree.heading("rate", text="Rate %")
        self.tax_tree.heading("override", text="Override")
        self.tax_tree.column("file", width=420, stretch=True)
        self.tax_tree.column("rate", width=90, anchor="e", stretch=False)
        self.tax_tree.column("override", width=90, anchor="center", stretch=False)

        # Tags for styling
        self.tax_tree.tag_configure("override", foreground=COLORS["accent"])
        self.tax_tree.tag_configure("error", foreground=COLORS["error"])

        vsb = ttk.Scrollbar(
            tax_table_container, orient="vertical", command=self.tax_tree.yview
        )
        self.tax_tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(
            tax_table_container, orient="horizontal", command=self.tax_tree.xview
        )
        self.tax_tree.configure(xscrollcommand=hsb.set)

        self.tax_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Edit on double click
        self.tax_tree.bind("<Double-1>", self._on_tax_tree_double_click)
        self._bind_mousewheel_to_scroll(self.tax_tree, self.tax_tree, orient="y")

        # Prompt Mode Panel
        self.tax_prompt_frame = ttk.Frame(self.tax_content_frame)
        ttk.Label(
            self.tax_prompt_frame,
            text="Interactive mode: CLI will ask for tax rates if needed.",
            foreground=COLORS["accent"],
        ).pack(pady=10)

    def _init_right_panel(self, parent):
        # Configure right_frame grid
        parent.grid_rowconfigure(0, weight=1)  # Terminal output (expandable)
        parent.grid_rowconfigure(1, weight=0, minsize=120)  # Summary (fixed minimum)
        parent.grid_columnconfigure(0, weight=1)

        # Terminal Output
        self.log_frame = ttk.LabelFrame(parent, text="Terminal Output", padding=10)
        self.log_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Configure log_frame grid
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=0)  # Toolbar row
        self.log_frame.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            self.log_frame,
            font=FONTS["log"],
            bg=COLORS["bg_primary"],
            fg=COLORS["text_primary"],
            relief="flat",
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(
            self.log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self._bind_mousewheel_to_scroll(self.log_text, self.log_text, orient="y")

        # Tags
        self.log_text.tag_config("INFO", foreground=COLORS["text_primary"])
        self.log_text.tag_config("WARNING", foreground=COLORS["warning"])
        self.log_text.tag_config("ERROR", foreground=COLORS["error"])
        self.log_text.tag_config("SUCCESS", foreground=COLORS["success"])
        self.log_text.tag_config("placeholder", foreground=COLORS["text_muted"])

        # Show idle placeholder
        self._show_idle_placeholder()

        toolbar = ttk.Frame(self.log_frame)
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.autoscroll_var).pack(
            side="left"
        )
        ttk.Button(toolbar, text="Clear", command=self._clear_log).pack(
            side="right", padx=2
        )
        ttk.Button(toolbar, text="Save Log", command=self._save_log).pack(
            side="right", padx=2
        )

        # Summary
        sum_frame = ttk.LabelFrame(parent, text="Run Summary", padding=10)
        sum_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        self.summary_text = tk.Text(
            sum_frame,
            height=6,
            font=FONTS["monospace"],
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_primary"],
            relief="flat",
            state="disabled",
        )
        self.summary_text.pack(fill="both", expand=True)

        # Tags
        self.summary_text.tag_config("placeholder", foreground=COLORS["text_muted"])

        # Show empty state with guidance (F-pattern: first content = instructions)
        _empty_guidance = (
            "No run yet. Summary will appear here after RUN.\n\n"
            "Quick start: (1) Choose Input and Output folders above, "
            "(2) Check Tax rate if needed, (3) Click Run."
        )
        self.summary_text.config(state="normal")
        self.summary_text.insert("1.0", _empty_guidance, "placeholder")
        self.summary_text.config(state="disabled")

        btn_row = ttk.Frame(sum_frame)
        btn_row.pack(fill="x", pady=(5, 0))
        ttk.Button(
            btn_row, text="Open Output Folder", command=self._open_output_dir
        ).pack(side="right")

    # Logic Methods
    def _schedule_update_preview(self):
        self.after(100, self._update_command_preview)

    def _update_tax_ui(self):
        mode = self.tax_mode_var.get()
        # Hide all
        if hasattr(self, "all_header_tools"):
            self.all_header_tools.pack_forget()
        self.tax_indiv_frame.grid_remove()
        self.tax_prompt_frame.grid_remove()
        if hasattr(self, "indiv_header_tools"):
            self.indiv_header_tools.pack_forget()

        if mode == "all":
            if hasattr(self, "all_header_tools"):
                self.all_header_tools.pack(side="right")
            # Enable Run button for "all" mode
            if self.ui_state != "running":
                self.run_btn.config(state="normal")
        elif mode == "individual":
            self.tax_indiv_frame.grid(row=0, column=0, sticky="nsew")
            if hasattr(self, "indiv_header_tools"):
                self.indiv_header_tools.pack(side="right")
            # Validate and update override indicators
            if hasattr(self, "tax_tree") and self.tax_tree.get_children():
                self._update_override_indicators()
                is_valid, _ = self._validate_tax_rates()
                # Update Run button based on validation
                if self.ui_state != "running":
                    if is_valid:
                        self.run_btn.config(state="normal")
                    else:
                        self.run_btn.config(state="disabled")
        else:
            self.tax_prompt_frame.grid(row=0, column=0, sticky="ew")
            # Enable Run button for "prompt" mode
            if self.ui_state != "running":
                self.run_btn.config(state="normal")

        # Update RUN button state after mode switch
        self._update_run_button_state()

        self._schedule_update_preview()
        # Refresh scroll region after layout changes (Individual adds tall file list)
        self.after(100, self._update_left_scroll_region)

    def _browse_input_folder(self):
        path = filedialog.askdirectory(initialdir=self.tool_root)
        if path:
            self.input_path_var.set(path)
            self._on_rescan()

    def _browse_input_file(self):
        path = filedialog.askopenfilename(filetypes=[("Word Documents", "*.docx")])
        if path:
            self.input_path_var.set(path)
            self._on_rescan()

    def _browse_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.tool_root)
        if path:
            self.output_dir_var.set(path)

    def _browse_prev_output(self):
        path = filedialog.askopenfilename(filetypes=[("Excel Files", "*.xlsx")])
        if path:
            self.prev_output_var.set(path)

    def _open_output_dir(self):
        path = self.output_dir_var.get()
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("Error", "Output directory does not exist")
            self._set_last_error("Output directory does not exist")

    def _open_path_in_os(self, path_obj: Path):
        """Best effort open file or folder."""
        try:
            if not path_obj.exists():
                return
            if sys.platform == "win32":
                os.startfile(str(path_obj))
            elif sys.platform == "darwin":
                import subprocess

                subprocess.run(["open", str(path_obj)], check=False)
            else:
                import subprocess

                subprocess.run(["xdg-open", str(path_obj)], check=False)
        except Exception as e:
            # We can log to queue if we want, but usually this runs in main thread
            # showing in console is safer or ignored
            print(f"Failed to auto-open: {e}")

    def _on_rescan(self):
        path_str = self.input_path_var.get().strip()
        if not path_str:
            self.set_state("idle", "Ready")
            return

        self.set_state("scanning", "Scanning…")

        path = Path(path_str)
        found = []
        if path.is_file() and path.suffix.lower() == ".docx":
            found = [path]
            base_path = path.parent
        elif path.is_dir():
            found = sorted(
                [p for p in path.rglob("*.docx") if not p.name.startswith("~$")]
            )
            base_path = path
        else:
            # Invalid path, clear
            self.discovered_files = []
            self.discovery_label.config(text="Found: 0 .docx")
            self.tax_tree.delete(*self.tax_tree.get_children())
            self.set_state("idle", "Ready")
            return

        self.discovered_files = found
        self.discovery_label.config(text=f"Found: {len(found)} .docx")

        # Update individual tax table using relative paths
        self.tax_tree.delete(*self.tax_tree.get_children())
        self.tax_rates = {}  # Reset tax rates dict
        self.tax_rate_errors = {}  # Reset errors
        default_rate = self.bulk_rate_var.get()
        self.default_tax_rate = default_rate

        for f in found:
            try:
                rel_path = str(f.relative_to(base_path).as_posix())
            except ValueError:
                rel_path = f.name
            # Initialize tax rate in dict
            self.tax_rates[rel_path] = default_rate
            self.tax_tree.insert("", "end", values=(rel_path, str(default_rate), "No"))

        # Update override indicators
        self._update_override_indicators()

        # Set state and update Run button
        # set_state will handle Run button enable/disable based on validation
        self.set_state("ready", "Ready")

        # Also update RUN button state explicitly
        self._update_run_button_state()

        self._schedule_update_preview()

    def _apply_bulk_rate(self):
        """Apply bulk rate to all rows with validation."""
        try:
            rate_str = str(self.bulk_rate_var.get()).strip().replace(",", ".")
            rate = float(rate_str)

            # Validate range
            if not (0 <= rate <= 100):
                self.tax_rate_errors["_bulk"] = "Invalid rate: must be 0–100"
                self._update_tax_error_display()
                return

            # Clear bulk error if valid
            if "_bulk" in self.tax_rate_errors:
                del self.tax_rate_errors["_bulk"]

            # Update default rate
            self.default_tax_rate = rate

            # Apply to all rows
            for item in self.tax_tree.get_children():
                fname = self.tax_tree.item(item)["values"][0]
                # Update dict
                self.tax_rates[fname] = rate
                # Clear any error for this file
                if fname in self.tax_rate_errors:
                    del self.tax_rate_errors[fname]
                # Update tree
                self.tax_tree.item(item, values=(fname, str(rate), "No"))

            # Clear all errors since we're applying a valid rate
            self.tax_rate_errors.clear()

            # Update override indicators
            self._update_override_indicators()

            # Update error display
            self._update_tax_error_display()

            # Update RUN button
            self._update_run_button_state()
        except ValueError:
            self.tax_rate_errors["_bulk"] = "Invalid rate format: must be a number"
            self._update_tax_error_display()
            self._update_run_button_state()

    def _update_override_indicators(self):
        """Update override column based on default rate."""
        try:
            # Update default_tax_rate from bulk_rate_var
            self.default_tax_rate = self.bulk_rate_var.get()

            for item in self.tax_tree.get_children():
                vals = list(self.tax_tree.item(item)["values"])
                if len(vals) < 1:
                    continue

                file_key = vals[0]

                # Get rate from dict if available, otherwise from tree
                if file_key in self.tax_rates:
                    row_rate = self.tax_rates[file_key]
                else:
                    try:
                        row_rate = (
                            float(vals[1]) if len(vals) > 1 else self.default_tax_rate
                        )
                        # Sync to dict
                        self.tax_rates[file_key] = row_rate
                    except (ValueError, IndexError):
                        row_rate = self.default_tax_rate
                        self.tax_rates[file_key] = row_rate

                if len(vals) < 3:
                    vals.extend(["No"] * (3 - len(vals)))

                # Check if rate differs from default
                if (
                    abs(row_rate - self.default_tax_rate) > 0.01
                ):  # Allow small floating point differences
                    vals[2] = "Yes"
                    # Update tree with current rate
                    vals[1] = str(row_rate)
                    current_tags = list(self.tax_tree.item(item)["tags"])
                    if "override" not in current_tags:
                        current_tags.append("override")
                    self.tax_tree.item(
                        item, values=tuple(vals), tags=tuple(current_tags)
                    )
                else:
                    vals[2] = "No"
                    vals[1] = str(row_rate)
                    # Remove override tag if present
                    current_tags = list(self.tax_tree.item(item)["tags"])
                    if "override" in current_tags:
                        current_tags.remove("override")
                    self.tax_tree.item(
                        item, values=tuple(vals), tags=tuple(current_tags)
                    )
        except Exception:
            pass

    def _validate_tax_rates(self) -> tuple[bool, list[str]]:
        """
        Validate all tax rates using tax_rates dict.

        Returns:
            Tuple of (is_valid: bool, error_list: list[str])
        """
        errors = []
        self.tax_rate_errors.clear()

        for item in self.tax_tree.get_children():
            vals = self.tax_tree.item(item)["values"]
            if len(vals) < 1:
                continue

            file_key = vals[0]

            # Get rate from dict if available, otherwise from tree
            if file_key in self.tax_rates:
                rate = self.tax_rates[file_key]
            else:
                # Read from tree and sync to dict
                if len(vals) < 2:
                    continue
                rate_str = str(vals[1]).strip().replace(",", ".")
                try:
                    rate = float(rate_str)
                    self.tax_rates[file_key] = rate
                except ValueError:
                    error_msg = f"Invalid rate format for {file_key}: must be a number"
                    errors.append(error_msg)
                    self.tax_rate_errors[file_key] = error_msg
                    # Apply error tag
                    current_tags = list(self.tax_tree.item(item)["tags"])
                    if "error" not in current_tags:
                        current_tags.append("error")
                    self.tax_tree.item(item, tags=tuple(current_tags))
                    continue

            # Validate range
            if not (0 <= rate <= 100):
                error_msg = f"Invalid rate for {file_key}: must be 0–100"
                errors.append(error_msg)
                self.tax_rate_errors[file_key] = error_msg
                # Apply error tag
                current_tags = list(self.tax_tree.item(item)["tags"])
                if "error" not in current_tags:
                    current_tags.append("error")
                self.tax_tree.item(item, tags=tuple(current_tags))
            else:
                # Remove error tag if present
                current_tags = list(self.tax_tree.item(item)["tags"])
                if "error" in current_tags:
                    current_tags.remove("error")
                self.tax_tree.item(item, tags=tuple(current_tags))
                # Clear error from dict if present
                if file_key in self.tax_rate_errors:
                    del self.tax_rate_errors[file_key]

        # Update error display
        self._update_tax_error_display()

        return (len(errors) == 0, errors)

    def _update_tax_error_display(self):
        """Update the tax error label to show all errors, and section 3 status line."""
        if not self.tax_rate_errors:
            self.tax_error_label.config(text="")
        else:
            # Show all errors (limit to first 3 for display)
            error_list = list(self.tax_rate_errors.values())
            if len(error_list) == 1:
                self.tax_error_label.config(text=error_list[0])
            else:
                display_errors = error_list[:3]
                error_text = f"{len(error_list)} errors found: " + "; ".join(
                    display_errors
                )
                if len(error_list) > 3:
                    error_text += f" (+{len(error_list) - 3} more)"
                self.tax_error_label.config(text=error_text)
        self._update_tax_status_label()

    def _update_tax_status_label(self):
        """Update section 3 status line: 'Tax rates valid' (success) or 'Tax rates invalid: N errors' (error)."""
        if not hasattr(self, "tax_status_label"):
            return
        if self.tax_rate_errors:
            n = len(self.tax_rate_errors)
            self.tax_status_label.config(
                text=f"Tax rates invalid: {n} error{'s' if n != 1 else ''}",
                fg=COLORS["error"],
            )
        else:
            self.tax_status_label.config(
                text="Tax rates valid",
                fg=COLORS["success"],
            )

    def _update_run_button_state(self):
        """Update RUN button state based on can_run_now(); show disable reason in status bar."""
        if self.ui_state == "running":
            self.run_btn.config(state="disabled")
            return

        self._update_tax_status_label()
        can_run, reason = self.can_run_now()
        if can_run:
            self.run_btn.config(state="normal")
            self._last_status_text = "Ready"
            self.status_label.config(text="Ready")
        else:
            self.run_btn.config(state="disabled")
            self._last_status_text = reason or "Ready"
            self.status_label.config(text=reason or "Ready")

    def can_run_now(self) -> tuple[bool, str | None]:
        """
        Check if RUN button should be enabled.

        Returns:
            Tuple of (can_run: bool, reason: str | None)
        """
        # Check if already running
        if self.ui_state == "running":
            return (False, "Already running")

        # Check required paths
        input_path_str = self.input_path_var.get().strip()
        if not input_path_str:
            return (False, "Input folder required")

        input_path = Path(input_path_str)
        if not input_path.exists():
            return (False, "Input folder does not exist")

        output_path_str = self.output_dir_var.get().strip()
        if not output_path_str:
            return (False, "Output folder required")

        output_path = Path(output_path_str)
        if not output_path.exists():
            return (False, "Output folder does not exist")

        # Check tax mode validation
        mode = self.tax_mode_var.get()
        if mode == "all":
            try:
                rate = self.tax_rate_all_var.get()
                if not (0 <= rate <= 100):
                    return (False, "Tax rate must be 0–100")
            except Exception:
                return (False, "Invalid tax rate format")
        elif mode == "individual":
            # Check for validation errors
            if self.tax_rate_errors:
                return (False, f"{len(self.tax_rate_errors)} tax rate errors found")
            # Also validate to ensure dict is in sync
            is_valid, _ = self._validate_tax_rates()
            if not is_valid:
                return (False, "Tax rate validation failed")

        return (True, None)

    def _make_argv(self) -> List[str]:
        argv = [self.input_path_var.get()]

        out_dir = self.output_dir_var.get()
        if out_dir:
            argv.extend(["--output-dir", out_dir])

        # Safely get int/float values
        try:
            cache_val = str(self.cache_size_var.get())
        except tk.TclError:
            cache_val = "1000"  # Default fallback for preview
        argv.extend(["--cache-size", cache_val])

        log_lvl = self.log_level_var.get()
        if log_lvl != "INFO":
            argv.extend(["--log-level", log_lvl])

        prev = self.prev_output_var.get()
        if prev:
            argv.extend(["--previous-output", prev])

        mode = self.tax_mode_var.get()
        if mode != "prompt":
            argv.extend(["--tax-rate-mode", mode])

        if mode == "all":
            try:
                rate_val = str(self.tax_rate_all_var.get())
            except tk.TclError:
                rate_val = "0"  # Fallback for display/empty
            argv.extend(["--tax-rate", rate_val])
        elif mode == "individual":
            map_path = str(Path(out_dir) / "tax_rate_map.json")
            argv.extend(["--tax-rate-map", map_path])

        return argv

    def _update_command_preview(self):
        argv = self._make_argv()
        # Use new multi-line formatter
        cmd = format_cmd_preview(argv)

        self.cmd_text.config(state="normal")
        self.cmd_text.delete("1.0", "end")
        self.cmd_text.insert("1.0", cmd)
        self.cmd_text.config(state="disabled")

    def _copy_command(self):
        """Copy single-line CMD-safe command."""
        argv = self._make_argv()
        cmd = flatten_cmd(argv)
        self.clipboard_clear()
        self.clipboard_append(cmd)

    def _copy_command_multiline(self):
        """Copy multi-line preview as-is."""
        self.clipboard_clear()
        self.clipboard_append(self.cmd_text.get("1.0", "end-1c"))

    def _show_idle_placeholder(self):
        """Show placeholder text in terminal output."""
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        placeholder_lines = [
            "No output yet.",
            "Select input, then press RUN.",
            "Logs will stream here.",
        ]
        for line in placeholder_lines:
            self.log_text.insert("end", line + "\n", "placeholder")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self._show_idle_placeholder()

    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end"))

    def _on_run(self, event=None):
        if self.is_running:
            return

        # --- Validation ---
        input_path_str = self.input_path_var.get().strip()
        if not input_path_str:
            messagebox.showerror("Validation Error", "Input path is required.")
            self._set_last_error("Input path is required.")
            return

        input_path = Path(input_path_str)
        if not input_path.exists():
            messagebox.showerror("Validation Error", "Input path does not exist.")
            self._set_last_error("Input path does not exist.")
            return

        if input_path.is_file():
            if input_path.suffix.lower() != ".docx":
                messagebox.showerror(
                    "Validation Error", "Input file must be a .docx file."
                )
                self._set_last_error("Input file must be a .docx file.")
                return
        elif input_path.is_dir() and not self.discovered_files:
            messagebox.showerror(
                "Validation Error", "No .docx files found in input directory."
            )
            self._set_last_error("No .docx files found in input directory.")
            return

        # Previous output validation
        prev_path_str = self.prev_output_var.get().strip()
        if prev_path_str:
            if not Path(prev_path_str).exists():
                messagebox.showerror(
                    "Validation Error", "Previous output file does not exist."
                )
                self._set_last_error("Previous output file does not exist.")
                return
            if not prev_path_str.lower().endswith(".xlsx"):
                messagebox.showerror(
                    "Validation Error", "Previous output must be an .xlsx file."
                )
                self._set_last_error("Previous output must be an .xlsx file.")
                return

        # Tax rate validation
        mode = self.tax_mode_var.get()
        if mode == "all":
            try:
                rate = self.tax_rate_all_var.get()
                if not (0 <= rate <= 100):
                    messagebox.showerror(
                        "Validation Error", "Tax rate must be between 0 and 100."
                    )
                    self._set_last_error("Tax rate must be between 0 and 100.")
                    return
            except Exception:
                messagebox.showerror("Validation Error", "Invalid tax rate format.")
                self._set_last_error("Invalid tax rate format.")
                return

        elif mode == "individual":
            if not self.tax_tree.get_children():
                messagebox.showerror(
                    "Validation Error", "No files to configure tax rates for."
                )
                self._set_last_error("No files to configure tax rates for.")
                return

            # Validate using new method
            is_valid, _ = self._validate_tax_rates()
            if not is_valid:
                messagebox.showerror(
                    "Validation Error",
                    "Invalid tax rates found. Please fix errors in the table.",
                )
                self._set_last_error(
                    "Invalid tax rates found. Please fix errors in the table."
                )
                return

        # --- End Validation ---

        # Prepare — show phase so user sees "what's happening" (visibility of system status)
        self.set_state("running", "Preparing…")
        self.is_running = True
        self.run_start_time = datetime.now()

        # Clear log and add header block
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")

        # Append header block
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        argv = self._make_argv()
        cmd_line = flatten_cmd(argv)
        header_block = f"""================================================
RUN START: {timestamp}
{cmd_line}
================================================
"""
        self.log_text.insert("end", header_block, "INFO")
        self.log_text.config(state="disabled")

        self.set_state("running", "Running…")

        out_dir = Path(self.output_dir_var.get())
        if not out_dir.exists():
            out_dir.mkdir(parents=True, exist_ok=True)

        # Capture state for post-run open
        self._last_output_dir = out_dir
        self._last_run_start_ts = datetime.now().timestamp()

        if mode == "individual":
            # Generate JSON map with percent values (0-100) from tax_rates dict
            default_rate = self.bulk_rate_var.get()
            tax_map = {"default": default_rate, "files": {}}
            # Use tax_rates dict if available, otherwise fall back to tree
            for file_key, rate in self.tax_rates.items():
                tax_map["files"][file_key] = rate

            map_path = out_dir / "tax_rate_map.json"
            with open(map_path, "w", encoding="utf-8") as f:
                json.dump(tax_map, f, indent=2)

        argv = self._make_argv()

        # Start Thread
        t = threading.Thread(target=self._run_cli_thread, args=(argv,))
        t.start()

    def _run_cli_thread(self, argv):
        # Redirect stdout/stderr
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = RedirectText(self.log_queue, ["INFO"])
        sys.stderr = RedirectText(self.log_queue, ["ERROR"])

        exit_code = 1
        start_time = datetime.now()

        try:
            exit_code = cli_main(argv)
        except Exception as e:
            print(f"GUI Error: {e}")
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

            elapsed = datetime.now() - start_time
            self.log_queue.put(("__DONE__", (exit_code, elapsed)))

    def _poll_log_queue(self):
        try:
            while True:
                msg, tags = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self._on_run_complete(*tags)
                else:
                    self.log_text.config(state="normal")
                    self.log_text.insert("end", msg + "\n", tags)
                    if self.autoscroll_var.get():
                        self.log_text.see("end")
                    self.log_text.config(state="disabled")
        except queue.Empty:
            pass

        self.after(100, self._poll_log_queue)

    def _schedule_elapsed_update(self):
        """Schedule periodic elapsed time updates while running."""
        if self.ui_state == "running" and self.run_start_time:
            elapsed = datetime.now() - self.run_start_time
            self.set_state("running", "Running…", elapsed=elapsed)
            self.elapsed_timer_id = self.after(1000, self._schedule_elapsed_update)
        else:
            self.elapsed_timer_id = None

    def _on_run_complete(self, exit_code, elapsed):
        self.is_running = False

        # Stop elapsed timer
        if self.elapsed_timer_id:
            self.after_cancel(self.elapsed_timer_id)
            self.elapsed_timer_id = None
        self.run_start_time = None

        # One-line status summary (Medium: status bar after Done/Error)
        file_count = len(self.discovered_files)
        if exit_code == 0:
            self.set_state("done", f"Done — {file_count} files", elapsed=elapsed)
            self._flash_done_feedback(elapsed)
        elif exit_code == 130:
            self.set_state("error", "Cancelled", elapsed=elapsed)
        else:
            self.set_state("error", "Failed — see Terminal Output", elapsed=elapsed)

        # Append footer block
        self.log_text.config(state="normal")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output_dir = self.output_dir_var.get()
        footer_block = f"""
================================================
RUN END: {timestamp}
Elapsed: {elapsed}
Output: {output_dir}
Files: {file_count}
================================================
"""
        self.log_text.insert("end", footer_block, "INFO")
        self.log_text.config(state="disabled")

        # Disable auto-scroll after completion
        self.autoscroll_var.set(False)

        # Auto-collapse header after first successful run (optional enhancement)
        # if exit_code == 0 and self.header_expanded:
        #     self._toggle_header()

        # Update summary
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        # Remove placeholder tag if present
        self.summary_text.tag_delete("placeholder")

        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        argv = self._make_argv()
        cmd_short = flatten_cmd(argv[:3]) if len(argv) > 3 else flatten_cmd(argv)

        self.summary_text.insert("end", f"Last run: {timestamp_str}\n")
        self.summary_text.insert("end", f"Last command: {cmd_short}\n")
        self.summary_text.insert("end", f"Files processed: {file_count}\n")
        self.summary_text.insert("end", f"Elapsed time: {elapsed}\n")
        self.summary_text.insert("end", f"Output folder: {output_dir}\n")

        self.summary_text.config(state="disabled")

        # Focus and scroll to summary panel (C2: keyboard focus after done/error)
        self.summary_text.focus_set()
        self.summary_text.see("1.0")  # Scroll to top of summary

        # Auto-open logic
        should_open = self.auto_open_var.get()
        # self.summary_text.insert("end", f"Auto-open preference: {should_open}\n") # Debug line

        if exit_code == 0 and should_open:
            try:
                # Find new XLSX files
                candidates = []
                if self._last_output_dir.exists():
                    for f in self._last_output_dir.glob("*.xlsx"):
                        # Increased buffer to 5.0s to ensure we catch files
                        if f.stat().st_mtime >= (self._last_run_start_ts - 5.0):
                            candidates.append(f)

                # Sort by mtime desc
                candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)

                if candidates:
                    # Limit to 3 files to avoid window flood
                    limit = 3
                    to_open = candidates[:limit]

                    for target in to_open:
                        self.summary_text.insert(
                            "end", f"Auto-opening: {target.name}\n"
                        )
                        self._open_path_in_os(target)

                    if len(candidates) > limit:
                        remaining = len(candidates) - limit
                        self.summary_text.insert(
                            "end", f"...and {remaining} more files (opening folder)\n"
                        )
                        self._open_path_in_os(self._last_output_dir)
                else:
                    self.summary_text.insert(
                        "end", "Auto-opening folder (no new output files found)\n"
                    )
                    self._open_path_in_os(self._last_output_dir)

            except Exception as e:
                self.summary_text.insert("end", f"Auto-open error: {e}\n")

        self.summary_text.config(state="disabled")

    def _on_cancel(self):
        self.log_text.config(state="normal")
        self.log_text.insert("end", "Cancel requested…\n", "WARNING")
        self.log_text.config(state="disabled")
        self.set_state("cancel_requested", "Cancel requested…")
        # There is no cooperative cancellation in CLI yet (KeyboardInterrupt is for shell)
        # We could try to set a flag in BatchProcessor if we had access to the instance
        pass

    def _on_tax_tree_double_click(self, event):
        """Handle double-click to start in-place editing of tax rate."""
        # Only allow editing in individual mode
        if self.tax_mode_var.get() != "individual":
            return

        # Cancel any existing edit
        if self.tax_edit_entry:
            self._cancel_tax_edit()

        # Identify clicked region and column
        region = self.tax_tree.identify_region(event.x, event.y)
        column = self.tax_tree.identify_column(event.x)
        item = self.tax_tree.identify_row(event.y)

        # Only allow editing Rate % column (column #2, index 1)
        if region != "cell" or column != "#2" or not item:
            return

        # Get current value
        vals = self.tax_tree.item(item)["values"]
        if len(vals) < 2:
            return

        current_value = str(vals[1])

        # Get cell bbox
        bbox = self.tax_tree.bbox(item, column)
        if not bbox:
            return

        # Create Entry overlay
        self.tax_edit_item = item
        self.tax_edit_entry = ttk.Entry(
            self.tax_tree,
            font=FONTS["ui"],
        )
        self.tax_edit_entry.insert(0, current_value)
        self.tax_edit_entry.select_range(0, tk.END)
        self.tax_edit_entry.focus()

        # Place entry over the cell
        self.tax_edit_entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])

        # Bind events
        self.tax_edit_entry.bind("<Return>", lambda e: self._commit_tax_edit())
        self.tax_edit_entry.bind("<Escape>", lambda e: self._cancel_tax_edit())
        # FocusOut: commit only if valid, otherwise keep focus
        self.tax_edit_entry.bind("<FocusOut>", self._on_tax_edit_focusout)

        # Prevent treeview from losing focus immediately
        self.tax_edit_entry.focus_set()

    def _commit_tax_edit(self):
        """Commit the current tax rate edit."""
        if not self.tax_edit_entry or not self.tax_edit_item:
            return

        # Get input value
        input_str = self.tax_edit_entry.get().strip()

        # Normalize comma to dot
        input_str = input_str.replace(",", ".")

        # Get file key
        vals = self.tax_tree.item(self.tax_edit_item)["values"]
        if len(vals) < 1:
            self._cancel_tax_edit()
            return

        file_key = vals[0]

        # Validate
        try:
            rate = float(input_str)
            if not (0 <= rate <= 100):
                # Invalid range - keep editor and show error
                self.tax_rate_errors[file_key] = (
                    f"Invalid rate for {file_key}: must be 0–100"
                )
                self.tax_edit_entry.focus_set()
                self._update_tax_error_display()
                self._update_run_button_state()
                return
        except ValueError:
            # Invalid format - keep editor and show error
            self.tax_rate_errors[file_key] = (
                f"Invalid rate format for {file_key}: must be a number"
            )
            self.tax_edit_entry.focus_set()
            self._update_tax_error_display()
            self._update_run_button_state()
            return

        # Valid - commit the change
        self.tax_rates[file_key] = rate
        if file_key in self.tax_rate_errors:
            del self.tax_rate_errors[file_key]

        # Update tree cell
        if len(vals) < 3:
            vals.extend(["No"] * (3 - len(vals)))
        vals[1] = str(rate)
        self.tax_tree.item(self.tax_edit_item, values=tuple(vals))

        # Recalculate override
        self._update_override_indicators()

        # Clear error display if no errors
        self._update_tax_error_display()

        # Update RUN button state
        self._update_run_button_state()

        # Clean up editor
        self._cancel_tax_edit()

    def _on_tax_edit_focusout(self, event):
        """Handle focus out - commit if valid, otherwise keep focus."""
        # Only handle if it's our edit entry
        if not self.tax_edit_entry or event.widget != self.tax_edit_entry:
            return

        # If focus is moving to another widget (not None), commit
        # If focus is None (clicking outside), also commit
        # The commit method will keep focus if invalid
        input_str = self.tax_edit_entry.get().strip().replace(",", ".")
        try:
            rate = float(input_str)
            if 0 <= rate <= 100:
                # Valid - commit
                self._commit_tax_edit()
            else:
                # Invalid - keep focus
                self.after_idle(lambda: self.tax_edit_entry.focus_set())
        except ValueError:
            # Invalid format - keep focus
            self.after_idle(lambda: self.tax_edit_entry.focus_set())

    def _cancel_tax_edit(self):
        """Cancel the current tax rate edit."""
        if self.tax_edit_entry:
            self.tax_edit_entry.destroy()
            self.tax_edit_entry = None
        self.tax_edit_item = None

    def _clamp_sash_position(self, event=None):
        """Clamp sash position to enforce minimum pane widths."""
        if (
            not hasattr(self, "main_paned")
            or not hasattr(self, "left_frame")
            or not hasattr(self, "right_frame")
        ):
            return

        self.update_idletasks()
        left_width = self.left_frame.winfo_width()
        right_width = self.right_frame.winfo_width()
        min_left = 540
        min_right = 400

        # Check if either pane is below minimum
        if left_width < min_left:
            # Calculate required sash position to give left pane minimum width
            sash_pos = min_left
            self.main_paned.sashpos(0, sash_pos)
        elif right_width < min_right:
            # Calculate required sash position to give right pane minimum width
            total_width = self.main_paned.winfo_width()
            sash_pos = total_width - min_right
            self.main_paned.sashpos(0, sash_pos)

    def _debug_layout(self):
        """Print layout dimensions for debugging (dev-only)."""
        self.update_idletasks()
        print("=== Layout Debug ===")
        print(f"Window: {self.winfo_width()}x{self.winfo_height()}")
        # Find left_frame from main_paned
        for child in self.winfo_children():
            if isinstance(child, ttk.PanedWindow):
                for pane in child.panes():
                    pane_widget = child.nametowidget(pane)
                    if hasattr(pane_widget, "winfo_width"):
                        print(
                            f"Left panel: {pane_widget.winfo_width()}x{pane_widget.winfo_height()}"
                        )
                        break
        if hasattr(self, "tax_indiv_frame"):
            print(
                f"Tax frame: {self.tax_indiv_frame.winfo_width()}x{self.tax_indiv_frame.winfo_height()}"
            )
        if hasattr(self, "tax_tree"):
            print(
                f"Tax tree: {self.tax_tree.winfo_width()}x{self.tax_tree.winfo_height()}"
            )
        print("===================")


if __name__ == "__main__":
    app = QualityAuditGUI()
    # Bindings
    app.bind("<Control-Return>", app._on_run)
    app.bind("<Control-l>", lambda e: app._clear_log())
    app.bind("<F5>", lambda e: app._on_rescan())
    app.mainloop()
