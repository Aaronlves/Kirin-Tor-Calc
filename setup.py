"""Setuptools hooks for reproducible local and CI builds."""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class CleanPackageBuild(build_py):
    """Remove files left by older Kirin package layouts before copying sources."""

    def run(self) -> None:
        package_root = Path(self.build_lib) / "kirin_tor"
        if package_root.is_symlink() or package_root.is_file():
            package_root.unlink()
        elif package_root.is_dir():
            shutil.rmtree(package_root)
        super().run()


setup(cmdclass={"build_py": CleanPackageBuild})
