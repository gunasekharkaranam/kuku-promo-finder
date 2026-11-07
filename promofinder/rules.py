"""Cheap, explainable rules: score how good a time window is as a promo.

These rules run with no model at all. They are used (1) as a free baseline,
(2) to check and re-score what the LLM proposes, and (3) to flag bad picks.
All scores are 0-10.
"""
import re

HOOK_WORDS = r"""slap|slaps|slapped|punch|punches|struck|strikes|strike|shove|shoves|grab|grabs|seize|seizes|
choke|chokes|kick|kicks|collapse|collapses|faint|faints|crash|crashes|smash|shatter|shatters|blood|bleed|bleeding|
dagger|knife|sword|blade|pistol|gun|fire|burn|burns|flames|chains|shackle|handcuff|kiss|kisses|throws|hurls|drags|
slams|rips|tears up|spits|lunges|pins|thrashes|whip|noose|gallows|poison|poisoned|witch|witchcraft|duke|duchess|
heir|alive|dead|die|kill|murder|traitor|treason|betray|liar|fraud|arrest|execute|execution|hang|sentence|pregnant|
divorce|wedding|bride|marry|married|abandon|jilted|disinherit|beggar|cripple|secret|truth|revealed|unmask"""
HOOK_RE = re.compile(r"\b(" + HOOK_WORDS.replace("\n", "") + r")\b", re.I)
HOT_TONES = re.compile(r"shout|scream|furious|venom|threat|menac|cruel|outrag|sinister|chill|accus|shock|stun|"
                       r"desperate|gasp|sob|incredul|mock|taunt|gloat|spite|harsh|savage|enraged|horrif|panic|roar", re.I)
SOFT_TONES = re.compile(r"gentle|tender|reassur|calm|soft|warm|sincere|affection|kind|relieved|content|grateful", re.I)
SFX_HIT = re.compile(r"slap|punch|crack|crash|thud|gasp|scream|boom|bang|slam|shatter|impact|smack|cliffhanger", re.I)
UNRESOLVED_ACTION = re.compile(r"\b(raises|reaches|lunges|draws|aims|steps forward|bursts|storms|freezes|stares|"
                               r"eyes widen|turns slowly|grabs|seizes|lifts|advances|looms|halts|stops dead|"
                               r"slams open|kicks open|appears|emerges|enters)\b", re.I)
THREAT_LINE = re.compile(r"\b(you will|you'll|or else|i will|i'll|never|how dare|you dare|who are you|what have you|"
                         r"you're finished|you are finished|kneel|guards|seize (her|him)|arrest)\b", re.I)
RESOLVE_LINE = re.compile(r"\b(thank you|it's all right|it's alright|you're safe|rest now|goodnight|good night|"
                          r"i love you|forgive|we're home|it's over)\b", re.I)
CONTEXT_REF = re.compile(r"\b(again|still|remember|as i said|as you said|yesterday|last night|earlier|"
                         r"before that|the letter|that night|like i told)\b", re.I)
STAKES = re.compile(r"\b(wife|husband|sister|mother|father|fiance|fiancé|duke|duchess|marry|married|wedding|bride|"
                    r"baby|child|heir|family|son|daughter)\b", re.I)
WEAK_OPEN = re.compile(r"^(and|but|so|then|yes|no|well|\.\.\.|because)\b", re.I)
ESTABLISHING = re.compile(r"\b(establishing|wide shot|exterior|aerial|landscape|drone shot)\b", re.I)


def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, x))


def _line_heat(e):
    """How 'hot' one event is (0-3)."""
    h = 0.0
    if HOOK_RE.search(e.text):
        h += 1.2
    if e.kind == "dialogue":
        if HOT_TONES.search(e.tone):
            h += 1.0
        if "!" in e.text:
            h += 0.4
        if "?" in e.text:
            h += 0.3
    if e.kind == "sfx" and SFX_HIT.search(e.text):
        h += 1.0
    if e.kind == "action" and UNRESOLVED_ACTION.search(e.text):
        h += 0.5
    return min(h, 3.0)


def events_in(events, a, b):
    return [e for e in events if e.end > a + 0.05 and e.start < b - 0.05]


def hook_score(events, a):
    """Is there something in the first 3 seconds that stops a scroll?"""
    first = [e for e in events if a - 0.05 <= e.start < a + 3.0 or (e.start < a and e.end > a + 0.5)]
    if not first:
        return 0.0, "nothing happens in first 3s"
    heat = sum(_line_heat(e) for e in first)
    talky = any(e.kind in ("dialogue", "action", "sfx") for e in first)
    s = 1.5 + 1.8 * heat + (1.0 if talky else -2.0)
    note = ""
    if all(e.kind == "camera" and ESTABLISHING.search(e.text) for e in first):
        s -= 3; note = "opens on an establishing shot"
    first_line = next((e for e in first if e.kind == "dialogue"), None)
    if first_line and WEAK_OPEN.search(first_line.text):
        s -= 1.5; note = "opens mid-conversation"
    return clamp(s), note


def cliff_score(events, b, next_events, episode_end):
    """Does it cut on an unresolved moment?"""
    last = [e for e in events if e.end >= b - 4.0 and e.start < b]
    if not last:
        return 0.0, "nothing at the end"
    s, note = 3.0, ""
    lines = [e for e in last if e.kind == "dialogue"]
    if any(e.kind == "sfx" and "cliffhanger" in e.text.lower() for e in last):
        s += 3.0  # the script itself marks this as a cliffhanger beat
    if lines:
        L = lines[-1]
        if "?" in L.text: s += 1.5
        if THREAT_LINE.search(L.text): s += 1.5
        if HOOK_RE.search(L.text): s += 1.0
        if HOT_TONES.search(L.tone): s += 0.8
        if RESOLVE_LINE.search(L.text) or SOFT_TONES.search(L.tone):
            s -= 2.5; note = "ends on a soft / resolving line"
    if any(e.kind == "action" and UNRESOLVED_ACTION.search(e.text) for e in last):
        s += 1.2
    # Cutting right before someone answers is a classic cliffhanger.
    nxt = [e for e in next_events if e.start < b + 2.5]
    if lines and any(e.kind == "dialogue" and e.speaker != lines[-1].speaker for e in nxt):
        s += 1.0
    if b >= episode_end - 1.5:
        s += 1.5  # episode endings are written as cliffhangers
    return clamp(s), note


def standalone_score(events, ep_number):
    """Would a stranger follow it? (rough proxy)"""
    speakers = {e.speaker.replace("LADY ", "").replace("LORD ", "").replace("THE ", "")
                for e in events if e.kind == "dialogue"}
    lines = [e for e in events if e.kind == "dialogue"]
    s, notes = 6.0, []
    if len(speakers) > 4:
        s -= 0.8 * (len(speakers) - 4); notes.append(f"{len(speakers)} speakers")
    refs = sum(1 for e in lines if CONTEXT_REF.search(e.text))
    if refs:
        s -= 0.8 * refs; notes.append("refers to earlier events")
    if any(STAKES.search(e.text) for e in events):
        s += 1.5
    if len(lines) < 2:
        s -= 1.5; notes.append("almost no dialogue")
    if ep_number == 1:
        s += 1.0
    return clamp(s), ", ".join(notes)


def intensity(events):
    talk = [e for e in events if e.kind != "camera"]
    if not talk:
        return 0.0
    return clamp(10 * sum(_line_heat(e) for e in talk) / (1.6 * len(talk)))


def duration_fit(d):
    if d < 20 or d > 60:
        return 0.0
    if 25 <= d <= 50:
        return 10.0
    return 7.0


def score_window(ep, a, b, next_ep=None):
    """Score one continuous window [a, b] inside episode `ep`."""
    evs = events_in(ep.events, a, b)
    nxt = [e for e in ep.events if e.start >= b - 0.05][:4]
    if not nxt and next_ep is not None:
        nxt = next_ep.events[:4]
    h, hn = hook_score(evs, a)
    c, cn = cliff_score(evs, b, nxt, ep.duration)
    st, sn = standalone_score(evs, ep.number)
    it = intensity(evs)
    return {"hook": round(h, 1), "cliff": round(c, 1), "standalone": round(st, 1),
            "intensity": round(it, 1), "notes": [n for n in (hn, cn, sn) if n]}


def combine(parts, duration):
    return round(0.35 * parts["hook"] + 0.30 * parts["cliff"] + 0.20 * parts["standalone"]
                 + 0.10 * parts["intensity"] + 0.05 * duration_fit(duration), 2)
