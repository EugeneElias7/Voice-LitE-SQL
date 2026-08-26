"""Voice-LitE-SQL -- microphone level probe.

Records a few seconds from every input device (or one device) and prints
the captured level, so you can see which microphone actually works.

Usage:
    python scripts/mic_probe.py                 # test ALL input devices (speak during the run!)
    python scripts/mic_probe.py --device 17     # test a single device index
    python scripts/mic_probe.py --seconds 2     # shorter/longer capture per device
"""

import argparse
import sys

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
PEAK_OK_THRESHOLD = 500


def level_of(frames):
    import struct
    count = len(frames) // SAMPLE_WIDTH
    if count == 0:
        return 0.0, 0
    samples = struct.unpack("<%dh" % count, frames[: count * SAMPLE_WIDTH])
    peak = max(abs(s) for s in samples)
    rms = (sum(s * s for s in samples) / count) ** 0.5
    return rms, peak


def main():
    parser = argparse.ArgumentParser(description="Microphone level probe")
    parser.add_argument("--device", type=int, default=None, help="single device index to test")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--list", action="store_true", help="list devices and exit")
    args = parser.parse_args()

    try:
        import pyaudio  # noqa: PLC0415
    except ImportError:
        print("ERROR: pyaudio is not installed - run: pip install pyaudio", file=sys.stderr)
        sys.exit(1)

    audio = pyaudio.PyAudio()
    try:
        devices = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if info.get("maxInputChannels", 0) > 0:
                default = info.get("isDefaultInputDevice", False)
                devices.append((index, info.get("name"), default))

        if args.list:
            for index, name, default in devices:
                print(f"  [{index}] {name}{'  <-- default' if default else ''}")
            return

        if args.device is not None:
            devices = [d for d in devices if d[0] == args.device]
            if not devices:
                print(f"ERROR: device {args.device} is not an input device.", file=sys.stderr)
                sys.exit(1)

        print(f"Recording {args.seconds:.0f}s from {len(devices)} device(s).")
        print(">>> SPEAK LOUDLY for the whole run <<<\n")
        results = []
        for index, name, default in devices:
            try:
                stream = audio.open(
                    format=audio.get_format_from_width(SAMPLE_WIDTH),
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    input_device_index=index,
                    frames_per_buffer=1024,
                )
                frames = []
                remaining = int(SAMPLE_RATE * args.seconds)
                while remaining > 0:
                    chunk = min(1024, remaining)
                    frames.append(stream.read(chunk, exception_on_overflow=False))
                    remaining -= chunk
                stream.stop_stream()
                stream.close()
                rms, peak = level_of(b"".join(frames))
                status = "OK - voice captured" if peak >= PEAK_OK_THRESHOLD else "SILENT"
                results.append((index, name, default, peak, rms, status))
                print(f"  [{index}] {name}{'  <-- default' if default else ''}")
                print(f"      peak={peak}  rms={rms:.1f}  -> {status}")
            except Exception as exc:
                print(f"  [{index}] {name}: could not open - {exc}")
        audio.terminate()

        good = [r for r in results if r[3] >= PEAK_OK_THRESHOLD]
        print("\nResult:", end=" ")
        if good:
            print("use --mic " + str(good[0][0]) + " (or --device " + str(good[0][0]) + " in record_audio.py)")
        else:
            print("NO working microphone detected. Check: Windows Settings > System > Sound > Microphone,")
            print("and that the mic is not muted in the input properties.")
    finally:
        if "audio" in dir() and audio:
            try:
                audio.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
