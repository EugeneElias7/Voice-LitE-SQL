"""Voice-LitE-SQL -- pure signal analysis for L5 microphone capture.

Everything here is hardware-free and deterministic so it can be unit-tested
with synthetic signals. Signals are represented as float samples in [-1, 1].

Design rules (per the L5 capture spec):
  * Validity is decided by a *combination* of metrics (RMS, variation,
    clipping, constant-signal ratio). Unique-sample count is reported as a
    diagnostic only and is never the sole criterion for rejecting a device.
  * No assumption that every microphone supports 16 kHz mono directly:
    the recorder captures in the device's native format and resamples to
    the Whisper-required 16 kHz mono afterwards.
"""

import math
import struct
import wave
from collections import Counter

FULL_SCALE = 32768.0

# Thresholds (all relative to a [-1, 1] float signal)
NOISE_FLOOR_RMS = 0.002       # ~-54 dBFS; quiet conversational speech clears this
NOISE_FLOOR_STD = 0.001
MAX_CLIPPING_PCT = 0.05       # >5% samples at/near full scale -> clipped
MAX_CONSTANT_PCT = 0.95       # >95% samples equal to the modal value -> constant
CLIP_NEAR_FULL = 0.985


def bytes_to_mono_float(frames, format_name, channels):
    """Convert raw PyAudio PCM frames to mono float samples in [-1, 1].

    ``format_name`` is one of ``int16``, ``int32``, ``float32`` (the width
    and encoding actually negotiated with the device). Multi-channel frames
    are down-mixed to mono by averaging.
    """
    if channels < 1 or len(frames) == 0:
        return []

    if format_name == "int16":
        count = len(frames) // 2
        raw = struct.unpack("<%dh" % count, frames[: count * 2])
        values = [s / FULL_SCALE for s in raw]
    elif format_name == "int32":
        count = len(frames) // 4
        raw = struct.unpack("<%dl" % count, frames[: count * 4])
        values = [(s >> 16) / FULL_SCALE for s in raw]
    elif format_name == "float32":
        count = len(frames) // 4
        raw = struct.unpack("<%df" % count, frames[: count * 4])
        values = [max(-1.0, min(1.0, s)) for s in raw]
    else:
        raise ValueError(f"unsupported format: {format_name}")

    if channels == 1:
        return values
    per_channel = [values[i::channels] for i in range(channels)]
    return [sum(frame) / channels for frame in zip(*per_channel)]


def _std(samples):
    n = len(samples)
    if n == 0:
        return 0.0
    mean = sum(samples) / n
    return math.sqrt(sum((s - mean) ** 2 for s in samples) / n)


def analyze_samples(samples):
    """Return a dict of signal metrics for a float sample list.

    Reported metrics:
      rms, peak, clipping_pct, zero_pct, constant_pct, unique, unique_ratio,
      std, has_variation, status
    """
    n = len(samples)
    if n == 0:
        return {
            "rms": 0.0,
            "peak": 0.0,
            "clipping_pct": 0.0,
            "zero_pct": 1.0,
            "constant_pct": 1.0,
            "unique": 0,
            "unique_ratio": 0.0,
            "std": 0.0,
            "has_variation": False,
            "status": "no_data",
        }

    rms = math.sqrt(sum(s * s for s in samples) / n)
    peak = max(abs(s) for s in samples)
    clipping = sum(1 for s in samples if abs(s) >= CLIP_NEAR_FULL) / n
    zero = sum(1 for s in samples if s == 0.0) / n
    mode_value, mode_count = Counter(samples).most_common(1)[0]
    constant = mode_count / n
    unique = len(set(samples))
    std = _std(samples)

    has_variation = (
        rms >= NOISE_FLOOR_RMS
        and std >= NOISE_FLOOR_STD
        and clipping <= MAX_CLIPPING_PCT
        and constant <= MAX_CONSTANT_PCT
    )

    if peak == 0.0:
        status = "silence"
    elif clipping > MAX_CLIPPING_PCT:
        status = "clipped"
    elif constant > MAX_CONSTANT_PCT:
        status = "constant"
    elif not has_variation and rms < NOISE_FLOOR_RMS:
        status = "low_level"
    elif has_variation:
        status = "usable"
    else:
        status = "indeterminate"

    return {
        "rms": round(rms, 5),
        "peak": round(peak, 5),
        "clipping_pct": round(clipping, 5),
        "zero_pct": round(zero, 5),
        "constant_pct": round(constant, 5),
        "unique": unique,
        "unique_ratio": round(unique / n, 6),
        "std": round(std, 5),
        "has_variation": has_variation,
        "status": status,
    }


def mono_float_to_pcm16(samples):
    """Quantize float samples to 16-bit signed PCM bytes."""
    out = []
    for s in samples:
        value = max(-1.0, min(1.0, s))
        out.append(int(round(value * (FULL_SCALE - 1))))
    return struct.pack("<%dh" % len(out), *out)


def resample_linear(samples, src_rate, dst_rate):
    """Linear-interpolation resampling of float samples.

    Exact for equal rates; otherwise scales by the rate ratio. Uses plain
    math so it stays dependency-free and deterministic.
    """
    n = len(samples)
    if n == 0 or src_rate == dst_rate:
        return samples
    out_n = int(round(n * dst_rate / src_rate))
    if out_n <= 0:
        out_n = 1
    if n == 1:
        return [samples[0]] * out_n
    src_step = (n - 1) / (out_n - 1) if out_n > 1 else 0.0
    result = []
    for i in range(out_n):
        pos = i * src_step
        low = int(math.floor(pos))
        high = min(n - 1, low + 1)
        frac = pos - low
        result.append(samples[low] * (1.0 - frac) + samples[high] * frac)
    return result


def write_wav(path, samples, rate):
    """Write mono 16-bit PCM WAV at ``rate`` (default 16 kHz Whisper format)."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(mono_float_to_pcm16(samples))
