"""Include application assets: the built web UI and the example config."""

from pathlib import Path
from shutil import copy2, copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        if getattr(self, "editable_mode", False):
            return  # an editable install serves ui/dist from the checkout
        root = Path(__file__).parent
        target = Path(self.build_lib) / "doblarr"
        ui = root / "ui" / "dist"
        if not (ui / "index.html").is_file():
            raise SystemExit("The web UI is not built: run `npm ci && npm run build:ui` first.")
        copytree(ui, target / "web", dirs_exist_ok=True)
        copy2(root / "config.example.yaml", target / "config.example.yaml")


setup(cmdclass={"build_py": BuildPy})
