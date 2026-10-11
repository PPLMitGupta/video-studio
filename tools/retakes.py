"""Propose cuts for mistakes and retakes. Proposals only: nothing is cut until it is approved
(copied into project.json "cuts").

From the narration (voiced recordings):
  cue words      "let me redo that", "scratch that", "sorry", "oops", "one more time", "hold on"
  restarts       the same five opening words again within 10 s
  repeats        a sentence said again almost word for word within 30 s (the earlier one is the retake)
From the screen (any recording):
  loops          the screen returns to exactly how it looked 5-40 s earlier (back, cancel, undo)

usage: retakes.py <work dir>   writes work/retakes.json, prints the proposals
"""
import json, re, sys
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np

CUES = re.compile(r"\b(let me (re ?do|redo|start over|try (that|this) again|do (that|this) again)|scratch that|"
                  r"sorry|oops|one more time|hold on|wait,? (no|let)|start again|that'?s wrong)\b", re.I)


def words(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


def from_transcript(segs):
    out = []
    for i, s in enumerate(segs):
        if CUES.search(s["text"]):
            a = segs[i - 1]["start"] if i else s["start"]
            b = segs[i + 1]["start"] if i + 1 < len(segs) else s["end"]
            out.append({"from": round(a, 2), "to": round(b, 2), "conf": "high",
                        "why": f'said "{CUES.search(s["text"]).group(0)}": cut the flawed take and the remark'})
        for j in range(i + 1, len(segs)):
            n = segs[j]
            if n["start"] - s["start"] > 30:
                break
            wa, wb = words(s["text"]), words(n["text"])
            gap = n["start"] - s["start"]
            # parallel phrasing ("This is the X. This is the Y.") is narration style, not a retake:
            # only a long repeated opening or an almost identical sentence counts
            if gap < 10 and len(wa) >= 5 and wa[:5] == wb[:5]:
                out.append({"from": round(s["start"], 2), "to": round(n["start"], 2), "conf": "medium",
                            "why": f'restarted "{" ".join(wa[:5])}..."'})
                break
            if len(wa) >= 5 and SequenceMatcher(None, wa, wb).ratio() >= 0.8:
                out.append({"from": round(s["start"], 2), "to": round(n["start"], 2), "conf": "medium",
                            "why": "said the same sentence again"})
                break
    return out


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def from_screen(hash_t, hash_v, frac, start, speech=()):
    """The screen comes back to an earlier state after something different was shown."""
    out = []
    n = len(hash_t)
    i = 0
    while i < n:
        for j in range(i + 10, min(n, i + 80)):           # 5-40 s later (hashes every 0.5 s)
            if hamming(hash_v[i], hash_v[j]) <= 2:
                mid = max(hamming(hash_v[i], hash_v[k]) for k in range(i, j))
                if mid >= 18:
                    a, b = float(hash_t[i]), float(hash_t[j])
                    talk = sum(max(0, min(b, e) - max(a, s)) for s, e in speech)
                    out.append({"from": round(a, 2), "to": round(b, 2), "conf": "low" if talk > 2 else "medium",
                                "why": "screen went back to how it looked before (back / cancel / undo?)"})
                    i = j
                    break
        i += 1
    return out


def main():
    work = Path(sys.argv[1])
    props = []
    segs = []
    if (work / "segments.json").exists():
        segs = json.loads((work / "segments.json").read_text())
        props += from_transcript(segs)
    if (work / "analysis.npz").exists():
        a = np.load(work / "analysis.npz")
        props += from_screen(a["hash_t"], a["hash_v"], a["frac"], float(a["start"]),
                             [(s["start"], s["end"]) for s in segs])
    props.sort(key=lambda p: p["from"])
    (work / "retakes.json").write_text(json.dumps(props, indent=1))
    for p in props:
        print(f'  {p["from"]:.1f}-{p["to"]:.1f}s  [{p["conf"]}]  {p["why"]}')
    return props


if __name__ == "__main__":
    main()
