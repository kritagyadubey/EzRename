"""Application settings stored outside the install directory.

Nothing is ever written next to the executable: a packaged EzRename may live in
``C:\\Program Files`` where ordinary users cannot write. Settings go to
``%APPDATA%\\EzRename`` on Windows (``~/.config/ezrename`` elsewhere) and the
history database to a local data directory. ``EZRENAME_HOME`` overrides both,
which keeps tests and portable installs away from real user data.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

from .. import APP_NAME

ENV_HOME = "EZRENAME_HOME"

DEFAULT_ACCENTS = ("blue", "violet", "teal", "amber", "rose")


def _env_home() -> Optional[Path]:
    raw = os.environ.get(ENV_HOME, "").strip()
    return Path(raw).expanduser() if raw else None


def config_dir() -> Path:
    """Directory that holds ``settings.json`` (and, by default, history)."""

    override = _env_home()
    if override is not None:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "ezrename"


def data_dir() -> Path:
    """Directory that holds the history database."""

    override = _env_home()
    if override is not None:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "ezrename"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    """Everything the GUI remembers between launches."""

    # --- appearance -----------------------------------------------------
    theme: str = "dark"          # dark | light | system
    accent: str = "blue"
    show_natural_sort_hint: bool = True

    # --- file selection -------------------------------------------------
    include_hidden: bool = False
    recursive: bool = False
    follow_symlinks: bool = False
    default_folder: str = ""
    last_folder: str = ""
    remember_last_folder: bool = True
    recent_folders: list[str] = field(default_factory=list)
    sort_key: str = "name"
    sort_reverse: bool = False

    # --- rename defaults ------------------------------------------------
    number_start: int = 1
    number_step: int = 1
    number_padding: int = 3
    number_style: str = "decimal"
    separator: str = "_"
    confirm_before_apply: bool = True
    show_preview_details: bool = True
    keep_operation_stack: bool = True
    operation_stack: list[dict] = field(default_factory=list)
    presets: dict[str, list[dict]] = field(default_factory=dict)

    # --- history --------------------------------------------------------
    history_limit: int = 1000
    confirm_before_undo: bool = True

    # --- window ---------------------------------------------------------
    window_width: int = 1280
    window_height: int = 820
    window_maximized: bool = False
    window_x: int = -1
    window_y: int = -1

    # --- meta -----------------------------------------------------------
    seen_welcome: bool = False
    last_version: str = ""

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppSettings":
        """Load settings, falling back to defaults for missing/!invalid values."""

        target = path or (config_dir() / "settings.json")
        settings = cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(raw, dict):
            return settings
        valid = {info.name: info for info in fields(cls)}
        for key, value in raw.items():
            info = valid.get(key)
            if info is None:
                continue
            default = getattr(settings, key)
            if isinstance(default, bool) and not isinstance(value, bool):
                continue
            if isinstance(default, int) and not isinstance(default, bool) and not isinstance(value, int):
                continue
            if isinstance(default, list) and not isinstance(value, list):
                continue
            if isinstance(default, dict) and not isinstance(value, dict):
                continue
            if isinstance(default, str) and not isinstance(value, str):
                continue
            setattr(settings, key, value)
        return settings

    def save(self, path: Optional[Path] = None) -> Path:
        """Write settings atomically and return the file that was written."""

        target = path or (config_dir() / "settings.json")
        ensure_dir(target.parent)
        payload = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, target)
        return target

    def update(self, **values: Any) -> None:
        for key, value in values.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def remember_folder(self, folder: str, *, limit: int = 10) -> None:
        """Track recently used folders for the dashboard and Open dialog."""

        folder = str(folder)
        recent = [item for item in self.recent_folders if item != folder]
        recent.insert(0, folder)
        self.recent_folders = recent[:limit]
        self.last_folder = folder

    def add_preset(self, name: str, stack: list[dict]) -> None:
        self.presets[name] = stack

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
