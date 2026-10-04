"""Per-computer paths. Absolute paths never enter a shared workspace."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from seqatelier.core.types import SeqAtelierError


def user_directory(kind: str) -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / "seqatelier" / kind
    if os.sys.platform == "darwin":
        base = Path.home() / "Library" / ("Caches" if kind == "cache" else "Application Support")
        return base / "seqatelier"
    defaults = {"config": ".config", "cache": ".cache", "data": ".local/share"}
    return Path(os.environ.get(f"XDG_{kind.upper()}_HOME", str(Path.home() / defaults[kind]))) / "seqatelier"


def config_path() -> Path:
    value = os.environ.get("SEQATELIER_CONFIG")
    return (Path(value) if value else user_directory("config") / "config.json").expanduser().resolve()


def lock_directory() -> Path:
    value = os.environ.get("SEQATELIER_CACHE_HOME")
    return (Path(value) if value else user_directory("cache")).expanduser().resolve() / "locks"


@dataclass(frozen=True)
class Selection:
    path: Path
    source: str
    workspace_id: str | None = None


def resolve_workspace(value: str | Path | None = None) -> Selection:
    """Explicit path > environment > registered location > platform default."""
    if value is not None:
        return Selection(Path(value).expanduser().resolve(), "argument")
    if os.environ.get("SEQATELIER_WORKSPACE"):
        return Selection(Path(os.environ["SEQATELIER_WORKSPACE"]).expanduser().resolve(), "environment")
    location = config_path()
    if location.exists():
        try:
            config = json.loads(location.read_text(encoding="utf-8"))
            selected = config["workspace"]
            path, identifier = selected["path"], selected["id"]
            if config["version"] != 1 or not isinstance(path, str) or not Path(path).is_absolute():
                raise ValueError("Unsupported configuration or non-absolute path")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("Missing workspace identity")
        except (ValueError, KeyError, TypeError) as exc:
            raise SeqAtelierError(
                f"Invalid local configuration: {location}. Use 'seqatelier workspace use PATH' to register it again."
            ) from exc
        return Selection(Path(path).resolve(), "configuration", identifier)
    return Selection((user_directory("data") / "default").resolve(), "default")
