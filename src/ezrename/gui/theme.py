"""The EzRename design system.

One place defines the palette, spacing, radii and typography, and one place
turns those tokens into the application stylesheet. Every widget in the app is
styled from here, which is what keeps the interface coherent instead of looking
like a pile of unrelated controls.
"""

from __future__ import annotations

import ctypes
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons


@dataclass(frozen=True)
class Palette:
    """Colour roles for one theme."""

    name: str
    dark: bool
    base: str          # window background
    surface: str       # cards and panels
    surface_alt: str   # inputs, alternate rows
    surface_hi: str    # hover
    border: str
    border_soft: str
    text: str
    text_muted: str
    text_dim: str
    sidebar: str
    sidebar_item: str
    success: str
    warning: str
    danger: str
    info: str
    shadow_alpha: int


DARK = Palette(
    name="dark",
    dark=True,
    base="#0E1014",
    surface="#15181E",
    surface_alt="#1B1F27",
    surface_hi="#232833",
    border="#2A3040",
    border_soft="#1F242E",
    text="#E9EDF4",
    text_muted="#9AA4B6",
    text_dim="#6C7686",
    sidebar="#111419",
    sidebar_item="#1A1F28",
    success="#3DDC97",
    warning="#F5B54B",
    danger="#F8767C",
    info="#5EA3FF",
    shadow_alpha=170,
)

LIGHT = Palette(
    name="light",
    dark=False,
    base="#F4F6F9",
    surface="#FFFFFF",
    surface_alt="#F1F4F8",
    surface_hi="#E7ECF3",
    border="#D8DEE8",
    border_soft="#E7EBF1",
    text="#161A20",
    text_muted="#5A6474",
    text_dim="#8A93A3",
    sidebar="#FFFFFF",
    sidebar_item="#EEF2F7",
    success="#12A06A",
    warning="#B57615",
    danger="#D64550",
    info="#2F6FE0",
    shadow_alpha=60,
)

#: Accent colour choices offered in Settings.
ACCENTS = {
    "blue": ("#4C8DFF", "#2F6BE0"),
    "violet": ("#A78BFA", "#7C5CF0"),
    "teal": ("#2ED3B7", "#17A38F"),
    "amber": ("#F5A524", "#C97F0D"),
    "rose": ("#FB7185", "#E04462"),
}

FONT_STACK = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "sans-serif")
MONO_STACK = ("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "monospace")

SIZES = {
    "display": 21,
    "title": 15,
    "section": 11,
    "body": 10,
    "small": 9,
    "tiny": 8,
}

RADIUS = {"card": 12, "control": 8, "pill": 999, "small": 6}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}


@dataclass
class Tokens:
    """Resolved design tokens for the running application."""

    palette: Palette
    accent: str
    accent_dark: str
    accent_soft: str
    icon_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "ezrename-icons")

    @property
    def dark(self) -> bool:
        return self.palette.dark

    # Convenience accessors so widgets can write ``tokens.text_muted``.
    @property
    def text(self) -> str:
        return self.palette.text

    @property
    def text_muted(self) -> str:
        return self.palette.text_muted

    @property
    def text_dim(self) -> str:
        return self.palette.text_dim

    @property
    def surface(self) -> str:
        return self.palette.surface

    @property
    def surface_alt(self) -> str:
        return self.palette.surface_alt

    @property
    def surface_hi(self) -> str:
        return self.palette.surface_hi

    @property
    def border(self) -> str:
        return self.palette.border

    @property
    def border_soft(self) -> str:
        return self.palette.border_soft

    @property
    def base(self) -> str:
        return self.palette.base

    @property
    def success(self) -> str:
        return self.palette.success

    @property
    def warning(self) -> str:
        return self.palette.warning

    @property
    def danger(self) -> str:
        return self.palette.danger

    @property
    def info(self) -> str:
        return self.palette.info

    def icon(self, name: str, *, color: Optional[str] = None, size: int = 18, muted: bool = False) -> QtGui.QIcon:
        tone = color or (self.palette.text_muted if muted else self.palette.text_muted)
        return icons.icon(name, tone, size)

    def accent_icon(self, name: str, size: int = 18) -> QtGui.QIcon:
        return icons.icon(name, self.accent, size)

    def mix(self, color: str, alpha: float, background: Optional[str] = None) -> str:
        """Blend *color* with the surface colour to fake translucency."""

        base = QtGui.QColor(background or self.palette.surface)
        foreground = QtGui.QColor(color)
        ratio = max(0.0, min(1.0, alpha))
        blended = QtGui.QColor(
            round(foreground.red() * ratio + base.red() * (1 - ratio)),
            round(foreground.green() * ratio + base.green() * (1 - ratio)),
            round(foreground.blue() * ratio + base.blue() * (1 - ratio)),
        )
        return blended.name()


def palette_for(name: str) -> Palette:
    return LIGHT if name == "light" else DARK


_CURRENT: Optional[Tokens] = None


def set_tokens(value: Tokens) -> Tokens:
    """Remember the active tokens so widgets can style themselves."""

    global _CURRENT
    _CURRENT = value
    return value


def tokens() -> Tokens:
    """Active design tokens (dark/blue by default)."""

    global _CURRENT
    if _CURRENT is None:
        _CURRENT = decorate_tokens(resolve_tokens("dark", "blue"))
    return _CURRENT


def resolve_tokens(theme_name: str, accent_name: str) -> Tokens:
    """Build tokens for a theme/accent pair.

    ``system`` follows the operating system colour scheme.
    """

    name = theme_name
    if name == "system":
        name = system_theme_name()
    accent, accent_dark = ACCENTS.get(accent_name, ACCENTS["blue"])
    palette = palette_for(name)
    return Tokens(
        palette=palette,
        accent=accent,
        accent_dark=accent_dark,
        accent_soft="",
    )


def system_theme_name() -> str:
    """Detect whether Windows is using a dark app theme."""

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except OSError:
            return "dark"
    return "dark"


def decorate_tokens(tokens: Tokens) -> Tokens:
    tokens.accent_soft = tokens.mix(tokens.accent, 0.16)
    return tokens


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #


def build_stylesheet(tokens: Tokens) -> str:
    p = tokens.palette
    a = tokens.accent
    icon_dir = tokens.icon_dir
    icon_dir.mkdir(parents=True, exist_ok=True)

    check = icons.write_qss_icon(icon_dir, "check", "#FFFFFF" if p.dark else "#FFFFFF", 14)
    chevron = icons.write_qss_icon(icon_dir, "chevron_down", p.text_muted, 14)
    radio = _write_radio_icon(icon_dir, a)

    def url(path: Path) -> str:
        return str(path).replace("\\", "/")

    family = ", ".join(f'"{name}"' if " " in name else name for name in FONT_STACK)
    mono = ", ".join(f'"{name}"' if " " in name else name for name in MONO_STACK)

    return f"""
* {{
    font-family: {family};
    font-size: {SIZES['body']}pt;
    color: {p.text};
}}
QWidget {{
    background: {p.base};
    color: {p.text};
}}
QMainWindow, QDialog {{ background: {p.base}; }}
QToolTip {{
    background: {p.surface_hi};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS['small']}px;
    padding: 6px 9px;
    font-size: {SIZES['small']}pt;
}}
QLabel {{ background: transparent; }}
QLabel[role="display"] {{ font-size: {SIZES['display']}pt; font-weight: 600; }}
QLabel[role="title"] {{ font-size: {SIZES['title']}pt; font-weight: 600; }}
QLabel[role="section"] {{
    font-size: {SIZES['small']}pt;
    font-weight: 600;
    color: {p.text_muted};
}}
QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="dim"] {{ color: {p.text_dim}; font-size: {SIZES['small']}pt; }}
QLabel[role="stat"] {{ font-size: 20pt; font-weight: 600; }}
QLabel[role="mono"] {{ font-family: {mono}; }}
QLabel[role="danger"] {{ color: {p.danger}; }}
QLabel[role="warning"] {{ color: {p.warning}; }}
QLabel[role="success"] {{ color: {p.success}; }}
QLabel[role="accent"] {{ color: {a}; }}

/* ---------- panels ---------- */
QFrame#Card, QFrame[card="true"] {{
    background: {p.surface};
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['card']}px;
}}
QFrame#CardFlat {{
    background: {p.surface_alt};
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['control']}px;
}}
QFrame#Sidebar {{
    background: {p.sidebar};
    border-right: 1px solid {p.border_soft};
}}
QFrame#Separator {{ background: {p.border_soft}; max-height: 1px; border: none; }}
QFrame#Toolbar {{
    background: {p.surface};
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['card']}px;
}}
QFrame#DropArea {{
    background: {p.surface_alt};
    border: 2px dashed {p.border};
    border-radius: {RADIUS['card']}px;
}}
QFrame#DropArea[active="true"] {{
    border: 2px dashed {a};
    background: {tokens.accent_soft};
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS['control']}px;
    padding: 7px 14px;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.surface_hi}; }}
QPushButton:pressed {{ background: {tokens.mix(a, 0.22)}; border-color: {a}; }}
QPushButton:disabled {{ color: {p.text_dim}; background: {p.surface_alt}; border-color: {p.border_soft}; }}
QPushButton[variant="primary"] {{
    background: {a};
    border: 1px solid {a};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {tokens.accent_dark}; border-color: {tokens.accent_dark}; }}
QPushButton[variant="primary"]:pressed {{ background: {tokens.accent_dark}; }}
QPushButton[variant="primary"]:disabled {{
    background: {tokens.mix(a, 0.28)};
    border-color: transparent;
    color: {p.text_muted};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {p.text_muted};
}}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_alt}; color: {p.text}; }}
QPushButton[variant="danger"] {{ background: {p.danger}; border-color: {p.danger}; color: #FFFFFF; font-weight: 600; }}
QPushButton[variant="danger"]:hover {{ background: {tokens.mix(p.danger, 0.85)}; }}
QPushButton[variant="quiet"] {{
    background: {p.surface};
    border: 1px solid {p.border};
    color: {p.text_muted};
}}
QPushButton[variant="quiet"]:hover {{ background: {p.surface_hi}; color: {p.text}; }}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS['control']}px;
    padding: 9px 12px;
    text-align: left;
    color: {p.text_muted};
    font-weight: 500;
}}
QPushButton#NavButton:hover {{ background: {p.sidebar_item}; color: {p.text}; }}
QPushButton#NavButton:checked {{
    background: {tokens.accent_soft};
    color: {a};
    font-weight: 600;
}}
QPushButton#IconButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS['small']}px;
    padding: 4px;
}}
QPushButton#IconButton:hover {{ background: {p.surface_hi}; border-color: {p.border}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS['control']}px;
    padding: 6px 10px;
    selection-background-color: {a};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {a};
    background: {p.surface};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p.text_dim}; }}
QLineEdit[state="error"] {{ border: 1px solid {p.danger}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({url(chevron)}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS['small']}px;
    selection-background-color: {tokens.accent_soft};
    selection-color: {p.text};
    padding: 4px;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border};
    background: {p.surface_alt};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {a}; }}
QCheckBox::indicator:checked {{
    background: {a};
    border-color: {a};
    image: url({url(check)});
}}
QRadioButton::indicator:checked {{ background: {p.surface_alt}; border-color: {a}; image: url({url(radio)}); }}

/* ---------- tables / lists ---------- */
QTableView, QTableWidget, QListView, QListWidget, QTreeView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['card']}px;
    gridline-color: {p.border_soft};
    outline: none;
    selection-background-color: {tokens.accent_soft};
    selection-color: {p.text};
}}
QTableView::item, QListView::item {{ padding: 5px 6px; border: none; }}
QTableView::item:hover, QListView::item:hover {{ background: {p.surface_hi}; }}
QTableView::item:selected, QListView::item:selected {{ background: {tokens.accent_soft}; color: {p.text}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {p.surface};
    color: {p.text_muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 9px 8px;
    font-size: {SIZES['small']}pt;
    font-weight: 600;
}}
QTableView QTableCornerButton::section {{ background: {p.surface}; border: none; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_dim}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {p.text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- progress / sliders ---------- */
QProgressBar {{
    background: {p.surface_alt};
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['small']}px;
    height: 8px;
    text-align: center;
    color: {p.text_muted};
}}
QProgressBar::chunk {{ background: {a}; border-radius: {RADIUS['small']}px; }}
QSplitter::handle {{ background: {p.border_soft}; }}
QSplitter::handle:hover {{ background: {a}; }}
QSlider::groove:horizontal {{ height: 5px; background: {p.surface_hi}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {a}; width: 15px; margin: -6px 0; border-radius: 7px;
}}

/* ---------- menus ---------- */
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS['control']}px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: {RADIUS['small']}px; }}
QMenu::item:selected {{ background: {tokens.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border_soft}; margin: 5px 8px; }}

/* ---------- badges / chips ---------- */
QLabel[badge="true"] {{
    border-radius: 9px;
    padding: 2px 9px;
    font-size: {SIZES['small']}pt;
    font-weight: 600;
    background: {p.surface_alt};
    color: {p.text_muted};
}}
QLabel[badge="true"][tone="ok"] {{ background: {tokens.mix(p.success, 0.18)}; color: {p.success}; }}
QLabel[badge="true"][tone="warn"] {{ background: {tokens.mix(p.warning, 0.20)}; color: {p.warning}; }}
QLabel[badge="true"][tone="bad"] {{ background: {tokens.mix(p.danger, 0.20)}; color: {p.danger}; }}
QLabel[badge="true"][tone="info"] {{ background: {tokens.mix(p.info, 0.18)}; color: {p.info}; }}
QLabel[badge="true"][tone="accent"] {{ background: {tokens.accent_soft}; color: {a}; }}

/* ---------- misc ---------- */
QStatusBar {{ background: {p.base}; color: {p.text_muted}; }}
QStatusBar::item {{ border: none; }}
QToolBar {{ background: transparent; border: none; spacing: 6px; }}
QGroupBox {{
    border: 1px solid {p.border_soft};
    border-radius: {RADIUS['card']}px;
    margin-top: 14px;
    padding: 12px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p.text_muted}; }}
QPlainTextEdit#Code {{ font-family: {mono}; font-size: {SIZES['small']}pt; }}
"""


def _write_radio_icon(directory: Path, color: str, size: int = 12) -> Path:
    """Small filled dot used by the stylesheet for checked radio buttons."""

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"radio_dot_{color.lstrip('#')}_{size}.png"
    if target.exists():
        return target
    ratio = 2
    pixmap = QtGui.QPixmap(size * ratio, size * ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(color))
    painter.drawEllipse(QtCore.QRectF(size * ratio * 0.18, size * ratio * 0.18,
                                      size * ratio * 0.64, size * ratio * 0.64))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    pixmap.save(str(target), "PNG")
    return target


# --------------------------------------------------------------------------- #
# Application level helpers
# --------------------------------------------------------------------------- #


def apply_theme(app: QtWidgets.QApplication, theme_name: str, accent_name: str) -> Tokens:
    """Apply a theme to the whole application and return its tokens."""

    tokens = set_tokens(decorate_tokens(resolve_tokens(theme_name, accent_name)))
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet(tokens))
    app.setWindowIcon(icons.app_icon(tokens.accent, tokens.accent_dark))

    qt_palette = QtGui.QPalette()
    p = tokens.palette
    qt_palette.setColor(QtGui.QPalette.Window, QtGui.QColor(p.base))
    qt_palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(p.text))
    qt_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(p.surface_alt))
    qt_palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(p.surface))
    qt_palette.setColor(QtGui.QPalette.Text, QtGui.QColor(p.text))
    qt_palette.setColor(QtGui.QPalette.Button, QtGui.QColor(p.surface_alt))
    qt_palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(p.text))
    qt_palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(tokens.accent))
    qt_palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#FFFFFF"))
    qt_palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(p.surface_hi))
    qt_palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(p.text))
    qt_palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(p.text_dim))
    app.setPalette(qt_palette)

    font = QtGui.QFont(base_family())
    font.setPointSizeF(max(9.0, min(12.0, app.font().pointSizeF())))
    app.setFont(font)
    return tokens


def base_family() -> str:
    """First available UI font from the preferred stack."""

    available = set(QtGui.QFontDatabase.families())
    for name in FONT_STACK:
        if name in available:
            return name
    return QtGui.QFont().family()


def mono_family() -> str:
    available = set(QtGui.QFontDatabase.families())
    for name in MONO_STACK:
        if name in available:
            return name
    return "Courier New"


def dark_title_bar(window: QtWidgets.QWidget, dark: bool = True) -> None:
    """Ask Windows to paint the native title bar dark.

    Keeping the native frame means resizing, Aero snap and keyboard shortcuts
    keep working exactly as users expect, while the title bar still matches the
    dark theme instead of glowing white above it.
    """

    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20=20H1+)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
        caption = ctypes.c_int(0x00FFFFFF if dark else 0x00000000)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)  # corner + border colour
        )
    except Exception:  # pragma: no cover - older Windows or no DWM
        pass


def rounded_shadow(widget: QtWidgets.QWidget, tokens: Tokens, blur: int = 26, y_offset: int = 6) -> None:
    """Attach a soft drop shadow used by floating surfaces."""

    effect = QtWidgets.QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    colour = QtGui.QColor(0, 0, 0, tokens.palette.shadow_alpha)
    effect.setColor(colour)
    widget.setGraphicsEffect(effect)


def elide(text: str, label: QtWidgets.QLabel, width: int) -> str:
    metrics = QtGui.QFontMetrics(label.font())
    return metrics.elidedText(text, QtCore.Qt.ElideMiddle, width)
