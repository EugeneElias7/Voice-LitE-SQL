"""Voice-LitE-SQL -- Level 6 verification: database-aware phonetic normalization.

Every assertion below documents a behavior verified during the L6 build;
the dataset expectations (18 recovered targets of 20, 3 drifted clean
texts) are the measured results of the default configuration, asserted
rather than manufactured.
"""

import json
from pathlib import Path

import pytest

from backend.database.executor import execute_sql
from backend.evaluation.evaluator import results_equal
from backend.llm import sql_generator
from backend.llm.sql_generator import generate_sql
from backend.phonetics import (
    DatabaseAwareNormalizer,
    DatabaseVocabulary,
    NormalizerConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "backend" / "datasets" / "custom" / "schema.json"
CORRUPTED_PATH = PROJECT_ROOT / "backend" / "datasets" / "custom" / "corrupted_queries.json"
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"


@pytest.fixture(scope="module")
def vocabulary():
    return DatabaseVocabulary.from_schema_json(SCHEMA_PATH)


@pytest.fixture(scope="module")
def normalizer(vocabulary):
    return DatabaseAwareNormalizer(vocabulary)


def correction_map(result):
    return {c.token: c for c in result.corrections if c.algorithm != "merge"}


# -- algorithms ---------------------------------------------------------------

def test_soundex_fixtures():
    from backend.phonetics.algorithms import phonetic_key

    assert phonetic_key("Robert", "soundex") == "R163"
    assert phonetic_key("Rupert", "soundex") == "R163"
    assert phonetic_key("Ashcraft", "soundex") == "A261"
    assert phonetic_key("Tymczak", "soundex") == "T522"


def test_metaphone_fixtures():
    from backend.phonetics.algorithms import phonetic_key

    assert phonetic_key("Broughton", "metaphone") == "BRTN"
    assert phonetic_key("Smith", "metaphone") == "SM0"
    assert phonetic_key("celery", "metaphone") == phonetic_key("salary", "metaphone")


def test_nysiis_fixtures():
    from backend.phonetics.algorithms import phonetic_key

    assert phonetic_key("MacCaffrey", "nysiis") == "MCAFRY"


def test_jaro_winkler_fixture():
    from backend.phonetics.algorithms import similarity

    assert similarity("MARTHA", "MARHTA", "jaro_winkler") == pytest.approx(0.961, abs=0.005)


def test_similarity_exact_and_algorithms():
    from backend.phonetics.algorithms import ALGORITHMS, similarity

    for algorithm in ALGORITHMS:
        assert similarity("sales", "sales", algorithm) == 1.0
    assert similarity("sales", "sails", "jaro_winkler") > 0.8
    assert similarity("sale", "sale_id", "jaro_winkler") < 1.0


def test_clean_token_and_number():
    from backend.phonetics.algorithms import clean_token, is_number

    assert clean_token("Sails!") == "sails"
    assert clean_token("sale_date") == "saledate"  # underscores are stripped
    assert is_number("2500")
    assert is_number("1,250.50")
    assert not is_number("sales")
    assert not is_number("")


def test_phonetic_matches():
    from backend.phonetics.algorithms import phonetic_matches

    assert phonetic_matches("celery", "salary")
    assert phonetic_matches("rejun", "region")
    assert phonetic_matches("hired", "hire")
    assert not phonetic_matches("celery", "category")
    assert phonetic_matches("sold", "sale")  # SLT vs SL: prefix counts, 'sold' is sale-related


# -- vocabulary ---------------------------------------------------------------

def test_vocabulary_tables_columns_words(vocabulary):
    terms = {t.term: t for t in vocabulary.terms}
    assert terms["sales"].kind == "table"
    assert terms["salary"].kind == "column"
    assert terms["quantity"].kind == "column"
    assert terms["sale"].kind == "word"
    assert terms["hire"].kind == "word"
    assert terms["hire"].parent == "hire_date"


def test_vocabulary_ambiguous_word_has_no_parent(vocabulary):
    assert vocabulary.lookup("name").parent is None
    assert vocabulary.lookup("customer").parent is None
    assert vocabulary.lookup("sale").parent is None
    assert vocabulary.lookup("date").parent is None


def test_vocabulary_multiword_spans(vocabulary):
    spans = dict(vocabulary.multiword_spans)
    assert spans["sale_date"] == ("sale", "date")
    assert spans["customer_name"] == ("customer", "name")
    assert spans["order_total"] == ("order", "total")


def test_vocabulary_all_corrupted_targets_grounded():
    vocabulary = DatabaseVocabulary.from_schema_json(SCHEMA_PATH)
    pairs = json.loads(CORRUPTED_PATH.read_text(encoding="utf-8"))
    for pair in pairs:
        target = pair["target"]
        words = target.split("_")
        assert all(
            vocabulary.lookup(word) is not None or word in vocabulary.candidates
            for word in words
        ), f"target {target} not in vocabulary"


# -- normalizer: recovered dataset targets ------------------------------------

RECOVERED_CASES = [
    ("Show total sails revenue", "Show total sales revenue", "sales"),
    ("Show employee celery", "Show employee salary", "salary"),
    ("What is the total avenue?", "What is the total revenue?", "revenue"),
    ("List all employe", "List all employee", "employee"),
    ("Which departmint is largest?", "Which department is largest?", "department"),
    ("How many products are in each catagory?", "How many products are in each category?", "category"),
    ("List all custumers", "List all customers", "customers"),
    ("What is the total quanity sold?", "What is the total quantity sold?", "quantity"),
    ("Which locashun has the most sales?", "Which location has the most sales?", "location"),
    ("Show sales by sail date", "Show sales by sale_date", "sale_date"),
    ("List all produsts", "List all products", "products"),
    ("List all oders", "List all orders", "orders"),
    ("Show the average budjet per department", "Show the average budget per department", "budget"),
    ("What is the prises of this product?", "What is the price of this product?", "price"),
    ("Which rejun has the most locations?", "Which region has the most locations?", "region"),
    ("Which sity has the most customers?", "Which city has the most customers?", "city"),
    ("What is the stasus of this order?", "What is the status of this order?", "status"),
    ("When were employees higher?", "When were employees hire?", "hire_date"),
    ("List all custumer names", "List all customer_name", "customer_name"),
]


def test_recovered_dataset_targets(normalizer):
    for corrupted, expected_text, expected_target in RECOVERED_CASES:
        result = normalizer.correct(corrupted)
        assert result.text == expected_text, f"{corrupted!r} -> {result.text!r}"
        schema_terms = {c.schema_term for c in result.corrections}
        assert expected_target in result.text.split() or expected_target in schema_terms, (
            f"target {expected_target!r} not recovered from {corrupted!r}"
        )


def test_valyu_not_fabricated(normalizer):
    result = normalizer.correct("What was the total order valyu?")
    assert result.text == "What was the total order valyu?"
    assert result.corrections == []


# -- normalizer: safety / negative controls -----------------------------------

def test_numbers_and_stopwords_untouched(normalizer):
    result = normalizer.correct("Show the total 2500 items in each category")
    assert "2500" in result.text
    for token in ("the", "in", "each"):
        assert token in result.text


def test_unknown_word_untouched(normalizer):
    result = normalizer.correct("Show me the supercalifragilistic report")
    assert "supercalifragilistic" in result.text
    assert result.corrections == []


def test_normal_language_preserved(normalizer):
    """'New York' must not be rewritten to any schema token."""
    result = normalizer.correct("List all customers in New York")
    assert result.text == "List all customers in New York"
    assert result.corrections == []
    for token in ("new", "york"):
        decision = next(d for d in result.decisions if d.original == token)
        assert not decision.applied
        assert decision.replacement == token


def test_table_names_are_candidates(normalizer):
    result = normalizer.correct("List all oders")
    correction = next(c for c in result.corrections if c.token == "oders")
    assert correction.corrected == "orders"
    assert correction.kind == "table"


def test_column_names_are_candidates(normalizer):
    result = normalizer.correct("Show employee celery")
    correction = next(c for c in result.corrections if c.token == "celery")
    assert correction.corrected == "salary"
    assert correction.kind == "column"


def test_multiple_corrections_in_one_sentence(normalizer):
    result = normalizer.correct("Show sails and oders by sity")
    assert result.text == "Show sales and orders by city"
    applied = [c for c in result.corrections if c.algorithm != "merge"]
    assert {c.token for c in applied} == {"sails", "oders", "sity"}


def test_deterministic_results(normalizer):
    text = "Show total sails revenue and employee celery"
    first = normalizer.correct(text)
    second = normalizer.correct(text)
    assert first.text == second.text
    assert [d.__dict__ for d in first.decisions] == [d.__dict__ for d in second.decisions]


# -- correction records -------------------------------------------------------

def test_correction_record_shape(normalizer):
    result = normalizer.correct("Show total sails revenue")
    decision = next(d for d in result.decisions if d.original == "sails")
    assert decision.replacement == "sales"
    assert decision.applied is True
    assert decision.strategy == "similarity"
    assert decision.confidence >= 0.85
    assert decision.candidate == "sales"
    assert set(decision.scores) == {"jaro_winkler", "levenshtein_ratio"}
    assert 0.0 <= decision.scores["jaro_winkler"] <= 1.0

    correction = next(c for c in result.corrections if c.token == "sails")
    assert correction.reason == "high_confidence"
    assert correction.scores == decision.scores


def test_rejected_token_recorded(normalizer):
    result = normalizer.correct("What was the total order valyu?")
    decision = next(d for d in result.decisions if d.original == "valyu")
    assert not decision.applied
    assert decision.replacement == "valyu"
    assert decision.reason == "below_threshold"
    assert decision.candidate is not None
    assert decision.candidate != decision.replacement


def test_exact_match_decision_recorded(normalizer):
    result = normalizer.correct("Show total sales revenue")
    decision = next(d for d in result.decisions if d.original == "sales")
    assert decision.reason == "exact_match"
    assert not decision.applied
    assert decision.confidence == 1.0


# -- configuration reproducibility --------------------------------------------

def test_configuration_is_frozen_and_reproducible(normalizer):
    frozen = NormalizerConfig()
    assert frozen.threshold == 0.75
    assert frozen.margin == 0.12
    assert frozen.high_confidence == 0.85
    assert frozen.min_token_len == 3
    assert frozen.tie_epsilon == 0.04
    assert frozen.algorithms == ("jaro_winkler", "levenshtein_ratio")
    assert frozen.phonetic_algorithm == "metaphone"
    assert frozen.phonetic_min_score == 0.55
    assert frozen.merge_multiword is True

    text = "Show total sails revenue and employee celery"
    first = normalizer.correct(text)
    second = DatabaseAwareNormalizer(normalizer.vocabulary).correct(text)
    assert first.text == second.text
    assert [d.__dict__ for d in first.decisions] == [d.__dict__ for d in second.decisions]


# -- arbitrary SQLite databases (L2 Schema Inspector) -------------------------

def test_arbitrary_sqlite_database_vocabulary(tmp_path):
    import sqlite3

    db = tmp_path / "books.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE books (book_id INTEGER, author_name TEXT, publish_year INTEGER)")
    conn.commit()
    conn.close()

    vocabulary = DatabaseVocabulary.from_database(db)
    terms = {t.term for t in vocabulary.terms}
    assert {"books", "author_name", "publish_year", "author", "name"} <= terms

    normalizer = DatabaseAwareNormalizer(vocabulary)
    result = normalizer.correct("List books by athor name")
    assert result.text == "List books by author_name"
    decision = next(d for d in result.decisions if d.original == "athor")
    assert decision.applied and decision.replacement == "author"


def test_enterprise_vocabulary_from_schema_inspector():
    from_database = DatabaseVocabulary.from_database(DB_PATH)
    from_json = DatabaseVocabulary.from_schema_json(SCHEMA_PATH)
    assert {t.term for t in from_database.terms} == {t.term for t in from_json.terms}
    assert {t.term for t in from_database.terms} >= {
        "sales", "salary", "sale_date", "customer_name", "order_total", "hire_date",
    }


# -- --no-phonetic ablation ---------------------------------------------------

def load_l5_asr_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "l5_asr", PROJECT_ROOT / "scripts" / "l5_asr.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_phonetic_ablation_flag():
    module = load_l5_asr_module()
    assert module.make_normalizer(no_phonetic=True, db_path=str(DB_PATH)) is None
    normalizer = module.make_normalizer(no_phonetic=False, db_path=str(DB_PATH))
    assert normalizer is not None
    assert normalizer.correct("Show employee celery").text == "Show employee salary"


def test_ambiguous_candidates_are_conservative(normalizer):
    """'sold' has close schema candidates (sale_id/sale_date) but no clear
    winner: it must be left unchanged and recorded as ambiguous."""
    result = normalizer.correct("What is the total quantity sold?")
    decision = next(d for d in result.decisions if d.original == "sold")
    assert not decision.applied
    assert decision.replacement == "sold"
    assert decision.reason == "ambiguous"
    assert decision.candidate == "sale_id"


def test_clean_schema_terms_unchanged(normalizer):
    result = normalizer.correct("List all customers by city and region")
    assert result.text == "List all customers by city and region"
    assert result.corrections == []


def test_exact_matches_never_reported_as_corrections(normalizer):
    result = normalizer.correct("Show total sales revenue")
    assert result.text == "Show total sales revenue"
    assert result.corrections == []


# -- normalizer: multi-word merge and correction report -----------------------

def test_merge_pass_creates_column(normalizer):
    result = normalizer.correct("Show sales by sail date")
    assert "sale_date" in result.text
    assert result.text == "Show sales by sale_date"
    merges = [c for c in result.corrections if c.algorithm == "merge"]
    assert len(merges) == 1
    assert merges[0].corrected == "Show sales by sale_date"


def test_correction_report_fields(normalizer):
    result = normalizer.correct("Show employee celery")
    celery = correction_map(result)["celery"]
    assert celery.corrected == "salary"
    assert celery.kind == "column"
    assert celery.algorithm == "phonetic"
    assert 0.5 <= celery.score <= 0.8
    assert result.text == "Show employee salary"


def test_phonetic_algorithm_field(normalizer):
    result = normalizer.correct("Show employee celery")
    assert any(c.algorithm == "phonetic" for c in result.corrections)


def test_punctuation_and_case_preserved(normalizer):
    result = normalizer.correct("What is the total avenue?")
    assert result.text == "What is the total revenue?"
    assert result.text.endswith("?")


# -- measured dataset behavior (regression pin) -------------------------------

def test_dataset_recovery_counts(normalizer):
    pairs = json.loads(CORRUPTED_PATH.read_text(encoding="utf-8"))
    strict = equivalent = grounded = 0
    for pair in pairs:
        result = normalizer.correct(pair["corrupted"])
        corrected_strings = {c.corrected for c in result.corrections}
        schema_terms = {c.schema_term for c in result.corrections}
        target = pair["target"]
        if target in result.text.split() or target in corrected_strings:
            strict += 1
            equivalent += 1
            grounded += 1
            continue
        if any(
            (c.endswith("s") and c[:-1] == (target[:-1] if target.endswith("s") else target))
            or (target.endswith("s") and c == target[:-1])
            for c in corrected_strings
        ) or any(s == target for s in schema_terms):
            equivalent += 1
            if any(s == target for s in schema_terms):
                grounded += 1
    assert strict == 17
    assert equivalent == 19
    assert grounded == 18


def test_dataset_drift_counts(normalizer):
    pairs = json.loads(CORRUPTED_PATH.read_text(encoding="utf-8"))
    drift = 0
    for pair in pairs:
        if normalizer.correct(pair["original"]).corrections:
            drift += 1
    assert drift == 3


def test_drift_is_schema_grounding_only(normalizer):
    pairs = json.loads(CORRUPTED_PATH.read_text(encoding="utf-8"))
    for pair in pairs:
        result = normalizer.correct(pair["original"])
        for correction in result.corrections:
            assert correction.algorithm in ("phonetic", "similarity", "merge")
            if correction.algorithm == "merge":
                assert "_" in correction.corrected


# -- downstream pipeline (mocked LLM, real executor) --------------------------

def test_downstream_normalized_text_reaches_llm(tmp_path, monkeypatch, normalizer):
    q26 = json.loads(
        (PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json").read_text(encoding="utf-8")
    )
    item = next(q for q in q26 if q["id"] == "q26")

    seen = {}

    def fake_generate(prompt, model=None, host=None, timeout=None):
        seen["prompt"] = prompt
        return (item["sql"], {})

    monkeypatch.setattr(sql_generator, "generate", fake_generate)
    corrupted = "What is the total quanity sold?"
    normalized = normalizer.correct(corrupted).text
    generated = generate_sql(normalized, DB_PATH)
    assert generated.success
    assert "quantity" in seen["prompt"]

    reference = execute_sql(item["sql"], DB_PATH)
    executed = execute_sql(generated.generated_sql, DB_PATH)
    assert results_equal(item["sql"], reference, generated.generated_sql, executed)


def test_no_cloud_dependency():
    for filename in ("algorithms.py", "vocabulary.py", "normalizer.py", "__init__.py"):
        source = (PROJECT_ROOT / "backend" / "phonetics" / filename).read_text(encoding="utf-8").lower()
        assert "import requests" not in source
        assert "urllib" not in source
        assert "api.openai" not in source
