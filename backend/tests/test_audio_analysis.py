"""Voice-LitE-SQL -- L5 audio analysis tests.

Covers the pure signal-metric calculations in scripts/audio_analysis.py using
synthetic test signals (silence, normal varying, clipped, constant,
low-amplitude) plus PCM conversion and resampling. No hardware involved.
"""

import math
import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audio_analysis import (
    analyze_samples,
    bytes_to_mono_float,
    mono_float_to_pcm16,
    resample_linear,
    write_wav,
)

RATE = 16000


def sine(freq=440.0, seconds=1.0, amplitude=0.3, rate=RATE):
    n = int(rate * seconds)
    return [amplitude * math.sin(2 * math.pi * freq * t / rate) for t in range(n)]


# ---------------------------------------------------------------------------
# silence
# ---------------------------------------------------------------------------
def test_silence_signal():
    metrics = analyze_samples([0.0] * 16000)
    assert metrics["peak"] == 0.0
    assert metrics["rms"] == 0.0
    assert metrics["zero_pct"] == 1.0
    assert metrics["constant_pct"] == 1.0
    assert metrics["has_variation"] is False
    assert metrics["status"] == "silence"


def test_silence_empty():
    metrics = analyze_samples([])
    assert metrics["status"] == "no_data"
    assert metrics["has_variation"] is False
    assert metrics["rms"] == 0.0


# ---------------------------------------------------------------------------
# normal varying signal
# ---------------------------------------------------------------------------
def test_normal_varying_signal():
    signal = sine(amplitude=0.3)
    metrics = analyze_samples(signal)
    assert metrics["has_variation"] is True
    assert metrics["status"] == "usable"
    assert metrics["peak"] == pytest.approx(0.3, abs=0.01)
    assert metrics["rms"] == pytest.approx(0.3 / math.sqrt(2), abs=0.01)
    assert metrics["clipping_pct"] == 0.0
    assert metrics["zero_pct"] < 0.01
    assert metrics["constant_pct"] < 0.05
    assert metrics["unique"] > 100
    assert 0.0 < metrics["unique_ratio"] <= 1.0


# ---------------------------------------------------------------------------
# clipped signal
# ---------------------------------------------------------------------------
def test_clipped_signal():
    signal = [max(-1.0, min(1.0, s)) for s in sine(amplitude=3.0)]
    metrics = analyze_samples(signal)
    assert metrics["clipping_pct"] > 0.05
    assert metrics["peak"] >= 0.985
    assert metrics["status"] == "clipped"
    assert metrics["has_variation"] is False


# ---------------------------------------------------------------------------
# constant signal
# ---------------------------------------------------------------------------
def test_constant_signal():
    metrics = analyze_samples([0.5] * 16000)
    assert metrics["constant_pct"] == 1.0
    assert metrics["std"] == 0.0
    assert metrics["status"] == "constant"
    assert metrics["has_variation"] is False


def test_constant_zero_offset():
    metrics = analyze_samples([0.0] * 8000 + [0.25] * 8000)
    assert metrics["constant_pct"] == 0.5
    assert metrics["has_variation"] is True
    assert metrics["status"] == "usable"


# ---------------------------------------------------------------------------
# low-amplitude signal
# ---------------------------------------------------------------------------
def test_low_amplitude_signal():
    signal = sine(amplitude=0.01)
    metrics = analyze_samples(signal)
    assert metrics["peak"] == pytest.approx(0.01, abs=0.001)
    assert metrics["rms"] == pytest.approx(0.01 / math.sqrt(2), abs=0.001)
    assert metrics["has_variation"] is True
    assert metrics["status"] == "usable"
    assert metrics["clipping_pct"] == 0.0


# ---------------------------------------------------------------------------
# multi-metric validity (unique count is NOT the sole criterion)
# ---------------------------------------------------------------------------
def test_unique_count_not_sole_validity_criterion():
    # A signal with only two distinct sample values but real variation is
    # still usable: unique-sample count alone never decides validity.
    quantized = [0.0, 0.01] * 8000
    metrics = analyze_samples(quantized)
    assert metrics["unique"] == 2
    assert metrics["unique_ratio"] < 0.001
    assert metrics["has_variation"] is True
    assert metrics["status"] == "usable"


# ---------------------------------------------------------------------------
# PCM conversion
# ---------------------------------------------------------------------------
def test_int16_roundtrip():
    samples = [0.0, 0.5, -0.5, 1.0, -1.0, 0.25]
    pcm = mono_float_to_pcm16(samples)
    decoded = bytes_to_mono_float(pcm, "int16", 1)
    for orig, conv in zip(samples, decoded):
        assert conv == pytest.approx(orig, abs=1.5 / 32768.0)


def test_stereo_downmix_to_mono():
    frames = struct.pack("<6h", 1000, 3000, -1000, 1000, 2000, -2000)
    mono = bytes_to_mono_float(frames, "int16", 2)
    assert len(mono) == 3
    assert mono[0] == pytest.approx(2000.0 / 32768.0, abs=1e-5)
    assert mono[1] == pytest.approx(0.0, abs=1e-5)


# ---------------------------------------------------------------------------
# resampling
# ---------------------------------------------------------------------------
def test_resample_same_rate():
    signal = sine()
    assert resample_linear(signal, 16000, 16000) == signal


def test_resample_downsample_length():
    signal = sine(seconds=1.0)
    out = resample_linear(signal, 44100, 16000)
    expected = round(len(signal) * 16000 / 44100)
    assert len(out) == expected
    assert max(abs(s) for s in out) <= 0.31


def test_resample_keeps_waveform():
    signal = sine(freq=440.0, seconds=0.5)
    out = resample_linear(signal, 16000, 8000)
    assert len(out) > 0
    assert 0.28 <= max(abs(s) for s in out) <= 0.31


def test_resample_empty():
    assert resample_linear([], 16000, 8000) == []


def test_resample_single_sample():
    assert resample_linear([0.5], 16000, 8000) == [0.5]


# ---------------------------------------------------------------------------
# WAV writing
# ---------------------------------------------------------------------------
def test_write_wav_16k_mono_int16(tmp_path):
    target = tmp_path / "test.wav"
    write_wav(target, sine(seconds=0.25), 16000)
    with wave.open(str(target), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() > 0
