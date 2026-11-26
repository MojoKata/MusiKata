"""The seam between two songs of different rates (A4.2, R7.6): each comes through a resampler of its
own, and a resampler at the edge of what it is given makes up what lies beyond it (FFmpeg's
mirrors the last samples at the end, and starts from nothing at the start), which near the seam
is heard as a click on loud music: up to a quarter of full scale on a 5 kHz tone.

So each is primed with what plausibly lies beyond its edge: the song before is continued past its
end, and the song after continued back before its start, each by linear prediction from its own
samples (Burg's method, as declickers and packet-loss concealment use it). Each resampler then
makes its frames near the seam from samples that go on, and what they made of the continuation is
dropped: the songs meet at the seam with nothing of one mixed into the other, so it is not a
crossfade (#4). On tones and on many tones together, what is heard at the seam then differs from
the tone going on by no more than resampling makes anywhere else in the song.

Plain NumPy over blocks (docs/process/coding.md)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .stream import Block

ORDER = 32  # the predictor's order: enough for a chord of tones, little enough to be fit fast
FIT = 1024  # samples of a song's edge the predictor is fit to
EXTEND = 128  # samples a song is continued by: past the reach of any resampler's filter


def predictor(samples: NDArray[np.float64], order: int = ORDER) -> NDArray[np.float64]:
    """The coefficients a[0..p] (a[0] = 1) of the linear predictor Burg's method fits to `samples`:
    x[n] is predicted as -sum(a[k] * x[n - k]). Its order is lower where there are too few
    samples, or the samples are silence; always stable (each reflection under 1)."""
    x = np.asarray(samples, np.float64)
    a = np.ones(1)
    forward, backward = x[1:].copy(), x[:-1].copy()
    for _ in range(min(order, max(0, len(x) - 1))):
        energy = float(np.dot(forward, forward) + np.dot(backward, backward))
        if energy <= 1e-20:
            break
        k = -2.0 * float(np.dot(forward, backward)) / energy
        a = np.concatenate([a, [0.0]])
        a = a + k * a[::-1]
        forward, backward = forward[1:] + k * backward[1:], backward[:-1] + k * forward[:-1]
    return a


def continued(samples: Block, n: int, fit: int = FIT, order: int = ORDER) -> Block:
    """`n` frames that plausibly follow `samples` (frames × channels), each channel predicted from
    its last `fit` samples; silence after silence, and nothing past full scale."""
    out = np.zeros((n, samples.shape[1]), np.float32)
    if not len(samples) or n <= 0:
        return out
    for c in range(samples.shape[1]):
        history = samples[-fit:, c].astype(np.float64)
        a = predictor(history, order)
        p = len(a) - 1
        if p == 0:
            continue
        taps = -a[1:][::-1]  # applied to the last p samples, oldest first
        buf = np.concatenate([np.zeros(max(0, p - len(history))), history[-p:], np.zeros(n)])
        for i in range(n):
            buf[p + i] = float(np.dot(taps, buf[i : i + p]))
        out[:, c] = np.clip(buf[p:], -1.0, 1.0)
    return out


def preceding(samples: Block, n: int, fit: int = FIT, order: int = ORDER) -> Block:
    """`n` frames that plausibly come before `samples`: `continued` run backwards in time."""
    return continued(samples[::-1], n, fit, order)[::-1].copy()
