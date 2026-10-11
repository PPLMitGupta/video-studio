"""Voice every line in work/lines.json with build.py's cache key, and write work/durations.json.

usage: tts_prep.py <project>
Run this before recording: the recorder paces each cue to its line's real length.
"""
import hashlib, json, sys
import numpy as np, soundfile as sf
from _common import kokoro, load_config, project

proj = project(sys.argv[1])
cfg = load_config(proj)
lines = json.loads((proj / "work/lines.json").read_text())
tts = proj / "work/tts"; tts.mkdir(parents=True, exist_ok=True)
k, out = None, {}
for cid, txt in lines.items():
    key = hashlib.sha1(f"{cfg['voice']}|{cfg['lang']}|{cfg['speed']}|{txt}".encode()).hexdigest()[:12]
    f = tts / f"{key}.wav"
    if not f.exists():
        k = k or kokoro()
        a, sr = k.create(txt, voice=cfg["voice"], speed=cfg["speed"], lang=cfg["lang"])
        sf.write(f, np.trim_zeros(a.astype(np.float32), "fb"), sr)
    a, sr = sf.read(f)
    out[cid] = round(len(a) / sr, 2)
(proj / "work/durations.json").write_text(json.dumps(out, indent=1))
print(f"{len(out)} lines, {sum(out.values()) / 60:.1f} min of voice")
