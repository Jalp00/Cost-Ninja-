"""Cost Ninja — Premium Obsidian & Neon Cyber CustomTkinter widgets."""

import customtkinter as ctk

# ── Obsidian & Neon Cyber Color Palette ──────────────────────────────────────────
THEME_COLORS = {
    # Backgrounds
    "bg_dark":       "#090C15",  # Deep obsidian
    "bg_medium":     "#111520",  # App background
    "bg_light":      "#1A2133",  # Cards/Frames
    "surface":       "#262F45",  # Hover states / glass

    # Accents
    "primary":       "#00F0FF",  # Neon Cyan
    "primary_hover": "#00C2CC",
    "accent":        "#9D4EDD",  # Electric Violet
    "accent_hover":  "#7B2CBF",
    "success":       "#39FF14",  # Neon Green
    "warning":       "#FFD700",  # Gold
    "error":         "#FF3333",  # Crimson Red

    # Text
    "text_primary":  "#F8FAFC",
    "text_secondary":"#94A3B8",
    "text_muted":    "#64748B",

    # Borders
    "border_default":"#1E293B",
    "border_glow":   "#00F0FF",
    "border_subtle": "#0F172A",
}

IMAGE_DISPLAY_MAX_WIDTH = 900
IMAGE_DISPLAY_MAX_HEIGHT = 400

# ── Premium font definitions ────────────────────────────────────────────────
FONT_TITLE    = ("Bahnschrift", 28, "bold")
FONT_SUBTITLE = ("Bahnschrift", 20, "bold")
FONT_SECTION  = ("Bahnschrift", 15, "bold")
FONT_ACCENT   = ("Segoe UI", 13, "bold")
FONT_BODY     = ("Segoe UI", 13)
FONT_BTN_LG   = ("Segoe UI", 14, "bold")
FONT_BTN_SM   = ("Segoe UI", 12, "bold")
FONT_MONO     = ("Consolas", 13)
FONT_MONO_SM  = ("Consolas", 12)


class NvidiaFrame(ctk.CTkFrame):
    """Frosted glass panel with subtle border."""
    def __init__(self, master, style="default", **kwargs):
        super().__init__(master, **kwargs)
        if style == "header":
            self.configure(
                fg_color=THEME_COLORS["bg_medium"],
                border_color=THEME_COLORS["border_subtle"],
                border_width=0,
                corner_radius=0,
            )
        elif style == "status":
            self.configure(
                fg_color=THEME_COLORS["bg_dark"],
                border_color=THEME_COLORS["border_subtle"],
                border_width=0,
                corner_radius=0,
            )
        else:
            self.configure(
                fg_color=THEME_COLORS["bg_light"],
                border_color=THEME_COLORS["border_default"],
                border_width=1,
                corner_radius=16, # More rounded
            )


class NvidiaButton(ctk.CTkButton):
    """Pill-shaped premium button."""

    def __init__(self, master, text="", command=None, style="primary", **kwargs):
        width = kwargs.pop("width", 0)
        height = kwargs.pop("height", 40)
        state = kwargs.pop("state", "normal")

        # Style definitions
        styles = {
            "primary": {
                "fg_color": THEME_COLORS["primary"],
                "hover_color": THEME_COLORS["primary_hover"],
                "text_color": "#090C15",
                "border_width": 0,
                "font": FONT_BTN_LG,
            },
            "accent": {
                "fg_color": THEME_COLORS["accent"],
                "hover_color": THEME_COLORS["accent_hover"],
                "text_color": "#F8FAFC",
                "border_width": 0,
                "font": FONT_BTN_LG,
            },
            "secondary": {
                "fg_color": THEME_COLORS["surface"],
                "hover_color": "#3B4863",
                "text_color": THEME_COLORS["text_primary"],
                "border_width": 1,
                "border_color": "#4B5B7E",
                "font": FONT_BTN_SM,
            },
            "warning": {
                "fg_color": THEME_COLORS["warning"],
                "hover_color": "#E6C200",
                "text_color": "#090C15",
                "border_width": 0,
                "font": FONT_BTN_LG,
            },
            "success": {
                "fg_color": THEME_COLORS["success"],
                "hover_color": "#2DE010",
                "text_color": "#090C15",
                "border_width": 0,
                "font": FONT_BTN_LG,
            },
        }

        config = dict(styles.get(style, styles["secondary"]))
        config.update(kwargs)

        self.active_fg_color = config.get("fg_color")
        self.active_text_color = config.get("text_color")
        self.active_border_color = config.get("border_color")

        if state == "disabled":
            config["fg_color"] = "#161C27"
            config["text_color_disabled"] = THEME_COLORS["text_muted"]
            if self.active_border_color:
                config["border_color"] = "#262F45"

        super().__init__(
            master, text=text, command=command,
            width=width, height=height, state=state,
            corner_radius=50, **config,
        )

    def configure(self, **kwargs):
        if "state" in kwargs:
            state = kwargs["state"]
            if state == "disabled":
                kwargs["fg_color"] = "#161C27"
                kwargs["text_color_disabled"] = THEME_COLORS["text_muted"]
                if self.active_border_color:
                    kwargs["border_color"] = "#262F45"
            elif state == "normal":
                kwargs["fg_color"] = self.active_fg_color
                kwargs["text_color"] = self.active_text_color
                if self.active_border_color:
                    kwargs["border_color"] = self.active_border_color
        super().configure(**kwargs)


class NvidiaEntry(ctk.CTkEntry):
    """Deep-dark input field with accent focus border."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=THEME_COLORS["bg_dark"],
            border_color=THEME_COLORS["border_default"],
            text_color=THEME_COLORS["text_primary"],
            placeholder_text_color=THEME_COLORS["text_muted"],
            corner_radius=10,
            border_width=1,
            font=FONT_BODY,
        )


class NvidiaTextbox(ctk.CTkTextbox):
    """Frosted output textbox with teal scrollbar."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=THEME_COLORS["bg_dark"],
            border_color=THEME_COLORS["border_default"],
            text_color=THEME_COLORS["text_primary"],
            corner_radius=12,
            border_width=1,
            scrollbar_button_color=THEME_COLORS["surface"],
            scrollbar_button_hover_color=THEME_COLORS["primary_hover"],
        )


class NvidiaLabel(ctk.CTkLabel):
    """Typography system — title, subtitle, section, accent, body."""
    def __init__(self, master, style="primary", **kwargs):
        if style == "title":
            text_color = THEME_COLORS["primary"]
            font = FONT_TITLE
        elif style == "subtitle":
            text_color = THEME_COLORS["text_primary"]
            font = FONT_SUBTITLE
        elif style == "section":
            text_color = THEME_COLORS["accent"]
            font = FONT_SECTION
        elif style == "accent":
            text_color = THEME_COLORS["primary"]
            font = FONT_ACCENT
        else:
            text_color = THEME_COLORS["text_secondary"]
            font = FONT_BODY
        super().__init__(master, text_color=text_color, font=font, **kwargs)
