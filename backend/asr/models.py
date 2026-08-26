"""Voice-LitE-SQL -- Level 5: ASR data model, spoken manifest, WER.

Everything here is local: no network calls, no cloud APIs.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptionResult:
    audio_path: str
    transcript: str
    model_name: str
    language: str = None
    duration: float = None
    transcription_time_ms: float = 0.0
    success: bool = False
    error: str = None

    def to_dict(self):
        return {
            "audio_path": self.audio_path,
            "transcript": self.transcript,
            "model_name": self.model_name,
            "language": self.language,
            "duration": self.duration,
            "transcription_time_ms": self.transcription_time_ms,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class SpokenSample:
    question_id: str
    reference_text: str
    audio_path: str  # relative to the spoken dataset directory


@dataclass
class SpokenManifest:
    samples: list
    spoken_dir: Path

    def audio_file(self, sample):
        """Absolute path of a sample's audio file (may not exist yet)."""
        return self.spoken_dir / sample.audio_path


def load_manifest(manifest_path, questions_path=None):
    """Load and validate a spoken dataset manifest.

    Returns a SpokenManifest. Raises ValueError with a clear message for
    structural problems, unknown question ids, or unsafe audio paths.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise ValueError(f"manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "samples" not in data:
        raise ValueError("manifest must contain a 'samples' list")
    if not isinstance(data["samples"], list) or not data["samples"]:
        raise ValueError("manifest 'samples' must be a non-empty list")

    question_ids = None
    if questions_path is not None:
        questions = json.loads(Path(questions_path).read_text(encoding="utf-8"))
        question_ids = {q["id"] for q in questions}

    spoken_dir = manifest_path.parent
    samples = []
    for index, entry in enumerate(data["samples"]):
        if not isinstance(entry, dict):
            raise ValueError(f"samples[{index}] is not an object")
        missing = {"question_id", "reference_text", "audio_path"} - set(entry)
        if missing:
            raise ValueError(f"samples[{index}] missing fields: {', '.join(sorted(missing))}")
        if not entry["reference_text"].strip():
            raise ValueError(f"samples[{index}] reference_text is empty")
        audio_path = entry["audio_path"]
        if Path(audio_path).is_absolute() or ".." in Path(audio_path).parts:
            raise ValueError(f"samples[{index}] audio_path must be relative: {audio_path}")
        if question_ids is not None and entry["question_id"] not in question_ids:
            raise ValueError(f"samples[{index}] unknown question_id '{entry['question_id']}'")
        samples.append(
            SpokenSample(
                question_id=entry["question_id"],
                reference_text=entry["reference_text"].strip(),
                audio_path=audio_path,
            )
        )
    return SpokenManifest(samples=samples, spoken_dir=spoken_dir)


# ---------------------------------------------------------------------------
# Word error rate (word-level Levenshtein distance / reference word count)
# ---------------------------------------------------------------------------
def _word_distance(reference, hypothesis):
    ref = reference.split()
    hyp = hypothesis.split()
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[n][m]


def compute_wer(reference, hypothesis):
    """Word error rate in [0.0, 1.0] (case/whitespace-normalized)."""
    ref_words = (reference or "").strip().lower().split()
    hyp_words = (hypothesis or "").strip().lower().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _word_distance(" ".join(ref_words), " ".join(hyp_words)) / len(ref_words)
