"""
UI Styles and Theme Configuration.

KPMG brand-aligned dark theme: primary blue accent, 8pt spacing grid,
semantic colors. See BRAND_KPMG.md for full token reference.
"""

import tkinter as tk
from tkinter import ttk

# Typography scale: caption / body / heading (Tk uses font tuples; line-height not applicable)
# UI: labels, buttons; Monospace: log, command preview
FONTS = {
    "caption": ("Segoe UI", 9),  # Small labels, hints
    "body": ("Segoe UI", 10),  # Default UI (labels, buttons)
    "heading": ("Segoe UI", 11),  # Section titles, emphasis
    "heading_bold": ("Segoe UI", 11, "bold"),  # LabelFrame section titles
    "monospace": ("Consolas", 11),
    "log": ("Consolas", 10),
    "ui": ("Segoe UI", 10),  # Alias for body
}

# 8pt spacing grid (px) for padx/pady and section padding
# Use: padx/pady = sm/base/lg; section padding = base (16) or lg (24)
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "base": 16,
    "lg": 24,
    "xl": 32,
    "xxl": 48,
}
# Section padding: use SPACING["base"] or SPACING["lg"] for LabelFrame padding
PADDING_SECTION = SPACING["base"]  # 16px
PADDING_INNER = SPACING["sm"]  # 8px between rows

# Colors (Dark Theme — KPMG brand). Single dict for easy theme swap.
# Semantic: surface = bg_primary; surface_raised = bg_secondary/bg_tertiary; text_primary/secondary/muted; accent; success/warning/error
COLORS = {
    "bg_primary": "#121212",  # surface (main window)
    "bg_secondary": "#1a1a2e",  # surface_raised (panels, inputs)
    "bg_tertiary": "#252538",  # surface_raised_high (headers, list headers)
    "text_primary": "#f5f5f5",
    "text_secondary": "#a0a0b0",
    "text_muted": "#6b6b80",
    "accent": "#00338D",  # KPMG blue
    "accent_hover": "#002366",
    "success": "#0d9488",
    "warning": "#d97706",
    "error": "#dc2626",
    "border": "#3f3f50",
    "select_bg": "#1e3a5f",
}
# Aliases for handoff/docs
SURFACE = "bg_primary"
SURFACE_RAISED = "bg_secondary"
SURFACE_RAISED_HIGH = "bg_tertiary"

# Breakpoints (px): compact vs full. Use winfo_width() to choose layout (e.g. hide banner in compact).
VIEW_MODES = {
    "compact_max_width": 1280,  # Below this: compact (e.g. hide banner by default, shorter labels)
    "full_min_width": 1280,
}


def apply_dark_theme(root: tk.Tk | tk.Toplevel) -> None:
    """Apply dark theme to Tkinter application."""
    style = ttk.Style(root)
    style.theme_use("clam")  # Use clam as base for better customizability

    # Configure generic colors
    root.configure(bg=COLORS["bg_primary"])

    # Configure TFrame
    style.configure(
        "TFrame",
        background=COLORS["bg_primary"],
    )

    # Configure TLabel - use text_secondary for normal labels
    style.configure(
        "TLabel",
        background=COLORS["bg_primary"],
        foreground=COLORS[
            "text_secondary"
        ],  # Use secondary instead of primary for normal text
        font=FONTS["ui"],
    )

    # Configure TButton
    style.configure(
        "TButton",
        background=COLORS["bg_secondary"],
        foreground=COLORS["text_primary"],
        borderwidth=0,
        focuscolor=COLORS["accent"],
        font=FONTS["ui"],
    )
    style.map(
        "TButton",
        background=[("active", COLORS["bg_tertiary"]), ("pressed", COLORS["accent"])],
        foreground=[("active", COLORS["text_primary"])],
    )

    # Configure TEntry
    style.configure(
        "TEntry",
        fieldbackground=COLORS["bg_secondary"],
        foreground=COLORS["text_primary"],
        insertcolor=COLORS["text_primary"],  # Cursor color
        borderwidth=0,
        relief="flat",
        padding=5,
    )

    # Configure TCombobox
    style.configure(
        "TCombobox",
        fieldbackground=COLORS["bg_secondary"],
        background=COLORS["bg_secondary"],
        foreground=COLORS["text_primary"],
        arrowcolor=COLORS["text_primary"],
        borderwidth=1,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["bg_secondary"])],
        selectbackground=[("readonly", COLORS["select_bg"])],
        selectforeground=[("readonly", COLORS["text_primary"])],
    )

    # Configure TRadiobutton
    style.configure(
        "TRadiobutton",
        background=COLORS["bg_primary"],
        foreground=COLORS["text_primary"],
        font=FONTS["ui"],
        indicatorcolor=COLORS["bg_secondary"],
        indicatorrelief="flat",
        indicatormargin=4,
    )
    style.map(
        "TRadiobutton",
        indicatorcolor=[("selected", COLORS["accent"]), ("pressed", COLORS["accent"])],
    )

    # Configure Treeview
    style.configure(
        "Treeview",
        background=COLORS["bg_secondary"],
        foreground=COLORS["text_primary"],
        fieldbackground=COLORS["bg_secondary"],
        borderwidth=0,
        font=FONTS["ui"],
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["bg_tertiary"],
        foreground=COLORS["text_primary"],
        relief="flat",
        font=FONTS["ui"],
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["select_bg"])],
        foreground=[("selected", COLORS["text_primary"])],
    )

    # Scrollbar
    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["bg_secondary"],
        troughcolor=COLORS["bg_primary"],
        borderwidth=0,
        arrowcolor=COLORS["text_secondary"],
    )

    # Labelframe - reduced border
    style.configure(
        "TLabelframe",
        background=COLORS["bg_primary"],
        foreground=COLORS["text_primary"],
        bordercolor=COLORS["border"],
        borderwidth=1,  # Reduced from default
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=COLORS["bg_primary"],
        foreground=COLORS["accent"],  # Section titles use accent
        font=FONTS["heading_bold"],
    )

    # Custom styles (KPMG accent)
    style.configure(
        "Accent.TButton",
        background=COLORS["accent"],
        foreground=COLORS["text_primary"],
        padding=(24, 12),  # Primary CTA: larger target (Fitts's Law)
    )
    style.map(
        "Accent.TButton",
        background=[
            ("active", COLORS.get("accent_hover", "#002366")),
            ("pressed", "#001a4d"),
        ],
    )

    style.configure(
        "Prompt.TLabel",
        foreground=COLORS["accent"],
        font=FONTS["monospace"],
    )
