"""Voice-LitE-SQL -- shared microphone utilities for L5 capture.

Provides:
  * enumerate_input_devices  : every input-capable device (host API, rates)
  * open_best_stream         : open a device in a supported native format
  * capture_and_analyze      : short probe -> full signal metrics
  * select_device            : pick the best usable device or defer to manual

The recorder never assumes 16 kHz mono: it opens whatever native format the
device supports (rate / channels / width) and resamples afterwards.
"""

import pyaudio

from scripts.audio_analysis import bytes_to_mono_float, analyze_samples

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

# Candidate native capture formats, most compatible first. paInt24 has no
# dedicated constant in pyaudio (it is 4), so int24 is omitted; int32 and
# float32 cover 4-byte devices.
FORMAT_CANDIDATES = (
    ("int16", pyaudio.paInt16, 2),
    ("int32", pyaudio.paInt32, 4),
    ("float32", pyaudio.paFloat32, 4),
)


def _is_virtual_device(name):
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in VIRTUAL_DEVICE_KEYWORDS)


def enumerate_input_devices(audio, include_virtual=False):
    """All input-capable devices as dicts.

    Each dict has: index, name, host_api, max_input_channels,
    default_sample_rate, is_default, virtual.
    """
    devices = []
    for index in range(audio.get_device_count()):
        try:
            info = audio.get_device_info_by_index(index)
        except Exception:
            continue
        if info.get("maxInputChannels", 0) <= 0:
            continue
        name = str(info.get("name", "?"))
        if not include_virtual and _is_virtual_device(name):
            continue
        try:
            host_api = audio.get_host_api_info_by_index(info.get("hostApi", 0))
            host_name = str(host_api.get("name", "?"))
        except Exception:
            host_name = "?"
        devices.append(
            {
                "index": index,
                "name": name,
                "host_api": host_name,
                "max_input_channels": int(info.get("maxInputChannels", 0)),
                "default_sample_rate": int(info.get("defaultSampleRate", 0) or 0),
                "is_default": bool(info.get("isDefaultInputDevice", False)),
                "virtual": _is_virtual_device(name),
            }
        )
    return devices


def _try_open(audio, index, fmt_name, fmt_const, width, channels, rate, chunk=1024):
    """Try to open one stream config; return (stream, fmt_name, width) or None."""
    try:
        stream = audio.open(
            format=fmt_const,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=index,
            frames_per_buffer=chunk,
        )
        return stream, fmt_name, width
    except Exception:
        return None


def open_best_stream(audio, index, preferred_rate=None):
    """Open an input stream in a native format the device actually supports.

    Tries, in order:
      1. the device's default sample rate
      2. 48 kHz, 44.1 kHz, 16 kHz (as fallbacks)
    each combined with mono then stereo, and int16 then int32 then float32.

    Returns (stream, format_name, sample_width, rate, channels) or raises
    OSError with a descriptive message.
    """
    info = audio.get_device_info_by_index(index)
    max_channels = int(info.get("maxInputChannels", 0))
    if max_channels <= 0:
        raise OSError(f"device [{index}] is not an input device")

    default_rate = int(info.get("defaultSampleRate", 0) or 0)
    rates = []
    for rate in (preferred_rate, default_rate, 48000, 44100, 16000):
        if rate and rate not in rates:
            rates.append(rate)

    channel_sets = ([1, 2] if max_channels >= 2 else [1])

    for rate in rates:
        for channels in channel_sets:
            for fmt_name, fmt_const, width in FORMAT_CANDIDATES:
                opened = _try_open(audio, index, fmt_name, fmt_const, width, channels, rate)
                if opened is not None:
                    return opened[0], opened[1], opened[2], rate, channels

    raise OSError(
        f"could not open device [{index}] in any supported format "
        f"(tried rates {rates}, channels {channel_sets})"
    )


def _read_frames(stream, rate, seconds, chunk=1024):
    """Read raw frames for ``seconds`` from an open stream."""
    frames = []
    remaining = int(rate * seconds)
    while remaining > 0:
        take = min(chunk, remaining)
        data = stream.read(take, exception_on_overflow=False)
        if not data:
            break
        frames.append(data)
        remaining -= take
    return b"".join(frames)


def capture_and_analyze(audio, index, seconds=1.5, preferred_rate=None, on_frames=None):
    """Capture a short probe from ``index`` and return full signal metrics.

    Returns a dict with device info + format + all analysis metrics, or
    ``None`` if the device cannot be opened.
    """
    try:
        stream, fmt_name, width, rate, channels = open_best_stream(
            audio, index, preferred_rate=preferred_rate
        )
    except OSError:
        return None
    try:
        frames = _read_frames(stream, rate, seconds)
    except Exception:
        return None
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass

    samples = bytes_to_mono_float(frames, fmt_name, channels)
    metrics = analyze_samples(samples)
    info = audio.get_device_info_by_index(index)
    try:
        host_name = str(audio.get_host_api_info_by_index(info.get("hostApi", 0)).get("name", "?"))
    except Exception:
        host_name = "?"
    return {
        "index": index,
        "name": str(info.get("name", "?")),
        "host_api": host_name,
        "is_default": bool(info.get("isDefaultInputDevice", False)),
        "capture_format": fmt_name,
        "capture_rate": rate,
        "capture_channels": channels,
        "capture_width": width,
        "frames_received": len(frames),
        **metrics,
    }


def _usable(metrics):
    """A device is usable when it delivered data with meaningful variation."""
    if metrics is None:
        return False
    return (
        metrics.get("frames_received", 0) > 0
        and metrics.get("has_variation", False)
        and metrics.get("peak", 0.0) >= 0.001
    )


def select_device(audio, probe_seconds=1.5, preferred=None):
    """Select the best input device to record from.

    Strategy:
      1. enumerate real (non-virtual) input devices,
      2. probe each candidate briefly and compute signal metrics,
      3. keep devices that are usable (real variation, not constant/clipped),
      4. prefer the system-default device among usable ones, else the one
         with the highest RMS,
      5. if nothing is usable, fall back to the default input device so the
         caller can still attempt recording and report the diagnostics.

    Returns (index, metrics_by_index, selected_report) where
    ``metrics_by_index`` maps device index -> full metrics (for reporting)
    and ``selected_report`` is the metrics dict of the chosen device.
    """
    devices = enumerate_input_devices(audio, include_virtual=False)
    if not devices:
        return None, {}, None

    metrics = {}
    for device in devices:
        report = capture_and_analyze(audio, device["index"], seconds=probe_seconds)
        if report is not None:
            metrics[device["index"]] = report

    usable = [r for r in metrics.values() if _usable(r)]
    if preferred is not None and preferred in metrics and _usable(metrics[preferred]):
        chosen = metrics[preferred]
    elif usable:
        chosen = next((r for r in usable if r.get("is_default")), None)
        if chosen is None:
            chosen = max(usable, key=lambda r: r.get("rms", 0.0))
    else:
        default_report = next((r for r in metrics.values() if r.get("is_default")), None)
        chosen = default_report or next(iter(metrics.values()), None)

    if chosen is None:
        return None, metrics, None
    return chosen["index"], metrics, chosen
