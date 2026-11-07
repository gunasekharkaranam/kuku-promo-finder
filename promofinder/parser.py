"""Parse Kuku screenplay .txt files into a flat list of timed events."""
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

TS = r"(\d+):(\d+(?:\.\d+)?)"
BLOCK_RE = re.compile(r"^\*\*(?P<head>[^*]+?):?\*\*\s*$")
TIME_RE = re.compile(rf"Start:\s*\(\s*{TS}\s*\)\s*\|\s*End:\s*\(\s*{TS}\s*\)")
SCENE_RE = re.compile(r"^SCENE\s+(\d+)")


def to_sec(m, s):
    return int(m) * 60 + float(s)


def fmt(t):
    """Seconds -> MM:SS.ss (same style as the screenplays)."""
    m = int(t // 60)
    return f"{m:02d}:{t - 60 * m:05.2f}"


@dataclass
class Event:
    ep: int
    idx: int
    kind: str          # dialogue | action | camera | sfx
    speaker: str       # character name for dialogue, else ""
    tone: str          # text in brackets after the name, e.g. "Cold, Commanding"
    text: str
    start: float
    end: float
    scene: int = 0
    heading: str = ""


@dataclass
class Episode:
    number: int
    title: str
    logline: str
    continuity: str
    events: list = field(default_factory=list)

    @property
    def duration(self):
        return max((e.end for e in self.events), default=0.0)

    def to_dict(self):
        d = asdict(self)
        d["duration"] = self.duration
        return d


def _kind(head):
    h = head.upper()
    if h.startswith("CAMERA"):
        return "camera", "", ""
    if h.startswith("ACTION"):
        return "action", "", ""
    if h.startswith("SOUND"):
        return "sfx", "", ""
    m = re.match(r"(?P<name>[^(]+?)\s*(?:\((?P<tone>[^)]*)\))?\s*$", head.strip())
    name = m.group("name").strip().upper() if m else head.strip().upper()
    tone = (m.group("tone") or "").strip() if m else ""
    return "dialogue", name, tone


def parse_episode(path):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    num, logline, cont = 0, "", ""
    for ln in lines[:10]:
        if ln.startswith("EPISODE NUMBER:"):
            d = re.findall(r"\d+", ln)
            num = int(d[0]) if d else 0
        elif ln.startswith("EPISODE LOGLINE:"):
            logline = ln.split(":", 1)[1].strip()
        elif ln.startswith("CONTINUITY NOTES:"):
            cont = ln.split(":", 1)[1].strip()
    if not num:
        d = re.findall(r"episode-(\d+)", Path(path).name)
        num = int(d[0]) if d else 0
    ep = Episode(num, Path(path).stem, logline, cont)

    scene, heading = 0, ""
    cur = None  # [kind, speaker, tone, start, end, textlines]

    def flush():
        if cur and cur[3] is not None:
            text = " ".join(t.strip() for t in cur[5] if t.strip()).strip()
            text = text.strip('"').strip() if cur[0] == "dialogue" else text
            ep.events.append(Event(num, len(ep.events), cur[0], cur[1], cur[2], text,
                                   cur[3], cur[4], scene, heading))

    for ln in lines:
        s = ln.strip()
        m = SCENE_RE.match(s)
        if m:
            flush(); cur = None
            scene = int(m.group(1)); continue
        if s.startswith("Scene heading:"):
            heading = s.split(":", 1)[1].strip(); continue
        if s.startswith(("Scene start:", "Scene end:", "Actions and dialogue:", "--- SCRIPT")):
            continue
        m = BLOCK_RE.match(s)
        if m:
            flush()
            k, sp, tone = _kind(m.group("head"))
            cur = [k, sp, tone, None, None, []]
            continue
        if cur is not None:
            m = TIME_RE.search(s)
            if m and cur[3] is None:
                cur[3] = to_sec(m.group(1), m.group(2))
                cur[4] = to_sec(m.group(3), m.group(4))
            elif s:
                cur[5].append(s)
    flush()
    ep.events.sort(key=lambda e: (e.start, e.idx))
    for i, e in enumerate(ep.events):
        e.idx = i
    return ep


def load_show(folder):
    files = sorted(Path(folder).glob("*.txt"))
    eps = [parse_episode(f) for f in files]
    eps.sort(key=lambda e: e.number)
    return eps
