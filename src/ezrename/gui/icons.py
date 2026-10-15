"""Vector icons drawn at runtime.

EzRename ships no binary icon files for the interface: every glyph is a small
SVG path rendered with ``QSvgRenderer`` and tinted on demand. That keeps the
project readable, scales cleanly on high-DPI displays and avoids resource
path problems in the packaged executable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6 import QtCore, QtGui, QtSvg

#: 24x24 viewBox icons. ``{c}`` is replaced with the requested colour.
ICON_SOURCES: Dict[str, str] = {
    "dashboard": "M3 3h7v8H3zM14 3h7v5h-7zM14 11h7v10h-7zM3 14h7v7H3z",
    "workspace": (
        "M4 5h7l1.5 2H20v11H4zM4 5V4h0"
        "|M9 12h6M9 15h4"
    ),
    "tools": "M4 6h16M4 12h16M4 18h16|M8 6v0M8 12v0",
    "history": "M12 7v5l3 2|M12 3a9 9 0 1 0 9 9|M3.5 8.5 4 4l4.5.6",
    "settings": (
        "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
        "|M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.1a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4Z"
    ),
    "folder": "M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2.5h8A1.5 1.5 0 0 1 20 9v8.5A1.5 1.5 0 0 1 18.5 19h-14A1.5 1.5 0 0 1 3 17.5z",
    "folder_open": "M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2.5h8A1.5 1.5 0 0 1 20 9v1H6.5L4 19h14.5l2-7",
    "file_plus": "M6 3h7l5 5v13H6zM13 3v5h5M12 13v5M9.5 15.5h5",
    "refresh": "M20 11a8 8 0 1 0-2.3 6M20 5v6h-6",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM16.5 16.5 21 21",
    "close": "M6 6l12 12M18 6 6 18",
    "check": "M4.5 12.5l5 5 10-11",
    "undo": "M4 11a8 8 0 1 1 2.3 6M4 5v6h6",
    "export": "M12 3v12M8 11l4 4 4-4M4 19h16",
    "plus": "M12 5v14M5 12h14",
    "minus": "M5 12h14",
    "trash": "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    "play": "M7 4l12 8-12 8z",
    "alert": "M12 3l9.5 17H2.5zM12 9v5M12 17h.01",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 8h.01M11 12h1v5h1",
    "sparkle": "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
    "chevron_down": "M6 9l6 6 6-6",
    "chevron_up": "M6 15l6-6 6 6",
    "chevron_right": "M9 6l6 6-6 6",
    "chevron_left": "M15 6l-6 6 6 6",
    "eye": "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z|M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "layers": "M12 4l8 4-8 4-8-4zM4 12l8 4 8-4M4 16l8 4 8-4",
    "swap": "M4 8h13l-4-4M20 16H7l4 4",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l4 2",
    "shield": "M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z|M9 12l2 2 4-4",
    "save": "M5 4h11l4 4v12H5zM8 4v6h8V4M8 20v-6h8v6",
    "filter": "M4 5h16l-6 7v6l-4 2v-8z",
    "keyboard": "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
    "info_square": "M4 4h16v16H4zM12 8h.01M11 11h1v6h1",
    "external": "M14 4h6v6M20 4l-8 8M18 14v6H4V6h6",
    "palette": "M12 21a9 9 0 1 1 0-18c5 0 9 3.1 9 7 0 2.5-2 4-4.5 4H15a1.5 1.5 0 0 0-1.2 2.4A1.6 1.6 0 0 1 12 21Z|M8 9h.01M12 7h.01M16 9h.01",
    "list": "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
}


def _renderer(svg: str) -> QtSvg.QSvgRenderer:
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    return renderer


def svg_pixmap(name: str, size: int, color: str, *, stroke: float = 1.7) -> QtGui.QPixmap:
    """Render one icon at *size* pixels in *color*."""

    body = ICON_SOURCES.get(name)
    if body is None:  # pragma: no cover - defensive
        return QtGui.QPixmap(size, size)
    paths = "".join(
        f'<path d="{segment}" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        for segment in body.split("|")
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{paths}</svg>'
    )
    ratio = 1.0
    try:  # pragma: no cover - only under a real GUI session
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            ratio = max(1.0, app.devicePixelRatio())
    except Exception:
        pass
    pixels = int(size * ratio)
    pixmap = QtGui.QPixmap(pixels, pixels)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    _renderer(svg).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


_ICON_CACHE: Dict[tuple, QtGui.QIcon] = {}


def icon(name: str, color: str, size: int = 18, *, stroke: float = 1.7) -> QtGui.QIcon:
    """Return a (cached) tinted icon."""

    key = (name, color, size, stroke)
    cached = _ICON_CACHE.get(key)
    if cached is None:
        cached = QtGui.QIcon(svg_pixmap(name, size, color, stroke=stroke))
        _ICON_CACHE[key] = cached
    return cached


def logo_pixmap(size: int, accent: str, accent_dark: str) -> QtGui.QPixmap:
    """Draw the EzRename mark: a rounded tile with a swap/rename glyph."""

    ratio = 2
    pixels = size * ratio
    pixmap = QtGui.QPixmap(pixels, pixels)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    rect = QtCore.QRectF(0.5, 0.5, pixels - 1, pixels - 1)
    radius = pixels * 0.26
    gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QtGui.QColor(accent))
    gradient.setColorAt(1.0, QtGui.QColor(accent_dark))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(gradient))
    painter.drawRoundedRect(rect, radius, radius)

    # soft highlight along the top edge
    highlight = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
    highlight.setColorAt(0.0, QtGui.QColor(255, 255, 255, 46))
    highlight.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
    painter.setBrush(QtGui.QBrush(highlight))
    painter.drawRoundedRect(rect.adjusted(pixels * 0.06, pixels * 0.05, -pixels * 0.06, -pixels * 0.5),
                            radius * 0.7, radius * 0.7)

    pen = QtGui.QPen(QtGui.QColor("#FFFFFF"))
    pen.setWidthF(pixels * 0.085)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    # two opposing arrows = rename / swap
    left = pixels * 0.28
    right = pixels * 0.72
    top = pixels * 0.38
    bottom = pixels * 0.62
    painter.drawLine(QtCore.QPointF(left, top), QtCore.QPointF(right, top))
    painter.drawLine(QtCore.QPointF(right, bottom), QtCore.QPointF(left, bottom))
    arrow = pixels * 0.11
    painter.drawLine(QtCore.QPointF(right - arrow, top - arrow), QtCore.QPointF(right, top))
    painter.drawLine(QtCore.QPointF(right - arrow, top + arrow), QtCore.QPointF(right, top))
    painter.drawLine(QtCore.QPointF(left + arrow, bottom - arrow), QtCore.QPointF(left, bottom))
    painter.drawLine(QtCore.QPointF(left + arrow, bottom + arrow), QtCore.QPointF(left, bottom))
    painter.end()
    pixmap.setDevicePixelRatio(1.0)
    return pixmap


def app_icon(accent: str, accent_dark: str) -> QtGui.QIcon:
    """Multi-resolution window/taskbar icon."""

    result = QtGui.QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(logo_pixmap(size, accent, accent_dark))
    return result


def write_qss_icon(directory: Path, name: str, color: str, size: int = 14) -> Path:
    """Write one tinted PNG used by the stylesheet (check marks, chevrons)."""

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}_{color.lstrip('#')}_{size}.png"
    if not target.exists():
        svg_pixmap(name, size, color, stroke=2.2).save(str(target), "PNG")
    return target


def asset_icon_path(relative: str) -> Optional[Path]:
    """Locate a file in the repository ``assets`` folder (development only)."""

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "assets" / relative
        if candidate.exists():
            return candidate
    return None
