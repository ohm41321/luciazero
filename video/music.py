"""Algorithmic score for the Luciazero intro video.

No samples and no generative model: every sound below is an oscillator or
seeded noise shaped by envelopes and filters. Timing comes from
timeline.json, the same file main.js reads, so a hit in the music lands on
the frame where the picture expects it.

Usage: python music.py [--cut NAME] [out/music.wav]

A cut (timeline.json › cuts) is composed from the same score: each sound lands
at its shot's time, the sounds of the ranges left out are dropped, and the
chapter cards get a hit and a held chord of their own.
"""

import argparse
import json
import math
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json")))
EV = TL["events"]

_cli = argparse.ArgumentParser(description="Synthesize the score, or a cut's score, to a WAV file.")
_cli.add_argument("--cut", help="a cut from timeline.json › cuts")
_cli.add_argument("out", nargs="?", help="output WAV (default: out/music.wav, or the cut's 'music')")
ARGS = _cli.parse_args()
CUT = TL["cuts"].get(ARGS.cut) if ARGS.cut else None
if ARGS.cut and CUT is None:
    _cli.error(f"timeline.json has no cut named {ARGS.cut}")

SR = 48000
BPM = TL["bpm"]
BEAT = 60.0 / BPM
BAR = 4 * BEAT
S16 = BEAT / 4
SRC_DUR = TL["duration"]  # the timeline's length; the cues are in its time

# The shots in output time. Without a cut, one shot plays the whole timeline.
SHOTS = []
for shot in CUT["shots"] if CUT else [{"src": [0, SRC_DUR]}]:
    start = SHOTS[-1]["end"] if SHOTS else 0.0
    SHOTS.append({**shot, "at": start, "end": start + (shot["src"][1] - shot["src"][0] if "src" in shot else shot["dur"])})
DUR = SHOTS[-1]["end"]
N = int(DUR * SR)
if CUT and not ("src" in SHOTS[-1] and SHOTS[-1]["src"][0] <= EV["fadeOut"] < SHOTS[-1]["src"][1] == SRC_DUR):
    sys.exit(f"cut {ARGS.cut} must end with a range that reaches the timeline's end ({SRC_DUR}s) and keeps its fade-out")
LEAD = 0.6  # a lead-in sound (a whoosh) may start this long before a range that follows a cut
RAW = False  # while True, times given to place() are output times already (the chapter cards)


def tmap(t, lead=False):
    """The output time of a moment of the timeline, or None if the cut leaves it out."""
    if RAW:
        return t
    for shot in SHOTS:
        if "src" in shot and shot["src"][0] <= t < shot["src"][1]:
            return shot["at"] + t - shot["src"][0]
    if lead:
        for shot in SHOTS:
            if "src" in shot and shot["at"] > 0 and shot["src"][0] - LEAD <= t < shot["src"][0]:
                return shot["at"] - (shot["src"][0] - t)
    return None


def kept(scene):
    a, b = TL["scenes"][scene]
    return any("src" in shot and shot["src"][0] < b and shot["src"][1] > a for shot in SHOTS)
rng = np.random.default_rng(41321)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def bus():
    return np.zeros((2, N))


BUS = {name: bus() for name in ("drums", "bass", "pad", "chords", "arp", "lead", "fx", "keys")}
SEND = bus()  # reverb send
KICKS = []


def place(dest, sig, t, gain=1.0, pan=0.0, send=0.0, lead=False):
    """Mix a mono or stereo signal into a bus at timeline time t (seconds); return its output time."""
    t = tmap(t, lead)
    if t is None:
        return None
    if sig.ndim == 1:
        a = (pan + 1) * math.pi / 4
        sig = np.vstack([sig * math.cos(a), sig * math.sin(a)]) * math.sqrt(2)
    i = int(round(t * SR))
    if i >= N:
        return None
    n = min(sig.shape[1], N - i)
    dest[:, i:i + n] += sig[:, :n] * gain
    if send:
        SEND[:, i:i + n] += sig[:, :n] * gain * send
    return t


def env_adsr(n, a, d, s, r, hold=None):
    """Linear attack, exponential decay to sustain, linear release."""
    t = np.arange(n) / SR
    hold = n / SR - r if hold is None else hold
    e = np.where(t < a, t / max(a, 1e-6), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6)))
    rel = np.clip((t - hold) / max(r, 1e-6), 0, 1)
    return e * (1 - rel)


def phase(freq, n):
    f = np.broadcast_to(np.asarray(freq, dtype=float), (n,))
    return np.cumsum(f) / SR, f


def saw(freq, n):
    """PolyBLEP band-limited sawtooth; freq may be a per-sample array."""
    ph, f = phase(freq, n)
    t = ph % 1.0
    dt = f / SR
    y = 2 * t - 1
    m = t < dt
    x = t[m] / dt[m]
    y[m] -= x + x - x * x - 1
    m = t > 1 - dt
    x = (t[m] - 1) / dt[m]
    y[m] -= x * x + x + x + 1
    return y


def pulse(freq, n, width=0.5):
    ph, f = phase(freq, n)
    a = saw(f, n)
    # a second saw offset by the pulse width, built from the same phase
    t = (ph + width) % 1.0
    dt = f / SR
    b = 2 * t - 1
    m = t < dt
    x = t[m] / dt[m]
    b[m] -= x + x - x * x - 1
    m = t > 1 - dt
    x = (t[m] - 1) / dt[m]
    b[m] -= x * x + x + x + 1
    return (a - b) * 0.5


def sine(freq, n):
    ph, _ = phase(freq, n)
    return np.sin(2 * np.pi * ph)


def noise(n):
    return rng.standard_normal(n)


def fft_filter(x, lo=None, hi=None, tilt_db_per_oct=0.0):
    """Zero-phase filter with smooth 24 dB/oct shoulders (lo = high-pass edge, hi = low-pass edge)."""
    single = x.ndim == 1
    xs = x[None, :] if single else x
    n = xs.shape[1]
    size = 1 << (n - 1).bit_length()
    spec = np.fft.rfft(xs, size, axis=1)
    f = np.fft.rfftfreq(size, 1 / SR)
    g = np.ones_like(f)
    if hi:
        g /= np.sqrt(1 + (f / hi) ** 8)
    if lo:
        with np.errstate(divide="ignore"):
            g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 8)
    if tilt_db_per_oct:
        g *= (np.maximum(f, 20) / 1000) ** (tilt_db_per_oct / 6.02)
    y = np.fft.irfft(spec * g, size, axis=1)[:, :n]
    return y[0] if single else y


def onepole_lp(x, cutoff, init=0.0):
    """One-pole low-pass with a per-sample cutoff array (Hz), its state starting at init."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = 1 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    s = float(init)
    xl, al = x.tolist(), a.tolist()
    for i in range(len(xl)):
        s += al[i] * (xl[i] - s)
        y[i] = s
    return y


def svf_bp(x, cutoff, q=4.0):
    """Chamberlin state-variable band-pass with a per-sample cutoff array."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    fcoef = (2 * np.sin(np.pi * np.minimum(c, SR / 6) / SR)).tolist()
    damp = 1.0 / q
    low = band = 0.0
    y = np.empty_like(x)
    xl = x.tolist()
    for i in range(len(xl)):
        low += fcoef[i] * band
        high = xl[i] - low - damp * band
        band += fcoef[i] * high
        y[i] = band
    return y


# ---------------------------------------------------------------- instruments


def kick(t, gain=1.0):
    """A punchy kick: a fast pitch drop into a round sub, a short click on top, driven."""
    n = int(0.42 * SR)
    tt = np.arange(n) / SR
    f = 47 + 160 * np.exp(-tt * 38)
    body = sine(f, n) * np.exp(-tt * 6.5)
    click = fft_filter(noise(n), lo=2000, hi=8000) * np.exp(-tt * 350) * 0.3
    at = place(BUS["drums"], np.tanh((body + click) * 1.8), t, 0.44 * gain)
    if at is not None:
        KICKS.append((at, gain))


def snap(t, gain=1.0, pan=0.08):
    """A finger snap: a short band of noise with a small knock under it."""
    n = int(0.2 * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=1800, hi=6500) * np.exp(-tt * 45)
    s += sine(1100, n) * np.exp(-tt * 90) * 0.25
    place(BUS["drums"], s, t, 0.3 * gain, pan=pan, send=0.22)


def clap(t, gain=1.0):
    n = int(0.4 * SR)
    tt = np.arange(n) / SR
    e = np.exp(-tt * 18)
    for k in (0.0, 0.011, 0.022):
        e = np.maximum(e, np.where(tt >= k, np.exp(-(tt - k) * 180), 0))
    s = fft_filter(noise(n), lo=900, hi=5500) * e
    place(BUS["drums"], s, t, 0.22 * gain, pan=-0.05, send=0.25)


def snare(t, gain=1.0):
    n = int(0.25 * SR)
    tt = np.arange(n) / SR
    tone = sine(200 + 60 * np.exp(-tt * 50), n) * np.exp(-tt * 25)
    s = fft_filter(noise(n), lo=1200, hi=7000) * np.exp(-tt * 24) + tone * 0.6
    place(BUS["drums"], s, t, 0.2 * gain, send=0.2)


def hat(t, gain=1.0, open_=False, pan=0.25):
    n = int((0.3 if open_ else 0.05) * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=7000, hi=13000) * np.exp(-tt * (10 if open_ else 80))
    place(BUS["drums"], s, t, 0.11 * gain, pan=pan)


def shaker(t, gain=1.0, pan=-0.3):
    n = int(0.09 * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=4000, hi=10000) * np.minimum(tt / 0.012, 1) * np.exp(-tt * 45)
    place(BUS["drums"], s, t, 0.12 * gain, pan=pan)


def crash(t, gain=1.0):
    """A soft cymbal, dark enough not to hiss over the mix."""
    n = int(2.2 * SR)
    tt = np.arange(n) / SR
    metal = sum(sine(f, n) for f in (2870, 3990, 5210, 6230)) * 0.05
    s = (fft_filter(noise(n), lo=3500, hi=10000) + metal) * np.exp(-tt * 2.2) * np.minimum(tt / 0.004, 1)
    place(BUS["drums"], np.vstack([s, np.roll(s, 37)]), t, 0.13 * gain, send=0.3)


def bonk(t, gain=1.0, pitch=190):
    """A cartoon wood-block tom for the failures: a pitch that falls and a knock."""
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    s = sine(pitch * (0.55 + 0.45 * np.exp(-tt * 18)), n) * np.exp(-tt * 9)
    s += fft_filter(noise(n), lo=500, hi=2500) * np.exp(-tt * 70) * 0.35
    place(BUS["drums"], np.tanh(s * 1.3), t, 0.55 * gain, send=0.2)


def bass_note(t, midi, dur, gain=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    s = saw(hz(midi), n) * 0.45 + sine(hz(midi), n) * 0.7 + sine(hz(midi - 12), n) * 0.35
    s = onepole_lp(s, 160 + 1100 * np.exp(-tt * 16))
    s *= env_adsr(n, 0.006, 0.2, 0.6, 0.03)
    place(BUS["bass"], s, t, 0.3 * gain)


def pad_chord(t, notes, dur, gain=1.0, bright=2000):
    """Detuned saws, softened with sines, behind everything."""
    n = int((dur + 0.5) * SR)
    left = np.zeros(n)
    right = np.zeros(n)
    for m in notes:
        for k, det in enumerate((-0.08, -0.03, 0.03, 0.08)):
            v = saw(hz(m + det), n) * 0.55 + sine(hz(m + det), n) * 0.6
            (left if k % 2 == 0 else right)[:] += v
    e = env_adsr(n, 0.3, 0.8, 0.8, 0.5, hold=dur)
    st = fft_filter(np.vstack([left, right]) * e, lo=140, hi=bright)
    place(BUS["pad"], st / (len(notes) * 2), t, 0.7 * gain, send=0.35)


def marimba(t, midi, gain=1.0, pan=0.0, send=0.25):
    """Marimba: a sine bar with its two inharmonic overtones and a soft mallet."""
    n = int(1.2 * SR)
    tt = np.arange(n) / SR
    f = hz(midi)
    s = sine(f, n) * np.exp(-tt * (5 + f / 350))
    s += 0.3 * sine(f * 3.93, n) * np.exp(-tt * 30) + 0.08 * sine(f * 9.2, n) * np.exp(-tt * 70)
    s *= np.minimum(tt / 0.0015, 1)
    s += fft_filter(noise(n), lo=300, hi=2500) * np.exp(-tt * 400) * 0.05
    place(BUS["keys"], s, t, 0.26 * gain, pan=pan, send=send)


def music_box(t, midi, gain=1.0, pan=0.0, bend=0.0):
    """A music-box tine: a pure tone with a quick bright partial. bend drifts it down in semitones."""
    n = int(1.6 * SR)
    tt = np.arange(n) / SR
    f = hz(midi) * 2 ** (-bend * np.minimum(tt / 0.4, 1) / 12)
    s = sine(f, n) * np.exp(-tt * 3.2) + 0.22 * sine(f * 4.0, n) * np.exp(-tt * 14)
    s *= np.minimum(tt / 0.001, 1)
    place(BUS["keys"], s, t, 0.17 * gain, pan=pan, send=0.45)


def bell(t, midi, gain=1.0, pan=0.0, decay=1.8, send=0.4):
    """A soft two-operator FM bell, kept for the few biggest moments."""
    n = int(2.6 * SR)
    tt = np.arange(n) / SR
    f = hz(midi)
    index = 1.3 * np.exp(-tt * 6)
    mod = np.sin(2 * np.pi * f * 2.0 * tt) * index
    s = np.sin(2 * np.pi * f * tt + mod) * np.exp(-tt * decay) * np.minimum(tt / 0.003, 1)
    place(BUS["keys"], fft_filter(s, hi=4500), t, 0.15 * gain, pan=pan, send=send)


def blip(t, f0, f1, dur=0.1, gain=1.0, pan=0.0, send=0.2):
    """A bubble pop: a sine that glides from f0 to f1."""
    n = int((dur + 0.08) * SR)
    tt = np.arange(n) / SR
    f = f0 * (f1 / f0) ** np.minimum(tt / dur, 1)
    s = (sine(f, n) + 0.15 * sine(2 * f, n)) * np.minimum(tt / 0.003, 1) * np.exp(-tt * 3 / dur)
    place(BUS["fx"], s, t, 0.2 * gain, pan=pan, send=send)


def boop(t, midi, dur=0.16, gain=1.0, pan=0.0):
    """A soft square note: two of them falling a minor third make an "uh-oh"."""
    n = int((dur + 0.1) * SR)
    s = fft_filter(pulse(hz(midi), n, 0.5), hi=1500) * env_adsr(n, 0.005, 0.1, 0.7, 0.08, hold=dur)
    place(BUS["fx"], s, t, 0.2 * gain, pan=pan, send=0.15)


def uh_oh(t, gain=1.0, midi=67):
    boop(t, midi, 0.13, gain)
    boop(t + 0.18, midi - 4, 0.22, gain)


def nope(t, gain=1.0):
    boop(t, 64, 0.08, gain, pan=0.2)
    boop(t + 0.11, 58, 0.14, gain, pan=0.2)


def tick(t, gain=1.0, freq=2000, pan=0.0):
    n = int(0.03 * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=freq * 0.6, hi=freq * 1.5) * np.exp(-tt * 700)
    s += sine(freq * 0.7, n) * np.exp(-tt * 300) * 0.3
    place(BUS["fx"], s, t, 0.15 * gain, pan=pan)


def sparkle(t, gain=1.0, count=22):
    """A handful of short, soft pings: glitter, not glass."""
    n = int(1.6 * SR)
    out = np.zeros((2, n))
    for _ in range(count):
        f = rng.uniform(1600, 5200)
        start = int(rng.uniform(0, 0.4) * SR)
        tt = np.arange(n - start) / SR
        s = np.sin(2 * np.pi * f * tt) * np.exp(-tt * rng.uniform(9, 20)) * rng.uniform(0.3, 1) * np.minimum(tt / 0.002, 1)
        side = int(rng.integers(0, 2))
        out[side, start:] += s * 0.7
        out[1 - side, start:] += s * 0.3
    place(BUS["fx"], out, t, 0.07 * gain, send=0.5)


def poof(t, gain=1.0):
    """A soft puff of noise, for things that vanish."""
    n = int(0.6 * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=400, hi=5000) * np.minimum(tt / 0.01, 1) * np.exp(-tt * 9)
    place(BUS["fx"], np.vstack([s, np.roll(s, 71)]), t, 0.22 * gain, send=0.4)


def sub_drop(t, gain=1.0):
    n = int(1.4 * SR)
    tt = np.arange(n) / SR
    s = sine(34 + 60 * np.exp(-tt * 3.2), n) * np.exp(-tt * 2.6)
    place(BUS["fx"], np.tanh(s * 1.3), t, 0.4 * gain)


def swell(t, dur, gain=1.0, lo=1500, hi=8000):
    """Noise that grows toward t + dur (a reversed-cymbal feel)."""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    s = fft_filter(noise(n), lo=lo, hi=hi) * (tt / dur) ** 3
    place(BUS["fx"], np.vstack([s, np.roll(s, 91)]), t, 0.22 * gain, send=0.3)


def whoosh(t, dur=0.5, gain=1.0):
    """A soft air sweep that peaks at t + dur, for scene changes."""
    n = int((dur + 0.25) * SR)
    tt = np.arange(n) / SR
    k = np.clip(tt / dur, 0, 1)
    s = svf_bp(noise(n), 500 + 3000 * k ** 2, q=1.6)
    s *= k ** 2 * np.exp(-np.maximum(tt - dur, 0) * 18)
    place(BUS["fx"], np.vstack([s, np.roll(s, 113)]), t, 0.12 * gain, send=0.25, lead=True)


def riser(t, dur, gain=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    k = tt / dur
    f = hz(57) * 2 ** (2.0 * k ** 1.6)
    s = sine(f, n) * 0.6 + saw(f * 2, n) * 0.15
    s = onepole_lp(s, 600 + 5000 * k ** 2)
    nz = svf_bp(noise(n), 600 + 6000 * k ** 2, q=2.5) * 0.35
    st = np.vstack([s + nz, s + np.roll(nz, 53)]) * (0.1 + 0.9 * k ** 2)
    place(BUS["fx"], st, t, 0.16 * gain, send=0.25)


def power(t, dur, up, gain=1.0):
    """A cute power-down ("pwoo") or power-up sweep."""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    k = tt / dur
    f = 70 * (900 / 70) ** (k if up else 1 - k)
    s = sine(f, n) + 0.3 * sine(2 * f, n)
    s *= np.minimum(tt / 0.01, 1) * (np.minimum((dur - tt) / 0.03, 1) if up else (1 - k) ** 1.5)
    place(BUS["fx"], s, t, 0.2 * gain, send=0.2)


def hum(t, dur, gain=1.0):
    """The daemon's standby hum while the bus is down."""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    s = fft_filter(saw(55, n) + saw(55.4, n), lo=40, hi=400) * np.minimum(tt / 0.1, 1) * np.minimum((dur - tt) / 0.05, 1)
    place(BUS["pad"], s, t, 0.12 * gain)


def voices(freq, n, detunes):
    """Saws a few cents apart, each from a random point in its cycle, so they beat instead of phasing."""
    out = []
    for det in detunes:
        f = np.asarray(freq, dtype=float) * 2 ** (det / 12)
        period = int(SR / float(np.min(f))) + 1
        off = int(rng.integers(0, period))
        fx = np.concatenate([np.full(off, float(np.ravel(f)[0])), np.broadcast_to(f, (n,))]) if np.ndim(f) else f
        out.append(saw(fx, n + off)[off:])
    return out


def supersaw(t, notes, dur, gain=1.0, bright=4200, attack=0.012, release=0.25, dest="chords", send=0.25, bend=None):
    """Future-bass chords: five detuned saws a note, spread across the stereo field.
    The kick's sidechain gives them their pump. bend is a per-sample pitch offset in semitones."""
    n = int((dur + release) * SR)
    st = np.zeros((2, n))
    spread = (-0.2, -0.08, 0.0, 0.08, 0.2)
    for m in notes:
        f = hz(m) * (2 ** (bend / 12) if bend is not None else 1.0)
        for k, v in enumerate(voices(f, n, spread)):
            a = (0.8 * (k - 2) / 2 + 1) * math.pi / 4  # voices spread from 0.8 left to 0.8 right
            st[0] += v * math.cos(a)
            st[1] += v * math.sin(a)
    st *= env_adsr(n, attack, 0.4, 0.8, release, hold=dur)
    st = fft_filter(st, lo=160, hi=bright)
    place(BUS[dest], st / (len(notes) * 2.2), t, 0.7 * gain, send=send)
    return st


def pluck(t, midi, gain=1.0, pan=0.0, decay=1.0, send=0.25, dest="arp"):
    """A bright synth pluck: harmonics that die away faster the higher they are."""
    n = int(0.8 * decay * SR)
    tt = np.arange(n) / SR
    f = hz(midi)
    s = np.zeros(n)
    for k in range(1, 14):
        if f * k > 15000:
            break
        s += np.sin(2 * np.pi * f * k * tt + k) / k * np.exp(-tt * (3 + 6 * k) / decay)
    s *= np.minimum(tt / 0.002, 1)
    place(BUS[dest], s, t, 0.16 * gain, pan=pan, send=send)


def sub(t, midi, dur, gain=1.0):
    """The low end under a bar: a slightly driven sine, pumped by the sidechain."""
    n = int((dur + 0.05) * SR)
    s = np.tanh(1.6 * sine(hz(midi), n)) * env_adsr(n, 0.004, 0.3, 0.9, 0.04, hold=dur)
    place(BUS["bass"], s, t, 0.2 * gain)


def lead(t0, notes, gain=1.0, vox=0.55):
    """The hook's voice: a gliding saw lead doubled by a vowel-shaped "vocal chop".
    notes are (start, midi, length) in seconds from t0."""
    end = max(a + d for a, _, d in notes) + 0.3
    n = int(end * SR)
    tt = np.arange(n) / SR
    target = np.full(n, float(notes[0][1]))
    gate = np.zeros(n)
    for a, m, d in notes:
        i0 = int(a * SR)
        target[i0:] = m
        u = np.arange(n - i0) / SR
        gate[i0:] = np.maximum(gate[i0:], np.minimum(u / 0.006, 1) * np.clip(1 - (u - d * 0.9) / 0.05, 0, 1))
    # a 4 ms glide between notes (starting on the first, not swept up from 0) and a little vibrato
    pitch = onepole_lp(target, 45.0, init=target[0]) + 0.07 * np.sin(2 * np.pi * 5.5 * tt)
    f = 440.0 * 2 ** ((pitch - 69) / 12)
    body = sum(voices(f, n, (-0.11, 0.0, 0.11))) / 3 + 0.35 * pulse(f / 2, n, 0.5)
    body = fft_filter(body, lo=200, hi=5200)
    v = saw(f, n)
    voice = fft_filter(v, lo=650, hi=1000) + 0.7 * fft_filter(v, lo=1050, hi=1500) + 0.3 * fft_filter(v, lo=2400, hi=3000)
    s = (body * (1 - vox) + voice * vox * 2.2) * gate
    place(BUS["lead"], np.vstack([s, 0.85 * np.roll(s, 360)]), t0, 0.3 * gain, send=0.3)


def impact(t, gain=1.0):
    """A cinematic hit: a low boom, a burst of air and a dark cymbal."""
    n = int(1.8 * SR)
    tt = np.arange(n) / SR
    boom = sine(38 + 110 * np.exp(-tt * 14), n) * np.exp(-tt * 2.2)
    air = fft_filter(noise(n), lo=300, hi=3500) * np.exp(-tt * 7) * 0.4
    crack = fft_filter(noise(n), lo=1500, hi=9000) * np.exp(-tt * 45) * 1.2  # the front edge, so it lands on its frame
    place(BUS["fx"], np.tanh((boom + air + crack) * 1.5), t, 0.34 * gain, send=0.35)
    crash(t, 0.6 * gain)


def gate_pad(t, notes, dur, lo_hz, hi_hz, gain=1.0, fall=None):
    """The intro's pulse: supersaw chords gated in eighths behind a filter that opens from
    lo_hz to hi_hz. fall = (start, seconds) pitches it all down like a tape stopping."""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    bend = None
    if fall:
        k = np.clip((tt - fall[0]) / fall[1], 0, 1)
        bend = -12 * k ** 2
    st = np.zeros((2, n))
    for m in notes:
        f = hz(m) * (2 ** (bend / 12) if bend is not None else 1.0)
        for k, v in enumerate(voices(f, n, (-0.15, 0.0, 0.15))):
            st[k % 2] += v
    ph = (tt / (BEAT / 2)) % 1.0
    st *= np.exp(-ph * 4) * np.minimum(ph / 0.02, 1)  # a pluck on every eighth
    cut = lo_hz * (hi_hz / lo_hz) ** (tt / dur)
    st = np.vstack([onepole_lp(onepole_lp(ch, cut), cut) for ch in st])
    st *= np.minimum(tt / 0.3, 1) * np.clip((dur - tt) / 0.05, 0, 1)
    place(BUS["chords"], st / (len(notes) * 1.5), t, 0.8 * gain, send=0.3)


# ---------------------------------------------------------------- the score
#
# C major at 120 BPM, a bar every two seconds. The hook is the opening lullaby
# (E G C G F A) set to a dance rhythm over the "royal road" progression (IV-V-iii-vi)
# that J-pop and anime lean on. It plays at the drop, under the relay and the bus, and
# in the last chorus; its first four notes, on the chord of the moment, are the sonic
# logo on verify GREEN and the chapter cards. An E major marks each moment of trouble
# and a C each moment of relief.

CHORDS = {
    "C": [55, 60, 64, 67], "Cadd9": [60, 64, 67, 74], "F": [53, 57, 60, 64], "G": [55, 59, 62, 67],
    "Em": [52, 55, 59, 62], "Am": [57, 60, 64, 67], "Dm": [53, 57, 62, 65], "E": [52, 56, 59, 64],
}
ROOT = {"C": 36, "Cadd9": 36, "F": 29, "G": 31, "Em": 28, "Am": 33, "Dm": 38, "E": 28}
TONES = {  # four chord tones for the marimba and plucks, low to high
    "C": [72, 76, 79, 84], "Cadd9": [72, 74, 76, 79], "F": [65, 69, 72, 76], "G": [67, 71, 74, 79],
    "Em": [64, 67, 71, 76], "Am": [69, 72, 76, 81], "Dm": [65, 69, 74, 77], "E": [64, 68, 71, 76],
}
ARP16 = [0, 1, 2, 3, 2, 1, 0, 2, 1, 3, 2, 0, 3, 2, 1, 2]
ARP8 = [0, 2, 1, 3, 2, 1, 3, 2]
PENTA = [72, 74, 76, 79, 81, 84, 86, 88, 91, 93, 96, 98, 100]
# The hook, a bar for each chord of the royal road: (sixteenth, midi, length in sixteenths).
# Bars one and three share a motif; bars two and four answer it in a 3-3-2 rhythm.
HOOK = {
    "F": [(0, 76, 2), (2, 79, 2), (4, 84, 3), (7, 79, 3), (10, 77, 2), (12, 81, 4)],  # E G C G F A, the lullaby
    "G": [(0, 79, 3), (3, 74, 3), (6, 76, 2), (8, 74, 4), (12, 71, 2), (14, 74, 2)],
    "Em": [(0, 76, 2), (2, 79, 2), (4, 83, 3), (7, 79, 3), (10, 76, 2), (12, 74, 4)],
    "Am": [(0, 72, 3), (3, 71, 3), (6, 69, 2), (8, 76, 6)],
}
PICKUP = [(14, 72, 1), (15, 74, 1)]  # C D, up into the hook's first E


def logo(chord):
    """The sonic logo: the hook's first four notes (up, up, top, back) on a chord's tones, at their sixteenths."""
    t = TONES[chord]
    return [(0, t[1]), (2, t[2]), (4, t[3]), (7, t[2])]


# (bar, chord, groove, hook voice) for every bar with a regular groove. Bars not listed
# are written by hand in compose(): the intro, the break on verify RED, the fix, the
# daemon going down and the final chord.
PLAN = [
    # the failures: a build that opens up under three hits
    (4, "Am", "build", None), (5, "F", "build", None), (6, "G", "build", None),
    # the drop: Lucia, the title and the hook
    (8, "F", "full", "lead"), (9, "G", "full", "lead"), (10, "Em", "full", "lead"), (11, "Am", "full", "lead"),
    (12, "F", "light", None), (13, "G", "light", None),
    (16, "Cadd9", "full", None), (17, "F", "air", None),
    # the caught scenes: a lighter groove under the reading, E on each red, C on each pass
    (18, "F", "light", None), (19, "G", "light", None), (20, "Em", "light", None), (21, "Am", "light", None),
    (22, "E", "light", None), (23, "Dm", "light", None), (24, "F", "light", None), (25, "G", "light", None), (26, "C", "light", None),
    (27, "F", "light", None), (28, "G", "light", None), (29, "C", "light", None), (30, "Am", "light", None),
    (31, "F", "light", None), (32, "G", "light", None), (33, "E", "light", None), (34, "Am", "light", None),
    (35, "F", "light", None), (36, "G", "light", None), (37, "E", "light", None), (38, "C", "light", None), (39, "G", "light", None),
    # bisect: curious, then found
    (40, "Am", "half", None), (41, "F", "half", None), (42, "Am", "half", None), (43, "F", "half", None),
    (44, "C", "light", None), (45, "G", "light", None),
    # the relay: the hook on the lead, then a lighter groove while session B checks the card;
    # the bus: the hook on plucks, under the packets
    (46, "F", "full", "lead"), (47, "G", "full", "lead"), (48, "Em", "full", "lead"), (49, "Am", "full", "lead"), (50, "F", "full", None),
    (51, "G", "light", None), (52, "Am", "light", None),
    (53, "F", "full", "pluck"), (54, "G", "full", "pluck"), (55, "Em", "full", "pluck"), (56, "Am", "full", "pluck"),
    (57, "F", "full", None), (58, "G", "full", None),
    (60, "F", "full", None), (61, "G", "light", None), (62, "Em", "light", None), (63, "C", "full", None),
    # evidence, safe to try
    (64, "F", "light", None), (65, "G", "light", None), (66, "C", "full", None), (67, "G", "light", None),
    (68, "F", "air", None), (69, "G", "air", None), (70, "C", "air", None),
    # the skills: the last chorus. The call to action lands on IV-V, the final chord on I.
    (71, "F", "full", "lead"), (72, "G", "full", "lead"), (73, "Em", "full", "lead"), (74, "Am", "full", "lead"),
    (75, "F", "full", None), (76, "G", "full", None), (77, "Am", "build", None),
    (78, "F", "full", "lead"), (79, "G", "full", "lead"),
]
CHORD_AT = {b: c for b, c, _, _ in PLAN}
CHORD_AT.update({0: "C", 1: "C", 2: "C", 3: "Am", 7: "E", 14: "E", 15: "Dm", 59: "C", 80: "Cadd9", 81: "Cadd9", 82: "Cadd9", 83: "Cadd9"})
for _b, _c, _k, _v in PLAN:
    assert not _v or _c in HOOK, f"bar {_b}: the hook has no bar for {_c}"


def at_bar(b, beat=0.0):
    return b * BAR + beat * BEAT


def chord_at(t):
    return CHORD_AT.get(int(t // BAR), "C")


def cue(v):
    """A timeline cue: seconds, an event name, or an event name plus or minus seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    for sign in ("+", "-"):
        name, _, off = v.partition(sign)
        if off:
            return EV[name] + (float(off) if sign == "+" else -float(off))
    return EV[v]


def voicing(chord):
    """The supersaw voicing: the chord, and its middle notes an octave up for shine."""
    notes = CHORDS[chord]
    return notes + [m + 12 for m in notes[1:3]]


def groove(b, chord, kind, hook=None):
    t0 = at_bar(b)
    tones = TONES[chord]
    root = ROOT[chord]
    if kind == "full":  # four on the floor, claps on two and four, pumping chords, a house bass
        for k in range(4):
            kick(at_bar(b, k))
        for k in (1, 3):
            clap(at_bar(b, k))
            snare(at_bar(b, k), 0.5)
        for s in range(16):
            hat(t0 + s * S16, 0.9 if s % 4 == 2 else 0.4, open_=(s % 4 == 2), pan=0.25 if s % 2 else -0.15)
        sub(t0, root, BAR)
        for s in (2, 6, 10, 14):
            bass_note(t0 + s * S16, root + 12, 2 * S16 * 0.9, 0.5)
        supersaw(t0, voicing(chord), BAR - 0.02, bright=4500)
        step = 2 if hook == "lead" else 1  # under the lead the arpeggio thins to eighths
        for s in range(0, 16, step):
            pluck(t0 + s * S16, tones[ARP16[s]] + 12, (0.3 if s % 4 else 0.45) * (0.7 if hook else 1), pan=0.4 * math.sin(s * 1.3), decay=0.45)
    elif kind == "light":  # under the reading: kick on one and three, off-beat stabs, a soft pad
        kick(at_bar(b, 0), 0.75)
        kick(at_bar(b, 2), 0.65)
        for k in (1, 3):
            snap(at_bar(b, k), 0.8)
        for s in range(2, 16, 4):
            shaker(t0 + s * S16, 0.8)
        sub(t0, root, BAR, 0.6)
        pad_chord(t0, CHORDS[chord], BAR, gain=0.6, bright=1800)
        for s in (2, 6, 10, 14):
            for i, m in enumerate(tones[:3]):
                pluck(t0 + s * S16, m, 0.2, pan=-0.3 + 0.3 * i, decay=0.35)
    elif kind == "half":  # half time: curious, a little tense
        kick(at_bar(b, 0), 0.9)
        kick(at_bar(b, 2.5), 0.7)
        clap(at_bar(b, 2), 0.9)
        for s in range(2, 16, 4):
            hat(t0 + s * S16, 0.7)
        sub(t0, root, BAR, 0.8)
        pad_chord(t0, CHORDS[chord], BAR, gain=0.7, bright=1400)
        for i in range(8):
            pluck(t0 + i * 2 * S16, tones[ARP8[i]], 0.35, pan=0.3 * math.sin(i * 1.7), decay=0.6)
    elif kind == "air":
        kick(at_bar(b, 0), 0.5)
        sub(t0, root, BAR * 0.95, 0.5)
        pad_chord(t0, CHORDS[chord], BAR, gain=0.8, bright=1500)
        for s in (0, 3, 6, 10):
            pluck(t0 + s * S16, tones[s % 4] + 12, 0.3, pan=0.3, decay=1.2)
    elif kind == "build":  # a four-on-the-floor build whose chords open up bar by bar
        for k in range(4):
            kick(at_bar(b, k), 0.7)
        for k in (1, 3):
            snare(at_bar(b, k), 0.5)
        for s in range(0, 16, 2 if b < 6 else 1):
            hat(t0 + s * S16, 0.5 if s % 4 == 2 else 0.3)
        sub(t0, root, BAR, 0.8)
        supersaw(t0, voicing(chord), BAR - 0.02, gain=0.7, bright={4: 1100, 5: 1600, 6: 2400}.get(b, 2000))
    if hook:
        notes = HOOK[chord]
        if hook == "lead":
            lead(t0, [(p * S16, m, n * S16) for p, m, n in notes])
        else:
            for p, m, n in notes:
                pluck(t0 + p * S16, m, 0.9, decay=0.5 + 0.1 * n)


def jingle(t, gain=1.0):
    """CAUGHT: the bar's chord tones, up and bright."""
    for i, m in enumerate(TONES[chord_at(t)] + [TONES[chord_at(t)][0] + 12]):
        marimba(t + i * 0.06, m + 12, 0.75 * gain, pan=-0.2 + i * 0.12, send=0.35)
    sparkle(t + 0.2, 0.6 * gain, count=12)


def terminal(name, pan=0.0):
    """Typing ticks for a terminal panel's commands, a tap for each output line, a pop for each box."""
    spec = TL["terms"][name]
    for line in spec["lines"]:
        t = cue(line["at"])
        if "cmd" in line:
            for i, ch in enumerate(line["cmd"]):
                tick(t + i / spec["cps"], 0.25 if ch == " " else 0.5, freq=1700 + 700 * rng.random(), pan=pan + rng.uniform(-0.1, 0.1))
        elif "box" in line:
            blip(t, 520, 880, 0.08, 0.6 if line.get("cls") != "bad" else 0.5, pan=pan)
        else:
            tick(t, 0.35, freq=1300, pan=pan)


def stop(t0, t1, floor=0.08, ramp=0.012, lead=1.0):
    """Stop-time: duck the groove between t0 and t1 so the next hit lands on a breath.
    lead is how much of the lead stays over the gap."""
    t0, t1 = tmap(t0), tmap(t1)
    if t0 is None or t1 is None:
        return
    tt = np.arange(N) / SR
    k = np.clip(np.minimum((tt - t0) / ramp, (t1 - tt) / ramp), 0, 1)
    g = 1 - (1 - floor) * k
    for name in ("drums", "bass", "keys", "chords", "arp", "pad"):
        BUS[name] *= g if name != "pad" else 1 - 0.6 * k
    if lead < 1:
        BUS["lead"] *= 1 - (1 - lead) * k


def compose():
    for b, chord, kind, hook in PLAN:
        groove(b, chord, kind, hook)

    # --- 0-8 s: false green. A filtered pulse opens under a music box, then a lie
    # stops the tape and shatters.
    gate_pad(0.0, CHORDS["C"] + [72], EV["shatter"], 350, 2400, gain=0.9, fall=(EV["zeroRun"], EV["shatter"] - EV["zeroRun"]))
    pad_chord(0.0, CHORDS["C"], EV["shatter"] - 0.2, gain=0.4, bright=1300)
    bass_note(0.0, 36, EV["zeroRun"] - 0.1, 0.4)
    lullaby = [(0.0, 76), (0.5, 79), (1.0, 84), (1.5, 79), (2.0, 77), (2.5, 81), (3.0, 79), (4.0, 76), (4.5, 74), (5.0, 72), (5.25, 71), (5.5, 69)]
    for dt, m in lullaby:
        t = 0.5 + dt
        bend = 0.0 if t < EV["zeroRun"] else 1.5 + 2.0 * (t - EV["zeroRun"])  # the lie goes out of tune
        music_box(t, m, 0.9, pan=0.2, bend=bend)
    tick(EV["prompt"], 0.8, freq=1600)
    typing = TL["typing"]
    for i, ch in enumerate(typing["text"]):
        tick(typing["start"] + i / typing["cps"], 0.3 if ch == " " else 0.6, freq=1800 + 700 * rng.random(), pan=rng.uniform(-0.2, 0.2))
    for i, m in enumerate((72, 76, 79, 84)):
        marimba(EV["checkRise"] + 0.35 + i * 0.07, m, 0.8, pan=-0.2 + i * 0.13)
    for i in range(5):  # "Did it actually run anything?", one word per step
        blip(EV["question"] + i * EV["qStep"], 420, 520, 0.05, 0.35)
    uh_oh(EV["zeroRun"], 0.9, midi=65)
    swell(EV["zeroRun"] + 0.2, EV["shatter"] - EV["zeroRun"] - 0.2, gain=0.7)
    kick(EV["shatter"], 1.0)
    impact(EV["shatter"], 1.0)
    crash(EV["shatter"], 0.6)
    poof(EV["shatter"], 1.0)
    sparkle(EV["shatter"], 1.3, count=30)
    pad_chord(EV["shatter"] + 0.1, CHORDS["Am"], 1.6, gain=0.5, bright=1100)

    # --- 8-16 s: three failures land on the build, then the vortex, a riser, a breath and the drop.
    for key in ("fail1", "fail2", "fail3"):
        impact(EV[key], 0.7)
        bonk(EV[key], 0.9)
        boop(EV[key] + 0.25, 60, 0.12, 0.5)
        boop(EV[key] + 0.42, 55, 0.2, 0.5)
    riser(EV["vortex"], EV["drop"] - EV["vortex"] - 0.25)
    for k in range(3):
        kick(at_bar(7, k), 0.8)
    sub(at_bar(7), ROOT["E"], BAR * 0.9, 0.8)
    supersaw(at_bar(7), voicing("E"), BAR - 0.3, gain=0.8, bright=3200)
    for s in range(16):
        if s % 2 == 0 or s >= 8:
            snare(at_bar(7) + s * S16, 0.35 + 0.04 * s)
    stop(EV["drop"] - 0.25, EV["drop"] - 0.01)

    # --- 16-24 s: the drop. The hook; Lucia assembles; the title.
    impact(EV["drop"], 1.0)
    crash(EV["drop"], 0.8)
    sub_drop(EV["drop"], 0.5)
    stop(EV["reveal"] - BEAT / 2, EV["reveal"] - 0.01, lead=0.35)  # the lead's note hangs, softly, over the gap
    crash(EV["reveal"], 0.7)
    snap(EV["reveal"], 1.2)
    for i, m in enumerate((79, 84, 88)):
        bell(EV["reveal"] + i * S16, m - 12, 0.9, pan=-0.3 + i * 0.3)
    sparkle(EV["reveal"], 0.8)
    for i, m in enumerate(TONES[chord_at(EV["title"])][:3]):
        marimba(EV["title"] + i * 0.03, m, 0.9)
    marimba(EV["tagline"], TONES[chord_at(EV["tagline"])][1], 0.7)
    marimba(EV["subline"], TONES[chord_at(EV["subline"])][2], 0.7)
    for i in range(6):  # "for Claude Code & Codex CLI" wipes in, a tick a word
        tick(EV["subline"] + 0.1 + i * 0.15, 0.4, freq=1500)

    # --- 24-36 s: the loop. plan, change, verify RED, fix, verify GREEN, the quote.
    marimba(EV["plan"], 84, 0.9, send=0.4)
    marimba(EV["change"], 86, 0.9, send=0.4)
    # verify RED: the groove stops and ticks nervously
    uh_oh(EV["verifyRed"], 1.1)
    bonk(EV["verifyRed"], 1.0, pitch=150)
    sub(at_bar(14), ROOT["E"], BAR * 0.95, 0.7)
    pad_chord(at_bar(14), CHORDS["E"], BAR, gain=0.6, bright=1200)
    for s in range(4, 16):
        tick(at_bar(14) + s * S16, 0.35 + 0.03 * s, freq=1400, pan=0.4 if s % 2 else -0.4)
    # fix: the kick returns under a rising arpeggio
    kick(at_bar(15, 0), 0.9)
    kick(at_bar(15, 2), 0.8)
    sub(at_bar(15), ROOT["Dm"] - 12, BAR, 0.7)
    for i in (0, 3, 4, 6):
        bass_note(at_bar(15) + i * 2 * S16, ROOT["Dm"], 2 * S16 * 1.4, 0.7)
    supersaw(at_bar(15), voicing("Dm"), BAR - 0.1, gain=0.6, bright=2200)
    for s in range(16):
        pluck(at_bar(15) + s * S16, TONES["Dm"][s % 4] + (12 if s >= 8 else 0), 0.35 + 0.03 * s, pan=0.3 * math.sin(s), decay=0.5)
    for s in range(12, 16):
        snare(at_bar(15) + s * S16, 0.45 + 0.1 * (s - 12))
    # verify GREEN: the sonic logo on bells
    crash(EV["verifyGreen"], 1.2)
    for p, m in logo("C"):
        bell(EV["verifyGreen"] + p * S16, m, 1.0 if p == 0 else 0.8, pan=-0.3 + p * 0.08)
    sparkle(EV["verifyGreen"] + 0.1, 0.8)

    # --- 36-80 s: Lucia presents the caught scenes.
    for scene in ("caught1", "caught2", "caught3", "exact", "probe", "bisect", "relay", "bus", "busSafe", "evidence", "safe", "skills"):
        if kept(scene):  # a cut leads into the scenes it keeps, not the ones it drops
            whoosh(EV[scene] - 0.5, 0.5, 0.8)
    for name, pan in (("t1", -0.2), ("t2", -0.2), ("t4a", -0.3), ("t4b", -0.2), ("t4c", -0.1), ("t5", -0.2),
                      ("tBis", -0.2), ("relayA", -0.4), ("relayB", 0.4), ("tBusA", -0.4), ("tBusB", 0.4), ("tWatch", 0.0), ("tLog", 0.0)):
        terminal(name, pan)
    for line in TL["lucia"]["lines"]:
        blip(cue(line["at"]), 620, 1250, 0.09, 0.8, pan=0.4)
    for at in TL["lucia"]["caught"]:
        jingle(cue(at))
    uh_oh(EV["c1Red"], 1.0)
    bonk(EV["c1Red"], 0.8, pitch=160)
    for i in range(1, 28):  # a tick as the ledger count reaches each of 1..27 (power1.inOut over 2 s in main.js)
        e = (i - 0.5) / 27
        u = math.sqrt(e / 2) if e < 0.5 else 1 - math.sqrt((1 - e) / 2)
        tick(EV["c3Count"] + 2.0 * u, 0.3, freq=1200 + 30 * i, pan=0.3)
    marimba(EV["c3H1"], 88, 0.9, send=0.4)
    boop(EV["c4Hostile"] + 1.0, 58, 0.2, 0.6)
    uh_oh(EV["c5Fail"], 0.9)
    for i, m in enumerate((72, 76, 79)):
        marimba(EV["c5Pass"] + i * 0.02, m + 12, 0.9)
    crash(EV["c5Pass"], 0.5)

    # --- 80-92 s: /bisect. Each probe answers good (up) or bad (down).
    for i in range(len(TL["bisect"]["commits"])):
        marimba(EV["bisNodes"] + i * 0.06, PENTA[i % len(PENTA)] - 12, 0.45, pan=-0.5 + i / 11)
    for _, ev, state in TL["bisect"]["steps"]:
        if state == "good":
            blip(EV[ev], 700, 1400, 0.1, 0.8, pan=-0.2)
        else:
            boop(EV[ev], 55, 0.2, 0.9, pan=0.2)
            bonk(EV[ev], 0.5, pitch=140)
    for i, m in enumerate((72, 76, 79, 84)):
        marimba(EV["bisFound"] + i * 0.05, m + 12, 0.9, pan=-0.3 + i * 0.2)
    sparkle(EV["bisFound"] + 0.05, 0.8)

    # --- 92-106 s: /lucia-relay, laptop to desktop. A card is drafted, sealed (a bell), handed over,
    # checked and consumed; a note for each of new session, new agent, new machine.
    blip(EV["relayCard"], 500, 900, 0.08, 0.7)
    for i in range(len(TL["relay"]["rows"])):
        t = EV["relayRows"] + i * EV["relayRowStep"]
        pluck(t, TONES[chord_at(t)][i % 4] + 12, 0.35, pan=-0.4 + i * 0.1, decay=0.4)
    stop(EV["relaySeal"] - BEAT / 2, EV["relaySeal"] - 0.01, floor=0.2, lead=0.4)
    crash(EV["relaySeal"], 0.6)
    snap(EV["relaySeal"], 1.0)
    for i, m in enumerate((76, 83)):
        bell(EV["relaySeal"] + i * 0.06, m, 0.9, pan=-0.2 + i * 0.3)
    blip(EV["relayLaunch"], 400, 1600, 0.22, 0.6, pan=0.3)
    bonk(EV["relayLand"], 1.0, pitch=240)
    marimba(EV["relayLand"], TONES[chord_at(EV["relayLand"])][3], 0.8, pan=0.4)
    for i, m in enumerate(TONES[chord_at(EV["relayValid"])][2:]):
        marimba(EV["relayValid"] + i * 0.12, m, 0.7, pan=0.4)
    stop(EV["relayConsumed"] - BEAT / 2, EV["relayConsumed"] - 0.01, floor=0.25, lead=0.5)  # a breath before the card goes
    poof(EV["relayConsumed"], 1.0)
    snap(EV["relayConsumed"], 1.0)
    sparkle(EV["relayConsumed"], 1.0)
    crash(EV["relayConsumed"], 0.7)
    for i in range(3):
        marimba(EV["relayFooter"] + 0.25 * i, TONES[chord_at(EV["relayFooter"])][i + 1], 0.55, pan=-0.4 + 0.2 * i)

    # --- 106-128 s: the agent bus. A task, a red finding, a fix, a green re-check;
    # then the daemon goes down, comes back and refuses three times.
    blip(EV["busHub"], 300, 700, 0.12, 0.8)
    blip(EV["pkt1"], 500, 1400, 0.3, 0.8, pan=-0.3)
    blip(EV["pkt2"] - 0.35, 500, 1400, 0.3, 0.7, pan=-0.3)
    uh_oh(EV["pkt2"] + 0.05, 0.6)
    blip(EV["pkt3"] - 0.35, 400, 900, 0.25, 0.6, pan=0.4)  # off to the implementer
    blip(EV["pkt4"] - 0.35, 900, 500, 0.25, 0.6, pan=0.4)  # the fix comes back
    marimba(EV["pkt4"], TONES[chord_at(EV["pkt4"])][2], 0.6, pan=0.3)
    blip(EV["pkt5"] - 0.35, 500, 1400, 0.3, 0.7, pan=-0.3)
    for i, m in enumerate(TONES[chord_at(EV["pkt5"])][2:]):
        marimba(EV["pkt5"] + i * 0.1, m + 12, 0.7, pan=-0.3)
    sparkle(EV["pkt5"] + 0.05, 0.5, count=10)
    # bar 59: a beat of groove, then the daemon goes down
    t0 = at_bar(59)
    for k in (0, 1):
        kick(at_bar(59, k))
    snap(at_bar(59, 1))
    sub(t0, ROOT["C"], BEAT * 1.9, 0.9)
    pad_chord(t0, CHORDS["C"], EV["bsDown"] - t0, bright=2400)
    for s in range(8):
        hat(t0 + s * S16, 0.6)
        pluck(t0 + s * S16, TONES["C"][ARP16[s]] + 12, 0.4, decay=0.45)
    power(EV["bsDown"], 0.6, up=False)
    hum(EV["bsDown"], EV["bsUp"] - EV["bsDown"])
    power(EV["bsUp"] - 0.45, 0.45, up=True)
    crash(EV["bsUp"], 0.9)
    clap(EV["bsUp"], 1.0)
    for key in ("bsRef1", "bsRef2", "bsRef3"):
        nope(EV[key], 0.9)
    jingle(EV["bsPass"])

    # --- 128-142 s: evidence (a bell), safe to try.
    for key, top in (("evBare", 6), ("evLz", 10)):
        for i in range(top):
            marimba(EV[key] + 1.1 * (i / top) ** 0.7, PENTA[i] - 12, 0.4, pan=-0.2 if key == "evBare" else 0.3)
    crash(EV["evDiff"], 0.9)
    for i, m in enumerate((79, 84)):
        bell(EV["evDiff"] + i * 0.06, m, 0.9, pan=0.3)
    sparkle(EV["evDiff"] + 0.05, 0.8)
    for i, m in enumerate((72, 74, 76, 79, 84)[:CUT.get("safeItems", 5) if CUT else 5]):  # a note an item
        marimba(EV["sfItems"] + i * EV["sfStep"] + 0.1, m, 0.7, pan=-0.3 + i * 0.15)

    # --- 142-168 s: the skills over the last chorus, a build, the call to action, the final chord.
    crash(EV["skills"], 0.8)
    for i in range(len(TL["skills"])):
        marimba(EV["chips"] + i * EV["chipStep"], PENTA[i % len(PENTA)], 0.45, pan=-0.5 + i / 12)
    lead(at_bar(77), [(p * S16, m, n * S16) for p, m, n in PICKUP])
    for s in range(8, 16):
        snare(at_bar(77) + s * S16, 0.35 + 0.06 * (s - 8))
    swell(EV["dive"], EV["cta"] - EV["dive"], gain=0.8, lo=800, hi=7000)
    stop(EV["cta"] - 0.25, EV["cta"] - 0.01)
    impact(EV["cta"], 0.8)
    for s in range(8, 14):
        snare(at_bar(79) + s * S16, 0.4 + 0.08 * (s - 8))
    stop(EV["final"] - 0.25, EV["final"] - 0.01, floor=0.15, lead=0.3)
    # the final chord
    crash(EV["final"], 1.2)
    kick(EV["final"], 1.1)
    sub_drop(EV["final"], 0.4)
    bass_note(EV["final"], 36, 3.5, 0.9)
    pad_chord(EV["final"], CHORDS["Cadd9"], SRC_DUR - EV["final"] - 0.4, gain=1.0, bright=3000)
    supersaw(EV["final"], voicing("Cadd9"), 3.0, gain=0.7, bright=3200, release=2.0)
    for i, m in enumerate((72, 76, 79, 84)):
        bell(EV["final"] + i * 0.08, m, 1.0, pan=-0.3 + i * 0.2, decay=1.4)
    sparkle(EV["final"] + 0.1, 1.0)
    blip(EV["final"] + 1.0, 700, 1400, 0.1, 0.6, pan=0.3)  # "Try it on your next bug fix."
    # the opening's lullaby again under the install card, in tune this time and home on C
    for dt, m in [(0.0, 76), (0.5, 79), (1.0, 84), (1.5, 79), (2.0, 77), (2.5, 81), (3.0, 79), (3.5, 76), (4.0, 74), (4.5, 72)]:
        music_box(EV["final"] + 1.6 + dt, m, 0.75, pan=0.2)


def chapter(t0, dur, chord):
    """A chapter card, in output time: the groove stops for a breath, one hit lands
    with the word, the chord is held under it and the sonic logo rings with its line."""
    stop(t0 - BEAT / 2, t0 - 0.01)
    kick(t0, 1.2)
    clap(t0, 0.8)
    impact(t0, 0.8)
    for i, m in enumerate(TONES[chord]):
        marimba(t0 + i * 0.025, m, 0.75, pan=-0.3 + i * 0.2, send=0.4)
    sparkle(t0 + 0.05, 0.6, count=14)
    pad_chord(t0, CHORDS[chord], dur - 0.3, gain=0.9, bright=2600)
    supersaw(t0, voicing(chord), dur - 0.3, gain=0.6, bright=2800, release=0.4)
    sub(t0, ROOT[chord], dur * 0.85, 0.9)
    for p, m in logo(chord):
        music_box(t0 + 0.5 + p * S16, m + 12, 0.8, pan=0.25)


def chapters():
    global RAW
    RAW = True
    try:
        for shot in SHOTS:
            if "card" in shot:
                chapter(shot["at"], shot["dur"], shot["chord"])
    finally:
        RAW = False


def reverb(x, seconds=2.6, predelay=0.02):
    n = int(seconds * SR)
    tt = np.arange(n) / SR
    ir = np.vstack([noise(n), noise(n)]) * np.exp(-tt * (6.9 / seconds))
    ir = fft_filter(ir, lo=180, hi=7000)
    ir = np.hstack([np.zeros((2, int(predelay * SR))), ir])
    ir /= np.sqrt(np.sum(ir ** 2, axis=1, keepdims=True))
    size = 1 << (x.shape[1] + ir.shape[1]).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size, axis=1) * np.fft.rfft(ir, size, axis=1), size, axis=1)
    return y[:, : x.shape[1]]


def delay(x, time, feedback, taps=4):
    y = x.copy()
    d = int(time * SR)
    for k in range(1, taps + 1):
        shifted = np.zeros_like(x)
        shifted[:, d * k:] = x[:, : -d * k] * feedback ** k
        if k % 2:  # ping-pong
            shifted = shifted[::-1]
        y += shifted
    return y


def sidechain(depth=0.55, release=0.16):
    duck = np.zeros(N)
    tt = np.arange(int(0.6 * SR)) / SR
    shape = np.exp(-tt / release)
    for t, g in KICKS:
        i = int(round(t * SR))
        n = min(len(shape), N - i)
        if n > 0:
            duck[i:i + n] = np.maximum(duck[i:i + n], shape[:n] * min(g, 1))
    return 1 - depth * duck


def render(path):
    compose()
    chapters()
    sc = sidechain()
    BUS["arp"] = delay(BUS["arp"], 3 * S16, 0.38)
    BUS["lead"] = delay(BUS["lead"], 3 * S16, 0.22, taps=3)
    for name in ("bass", "pad", "arp"):
        BUS[name] *= sc
    BUS["chords"] *= sidechain(0.8, 0.22)  # the future-bass pump
    dry = sum(BUS.values())
    wet = reverb(SEND) * 0.55
    mix = dry + wet * np.vstack([sc, sc]) ** 0.5
    # gentle master: soft clip, fade out, normalize to -1 dBFS
    mix = np.tanh(mix * 1.1) / 1.1
    tt = np.arange(N) / SR
    fade = np.clip((DUR - tt) / (DUR - tmap(EV["fadeOut"])), 0, 1) ** 1.5
    mix *= fade
    mix[:, :64] *= np.linspace(0, 1, 64)
    peak = np.max(np.abs(mix))
    mix *= 10 ** (-1 / 20) / peak
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2").T.copy()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path}: {DUR:.1f}s, {SR} Hz stereo, peak -1.0 dBFS")


if __name__ == "__main__":
    render(ARGS.out or os.path.join(HERE, "out", CUT["music"] if CUT else "music.wav"))
