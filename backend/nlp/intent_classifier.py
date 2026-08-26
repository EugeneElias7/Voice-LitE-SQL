"""Voice-LitE-SQL -- Level 8.1: Query Intent Classification.

Lightweight deterministic intent classification using lexical patterns,
question structure, and schema matches. No external LLM required.
"""

from dataclasses import dataclass
from enum import Enum
import re


class QueryIntent(Enum):
    """High-level query intent categories."""
    SELECT = "SELECT"
    WHERE = "WHERE"
    JOIN = "JOIN"
    GROUP_BY = "GROUP_BY"
    ORDER_BY = "ORDER_BY"
    AGGREGATE = "AGGREGATE"
    COMPLEX = "COMPLEX"


@dataclass(frozen=True)
class IntentResult:
    """Result of intent classification."""
    primary_intent: QueryIntent
    join_required: bool
    aggregation_required: bool
    grouping_required: bool
    ordering_required: bool
    subquery_likely: bool
    confidence: float


# Lexical patterns for intent detection
SELECT_PATTERNS = [
    r"\b(list|show|display|get|find)\b",
    r"\b(all)\b",
]

WHERE_PATTERNS = [
    r"\b(which|what|where)\b.*\b(is|are|was|were|has|have)\b",
    r"\b(filter|where)\b",
    r"\b(more than|less than|greater than|fewer than|over|under|above|below)\b",
    r"\b(equal to|equals|==)\b",
    r"\b(from|in|at)\b",
]

JOIN_PATTERNS = [
    r"\b(with|along with|together with)\b",
    r"\b(each|every)\b.*\b(and|with)\b",
    r"\b(and|with)\b.*\b(name|title|id)\b",
    r"\b(each)\b.*\b(sale|order|employee|customer|product)\b.*\b(with|and)\b",
]

GROUP_BY_PATTERNS = [
    r"\b(per)\b",
    r"\b(each)\b.*\b(department|category|city|region|employee|product|customer)\b",
    r"\b(group|grouped)\b",
    r"\b(how many|count of|number of)\b.*\b(per|each|by)\b",
]

ORDER_BY_PATTERNS = [
    r"\b(sort|order|rank)\b",
    r"\b(sorted|ordered)\b.*\b(by)\b",
    r"\b(highest|lowest|top|bottom|most|least)\b.*\b(to|first|last)\b",
    r"\b(ascending|descending|alphabetical|chronological)\b",
    r"\b(first|last|latest|earliest|recent)\b",
    r"\blimit\b",
]

AGGREGATE_PATTERNS = [
    r"\b(average|mean|avg)\b",
    r"\b(sum|total)\b",
    r"\b(count|how many)\b",
    r"\b(max|maximum)\b",
    r"\b(min|minimum)\b",
    # "highest/lowest/most/least" removed - they're in ORDER_BY
]

COMPLEX_PATTERNS = [
    r"\b(highest|lowest)\b.*\b(average|avg)\b",
    r"\b(more than|less than)\b.*\b(average|avg)\b",
    r"\b(having|with)\b.*\b(more than|less than|over|under)\b",
    r"\b(which|what)\b.*\b(highest|lowest|most|least)\b",
    r"\b(never|not).*\b(placed|made|ordered)\b",
]


def _has_pattern(text, patterns):
    """Check if any pattern matches the text."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _count_pattern_matches(text, patterns):
    """Count how many patterns match."""
    text_lower = text.lower()
    return sum(1 for p in patterns if re.search(p, text_lower))


def _detect_subquery_likely(text):
    """Detect if subquery is likely needed."""
    text_lower = text.lower()
    subquery_indicators = [
        r"more than.*average",
        r"less than.*average",
        r"higher than.*average",
        r"lower than.*average",
        r"above.*average",
        r"below.*average",
        r"(highest|lowest).*average",
        r"never.*(placed|made|ordered)",
        r"not.*(in|exists)",
    ]
    return any(re.search(p, text_lower) for p in subquery_indicators)


def classify_intent(question, schema_tables=None):
    """Classify the intent of a natural language question.

    Parameters
    ----------
    question : str
        The natural language question.
    schema_tables : list[str] | None
        Optional list of available table names for schema-aware classification.

    Returns
    -------
    IntentResult
        Structured intent classification result.
    """
    text = question.strip()

    # Count pattern matches for each intent
    select_score = _count_pattern_matches(text, SELECT_PATTERNS)
    where_score = _count_pattern_matches(text, WHERE_PATTERNS)
    join_score = _count_pattern_matches(text, JOIN_PATTERNS)
    group_score = _count_pattern_matches(text, GROUP_BY_PATTERNS)
    order_score = _count_pattern_matches(text, ORDER_BY_PATTERNS)
    agg_score = _count_pattern_matches(text, AGGREGATE_PATTERNS)
    complex_score = _count_pattern_matches(text, COMPLEX_PATTERNS)

    # Determine primary intent
    scores = {
        QueryIntent.SELECT: select_score,
        QueryIntent.WHERE: where_score,
        QueryIntent.JOIN: join_score,
        QueryIntent.GROUP_BY: group_score,
        QueryIntent.ORDER_BY: order_score,
        QueryIntent.AGGREGATE: agg_score,
        QueryIntent.COMPLEX: complex_score * 2,  # Weight complex higher
    }

    # Special case: if complex patterns match, boost COMPLEX
    if complex_score > 0:
        primary = QueryIntent.COMPLEX
    elif order_score > 0 and order_score >= agg_score:
        primary = QueryIntent.ORDER_BY
    elif agg_score > 0:
        primary = QueryIntent.AGGREGATE
    elif join_score > 0 and join_score >= group_score:
        primary = QueryIntent.JOIN
    elif group_score > 0:
        primary = QueryIntent.GROUP_BY
    elif where_score > 0:
        primary = QueryIntent.WHERE
    else:
        primary = QueryIntent.SELECT

    # Determine feature flags
    join_required = join_score > 0 or primary in (QueryIntent.JOIN, QueryIntent.GROUP_BY, QueryIntent.COMPLEX)
    aggregation_required = agg_score > 0 or primary in (QueryIntent.AGGREGATE, QueryIntent.GROUP_BY, QueryIntent.COMPLEX)
    grouping_required = group_score > 0 or primary in (QueryIntent.GROUP_BY, QueryIntent.COMPLEX)
    ordering_required = order_score > 0 or primary in (QueryIntent.ORDER_BY, QueryIntent.COMPLEX)
    subquery_likely = _detect_subquery_likely(text)

    # Confidence based on pattern match strength
    total_matches = sum(scores.values())
    max_score = max(scores.values()) if scores else 0
    confidence = min(1.0, max_score / max(1, total_matches)) if total_matches > 0 else 0.5

    return IntentResult(
        primary_intent=primary,
        join_required=join_required,
        aggregation_required=aggregation_required,
        grouping_required=grouping_required,
        ordering_required=ordering_required,
        subquery_likely=subquery_likely,
        confidence=round(confidence, 3),
    )