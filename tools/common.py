"""Shared paths and helpers for the video-studio tools.

Two places:
  ROOT  the plugin (this repo): code, brand.json, pronunciations.json, voice samples. Shared by the team.
  HOME  each person's workspace (default ~/VideoStudio, or $VIDEO_STUDIO_HOME): the Python env,
        ffmpeg, the voice model and every project. Created by setup.sh; never inside the plugin,
        because a plugin update replaces the plugin folder.
"""
import json, os, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("VIDEO_STUDIO_HOME", Path.home() / "VideoStudio")).expanduser()
BIN = HOME / "bin"
MODELS = HOME / "models"
PROJECTS = HOME / "projects"
# espeak-ng silently falls back to a baked-in path when its data path is > ~160 chars,
# so keep a copy somewhere short (setup.sh creates it).
ESPEAK_DATA = Path.home() / ".cache" / "espeak-ng-data"
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

DEFAULTS = {
    "voice": "am_michael",   # Kokoro voice; the user picked "2 male US"
    "lang": "en-us",
    "speed": 1.0,
    "min_gap": 0.25,         # min silence between consecutive voice lines (s)
    "loudness": -16,         # integrated LUFS target
}


def ffmpeg():
    """Path to our own ffmpeg (a standalone build from imageio-ffmpeg; a system ffmpeg may be
    missing, a different version, or blocked by macOS)."""
    exe = BIN / "ffmpeg"
    if not exe.exists():
        import imageio_ffmpeg
        BIN.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(imageio_ffmpeg.get_ffmpeg_exe(), BIN), exe)
    # mlx_whisper shells out to plain "ffmpeg": make sure ours wins
    os.environ["PATH"] = f"{BIN}{os.pathsep}{os.environ['PATH']}"
    return str(exe)


def run_ffmpeg(*args):
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def duration(path):
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = out.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def kokoro():
    from kokoro_onnx import Kokoro, EspeakConfig
    import espeakng_loader
    lib = espeakng_loader.get_library_path()
    return Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"),
                  espeak_config=EspeakConfig(data_path=str(ESPEAK_DATA), lib_path=lib))


def project_dir(name_or_path):
    p = Path(name_or_path)
    return p if p.is_dir() else PROJECTS / name_or_path


def load_config(proj):
    cfg = dict(DEFAULTS)
    cfg.update(json.loads((proj / "project.json").read_text()))
    return cfg


def fmt(t):
    t = round(t, 1)
    return f"{int(t // 60)}:{t % 60:04.1f}"
