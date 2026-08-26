"""Voice-LitE-SQL -- pure-Python voice capture with automatic device
selection and an offline TTS fallback.

Capture path:
  1. Ensure the default Windows microphone is unmuted and at a usable level
     (a muted capture endpoint silently returns digital silence -- this was
     the cause of "everything is silent" on the original machine).
  2. Try every real capture backend in order: pyaudio (PortAudio shared),
     sounddevice (PortAudio), soundcard (pure WASAPI). Each backend probes
     every input device and scores the signal.
  3. A device is usable when it shows real voice-like content: RMS above the
     noise floor, meaningful variation, low constant-signal ratio, AND most
     spectral energy inside the 80 Hz - 4 kHz speech band. The speech-band
     ratio is a hard gate that rejects phantom devices and driver noise.
  4. If a real microphone works it is returned and used. If no device
     carries voice, the caller may fall back to synthesizing the reference
     utterances with the offline Windows SAPI TTS engine so the full
     Whisper -> L6 -> L3/L4 chain can still be exercised end-to-end.

The fallback is explicit and reported, never silent.
"""

import math
import sys
import time
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audio_analysis import analyze_samples, resample_linear, write_wav  # noqa: E402

TARGET_RATE = 16000
PROBE_SECONDS = 1.5

# Virtual / mapper / loopback devices that never carry real microphone voice.
VIRTUAL_DEVICE_KEYWORDS = (
    "sound mapper",
    "primary sound capture",
    "stereo mix",
    "loopback",
    "what u hear",
    "wave out mix",
    "afdinstall",
    "amdafd",
)

# A real voice capture must clear these thresholds on the probe.
MIN_RMS = 0.01
MAX_CONSTANT_PCT = 0.90
MIN_UNIQUE_RATIO = 0.0005
MIN_VARIATION = True

# Speech-band limits: conversational voice is concentrated roughly between
# 80 Hz and 4 kHz. Synthetic/driver noise typically spreads all the way to
# Nyquist (e.g. the phantom AMD device peaks at 22 kHz). A real mic must
# have most of its energy inside the speech band.
SPEECH_BAND_HZ = (80.0, 4000.0)
MIN_VOICE_BAND_RATIO = 0.5


def _add_voice_band(results, backend):
    """Compute voice-band ratio for each report using its capture rate."""
    for report in results:
        rate = report.get("capture_rate") or TARGET_RATE
        samples = _probe_samples_from_report(report)
        report["voice_band_ratio"] = _voice_band_ratio(samples, rate)
    return results


def _probe_samples_from_report(report):
    """Re-decode the report's raw frames into float samples (best effort)."""
    frames = report.get("_raw_frames")
    if not frames:
        return []
    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415

    return bytes_to_mono_float(
        frames,
        report.get("capture_format", "int16"),
        report.get("capture_channels", 1),
    )


def _voice_band_ratio(samples, rate):
    """Fraction of spectral energy inside the speech band (0.0-1.0)."""
    n = len(samples)
    if n < 256 or rate <= 0:
        return 0.0
    mean = sum(samples) / n
    centered = [s - mean for s in samples]
    # Real FFT of the centered signal (pure python, no numpy dependency).
    nfft = 1
    while nfft < n:
        nfft *= 2
    if nfft > 16384:
        nfft = 16384
    coeffs = _fft(centered[:nfft])
    total = 0.0
    band = 0.0
    for i in range(nfft // 2 + 1):
        freq = i * rate / nfft
        mag2 = (coeffs[2 * i] * coeffs[2 * i] + coeffs[2 * i + 1] * coeffs[2 * i + 1]) if 2 * i + 1 < len(coeffs) else (coeffs[2 * i] * coeffs[2 * i])
        if freq > 0:
            total += mag2
            if SPEECH_BAND_HZ[0] <= freq <= SPEECH_BAND_HZ[1]:
                band += mag2
    return (band / total) if total > 0 else 0.0


def _fft(samples):
    """Iterative radix-2 Cooley-Tukey FFT, real input -> complex interleaved
    (real, imag) list. Pure python fallback; small and deterministic."""
    n = len(samples)
    levels = 0
    size = 1
    while size < n:
        size *= 2
        levels += 1
    # zero-pad to power of two
    padded = list(samples) + [0.0] * (size - n)
    # bit-reversal permutation
    out = [0.0] * (2 * size)
    for i in range(size):
        j = i
        rev = 0
        for _ in range(levels):
            rev = (rev << 1) | (j & 1)
            j >>= 1
        out[2 * i] = padded[rev]
        out[2 * i + 1] = 0.0
    # butterfly stages
    length = 2
    while length <= size:
        half = length // 2
        step_t = -2.0 * math.pi / length
        for i in range(0, size, length):
            for k in range(half):
                w_re = math.cos(step_t * k)
                w_im = math.sin(step_t * k)
                even = i + k
                odd = even + half
                e_re = out[2 * even]
                e_im = out[2 * even + 1]
                o_re = out[2 * odd]
                o_im = out[2 * odd + 1]
                t_re = w_re * o_re - w_im * o_im
                t_im = w_re * o_im + w_im * o_re
                out[2 * even] = e_re + t_re
                out[2 * even + 1] = e_im + t_im
                out[2 * odd] = e_re - t_re
                out[2 * odd + 1] = e_im - t_im
        length *= 2
    return out


class NoVoiceCaptureError(Exception):
    """Raised when no backend/device produced a voice-like signal."""


def ensure_mic_unmuted():
    """Ensure the default Windows microphone is unmuted and at a usable level.

    Windows captures consistently return digital silence when the default
    capture endpoint is muted (level shows e.g. 97% but mute=1). This queries
    the Core Audio endpoint volume via pycaw and unmutes / raises the level
    if needed. Safe no-op if pycaw is not installed.
    """
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # noqa: PLC0415
        from comtypes import CLSCTX_ALL, cast, POINTER  # noqa: PLC0415
    except ImportError:
        return False
    try:
        mic = AudioUtilities.GetMicrophone()
        if mic is None:
            return False
        iface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        changed = False
        if vol.GetMute():
            vol.SetMute(0, None)
            changed = True
        if vol.GetMasterVolumeLevelScalar() < 0.5:
            vol.SetMasterVolumeLevelScalar(1.0, None)
            changed = True
        return changed
    except Exception:
        return False


def _is_virtual(name):
    lowered = (name or "").lower()
    return any(k in lowered for k in VIRTUAL_DEVICE_KEYWORDS)


def _score_metrics(metrics):
    """0.0 (garbage) -> 1.0 (clear voice) score from the analysis dict."""
    if not metrics or not metrics.get("frames_received"):
        return 0.0
    rms = metrics.get("rms", 0.0)
    constant = metrics.get("constant_pct", 1.0)
    unique_ratio = metrics.get("unique_ratio", 0.0)
    voice_ratio = metrics.get("voice_band_ratio", 0.0)
    # Speech-band energy is a hard gate: real voice concentrates below 4 kHz,
    # driver/phantom noise spreads to Nyquist. Below the threshold the device
    # is rejected outright no matter how much 'variation' it shows.
    if voice_ratio < MIN_VOICE_BAND_RATIO:
        return 0.0
    score = 0.0
    if rms >= MIN_RMS:
        score += 0.5
    if constant <= MAX_CONSTANT_PCT:
        score += 0.3
    if unique_ratio >= MIN_UNIQUE_RATIO:
        score += 0.2
    if metrics.get("has_variation"):
        score = max(score, 0.5)
    return min(score, 1.0)


def _is_real_voice(metrics):
    """A device carries real voice only when the probe shows actual variation
    (not a constant/noise floor) AND most energy is in the speech band AND the
    signal is above the noise floor. RMS alone must never pass a device: a
    constant-signal device can score 0.5 from RMS but is not voice."""
    if not metrics or not metrics.get("frames_received"):
        return False
    return (
        metrics.get("has_variation", False)
        and metrics.get("voice_band_ratio", 0.0) >= MIN_VOICE_BAND_RATIO
        and metrics.get("rms", 0.0) >= MIN_RMS
        and metrics.get("constant_pct", 1.0) <= MAX_CONSTANT_PCT
    )


# ---------------------------------------------------------------------------
# Backend 1: pyaudio
# ---------------------------------------------------------------------------
def _capture_pyaudio():
    import numpy as np  # noqa: PLC0415
    import pyaudio  # noqa: PLC0415

    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415
    from scripts.mic_utils import enumerate_input_devices, open_best_stream  # noqa: PLC0415

    audio = pyaudio.PyAudio()
    try:
        results = []
        for device in enumerate_input_devices(audio, include_virtual=False):
            try:
                stream, fmt_name, width, rate, channels = open_best_stream(audio, device["index"])
            except OSError:
                continue
            try:
                frames = b""
                remaining = int(rate * PROBE_SECONDS)
                while remaining > 0:
                    take = min(1024, remaining)
                    data = stream.read(take, exception_on_overflow=False)
                    if not data:
                        break
                    frames += data
                    remaining -= take
                stream.stop_stream()
                stream.close()
            except Exception:
                continue
            if not frames:
                continue
            samples = bytes_to_mono_float(frames, fmt_name, channels)
            metrics = analyze_samples(samples)
            info = audio.get_device_info_by_index(device["index"])
            try:
                host_name = str(audio.get_host_api_info_by_index(info.get("hostApi", 0)).get("name", "?"))
            except Exception:
                host_name = "?"
            report = {
                "index": device["index"],
                "name": device["name"],
                "host_api": host_name,
                "is_default": device["is_default"],
                "capture_format": fmt_name,
                "capture_rate": rate,
                "capture_channels": channels,
                "capture_width": width,
                "frames_received": len(frames),
                "_raw_frames": frames,
                "backend": "pyaudio",
                **metrics,
            }
            results.append(report)
    finally:
        audio.terminate()
    return _add_voice_band(results, "pyaudio")


# ---------------------------------------------------------------------------
# Backend 2: sounddevice
# ---------------------------------------------------------------------------
def _capture_sounddevice():
    import numpy as np  # noqa: PLC0415
    import sounddevice as sd  # noqa: PLC0415

    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415

    results = []
    for index in range(sd.query_devices().__len__() or 0):
        try:
            info = sd.query_devices(index, "input")
        except Exception:
            continue
        name = str(info.get("name", "?"))
        channels = int(info.get("max_input_channels", 0))
        if channels <= 0 or _is_virtual(name):
            continue
        default_rate = int(info.get("default_samplerate", 0) or 0)
        rates = [r for r in (default_rate, 48000, 44100, 16000) if r]
        captured = None
        for rate in dict.fromkeys(rates):
            for ch in ([1, 2] if channels >= 2 else [1]):
                try:
                    data = sd.rec(
                        int(rate * PROBE_SECONDS), samplerate=rate, channels=ch,
                        dtype="float32", device=index, blocking=True,
                    )
                    captured = (data, rate, ch)
                    break
                except Exception:
                    continue
            if captured:
                break
        if captured is None:
            continue
        data, rate, ch = captured
        arr = data[:, 0] if data.ndim > 1 and data.shape[1] > 1 else data.ravel()
        pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
        frames = pcm.tobytes()
        samples = bytes_to_mono_float(frames, "int16", 1)
        metrics = analyze_samples(samples)
        results.append(
            {
                "index": index,
                "name": name,
                "host_api": "sounddevice",
                "is_default": index == sd.default.device[0] if sd.default.device else False,
                "capture_format": "float32",
                "capture_rate": rate,
                "capture_channels": ch,
                "capture_width": 4,
                "frames_received": len(frames),
                "_raw_frames": frames,
                "backend": "sounddevice",
                **metrics,
            }
        )
    return _add_voice_band(results, "sounddevice")


# ---------------------------------------------------------------------------
# Backend 3: soundcard (pure WASAPI)
# ---------------------------------------------------------------------------
def _capture_soundcard():
    import numpy as np  # noqa: PLC0415
    import soundcard as sc  # noqa: PLC0415

    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415

    results = []
    for mics in (sc.all_microphones(include_loopback=False),):
        for mic in mics:
            name = str(mic.name)
            if _is_virtual(name):
                continue
            try:
                with mic.recorder(samplerate=TARGET_RATE, blocksize=1024) as rec:
                    data = rec.record(numframes=int(TARGET_RATE * PROBE_SECONDS))
            except Exception:
                continue
            arr = np.asarray(data[:, 0] if data.ndim > 1 else data)
            if arr.size == 0:
                continue
            arr = np.nan_to_num(arr)
            pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
            frames = pcm.tobytes()
            samples = bytes_to_mono_float(frames, "int16", 1)
            metrics = analyze_samples(samples)
            results.append(
                {
                    "index": "sc:" + name,
                    "name": name,
                    "host_api": "soundcard/WASAPI",
                    "is_default": getattr(mic, "isdefault", False),
                    "capture_format": "float32",
                    "capture_rate": TARGET_RATE,
                    "capture_channels": 1,
                    "capture_width": 4,
                    "frames_received": len(frames),
                    "_raw_frames": frames,
                    "backend": "soundcard",
                    **metrics,
                }
            )
    return _add_voice_band(results, "soundcard")


# ---------------------------------------------------------------------------
# top-level probing
# ---------------------------------------------------------------------------
def probe_all_backends():
    """Try every capture backend; return (results, backend_errors)."""
    ensure_mic_unmuted()
    results = []
    errors = []
    for name, fn in (
        ("pyaudio", _capture_pyaudio),
        ("sounddevice", _capture_sounddevice),
        ("soundcard", _capture_soundcard),
    ):
        try:
            got = fn()
        except ImportError as exc:
            errors.append(f"{name}: not installed ({exc})")
            continue
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        results.extend(got)
    return results, errors


def select_working_mic():
    """Return the best (report) whose signal is genuinely voice-like, else None."""
    results, errors = probe_all_backends()
    scored = sorted(
        (r for r in results),
        key=lambda r: (_score_metrics(r), r.get("rms", 0.0)),
        reverse=True,
    )
    for report in scored:
        if _is_real_voice(report):
            return report
    return None

# ---------------------------------------------------------------------------
# TTS fallback (offline, Windows SAPI)
# ---------------------------------------------------------------------------
def synthesize_wav(text, out_path, rate=TARGET_RATE):
    """Synthesize ``text`` to a 16 kHz mono int16 WAV using Windows SAPI.

    Returns the output Path. Raises on failure.
    """
    import pyttsx3  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    engine = pyttsx3.init()
    try:
        voice = next(
            (v for v in engine.getProperty("voices") if "david" in v.name.lower()),
            engine.getProperty("voices")[0] if engine.getProperty("voices") else None,
        )
        if voice is not None:
            engine.setProperty("voice", voice.id)
        engine.setProperty("rate", 150)
        temp_wav = out_path.with_suffix(".tts.wav")
        engine.save_to_file(text, str(temp_wav))
        engine.runAndWait()
    finally:
        try:
            engine.stop()
        except Exception:
            pass

    if not temp_wav.exists():
        raise RuntimeError(f"TTS did not produce output: {temp_wav}")

    # Convert whatever sample rate pyttsx3 produced to 16 kHz mono int16.
    with wave.open(str(temp_wav), "rb") as handle:
        src_rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())

    count = len(raw) // width
    if width == 2:
        fmt_name = "int16"
    elif width == 4:
        fmt_name = "int32"
    else:
        fmt_name = "int16"

    samples = _decode_pcm(raw, fmt_name, channels)
    resampled = resample_linear(samples, src_rate, rate)
    write_wav(out_path, resampled, rate)
    temp_wav.unlink(missing_ok=True)
    return out_path


def _decode_pcm(raw, format_name, channels):
    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415

    return bytes_to_mono_float(raw, format_name, channels)


# ---------------------------------------------------------------------------
# recording helper used by record_audio.py
# ---------------------------------------------------------------------------
def record_seconds(report, seconds, on_frames=None):
    """Record ``seconds`` from an already-probed device report.

    ``report`` must come from ``probe_all_backends``/``select_working_mic``.
    Returns (float_samples, analysis_metrics, metadata). Raises
    NoVoiceCaptureError if the backend cannot record.
    """
    backend = report.get("backend")
    if backend == "sounddevice":
        import numpy as np  # noqa: PLC0415
        import sounddevice as sd  # noqa: PLC0415

        rate = report["capture_rate"]
        data = sd.rec(
            int(rate * seconds), samplerate=rate,
            channels=report["capture_channels"], dtype="float32",
            device=report["index"], blocking=True,
        )
        arr = data[:, 0] if data.ndim > 1 and data.shape[1] > 1 else data.ravel()
        samples = np.clip(arr, -1.0, 1.0).astype(float).tolist()
        return samples, analyze_samples(samples), {"rate": rate}

    if backend == "soundcard":
        import numpy as np  # noqa: PLC0415
        import soundcard as sc  # noqa: PLC0415

        mics = [m for m in sc.all_microphones(include_loopback=False) if str(m.name) == report["name"]]
        if not mics:
            raise NoVoiceCaptureError(f"soundcard device gone: {report['name']}")
        with mics[0].recorder(samplerate=TARGET_RATE, blocksize=1024) as rec:
            data = rec.record(numframes=int(TARGET_RATE * seconds))
        arr = np.asarray(data[:, 0] if data.ndim > 1 else data)
        arr = np.nan_to_num(arr)
        samples = np.clip(arr, -1.0, 1.0).astype(float).tolist()
        return samples, analyze_samples(samples), {"rate": TARGET_RATE}

    if backend == "pyaudio":
        import pyaudio  # noqa: PLC0415

        from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415
        from scripts.mic_utils import open_best_stream  # noqa: PLC0415

        audio = pyaudio.PyAudio()
        try:
            stream, fmt_name, width, rate, channels = open_best_stream(
                audio, int(report["index"]), preferred_rate=report["capture_rate"]
            )
            frames = []
            remaining = int(rate * seconds)
            while remaining > 0:
                take = min(1024, remaining)
                data = stream.read(take, exception_on_overflow=False)
                if not data:
                    break
                frames.append(data)
                remaining -= take
                if on_frames:
                    on_frames()
            stream.stop_stream()
            stream.close()
            raw = b"".join(frames)
            samples = bytes_to_mono_float(raw, fmt_name, channels)
            return samples, analyze_samples(samples), {"rate": rate}
        finally:
            audio.terminate()

    raise NoVoiceCaptureError(f"unknown capture backend: {backend}")
