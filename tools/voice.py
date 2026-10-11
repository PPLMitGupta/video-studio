"""AI voice: Kokoro TTS per script line (cached), pronunciation fixes, and placement on the output timeline."""
import hashlib, json, re
from pathlib import Path
import numpy as np
import soundfile as sf
from common import HOME, ROOT, kokoro

SR = 24000  # Kokoro output rate


def load_script(proj):
    """script.tsv rows: start<TAB>text[<TAB>step title]. Returns [(t, text, step)]."""
    rows = []
    for l in (proj / "script.tsv").read_text().splitlines():
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        parts = l.rstrip("\n").split("\t")
        rows.append((float(parts[0]), parts[1].strip(), parts[2].strip() if len(parts) > 2 else ""))
    return rows


def load_pronunciations(cfg):
    """Global pronunciations.json plus project overrides. {"SIMMS": "sims", ...}; "" disables a term."""
    d = {}
    for p in (ROOT / "pronunciations.json", HOME / "pronunciations.json"):   # team list, then personal
        if p.exists():
            d.update(json.loads(p.read_text()))
    d.update(cfg.get("pronunciations", {}))
    return {k: v for k, v in d.items() if v}


def spoken(text, pron):
    """What the voice actually reads. Captions keep the written text."""
    for term in sorted(pron, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(term)}(?![\w-])", pron[term], text)
    return text


def tts_cached(text, cfg, tts_dir, k=None):
    """Return (audio float32 @24k, kokoro instance). Cache key = voice|lang|speed|spoken text."""
    key = hashlib.sha1(f"{cfg['voice']}|{cfg['lang']}|{cfg['speed']}|{text}".encode()).hexdigest()[:12]
    f = Path(tts_dir) / f"{key}.wav"
    if f.exists():
        audio, _ = sf.read(f, dtype="float32")
        return audio, k
    k = k or kokoro()
    audio, sr = k.create(text, voice=cfg["voice"], speed=cfg["speed"], lang=cfg["lang"])
    assert sr == SR
    audio = np.trim_zeros(audio.astype(np.float32), "fb")
    sf.write(f, audio, SR)
    return audio, k


def place_lines(rows, tl, cfg, tts_dir, pron=None):
    """Voice every row and place it at map(start), pushed later only if the previous line runs long.

    Returns (track @24k, placements, voice_end). Placements are on the output timeline."""
    pron = pron or {}
    Path(tts_dir).mkdir(parents=True, exist_ok=True)
    k = None
    track = np.zeros(int((tl.out_dur + 1) * SR), dtype=np.float32)
    placements, cursor = [], 0.0
    for i, (t, txt, step) in enumerate(rows):
        say = spoken(txt, pron)
        audio, k = tts_cached(say, cfg, tts_dir, k)
        want = tl.map(t)
        at = max(want, cursor + cfg["min_gap"]) if i else want
        s = int(at * SR)
        if s + len(audio) > len(track):
            track = np.pad(track, (0, s + len(audio) - len(track)))
        track[s:s + len(audio)] += audio
        cursor = at + len(audio) / SR
        p = {"orig": t, "target": round(want, 2), "placed": round(at, 2), "dur": round(len(audio) / SR, 2), "text": txt}
        if step:
            p["step"] = step
        if say != txt:
            p["spoken"] = say
        placements.append(p)
    return track, placements, cursor
