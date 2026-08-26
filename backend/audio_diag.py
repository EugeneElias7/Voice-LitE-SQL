"""Audio diagnostic module for Voice-LitE-SQL.
Analyzes audio files, converts to 16kHz mono PCM WAV, runs Whisper ASR comparison.
"""

import os
import tempfile
import wave
import struct
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any
import av

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


def analyze_audio_file(audio_path: str) -> Dict[str, Any]:
    """Analyze an audio file and return detailed metrics."""
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    file_size = path.stat().st_size
    mime_type = _guess_mime_from_extension(path.suffix)

    # Use PyAV to decode and analyze
    container = av.open(str(path))
    audio_stream = None
    for s in container.streams:
        if s.type == 'audio':
            audio_stream = s
            break

    if audio_stream is None:
        container.close()
        raise ValueError("No audio stream found in file")

    # Extract basic properties
    sample_rate = audio_stream.rate or 48000
    channels = audio_stream.channels or 1
    duration = float(audio_stream.duration * audio_stream.time_base) if audio_stream.duration else 0.0
    codec_name = audio_stream.codec_context.name if audio_stream.codec_context else "unknown"

    # Decode all audio frames to numpy array for analysis
    frames = []
    for frame in container.decode(audio_stream):
        arr = frame.to_ndarray()
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        elif arr.ndim == 2 and arr.shape[0] != channels:
            arr = arr.T
        frames.append(arr)
    container.close()

    if not frames:
        raise ValueError("No audio frames decoded")

    audio_data = np.concatenate(frames, axis=1).astype(np.float32)

    # If stereo/multi-channel, average to mono for metrics
    if audio_data.shape[0] > 1:
        mono_data = np.mean(audio_data, axis=0)
    else:
        mono_data = audio_data[0]

    # Normalize to [-1, 1] range
    max_val = np.max(np.abs(mono_data))
    if max_val > 0:
        mono_data = mono_data / max_val

    # Compute metrics - convert to Python native types
    rms = float(np.sqrt(np.mean(mono_data ** 2)))
    peak = float(np.max(np.abs(mono_data)))

    # Speech-band energy (300-3400 Hz) - approximate via bandpass
    speech_band_energy = _compute_speech_band_energy(mono_data, sample_rate)

    return {
        "file_path": str(path),
        "file_size_bytes": int(file_size),
        "mime_type": mime_type,
        "codec": codec_name,
        "sample_rate": int(sample_rate),
        "channels": int(channels),
        "duration_seconds": round(float(duration), 3),
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "speech_band_energy": round(speech_band_energy, 6),
        "max_amplitude": float(max_val),
    }


def _guess_mime_from_extension(ext: str) -> str:
    ext = ext.lower()
    mime_map = {
        ".webm": "audio/webm;codecs=opus",
        ".ogg": "audio/ogg;codecs=opus",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".mp4": "audio/mp4",
    }
    return mime_map.get(ext, "application/octet-stream")


def _compute_speech_band_energy(audio: np.ndarray, sample_rate: int) -> float:
    """Approximate speech band energy (300-3400 Hz) using simple FFT."""
    n = len(audio)
    if n < 1024:
        return 0.0

    # Use a segment of up to 4096 samples
    segment_len = min(4096, n)
    start = n // 2 - segment_len // 2
    segment = audio[start:start + segment_len]

    # Apply Hann window
    window = np.hanning(segment_len)
    segment = segment * window

    # FFT
    fft = np.fft.rfft(segment)
    freqs = np.fft.rfftfreq(segment_len, 1.0 / sample_rate)

    # Band mask for 300-3400 Hz
    mask = (freqs >= 300) & (freqs <= 3400)
    if not np.any(mask):
        return 0.0

    # Energy in speech band
    band_energy = np.sum(np.abs(fft[mask]) ** 2)
    total_energy = np.sum(np.abs(fft) ** 2)

    if total_energy > 0:
        return float(band_energy / total_energy)
    return 0.0


def convert_to_16k_mono_wav(input_path: str, output_path: Optional[str] = None) -> str:
    """Convert any audio file to 16kHz mono PCM WAV using PyAV.
    Returns the path to the converted WAV file.
    """
    input_path = str(input_path)
    if output_path is None:
        output_path = str(Path(input_path).with_suffix('.16k.wav'))

    # Open input with PyAV
    input_container = av.open(input_path)
    audio_stream = None
    for s in input_container.streams:
        if s.type == 'audio':
            audio_stream = s
            break

    if audio_stream is None:
        input_container.close()
        raise ValueError("No audio stream found")

    # Create resampler: to 16kHz, mono, s16 (signed 16-bit PCM)
    resampler = av.audio.resampler.AudioResampler(
        format='s16',
        layout='mono',
        rate=16000,
    )

    # Decode and resample all frames
    resampled_frames = []
    for frame in input_container.decode(audio_stream):
        resampled = resampler.resample(frame)
        if resampled is not None:
            if isinstance(resampled, list):
                resampled_frames.extend(resampled)
            else:
                resampled_frames.append(resampled)

    input_container.close()

    if not resampled_frames:
        raise ValueError("No audio frames after resampling")

    # Write to WAV file
    with wave.open(output_path, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit = 2 bytes
        wav_file.setframerate(16000)

        for frame in resampled_frames:
            arr = frame.to_ndarray()
            if arr.ndim == 2:
                arr = arr[0]  # mono
            # Ensure int16
            if arr.dtype != np.int16:
                arr = np.clip(arr, -32768, 32767).astype(np.int16)
            wav_file.writeframes(arr.tobytes())

    return output_path


def run_whisper_transcription(audio_path: str, model_name: str = "small",
                               compute_type: str = "int8", language: Optional[str] = None) -> Dict[str, Any]:
    """Run faster-whisper transcription on an audio file."""
    if WhisperModel is None:
        return {"error": "faster_whisper not installed", "transcript": ""}

    try:
        model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        segments, info = model.transcribe(audio_path, language=language)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {
            "transcript": text,
            "language": info.language,
            "duration": info.duration,
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "transcript": "", "success": False}


def full_diagnostic(audio_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run complete diagnostic on an audio file."""
    input_path = Path(audio_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {audio_path}")

    if output_dir is None:
        output_dir = input_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Analyze original file
    original_analysis = analyze_audio_file(str(input_path))

    # 2. Convert to 16kHz mono WAV
    wav_path = output_dir / f"{input_path.stem}.16k.wav"
    convert_to_16k_mono_wav(str(input_path), str(wav_path))

    # 3. Analyze converted WAV
    wav_analysis = analyze_audio_file(str(wav_path))

    # 4. Run Whisper on original
    original_transcript = run_whisper_transcription(str(input_path))

    # 5. Run Whisper on converted WAV
    wav_transcript = run_whisper_transcription(str(wav_path))

    return {
        "input_file": str(input_path),
        "original_analysis": original_analysis,
        "converted_wav": str(wav_path),
        "wav_analysis": wav_analysis,
        "original_transcript": original_transcript,
        "wav_transcript": wav_transcript,
    }


def generate_reference_wav(text: str, output_path: str, rate: int = 16000) -> str:
    """Generate a reference WAV file using pyttsx3 (offline TTS)."""
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1.0)

    # Save to WAV - pyttsx3 saves in system default format
    engine.save_to_file(text, output_path)
    engine.runAndWait()

    # Convert to 16kHz mono PCM if needed
    return convert_to_16k_mono_wav(output_path, output_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python audio_diag.py <audio_file> [output_dir]")
        sys.exit(1)

    audio_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    result = full_diagnostic(audio_file, output_dir)

    import json
    print(json.dumps(result, indent=2))