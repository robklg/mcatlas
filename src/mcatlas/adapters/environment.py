"""Guesses about this computer for `mcatlas init`: where the Minecraft launcher keeps its
files (player names, Java, client jars) and the local time zone.

Only suggestions: every one is shown to the user, who can change it. Nothing here reads worlds.
"""

import locale
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Final

from mcatlas.core.model import Language

# The launcher's Java runtimes, newest last (epsilon = Java 25, which BlueMap 5.17+ needs).
_RUNTIMES: Final = ("alpha", "beta", "gamma", "delta", "epsilon")
_RELEASE: Final = re.compile(r"^\d+\.\d+(\.\d+)?$")


def minecraft_dir() -> Path | None:
    """The launcher's folder: the standard place per operating system."""
    home = Path.home()
    if sys.platform == "darwin":
        candidate = home / "Library" / "Application Support" / "minecraft"
    elif sys.platform == "win32":
        candidate = Path(os.environ.get("APPDATA", home)) / ".minecraft"
    else:
        candidate = home / ".minecraft"
    return candidate if candidate.is_dir() else None


def usercache() -> Path | None:
    base = minecraft_dir()
    path = base / "usercache.json" if base else None
    return path if path is not None and path.is_file() else None


def java() -> Path | None:
    """The newest Java the launcher ships, else `java` on the PATH."""
    base = minecraft_dir()
    if base is not None:
        name = "java.exe" if sys.platform == "win32" else "java"
        found = [p for p in (base / "runtime").glob(f"java-runtime-*/**/bin/{name}") if p.is_file()]

        def rank(p: Path) -> int:
            runtime = next((part for part in p.parts if part.startswith("java-runtime-")), "")
            flavour = runtime.removeprefix("java-runtime-")
            return _RUNTIMES.index(flavour) if flavour in _RUNTIMES else -1

        if found:
            return max(found, key=rank)
    on_path = shutil.which("java")
    return Path(on_path) if on_path else None


def client_jar() -> Path | None:
    """The most recently used release client jar (versions/<id>/<id>.jar)."""
    base = minecraft_dir()
    if base is None:
        return None
    jars = [
        d / f"{d.name}.jar"
        for d in (base / "versions").glob("*")
        if _RELEASE.match(d.name) and (d / f"{d.name}.jar").is_file()
    ]
    return max(jars, key=lambda p: p.stat().st_mtime) if jars else None


def timezone() -> str:
    """The IANA name of the local time zone, from /etc/localtime or $TZ; UTC if unknown."""
    tz = os.environ.get("TZ", "")
    if "/" in tz:
        return tz.lstrip(":")
    target = os.path.realpath("/etc/localtime")
    _, sep, name = target.partition("zoneinfo/")
    return name if sep and name else "UTC"


def language() -> Language:
    """Dutch when the system speaks Dutch, else English."""
    code = os.environ.get("LANG", "") or (locale.getlocale()[0] or "")
    return "nl" if code.lower().startswith("nl") else "en"
