"""Voice-LitE-SQL -- Level 6: database-aware phonetic normalization.

Corrects ASR/noise errors by grounding tokens in the schema vocabulary of
the database being queried. Strategy per token:

1. skip numbers, stopwords and very short tokens;
2. exact vocabulary match -> unchanged;
3. best similarity over the configured algorithms, gated by a threshold
   and an ambiguity margin (the best candidate must clearly win);
4. phonetic fallback: tokens whose phonetic encoding (e.g. Metaphone)
   matches a vocabulary term even when plain similarity is low
   ('celery' -> 'salary', 'rejun' -> 'region');
5. multi-word merge: adjacent corrected tokens that spell a column
   like ``sale date`` are merged into ``sale_date``.

The result is a corrected text plus an explicit correction report.
"""

import re
from dataclasses import dataclass, field

from backend.phonetics.algorithms import (
    clean_token,
    is_number,
    phonetic_key,
    phonetic_matches,
    similarity,
)
from backend.phonetics.vocabulary import DatabaseVocabulary

STOPWORDS = frozenset(
    """
    the a an of in on at by to for and or but with without is are was were be
    been being am has have had do does did this that these those it its what
    which who whom whose when where why how all any most many much each every
    some few per from into about after before between under over then than as
    so also their there they we you he she them us our your his her not no yes
    """.split()
)

TOKEN_PATTERN = re.compile(r"\S+")


@dataclass
class NormalizerConfig:
    threshold: float = 0.75
    margin: float = 0.12
    high_confidence: float = 0.85
    min_token_len: int = 3
    tie_epsilon: float = 0.04
    algorithms: tuple = ("jaro_winkler", "levenshtein_ratio")
    phonetic_algorithm: str = "metaphone"
    phonetic_min_score: float = 0.55
    merge_multiword: bool = True


@dataclass
class Correction:
    token: str
    corrected: str
    kind: str  # table | column | word
    parent: str = None  # parent column when kind == "word"
    score: float = 0.0
    algorithm: str = "similarity"
    reason: str = None
    scores: dict = field(default_factory=dict)

    @property
    def schema_term(self):
        return self.parent or self.corrected


@dataclass
class TokenDecision:
    """Record for one examined token, whether or not it was corrected.

    Serialized shape (as required by the L6 spec):
    ``original``, ``replacement``, ``confidence``, ``applied``,
    ``strategy``, ``reason``, ``scores`` (per-algorithm), ``candidate``.
    """

    original: str
    replacement: str
    confidence: float
    applied: bool
    strategy: str  # similarity | phonetic | none
    reason: str  # exact_match | high_confidence | margin | phonetic |
    #             # below_threshold | ambiguous | phonetic_below_min | not_found
    scores: dict = field(default_factory=dict)
    candidate: str = None


@dataclass
class NormalizationResult:
    text: str
    corrections: list = field(default_factory=list)
    decisions: list = field(default_factory=list)

    @property
    def corrected_tokens(self):
        return {c.token for c in self.corrections}


class DatabaseAwareNormalizer:
    def __init__(self, vocabulary, config=None):
        if not isinstance(vocabulary, DatabaseVocabulary):
            vocabulary = DatabaseVocabulary(vocabulary)
        self.vocabulary = vocabulary
        self.config = config or NormalizerConfig()

    # ------------------------------------------------------------------
    def _candidate_scores(self, token, candidate):
        """Per-algorithm similarity scores for one candidate."""
        return {
            algorithm: similarity(token, candidate, algorithm)
            for algorithm in self.config.algorithms
        }

    def _best_candidate(self, token):
        """Best vocabulary term for ``token`` (no gating yet).

        Near-ties (within ``tie_epsilon``) are resolved by plural agreement
        with the token, then by preferring plain terms over underscored
        column names, then shorter strings ('sail' -> 'sale', not
        'sale_id'; 'oders' -> 'orders', not 'order').

        Returns (term, score, second_score, per_algorithm_scores) where
        ``second_score`` is the highest score of any other candidate.
        """
        scored = []
        for candidate in self.vocabulary.candidates:
            scores = self._candidate_scores(token, candidate)
            score = max(scores.values()) if scores else 0.0
            if score > 0.0:
                scored.append((score, candidate, scores))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not scored:
            return None, 0.0, 0.0, {}

        epsilon = self.config.tie_epsilon
        tied = [item for item in scored if item[0] >= scored[0][0] - epsilon]
        if len(tied) > 1:
            token_plural = token.endswith("s") and len(token) > 3
            tied.sort(
                key=lambda item: (
                    ((item[1].endswith("s") and len(item[1]) > 3) != token_plural),
                    "_" in item[1],
                    len(item[1]),
                )
            )
        best_score, best_term, best_scores = tied[0]
        second_score = max(
            (score for score, candidate, _ in scored if candidate != best_term),
            default=0.0,
        )
        return best_term, best_score, second_score, best_scores

    def _related_candidates(self, token):
        """All phonetically matching candidates, sorted by score desc.

        Candidates are (score, term) pairs; scores below
        ``phonetic_min_score`` are kept so ambiguity can still be judged,
        but only candidates above the minimum are ever selected.
        """
        out = []
        for term in self.vocabulary.candidates:
            if not phonetic_matches(token, term, self.config.phonetic_algorithm):
                continue
            score = max(
                similarity(token, term, algorithm)
                for algorithm in self.config.algorithms
            )
            out.append((score, term))
        out.sort(reverse=True)
        return out

    @staticmethod
    def _phonetically_related(a, b):
        """True when two tokens share a phonetic encoding (any key length).

        Used to decide whether a similarity-best candidate is a real match
        or a coincidental orthographic overlap ('rejun' is related to
        'region', unrelated to 'revenue'; 'sail' is related to 'sale').
        """
        key_a, key_b = phonetic_key(a), phonetic_key(b)
        if not key_a or not key_b:
            return False
        return key_a == key_b or key_a.startswith(key_b) or key_b.startswith(key_a)

    def _decide_token(self, token):
        """Decide the fate of one examined token.

        Returns (corrected_term_or_token, correction_or_None, decision)
        where ``decision`` records original/replacement/confidence/applied/
        strategy/reason/scores even when nothing was corrected.
        """
        term, score, second_score, best_scores = self._best_candidate(token)
        related = self._related_candidates(token)
        phonetic_term = None
        phonetic_score = 0.0
        phonetic_scores = {}
        if related and related[0][0] >= self.config.phonetic_min_score:
            phonetic_score, phonetic_term = related[0]
            phonetic_scores = self._candidate_scores(token, phonetic_term)
        related_second = related[1][0] if len(related) > 1 else 0.0

        via_phonetic = False
        if (
            term is not None
            and phonetic_term is not None
            and phonetic_term != term
            and not self._phonetically_related(token, term)
            and phonetic_score >= self.config.phonetic_min_score
            and score - phonetic_score < 0.2
        ):
            term, score = phonetic_term, phonetic_score
            best_scores = phonetic_scores
            via_phonetic = True

        if term is None:
            decision = TokenDecision(token, token, 0.0, False, "none", "not_found")
            return token, None, decision
        if term == token:
            decision = TokenDecision(token, token, 1.0, False, "none", "exact_match")
            return token, None, decision

        term_related = self._phonetically_related(token, term)
        margin_base = related_second if term_related else second_score

        accepted = False
        strategy, reason = "similarity", None
        if score >= self.config.high_confidence:
            accepted, reason = True, "high_confidence"
        elif via_phonetic and score >= self.config.phonetic_min_score:
            accepted, strategy, reason = True, "phonetic", "phonetic"
        elif score >= self.config.threshold and score - margin_base >= self.config.margin:
            accepted, reason = True, "margin"
        elif via_phonetic:
            strategy, reason = "phonetic", "phonetic_below_min"
        elif score >= self.config.threshold:
            reason = "ambiguous"
        else:
            reason = "below_threshold"

        rounded_scores = {
            algorithm: round(value, 4) for algorithm, value in best_scores.items()
        }
        decision = TokenDecision(
            original=token,
            replacement=term if accepted else token,
            confidence=round(score, 4),
            applied=accepted,
            strategy=strategy,
            reason=reason,
            scores=rounded_scores,
            candidate=term,
        )
        if not accepted:
            return token, None, decision

        vocab_term = self.vocabulary.lookup(term)
        correction = Correction(
            token=token,
            corrected=term,
            kind=vocab_term.kind if vocab_term else "word",
            parent=vocab_term.parent if vocab_term else None,
            score=round(score, 4),
            algorithm=strategy,
            reason=reason,
            scores=rounded_scores,
        )
        return term, correction, decision

    # ------------------------------------------------------------------
    def _merge_multiword(self, tokens):
        """Merge consecutive tokens spelling a column into the canonical name.

        Comparison uses cleaned (lowercase, alphanumeric) forms; the merged
        result keeps the canonical column string.
        """
        spans = self.vocabulary.multiword_spans
        if not spans:
            return tokens
        merged = []
        i = 0
        while i < len(tokens):
            replaced = False
            for canonical, words in spans:
                window = tokens[i : i + len(words)]
                if tuple(clean_token(t) for t in window) == words:
                    merged.append(canonical)
                    i += len(words)
                    replaced = True
                    break
            if not replaced:
                merged.append(tokens[i])
                i += 1
        return merged

    def correct(self, text):
        """Normalize ``text`` against the vocabulary; returns a result.

        Every examined (candidate-eligible) token produces a
        ``TokenDecision`` record — including tokens left unchanged, with
        the reason (exact match, below threshold, ambiguous, not found).
        """
        raw_tokens = TOKEN_PATTERN.findall(text)
        corrected_tokens = []
        corrections = []
        decisions = []
        for raw in raw_tokens:
            token = clean_token(raw)
            prefix = raw[: len(raw) - len(raw.lstrip("'\"("))]
            suffix = raw[len(raw.rstrip(".,;:!?\"')")) :]
            if (
                not token
                or is_number(token)
                or len(token) < self.config.min_token_len
                or token in STOPWORDS
            ):
                corrected_tokens.append(raw)
                continue
            term, correction, decision = self._decide_token(token)
            decisions.append(decision)
            if correction:
                corrected_tokens.append(prefix + correction.corrected + suffix)
                corrections.append(correction)
            else:
                corrected_tokens.append(raw)

        if self.config.merge_multiword:
            merged_tokens = self._merge_multiword(corrected_tokens)
            if merged_tokens != corrected_tokens:
                corrections.append(
                    Correction(
                        token=" ".join(clean_token(t) for t in corrected_tokens),
                        corrected=" ".join(merged_tokens),
                        kind="column",
                        algorithm="merge",
                        reason="merge",
                    )
                )
                corrected_tokens = merged_tokens

        return NormalizationResult(
            text=" ".join(corrected_tokens),
            corrections=corrections,
            decisions=decisions,
        )
