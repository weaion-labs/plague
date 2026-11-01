"""Download the Lightpanda nightly binary for this platform."""

from __future__ import annotations

import os
import platform
import shutil
import stat
from pathlib import Path
from typing import Callable

import httpx

from .config import project_cache_dir

RELEASE = "https://github.com/lightpanda-io/browser/releases/download/nightly"

ASSETS = {
    ("linux", "x86_64"): "lightpanda-x86_64-linux",
    ("linux", "amd64"): "lightpanda-x86_64-linux",
    ("linux", "aarch64"): "lightpanda-aarch64-linux",
    ("linux", "arm64"): "lightpanda-aarch64-linux",
    ("darwin", "x86_64"): "lightpanda-x86_64-macos",
    ("darwin", "arm64"): "lightpanda-aarch64-macos",
    ("darwin", "aarch64"): "lightpanda-aarch64-macos",
}

Progress = Callable[[int, int], None]


class InstallError(RuntimeError):
    pass


def asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    asset = ASSETS.get((system, machine))
    if not asset:
        raise InstallError(
            f"no Lightpanda nightly for {system}/{machine}; "
            "Windows users need WSL2"
        )
    return asset


def install_lightpanda(
    destination: str | Path | None = None,
    *,
    force: bool = False,
    progress: Progress | None = None,
) -> Path:
    target = Path(destination) if destination else project_cache_dir() / "bin" / "lightpanda"
    if target.is_file() and os.access(target, os.X_OK) and not force:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    asset = asset_name()
    url = f"{RELEASE}/{asset}"
    temporary = target.with_suffix(target.suffix + ".part")

    try:
        with httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=180.0),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            written = 0
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise InstallError(f"download failed: {exc}") from exc

    temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.move(str(temporary), str(target))
    return target
