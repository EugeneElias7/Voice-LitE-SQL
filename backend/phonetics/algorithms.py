"""Voice-LitE-SQL -- Level 6: phonetic algorithms.

Thin, dependency-based wrappers around jellyfish / rapidfuzz (both listed
in requirements.txt). Every similarity/encoding function here is pure and
tested. Algorithms are chosen by short names so the offline evaluator can
compare configurations without code changes.
"""

from functools import lru_cache

import jellyfish
from rapidfuzz import fuzz

ALGORITHMS = (
    "jaro_winkler",
    "jaro",
    "levenshtein_ratio",
    "damerau_ratio",
    "soundex",
    "metaphone",
    "nysiis",
)

_SIMILARITY_ALGORITHMS = ("jaro_winkler", "jaro", "levenshtein_ratio", "damerau_ratio")
_PHONETIC_ALGORITHMS = ("soundex", "metaphone", "nysiis")


def clean_token(token):
    """Lowercase and strip non-alphanumeric characters for comparison."""
    return "".join(ch for ch in str(token).lower() if ch.isalnum())


def is_number(token):
    text = clean_token(token)
    if not text:
        return False
    return text.replace(",", ".").replace(".", "", 1).isdigit()


@lru_cache(maxsize=8192)
def phonetic_key(token, algorithm="metaphone"):
    """Phonetic encoding of a token, or '' when it encodes to nothing."""
    text = clean_token(token)
    if not text:
        return ""
    if algorithm == "soundex":
        return jellyfish.soundex(text)
    if algorithm == "metaphone":
        return jellyfish.metaphone(text)
    if algorithm == "nysiis":
        return jellyfish.nysiis(text)
    raise ValueError(f"unknown phonetic algorithm: {algorithm}")


@lru_cache(maxsize=8192)
def similarity(token_a, token_b, algorithm="jaro_winkler"):
    """Normalized similarity in [0, 1]. Higher is more similar."""
    a = clean_token(token_a)
    b = clean_token(token_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if algorithm == "jaro_winkler":
        return jellyfish.jaro_winkler_similarity(a, b)
    if algorithm == "jaro":
        return jellyfish.jaro_similarity(a, b)
    if algorithm == "levenshtein_ratio":
        return fuzz.ratio(a, b) / 100.0
    if algorithm == "damerau_ratio":
        distance = jellyfish.damerau_levenshtein_distance(a, b)
        return 1.0 - distance / max(len(a), len(b))
    raise ValueError(f"unknown similarity algorithm: {algorithm}")


def phonetic_matches(a, b, algorithm="metaphone"):
    """True when two tokens share a phonetic encoding (exact or prefix).

    The prefix rule handles suffix noise ('hired' -> 'hire'); a minimum
    encoding length avoids accidental one-letter matches.
    """
    key_a = phonetic_key(a, algorithm)
    key_b = phonetic_key(b, algorithm)
    if not key_a or not key_b:
        return False
    if len(key_a) < 3 and len(key_b) < 3:
        return False
    return key_a == key_b or key_a.startswith(key_b) or key_b.startswith(key_a)


def best_similarity(token, candidates, algorithms=("jaro_winkler", "levenshtein_ratio")):
    """Best normalized similarity of token against a set of candidates.

    Returns (best_score, best_candidate). The token itself is the best
    candidate whenever it appears in ``candidates`` (score 1.0).
    """
    best_score, best_candidate = 0.0, None
    for candidate in candidates:
        score = max(similarity(token, candidate, alg) for alg in algorithms)
        if score > best_score:
            best_score, best_candidate = score, candidate
    return best_score, best_candidate
