"""The one place that knows how source time becomes output time.

Output = [intro card] + source with cuts removed, speed-ups applied and holds (frozen frames)
inserted + [outro card]. Everything that is placed in time (voice lines, captions, step titles,
clicks, sound effects, the camera) goes through Timeline.map(), so nothing drifts.

  src time      seconds in the original recording
  content time  src with cuts and speed-ups applied (what the ffmpeg decoder delivers)
  out time      content plus holds plus the intro offset (what the viewer sees)
"""


class Timeline:
    def __init__(self, src_dur, cuts=(), speedups=(), holds=(), intro=0.0, outro=0.0):
        self.src_dur = float(src_dur)
        self.cuts = sorted((float(a), float(b)) for a, b in cuts)
        self.intro, self.outro = float(intro), float(outro)
        # a speed-up never overlaps a cut: trim it to what remains
        sp = []
        for lo, hi, s in sorted(speedups):
            parts = [(float(lo), float(hi))]
            for a, b in self.cuts:
                parts = [q for p in parts for q in ((p[0], min(p[1], a)), (max(p[0], b), p[1])) if q[1] - q[0] > 1e-3]
            sp += [(a, b, float(s)) for a, b in parts]
        self.speedups = sp
        self.holds = sorted((float(t), float(d)) for t, d in holds)   # (src time, seconds frozen)
        self.content_dur = self.content(self.src_dur)
        self.out_dur = self.intro + self.content_dur + sum(d for _, d in self.holds) + self.outro

    # ---- source -> content (same formula build.py always used, so old projects place identically)
    def content(self, t):
        return (t - sum(min(max(t - lo, 0), hi - lo) * (1 - 1 / s) for lo, hi, s in self.speedups)
                - sum(min(max(t - a, 0), b - a) for a, b in self.cuts))

    def in_cut(self, t):
        return any(a < t < b for a, b in self.cuts)

    def map(self, t):
        """Source time -> output time. A time inside a cut maps to the cut point."""
        return self.intro + self.content(t) + sum(d for th, d in self.holds if th < t)

    # ---- output -> content (for the renderer): (content time, kind) with kind in intro/content/hold/outro
    def at_out(self, T):
        if T < self.intro:
            return 0.0, "intro"
        c = T - self.intro
        for th, d in self.holds:
            ch = self.content(th)
            if c < ch:
                break
            if c < ch + d:
                return ch, "hold"
            c -= d
        if c >= self.content_dur:
            return self.content_dur, "outro"
        return c, "content"

    def cut_points(self):
        """Output times where a cut joins two pieces (the renderer cross-fades there)."""
        return [self.map(b) for a, b in self.cuts if 0 < a and b < self.src_dur]

    def speed_at(self, t):
        for lo, hi, s in self.speedups:
            if lo <= t < hi:
                return s
        return 1.0

    def ffmpeg_filter(self):
        """Decoder-side filter: drop cut frames, retime speed-ups, constant 30 fps."""
        expr = "T" + "".join(f"-clip(T-{lo},0,{hi - lo:.3f})*{1 - 1 / s:.6f}" for lo, hi, s in self.speedups)
        expr += "".join(f"-clip(T-{a},0,{b - a:.3f})" for a, b in self.cuts)
        sel = ""
        if self.cuts:
            sel = "select='not(" + "+".join(f"between(t,{a},{b})" for a, b in self.cuts) + ")',"
        return f"{sel}setpts='({expr})/TB',fps=30"
