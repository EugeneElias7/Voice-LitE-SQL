"""Voice-LitE-SQL -- Convert externally-recorded audio (e.g. Windows Voice
Recorder .m4a) into the Whisper-format WAV files expected by the L5 spoken
manifest.

Bypasses PyAudio entirely: this machine's Windows audio drivers deliver a
synthetic constant tone through PyAudio, so recordings are captured with the
regular Windows apps instead and converted here.

Usage:
  python scripts/convert_audio.py --src path/to/q01.m4a --id q01
  python scripts/convert_audio.py --src path/to/dir --all
"""

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

AUDIO_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "audio"
TARGET_RATE = 16000


def convert_to_wav(src: Path, out: Path) -> None:
    """Decode any audio via PyAV (no external ffmpeg) and write 16 kHz mono
    int16 WAV. Returns after writing; raises on any failure."""
    import numpy as np
    import av

    container = av.open(str(src))
    stream = container.streams.audio[0]
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=TARGET_RATE,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    written = 0
    with av.open(str(tmp), "w", format="wav") as wav:
        out_stream = wav.add_stream("pcm_s16le", rate=TARGET_RATE)
        out_stream.layout = "mono"
        for frame in container.decode(stream):
            frames = resampler.resample(frame)
            for f in frames:
                for p in out_stream.encode(f):
                    wav.mux(p)
                    written += 1
        for f in resampler.resample(None):
            for p in out_stream.encode(f):
                wav.mux(p)
                written += 1
        for p in out_stream.encode(None):
            wav.mux(p)
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"no audio decoded from {src}")
    tmp.replace(out)


def convert_one(src: Path, sample_id: str) -> None:
    out = AUDIO_DIR / f"{sample_id}.wav"
    convert_to_wav(src, out)
    print(f"Saved: {out}  (16 kHz mono int16, from {src.name})")


def convert_dir(src_dir: Path) -> None:
    supported = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mkv"}
    files = sorted(
        p for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported
    )
    if not files:
        print(f"No audio files found in {src_dir}")
        sys.exit(1)
    for p in files:
        sample_id = p.stem.split("_")[0].split("-")[0].replace(" ", "")
        convert_one(p, sample_id)


def main():
    parser = argparse.ArgumentParser(description="Convert external recordings to L5 WAV files")
    parser.add_argument("--src", required=True, help="audio file or directory")
    parser.add_argument("--id", default=None, help="sample id (q01, q05, ...); auto from filename when --all")
    parser.add_argument("--all", action="store_true", help="convert every audio file in the directory")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"ERROR: {src} does not exist", file=sys.stderr)
        sys.exit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and args.all:
        convert_dir(src)
    elif args.id:
        convert_one(src, args.id)
    else:
        print("Provide --id <sample> for a single file, or --all for a directory.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
