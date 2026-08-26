"""Voice-LitE-SQL -- L5 prep: record WAV audio for the spoken dataset.

Captures microphone audio in the device's NATIVE format (whatever sample
rate / channels / width the device actually supports), analyzes the signal,
then resamples to the Whisper-required 16 kHz mono 16-bit WAV.

Modes:
    python scripts/record_audio.py                   normal recording (auto device)
    python scripts/record_audio.py --list-devices    enumerate devices, no capture
    python scripts/record_audio.py --diagnose        full signal diagnostics, no save
    python scripts/record_audio.py --device 8        force a specific device index
    python scripts/record_audio.py --limit 2         record only the first N samples
    python scripts/record_audio.py --synth           synthesize the samples with
                                                     offline TTS (no microphone)
"""

import argparse
import sys
import time
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.asr.models import load_manifest  # noqa: E402
from scripts.audio_analysis import bytes_to_mono_float, analyze_samples, resample_linear, write_wav  # noqa: E402
from scripts.mic_utils import (  # noqa: E402
    capture_and_analyze,
    enumerate_input_devices,
    open_best_stream,
    select_device,
)

DEFAULT_MANIFEST = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "manifest.json"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"

WHISPER_RATE = 16000  # resample target for the saved WAV


def _build_sd_report(index):
    """Build a voice_capture-compatible report for a sounddevice device index,
    so the proven ``record_seconds`` path can be used."""
    import numpy as np  # noqa: PLC0415
    import sounddevice as sd  # noqa: PLC0415

    from scripts.audio_analysis import bytes_to_mono_float  # noqa: PLC0415

    info = sd.query_devices(index, "input")
    name = str(info.get("name", "?"))
    channels = int(info.get("max_input_channels", 0))
    if channels <= 0:
        return None
    default_rate = int(info.get("default_samplerate", 0) or 0)
    for rate in dict.fromkeys([r for r in (default_rate, 48000, 44100, 16000) if r]):
        for ch in ([1, 2] if channels >= 2 else [1]):
            try:
                data = sd.rec(
                    int(rate * 1.5), samplerate=rate, channels=ch,
                    dtype="float32", device=index, blocking=True,
                )
            except Exception:
                continue
            arr = data[:, 0] if data.ndim > 1 and data.shape[1] > 1 else data.ravel()
            pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
            frames = pcm.tobytes()
            samples = bytes_to_mono_float(frames, "int16", 1)
            from scripts.audio_analysis import analyze_samples  # noqa: PLC0415
            metrics = analyze_samples(samples)
            try:
                from scripts.voice_capture import _voice_band_ratio  # noqa: PLC0415
                vbr = _voice_band_ratio(samples, rate)
            except Exception:
                vbr = 0.0
            return {
                "index": index,
                "name": name,
                "backend": "sounddevice",
                "capture_rate": rate,
                "capture_channels": ch,
                "frames_received": len(frames),
                "voice_band_ratio": vbr,
                **metrics,
            }
    return None


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------
def _format_report(report):
    if report is None:
        return "  (no data)"
    status = report.get("status", "?")
    flags = []
    if report.get("frames_received", 0) == 0:
        flags.append("NO DATA")
    if report.get("clipping_pct", 0.0) > 0.05:
        flags.append("CLIPPED")
    if report.get("constant_pct", 0.0) > 0.95:
        flags.append("CONSTANT")
    if report.get("zero_pct", 0.0) > 0.9:
        flags.append("SILENT")
    line = (
        f"  [{report['index']}] {report['name']}"
        f"{'  <-- default' if report.get('is_default') else ''}\n"
        f"      host={report.get('host_api', '?')}  "
        f"rate={report.get('capture_rate')}  ch={report.get('capture_channels')}  "
        f"format={report.get('capture_format')}\n"
        f"      rms={report.get('rms')}  peak={report.get('peak')}  "
        f"clipping={report.get('clipping_pct')*100:.2f}%  "
        f"constant={report.get('constant_pct')*100:.1f}%  "
        f"unique={report.get('unique')}  variation={report.get('has_variation')}\n"
        f"      status={status}"
    )
    if flags:
        line += "  [" + ",".join(flags) + "]"
    return line


def _print_selected(report):
    print("  Selected device:")
    print(_format_report(report))


# ---------------------------------------------------------------------------
# capture helpers
# ---------------------------------------------------------------------------
def _read_native_frames(stream, rate, seconds, chunk=1024):
    frames = []
    remaining = int(rate * seconds)
    last_meter = time.perf_counter()
    while remaining > 0:
        take = min(chunk, remaining)
        data = stream.read(take, exception_on_overflow=False)
        if not data:
            break
        frames.append(data)
        remaining -= take
        now = time.perf_counter()
        if now - last_meter >= 0.8:
            last_meter = now
            print("    ... recording ...")
    return b"".join(frames)


def _analyze_native(frames, fmt_name, channels):
    samples = bytes_to_mono_float(frames, fmt_name, channels)
    return samples, analyze_samples(samples)


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------
def list_devices_mode(audio):
    devices = enumerate_input_devices(audio, include_virtual=True)
    print("Input-capable devices:")
    for device in devices:
        marker = " <-- default" if device["is_default"] else ""
        virtual = " [virtual]" if device["virtual"] else ""
        print(
            f"  [{device['index']}] {device['name']}{marker}{virtual}\n"
            f"      host={device['host_api']}  max_input_ch={device['max_input_channels']}  "
            f"default_rate={device['default_sample_rate']}"
        )


def diagnose_mode(audio, device=None, seconds=1.5):
    print(f"Diagnosing input devices (capture {seconds:.1f}s per device, no recordings saved)...\n")
    if device is not None:
        report = capture_and_analyze(audio, device, seconds=seconds)
        if report is None:
            print(f"  Device [{device}] could not be opened.")
        else:
            print(_format_report(report))
        return
    devices = enumerate_input_devices(audio, include_virtual=True)
    for d in devices:
        report = capture_and_analyze(audio, d["index"], seconds=seconds)
        print(_format_report(report) if report is not None else f"  [{d['index']}] {d['name']} - could not open")


def _pick_manual(metrics, default_index=None):
    """Interactive device picker when auto-selection is ambiguous."""
    reports = list(metrics.values())
    reports.sort(key=lambda r: (0 if r.get("is_default") else 1, -r.get("rms", 0.0)))
    print("\n  No clearly usable microphone was detected automatically.")
    print("  Choose a device to record with:")
    for report in reports:
        print(
            f"    [{report['index']}] {report['name']}"
            f"{'  <-- default' if report.get('is_default') else ''}  "
            f"rms={report.get('rms')}  peak={report.get('peak')}  "
            f"status={report.get('status')}"
        )
    while True:
        choice = input("  Enter device index (or press Enter for the default): ").strip()
        if not choice:
            return default_index
        try:
            chosen = int(choice)
        except ValueError:
            print("    Invalid number.")
            continue
        if chosen in metrics:
            return chosen
        print(f"    Device [{chosen}] not in the probed list.")


def record_samples(args, audio, device_index, device_report):
    """Record each manifest sample to a resampled 16 kHz mono WAV."""
    manifest = load_manifest(args.manifest, questions_path=args.questions)
    missing = [s for s in manifest.samples if not manifest.audio_file(s).exists()]
    if args.force:
        missing = list(manifest.samples)
    if args.limit:
        missing = missing[:args.limit]
    if not missing:
        print("All manifest samples already have audio files.")
        return

    print(f"\nRecording with device [{device_index}] {device_report['name']}")

    try:
        stream, fmt_name, width, rate, channels = open_best_stream(audio, device_index)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Native format        : {rate} Hz, {channels} ch, {fmt_name} ({width}-byte)")
    print(f"Output format        : {WHISPER_RATE} Hz, mono, int16 (Whisper format)")
    print(f"Recording duration   : {args.seconds:.1f}s per question\n")

    skipped = []
    try:
        for index, sample in enumerate(missing, start=1):
            target = manifest.audio_file(sample)
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"[{index}/{len(missing)}] {sample.question_id}")
            print(f'    Say: "{sample.reference_text}"')
            print("    Press Enter to START recording...")
            input()
            frames = _read_native_frames(stream, rate, args.seconds)
            samples, metrics = _analyze_native(frames, fmt_name, channels)
            resampled = resample_linear(samples, rate, WHISPER_RATE)
            write_wav(target, resampled, WHISPER_RATE)

            duration = len(frames) / (rate * channels * width)
            print(f"    duration={duration:.1f}s  rms={metrics['rms']}  peak={metrics['peak']}  "
                  f"clipping={metrics['clipping_pct']*100:.2f}%  constant={metrics['constant_pct']*100:.1f}%")
            if metrics["status"] in ("silence", "constant", "clipped", "low_level"):
                print(f"    WARNING: signal status '{metrics['status']}'. This recording may not contain clear voice.")
                print("    Tip: re-run with --device <index> to pick a different microphone.")
            print(f"    Saved: {target}")
    except KeyboardInterrupt:
        print("\nRecording cancelled.")
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass

    if skipped:
        print(f"\nSkipped: {', '.join(skipped)}")
    print("\nDone. Run: python scripts/l5_asr.py --manifest")


def synth_samples(args):
    """Synthesize manifest samples with offline TTS (no microphone needed)."""
    from scripts.voice_capture import synthesize_wav  # noqa: PLC0415

    manifest = load_manifest(args.manifest, questions_path=args.questions)
    missing = [s for s in manifest.samples if not manifest.audio_file(s).exists()]
    if args.force:
        missing = list(manifest.samples)
    if args.limit:
        missing = missing[:args.limit]
    if not missing:
        print("All manifest samples already have audio files.")
        return

    print(f"Synthesizing {len(missing)} samples with offline TTS (Windows SAPI)...\n")
    for sample in missing:
        target = manifest.audio_file(sample)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            synthesize_wav(sample.reference_text, target)
            print(f"    {sample.question_id}: {sample.reference_text!r}")
            print(f"        -> {target}")
        except Exception as exc:
            print(f"    {sample.question_id}: TTS FAILED - {exc}", file=sys.stderr)

    print("\nDone. Run: python scripts/l5_asr.py --manifest")


def _beep(freq=880, duration_ms=120):
    """Short system beep via winsound (Windows only)."""
    try:
        import winsound  # noqa: PLC0415
        winsound.Beep(freq, duration_ms)
    except Exception:
        pass


def record_using_report(args, report):
    """Record every manifest sample through the proven multi-backend
    ``record_seconds`` path (sounddevice works reliably on this machine;
    PyAudio's shared-mode streams return empty buffers)."""
    import time  # noqa: PLC0415

    from scripts.voice_capture import record_seconds  # noqa: PLC0415

    manifest = load_manifest(args.manifest, questions_path=args.questions)
    missing = [s for s in manifest.samples if not manifest.audio_file(s).exists()]
    if args.force:
        missing = list(manifest.samples)
    if args.limit:
        missing = missing[:args.limit]
    if not missing:
        print("All manifest samples already have audio files.")
        return

    print(f"\nRecording with [{report['index']}] {report['name']}  "
          f"(backend={report['backend']})")
    print(f"Recording duration   : {args.seconds:.1f}s per question")
    print(f"Retry on silence     : ON   (auto re-record bad takes)\n")

    for sample in missing:
        target = manifest.audio_file(sample)
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{sample.question_id}] Say: \"{sample.reference_text}\"")
        print("    Press Enter, get ready, then speak when the recording starts...")
        input()
        # 1s pause + beeps so the user is ready before capture begins
        _beep(660, 100)
        time.sleep(1.0)
        _beep(880, 150)
        for _ in range(3):
            samples, metrics, meta = record_seconds(report, args.seconds)
            print(f"    rms={metrics['rms']}  peak={metrics['peak']}  "
                  f"constant={metrics['constant_pct']*100:.1f}%  status={metrics['status']}")
            if metrics["status"] not in ("silence", "constant", "low_level"):
                break
            _beep(330, 200)
            print("    No voice detected - speak after the beep, retrying...\n")
            time.sleep(1.0)
        resampled = resample_linear(samples, meta["rate"], WHISPER_RATE)
        write_wav(target, resampled, WHISPER_RATE)
        print(f"    Saved: {target}\n")

    print("Done. Run: python scripts/l5_asr.py --manifest")


def run_auto(args):
    """Record manifest samples using the multi-backend auto-selection
    (pyaudio + sounddevice + soundcard) with voice-band scoring."""
    from scripts.voice_capture import select_working_mic  # noqa: PLC0415

    report = select_working_mic()
    if report is None:
        print("ERROR: no voice-capable microphone detected.", file=sys.stderr)
        print("Hints:", file=sys.stderr)
        print("  - plug in your 3.5mm earphone/headset mic", file=sys.stderr)
        print("  - check Windows: Settings > System > Sound > Input (not muted, level > 50%)", file=sys.stderr)
        print("  - or use --synth to generate the dataset with offline TTS", file=sys.stderr)
        sys.exit(1)

    print(f"  Selected: {report['name']}  (backend={report['backend']}, "
          f"rms={report['rms']}, voice_band={report.get('voice_band_ratio', 0):.2f})")
    record_using_report(args, report)


def run_record(args):
    try:
        import pyaudio  # noqa: PLC0415
    except ImportError:
        print("ERROR: pyaudio is not installed - run: pip install pyaudio", file=sys.stderr)
        sys.exit(1)

    audio = pyaudio.PyAudio()

    try:
        from scripts.voice_capture import ensure_mic_unmuted  # noqa: PLC0415
        if ensure_mic_unmuted():
            print("INFO: the Windows microphone was muted - unmuted it.")
    except Exception:
        pass

    if getattr(args, "auto", False):
        run_auto(args)
        audio.terminate()
        return

    if getattr(args, "list_devices", False):
        list_devices_mode(audio)
        audio.terminate()
        return

    if getattr(args, "diagnose", False):
        diagnose_mode(audio, device=getattr(args, "device", None), seconds=args.probe_seconds)
        audio.terminate()
        return

    # normal recording: always use the sounddevice path (proven reliable here;
    # PyAudio's shared-mode streams return empty buffers on this machine).
    import sounddevice as sd  # noqa: PLC0415

    if getattr(args, "device", None) is not None:
        report = _build_sd_report(args.device)
        if report is None:
            print(f"ERROR: could not open device [{args.device}].", file=sys.stderr)
            print("Run: python scripts/record_audio.py --list-devices", file=sys.stderr)
            audio.terminate()
            sys.exit(1)
        print("Explicit --device selection:")
        print(f"  [{report['index']}] {report['name']}  rms={report['rms']}  "
              f"status={report['status']}")
    else:
        print("Selecting the active microphone - speak normally during the probe...\n")
        from scripts.voice_capture import select_working_mic  # noqa: PLC0415

        report = select_working_mic()
        if report is None:
            print("ERROR: no usable input devices found.", file=sys.stderr)
            print("Run: python scripts/record_audio.py --list-devices", file=sys.stderr)
            audio.terminate()
            sys.exit(1)
        print(f"  Selected: [{report['index']}] {report['name']}  rms={report['rms']}  "
              f"status={report['status']}")

    try:
        record_using_report(args, report)
    finally:
        audio.terminate()


def main():
    parser = argparse.ArgumentParser(description="Record WAV files for the L5 spoken dataset")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list-devices", action="store_true", help="enumerate input devices and exit (no capture)")
    parser.add_argument("--diagnose", action="store_true", help="capture and analyze every device, save nothing")
    parser.add_argument("--device", type=int, default=None, help="input device index (default: auto-select)")
    parser.add_argument("--probe-seconds", type=float, default=1.5, help="probe/diagnose capture length in seconds")
    parser.add_argument("--force", action="store_true", help="re-record samples that already have audio files")
    parser.add_argument("--seconds", type=float, default=6.0, help="recording duration in seconds per question")
    parser.add_argument("--interactive", action="store_true", help="always ask which device to use when auto-select is uncertain")
    parser.add_argument("--synth", action="store_true", help="synthesize samples with offline TTS instead of recording from a microphone")
    parser.add_argument("--auto", action="store_true", help="use multi-backend auto-selection (pyaudio+sounddevice+soundcard) instead of PyAudio only")
    args = parser.parse_args()

    if args.synth:
        synth_samples(args)
        return

    run_record(args)


if __name__ == "__main__":
    main()
