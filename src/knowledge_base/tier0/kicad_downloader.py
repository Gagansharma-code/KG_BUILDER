"""Download KiCad official symbol and footprint repositories via git."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

KICAD_REPOS = {
    "kicad-symbols": "https://github.com/KiCad/kicad-symbols.git",
    "kicad-footprints": "https://github.com/KiCad/kicad-footprints.git",
}
DEFAULT_REPOS_DIR = Path("data/kicad_repos")


def download_kicad_libraries(
    repos_dir: Path = DEFAULT_REPOS_DIR,
    branch: str = "master",
) -> dict[str, Path]:
    """
    Clone KiCad symbol and footprint repos into repos_dir.
    If a repo already exists, runs `git pull` instead of clone.

    Args:
        repos_dir: Directory to clone into. Created if not exists.
        branch: Branch to clone. Default "master".

    Returns:
        Dict mapping repo name → local Path.
        e.g. {"kicad-symbols": Path("data/kicad_repos/kicad-symbols"), ...}

    Raises:
        RuntimeError: If git is not installed or clone/pull fails.
    """
    repos_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    for repo_name, url in KICAD_REPOS.items():
        dest = repos_dir / repo_name
        git_dir = dest / ".git"

        if git_dir.exists():
            logger.info("Pulling %s in %s", repo_name, dest)
            try:
                subprocess.run(
                    ["git", "pull", "origin", branch],
                    cwd=dest,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(exc.stderr) from exc
        else:
            logger.info("Cloning %s into %s", repo_name, dest)
            try:
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--depth=1",
                        "--branch",
                        branch,
                        url,
                        str(dest),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(exc.stderr) from exc

        result[repo_name] = dest

    return result
