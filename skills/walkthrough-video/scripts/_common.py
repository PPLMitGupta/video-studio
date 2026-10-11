"""Shared setup: find the plugin's tools folder and a project folder."""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "tools"     # <plugin>/skills/walkthrough-video/scripts -> <plugin>/tools
sys.path.insert(0, str(TOOLS))
from common import PROJECTS, ffmpeg, kokoro, load_config  # noqa: E402,F401


def project(arg):
    p = Path(arg)
    return p if p.is_dir() else PROJECTS / arg
