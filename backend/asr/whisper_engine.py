"""Voice-LitE-SQL -- Level 5: local speech-to-text engine.

Wraps Whisper (openai-whisper, or faster-whisper if installed) running
100% locally. No cloud APIs. No automatic model downloads: if the model is
not already present locally, a clear error is returned.

Engine behavior is fully deterministic-testable: ``_run_transcription`` is
the only seam that touches a real model.
"""

import os
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

try:
    import av  # noqa: F401 - optional, only needed for voice
    _AV_AVAILABLE = True
except ImportError:
    av = None  # type: ignore
    _AV_AVAILABLE = False

from backend.asr.models import TranscriptionResult

DEFAULT_MODEL = "small"
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mkv"}


class ASRError(Exception):
    """Raised for audio/model/dependency configuration problems."""


class WhisperEngine:
    def __init__(self, model_name=DEFAULT_MODEL, device="cpu", compute_type=None,
                 language=None, backend="auto", download_root=None):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.backend = backend
        self.download_root = download_root
        self._model = None
        self._active_backend = None

    # -- audio validation -------------------------------------------------
    def _validate_audio(self, audio_path):
        path = Path(audio_path)
        if not path.exists():
            raise ASRError(f"audio file not found: {path}")
        if not path.is_file():
            raise ASRError(f"audio path is not a file: {path}")
        if path.stat().st_size == 0:
            raise ASRError(f"audio file is empty: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ASRError(f"unsupported audio format '{path.suffix}' (supported: {supported})")
        return path

    # -- backend / model loading (no auto-download) ------------------------
    def _import_backend(self):
        if self.backend in ("auto", "faster-whisper"):
            try:
                import faster_whisper  # noqa: PLC0415
                return "faster-whisper", faster_whisper
            except ImportError:
                if self.backend == "faster-whisper":
                    raise ASRError(
                        "faster-whisper is not installed (pip install faster-whisper)"
                    ) from None
        if self.backend in ("auto", "whisper"):
            try:
                os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
                import whisper  # noqa: PLC0415
                return "openai-whisper", whisper
            except ImportError:
                raise ASRError(
                    "openai-whisper is not installed (pip install openai-whisper)"
                ) from None
        raise ASRError(f"unknown backend '{self.backend}' (use 'auto', 'whisper' or 'faster-whisper')")

    def _model_available(self, backend):
        name = self.model_name
        if Path(name).suffix == ".pt" or "/" in name or "\\" in name:
            return Path(name).exists()
        if backend == "openai-whisper":
            root = Path(self.download_root) if self.download_root else Path.home() / ".cache" / "whisper"
            return (root / f"{name}.pt").exists()
        roots = []
        if self.download_root:
            roots.append(Path(self.download_root))
        for env_name in ("HF_HOME", "HF_HUB_CACHE"):
            if os.environ.get(env_name):
                roots.append(Path(os.environ[env_name]))
        roots.append(Path.home() / ".cache" / "huggingface" / "hub")
        sanitized = name.replace(".", "-")
        for root in roots:
            hub = root if root.name == "hub" else root / "hub"
            if (hub / f"models--Systran--faster-whisper-{sanitized}").exists():
                return True
        return False

    def _load_model(self, backend, module):
        if not self._model_available(backend):
            raise ASRError(
                f"whisper model '{self.model_name}' not found locally. "
                "Download it manually first (it will not be downloaded automatically)."
            )
        if backend == "faster-whisper":
            compute = self.compute_type or "default"
            return module.WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=compute,
                download_root=self.download_root,
            )
        return module.load_model(
            self.model_name,
            device=self.device,
            download_root=self.download_root,
        )

    # -- transcription seam (overridden in tests) --------------------------
    def _run_transcription(self, backend, model, audio_path):
        if backend == "faster-whisper":
            segments, info = model.transcribe(str(audio_path), language=self.language or None)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text, getattr(info, "language", None), getattr(info, "duration", None)
        result = model.transcribe(str(audio_path), language=self.language)
        return result["text"].strip(), result.get("language"), result.get("duration")

    # -- public API ---------------------------------------------------------
    def _convert_to_16k_mono_wav(self, audio_path: str) -> str:
        """Convert any audio file to 16kHz mono PCM WAV using PyAV.
        Returns the path to the converted WAV file (temp file).
        """
        if not _AV_AVAILABLE or av is None:
            raise ASRError("PyAV not installed - voice transcription unavailable (pip install av)")
        # Open input with PyAV
        input_container = av.open(audio_path)
        audio_stream = None
        for s in input_container.streams:
            if s.type == 'audio':
                audio_stream = s
                break

        if audio_stream is None:
            input_container.close()
            raise ASRError("No audio stream found in audio file")

        # Create resampler: to 16kHz, mono, fltp (float planar)
        resampler = av.audio.resampler.AudioResampler(
            format='fltp',
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
            raise ASRError("No audio frames after resampling")

        # Write to temporary WAV file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        tmp.close()

        with wave.open(tmp.name, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit = 2 bytes
            wav_file.setframerate(16000)

            for frame in resampled_frames:
                arr = frame.to_ndarray()
                if arr.ndim == 2:
                    arr = arr[0]  # mono
                # fltp format is float32 in [-1, 1], convert to int16
                if arr.dtype == np.float32:
                    arr = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
                elif arr.dtype != np.int16:
                    arr = np.clip(arr, -32768, 32767).astype(np.int16)
                wav_file.writeframes(arr.tobytes())

        return tmp.name

    def transcribe(self, audio_path):
        """Transcribe a local audio file; always returns a TranscriptionResult.
        Converts audio to 16kHz mono PCM WAV before transcription for consistency.
        """
        try:
            path = self._validate_audio(audio_path)
        except ASRError as exc:
            return TranscriptionResult(str(audio_path), "", self.model_name, success=False, error=str(exc))

        if self._model is None:
            try:
                backend, module = self._import_backend()
                self._model = self._load_model(backend, module)
                self._active_backend = backend
            except ASRError as exc:
                return TranscriptionResult(str(path), "", self.model_name, success=False, error=str(exc))
            except Exception as exc:
                return TranscriptionResult(str(path), "", self.model_name, success=False, error=f"model load failed: {exc}")

        # Convert to 16kHz mono WAV for consistent transcription
        wav_path = None
        try:
            wav_path = self._convert_to_16k_mono_wav(str(path))
            started = time.perf_counter()
            text, language, duration = self._run_transcription(self._active_backend, self._model, wav_path)
        except Exception as exc:
            return TranscriptionResult(str(path), "", self.model_name, success=False, error=f"transcription failed: {exc}")
        finally:
            # Cleanup temp WAV
            if wav_path:
                try:
                    Path(wav_path).unlink(missing_ok=True)
                except OSError:
                    pass

        elapsed = (time.perf_counter() - started) * 1000.0

        return TranscriptionResult(
            audio_path=str(path),
            transcript=text,
            model_name=self.model_name,
            language=language,
            duration=duration,
            transcription_time_ms=round(elapsed, 3),
            success=True,
            error=None,
        )
