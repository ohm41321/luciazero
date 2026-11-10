"""Verify a rendered intro video against timeline.json. Exit 0 only if every check passes.

Checks the container (codec, size, frame rate, frame count, duration), the
audio (no clipping, no dropouts, a transient on each musical hit) and the
picture (no empty scenes, the flash and the check breaking on the shatter
frame, red on verify RED and green on verify GREEN, the relay card on screen
when it is sealed),
so picture and sound are proven to line up on the same cue times.

The page is light, so picture checks look for content, change and color
against the pale background rather than for brightness against black.

Usage: python verify.py [--cut NAME] [out/luciazero-intro.mp4] [WIDTHxHEIGHT]
(the size defaults to the timeline's; web.sh checks its 720p copy with 1280x720)

A cut (timeline.json › cuts) is checked on the cues it keeps, each at its
shot's time, plus a hit and content on each chapter card.
"""

import argparse
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json")))
EV = TL["events"]
FPS = TL["fps"]
_cli = argparse.ArgumentParser(description="Verify a rendered intro video, or a cut of it, against timeline.json.")
_cli.add_argument("--cut", help="a cut from timeline.json › cuts")
_cli.add_argument("path", nargs="?", help="the MP4 (default: out/luciazero-intro.mp4, or the cut's 'file')")
_cli.add_argument("size", nargs="?", help="WIDTHxHEIGHT (default: the timeline's)")
ARGS = _cli.parse_args()
CUT = TL["cuts"].get(ARGS.cut) if ARGS.cut else None
if ARGS.cut and CUT is None:
    _cli.error(f"timeline.json has no cut named {ARGS.cut}")

# The shots in output time, as main.js and music.py lay them out. Without a cut, one shot plays the whole timeline.
SHOTS = []
for shot in CUT["shots"] if CUT else [{"src": [0, TL["duration"]]}]:
    start = SHOTS[-1]["end"] if SHOTS else 0.0
    SHOTS.append({**shot, "at": start, "end": start + (shot["src"][1] - shot["src"][0] if "src" in shot else shot["dur"])})
DUR = SHOTS[-1]["end"]
FRAMES = int(round(FPS * DUR))
if CUT and not ("src" in SHOTS[-1] and SHOTS[-1]["src"][0] <= EV["fadeOut"] < SHOTS[-1]["src"][1] == TL["duration"]):
    sys.exit(f"cut {ARGS.cut} must end with a range that reaches the timeline's end and keeps its fade-out")


def tmap(t):
    """The output time of a moment of the timeline, or None if the cut leaves it out."""
    for shot in SHOTS:
        if "src" in shot and shot["src"][0] <= t < shot["src"][1]:
            return shot["at"] + t - shot["src"][0]
    return None

# Picture thresholds, set from the 152 s render of 2026-09-29 and rechecked on the 156 s render and the
# launch cut of the same day, and on the 164 s render and its launch cut of 2026-09-30, which all measured
# the same values (in brackets).
SCENE_STD = 0.05      # luma std of a scene [0.082-0.166], of a chapter card [0.129-0.163]; page and drifting particles only [0.030]
SHATTER_RATIO = 2.0   # change on the shatter frame over the two frames before [3.4; the flash alone about 2.3]
COLOR_GAIN = 0.005    # growth in the share of red / green pixels after verify [+1.1, +1.6 points]
CHECK_BOX = (slice(55, 200), slice(160, 330))  # the 3D check at quarter scale
CARD_DROP = 0.15      # darkest-1% luma drop in the card box when the card is sealed [0.32]
# Audio hit onset against its cue, measured on the intro, launch and teaser renders of 2026-09-30: cues
# [-20, +1 ms], chapter cards [-37, -18 ms] (the whoosh into a card rises before its hit). The intro with
# its audio moved 80 ms early measured [-89, -78 ms], 80 ms late [+70, +81 ms].
ONSET_TOL = 0.05

results = []


def check(name, ok, detail):
    results.append((bool(ok), name, detail))


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,sample_rate,channels,pix_fmt,color_space,start_time:format=duration",
         "-of", "json", path],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def audio(path, sr=48000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, "<f4").reshape(-1, 2), sr


def frames(path, indices, w=480, h=270):
    expr = "+".join(f"eq(n\\,{i})" for i in sorted(indices))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select='{expr}',scale={w}:{h}", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    arr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(float) / 255
    return dict(zip(sorted(indices), arr))


def main(path, size=None):
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    num, den = map(int, v["r_frame_rate"].split("/"))
    check("video codec", v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p", f'{v["codec_name"]} {v["pix_fmt"]}')
    want = tuple(map(int, size.split("x"))) if size else (TL["width"], TL["height"])
    check("video size", (v["width"], v["height"]) == want, f'{v["width"]}x{v["height"]}')
    check("frame rate", num / den == FPS, f"{num}/{den}")
    check("frame count", int(v["nb_read_frames"]) == FRAMES, f'{v["nb_read_frames"]} (want {FRAMES})')
    check("bt709 tagged", v.get("color_space") == "bt709", v.get("color_space"))
    check("duration", abs(dur - DUR) < 0.08, f"{dur:.3f}s")
    check("audio stream", a is not None and a["codec_name"] == "aac" and int(a["channels"]) == 2, f'{a and a["codec_name"]} {a and a["channels"]}ch')
    # The sample analysis below ignores a stream's start offset, so the offset itself must be checked here.
    skew = float(a["start_time"]) - float(v["start_time"]) if a else float("inf")
    check("audio starts with video", abs(skew) < 0.5 / FPS, f"audio start - video start = {skew * 1000:+.1f} ms")

    x, sr = audio(path)
    mono = x.mean(axis=1)
    peak = 20 * np.log10(np.max(np.abs(x)) + 1e-12)
    check("audio not clipping", peak < -0.1, f"peak {peak:.2f} dBFS")
    win = sr // 2
    rms = [20 * np.log10(np.sqrt(np.mean(mono[i:i + win] ** 2)) + 1e-12) for i in range(0, int(tmap(EV["fadeOut"]) * sr), win)]
    quiet = [f"{i * 0.5:.1f}s" for i, r in enumerate(rms) if i >= 1 and r < -40]
    check("no audio dropouts", not quiet, f"quietest half-second {min(rms[1:]):.1f} dB" + (f"; silent at {quiet}" if quiet else ""))

    env = np.sqrt(np.convolve(mono ** 2, np.ones(480) / 480, mode="same"))  # 10 ms RMS
    cues = [(cue, tmap(EV[cue])) for cue in ("shatter", "fail1", "drop", "reveal", "verifyRed", "verifyGreen", "c1Red", "c5Pass", "bisFound",
                                                "relaySeal", "relayLand", "relayConsumed", "pkt1", "bsUp", "evDiff", "final")]
    cues = [(cue, t) for cue, t in cues if t is not None] + [(f'card {shot["card"]}', shot["at"]) for shot in SHOTS if "card" in shot]
    for cue, t in cues:
        before = env[int((t - 0.25) * sr):int((t - 0.03) * sr)].mean()
        hit = env[int((t - 0.01) * sr):int((t + 0.06) * sr)]
        gain = 20 * np.log10(hit.max() / (before + 1e-9))
        # Where the hit starts: the first moment within 100 ms of the cue, either side, that rises 4 dB over the
        # level before it. The window is wider than the tolerance so that an early or a late hit can fail;
        # the gain alone passes a hit 80 ms early, whose loud tail still fills the window above.
        near = env[int((t - 0.1) * sr):int((t + 0.1) * sr)]
        rise = np.nonzero(near > before * 10 ** (4 / 20))[0]
        onset = rise[0] / sr - 0.1 if len(rise) else float("inf")
        check(f"audio hit at {cue} ({t:.2f}s)", gain > 4 and abs(onset) <= ONSET_TOL, f"+{gain:.1f} dB, onset {onset * 1000:+.0f} ms")

    f = lambda t: int(round(t * FPS))
    # A picture cue is compared with frames around it, so it is checked only where one shot keeps that whole stretch.
    kept = lambda t0, t1: any("src" in shot and shot["src"][0] <= t0 and t1 < shot["src"][1] for shot in SHOTS)
    shatter = kept(EV["shatter"] - 0.15, EV["shatter"] + 0.05)
    s = f(tmap(EV["shatter"])) if shatter else None
    idx = (set(range(s - 3, s + 1)) if shatter else set()) | {FRAMES - 1}
    colors = [cue for cue in ("verifyRed", "verifyGreen") if kept(EV[cue] - 0.2, EV[cue] + 0.2)]
    for cue in colors:
        idx |= {f(tmap(EV[cue])) - 6, f(tmap(EV[cue])) + 6}
    relay = kept(EV["relayCard"] - 0.2, EV["relaySeal"] + 0.1)
    if relay:
        idx |= {f(tmap(EV["relayCard"])) - 6, f(tmap(EV["relaySeal"])) + 3}
    # One beat past the midpoint of each scene's kept part: cards swap on bar lines, and a sample
    # on a bar line can catch the one empty frame between two cards. Chapter cards at their middle.
    mids = []
    for shot in SHOTS:
        if "card" in shot:
            mids.append((f'card {shot["card"]}', shot["at"] + shot["dur"] / 2))
            continue
        for name, (a0, b0) in TL["scenes"].items():
            a1, b1 = max(a0, shot["src"][0]), min(b0, shot["src"][1])
            if b1 - a1 > 60 / TL["bpm"]:
                mids.append((name, shot["at"] + min((a1 + b1) / 2 + 60 / TL["bpm"], b1 - 0.25) - shot["src"][0]))
    idx |= {f(m) for _, m in mids}
    fr = frames(path, idx)
    luma = lambda im: (im * [0.2126, 0.7152, 0.0722]).sum(axis=2)

    # A scene with only the page behind it is flat; cards, ink and Lucia are not.
    # The last frame (faded to the page color) is the empty reference.
    blank = luma(fr[FRAMES - 1]).std()
    for name, m in mids:
        sd = luma(fr[f(m)]).std()
        check(f"scene {name} has content", sd > SCENE_STD, f"luma std {sd:.3f} at {m:.1f}s (empty page {blank:.3f})")
    if shatter:
        # The white flash is the largest frame-to-frame change around the shatter, on the cue frame.
        d = {k: np.abs(fr[k] - fr[k - 1]).mean() for k in (s - 2, s - 1, s)}
        check("flash lands on the shatter frame", d[s] > SHATTER_RATIO * max(d[s - 1], d[s - 2]),
              f"mean |change| {d[s]:.4f} at frame {s}, {max(d[s - 1], d[s - 2]):.4f} on the two frames before")
        # The check breaks on the same frame: its ink outline is gone, since the shards have none.
        # The flash lifts dark pixels too, so its opacity is estimated from the page to the right
        # of the terminal (out = in * (1 - a) + a) and divided out before counting ink.
        pre, hit = luma(fr[s - 1]), luma(fr[s])
        a = min(max(float(np.median(((hit - pre) / (1 - pre + 1e-6))[0:30, 360:480])), 0.0), 0.95)
        ink = lambda l: (l[CHECK_BOX] < 0.3).mean()
        before, after = ink(pre), ink((hit - a) / (1 - a))
        check("check breaks on the shatter frame", before > 0.005 and after < 0.2 * before,
              f"ink outline {before * 100:.2f}% of the check box on frame {s - 1}, {after * 100:.2f}% on frame {s} (flash {a:.2f} divided out)")
    # verify RED and GREEN: the share of strongly red or green pixels grows after the cue.
    # Red excludes the pastel pink of the confetti (#ff93ab, green channel 0.58); green excludes teal (blue above green).
    red = lambda im: ((im[..., 0] > im[..., 1] + 0.3) & (im[..., 0] > im[..., 2] + 0.2) & (im[..., 1] < 0.45)).mean()
    green = lambda im: ((im[..., 1] > im[..., 0] + 0.3) & (im[..., 1] > im[..., 2] + 0.1)).mean()
    for cue, share, word in (("verifyRed", red, "red"), ("verifyGreen", green, "green")):
        if cue not in colors:
            continue
        a0, b0 = share(fr[f(tmap(EV[cue])) - 6]), share(fr[f(tmap(EV[cue])) + 6])
        check(f"verify {word.upper()} frame turns {word}", b0 - a0 > COLOR_GAIN,
              f"{word} pixels {a0 * 100:.1f}% before, {b0 * 100:.1f}% after")
    # The card hovers at CARD_HOME in main.js (1400, 250), 518 x 324 px; the box is that area at quarter scale.
    # Before the card the box is pale page; the sealed card puts ink lines and text in it.
    if relay:
        card_box = lambda im: np.percentile(luma(im[22:103, 285:415]), 1)
        empty, sealed = card_box(fr[f(tmap(EV["relayCard"])) - 6]), card_box(fr[f(tmap(EV["relaySeal"])) + 3])
        check("relay card on screen when sealed", empty - sealed > CARD_DROP, f"darkest 1% luma {empty:.2f} before the card, {sealed:.2f} at the seal")

    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(1 for ok, _, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(ARGS.path or os.path.join(HERE, "out", CUT["file"] if CUT else "luciazero-intro.mp4"), ARGS.size))
