"""Make short voice samples to choose from.

usage: samples.py [voice ...] [--text "..."]
default voices: af_heart am_michael bf_emma bm_george (US female/male, UK female/male)
"""
import argparse
import soundfile as sf
from common import ROOT, kokoro, run_ffmpeg

TEXT = ("Let's walk through how to create a new district. These are the districts already on our platform, "
        "along with their current status. Once the district administrator has been onboarded, "
        "we can mark the district as active.")

ap = argparse.ArgumentParser()
ap.add_argument("voices", nargs="*", default=["af_heart", "am_michael", "bf_emma", "bm_george"])
ap.add_argument("--text", default=TEXT)
a = ap.parse_args()
k = kokoro()
out = ROOT / "voice_samples"
out.mkdir(exist_ok=True)
for v in a.voices:
    audio, sr = k.create(a.text, voice=v, lang="en-gb" if v.startswith("b") else "en-us")
    wav = out / f"{v}.wav"
    sf.write(wav, audio, sr)
    run_ffmpeg("-i", str(wav), "-c:a", "aac", "-b:a", "160k", str(wav.with_suffix(".m4a")))
    wav.unlink()
    print(wav.with_suffix(".m4a"))
