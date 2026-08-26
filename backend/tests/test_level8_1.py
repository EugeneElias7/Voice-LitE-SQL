"""Voice-LitE-SQL -- Level 8.1: Tests for NLP + Schema-Linking components."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.nlp.intent_classifier import classify_intent, QueryIntent
from backend.nlp.schema_linker import link_schema_entities, SchemaLinker
from backend.nlp.phrase_matcher import match_phrases, PhraseMatcher
from backend.retrieval.reranker import RerankWeights, rerank_retrieval
from backend.retrieval.relationship_filter import filter_relationships, RelationshipFilter
from backend.validation.sql_structure_validator import validate_sql_structure
from backend.database.schema_inspector import inspect_database


DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"


def test_intent_classifier():
    """Test query intent classification."""
    print("Testing intent classifier...")

    # Simple SELECT
    result = classify_intent("List all product names.")
    assert result.primary_intent == QueryIntent.SELECT
    assert not result.join_required
    print(f"  SELECT: {result.primary_intent.value}, join={result.join_required}")

    # WHERE
    result = classify_intent("Which employees earn more than 100000?")
    assert result.primary_intent == QueryIntent.WHERE
    print(f"  WHERE: {result.primary_intent.value}")

    # JOIN
    result = classify_intent("Show each sale with the product name sold.")
    assert result.primary_intent == QueryIntent.JOIN
    assert result.join_required
    print(f"  JOIN: {result.primary_intent.value}, join={result.join_required}")

    # GROUP BY
    result = classify_intent("How many employees work in each department?")
    assert result.primary_intent in (QueryIntent.GROUP_BY, QueryIntent.AGGREGATE)
    assert result.grouping_required
    print(f"  GROUP BY: {result.primary_intent.value}, grouping={result.grouping_required}")

    # ORDER BY
    result = classify_intent("List employees sorted by salary from highest to lowest.")
    assert result.primary_intent == QueryIntent.ORDER_BY
    assert result.ordering_required
    print(f"  ORDER BY: {result.primary_intent.value}, ordering={result.ordering_required}")

    # AGGREGATE
    result = classify_intent("What is the average salary of employees?")
    assert result.primary_intent == QueryIntent.AGGREGATE
    assert result.aggregation_required
    print(f"  AGGREGATE: {result.primary_intent.value}, agg={result.aggregation_required}")

    # COMPLEX
    result = classify_intent("Which department has the highest average salary?")
    assert result.primary_intent == QueryIntent.COMPLEX
    assert result.aggregation_required
    assert result.grouping_required
    assert result.subquery_likely
    print(f"  COMPLEX: {result.primary_intent.value}, subquery={result.subquery_likely}")

    # Subquery detection
    result = classify_intent("Which employees earn more than the average salary?")
    assert result.subquery_likely
    print(f"  Subquery detection: {result.subquery_likely}")

    print("  All intent classifier tests passed!")


def test_schema_linker():
    """Test schema/entity linking."""
    print("Testing schema linker...")

    linker = SchemaLinker(str(DB_PATH))

    # Table linking
    tables = linker.link_tables("List all employee names.")
    assert any(t.table == "employees" for t in tables)
    print(f"  Table linking: {[t.table for t in tables]}")

    # Column linking
    columns = linker.link_columns("Which employees have salary more than 100000?", candidate_tables=["employees"])
    assert any(c.table == "employees" and c.column == "salary" for c in columns)
    print(f"  Column linking: {[(c.table, c.column) for c in columns]}")

    # Phrase variations
    tables = linker.link_tables("Show me the departments.")
    assert any(t.table == "departments" for t in tables)
    print(f"  Plural handling: {[t.table for t in tables]}")

    # Fuzzy matching
    tables = linker.link_tables("List all employe names.")  # typo
    print(f"  Fuzzy matching: {[t.table for t in tables]}")

    # Full linking
    all_entities = linker.link_all("Show each sale with the product name sold.")
    print(f"  Full linking: {[(e.entity_type, e.table, e.column) for e in all_entities]}")

    print("  All schema linker tests passed!")


def test_phrase_matcher():
    """Test phrase/n-gram matching."""
    print("Testing phrase matcher...")

    matcher = PhraseMatcher(str(DB_PATH))

    # Multi-word column matching
    matches = matcher.match_phrases("List all employee names.")
    col_matches = [m for m in matches if m.entity_type == "column"]
    assert any(m.column == "employee_name" for m in col_matches)
    print(f"  Phrase 'employee names' -> column: {[(m.table, m.column) for m in col_matches]}")

    # Concept phrases
    matches = matcher.match_phrases("What is the average salary?")
    concept_matches = [m for m in matches if m.entity_type == "concept"]
    assert any("aggregation" in m.concept for m in concept_matches)
    print(f"  Concept 'average' -> {[(m.concept) for m in concept_matches]}")

    # GROUP BY concept
    matches = matcher.match_phrases("How many employees per department?")
    concept_matches = [m for m in matches if m.entity_type == "concept"]
    assert any("grouping" in m.concept for m in concept_matches)
    print(f"  Concept 'per' -> {[(m.concept) for m in concept_matches]}")

    print("  All phrase matcher tests passed!")


def test_reranker():
    """Test candidate reranking."""
    print("Testing reranker...")

    # This test requires a retriever, so we'll test the scoring logic directly
    from backend.retrieval.schema_retriever import RetrievedItem, RetrievalResult
    from backend.nlp.intent_classifier import IntentResult, QueryIntent
    from backend.nlp.schema_linker import LinkedEntity
    from backend.nlp.phrase_matcher import PhraseMatch

    # Create mock retrieval items
    items = [
        RetrievedItem("column", "col:employees.employee_name", "employees", "employee_name",
                      text="COLUMN: employees.employee_name", score=0.5, distance=0.5),
        RetrievedItem("column", "col:products.product_name", "products", "product_name",
                      text="COLUMN: products.product_name", score=0.4, distance=0.6),
        RetrievedItem("relationship", "rel:sales->products", "sales", "product_id",
                      fk_source_table="sales", fk_source_column="product_id",
                      fk_target_table="products", fk_target_column="product_id",
                      text="RELATIONSHIP", score=0.3, distance=0.7),
    ]
    retrieval = RetrievalResult("List all product names.", 5, items, "")

    intent = IntentResult(QueryIntent.SELECT, False, False, False, False, False, 0.9)
    linked = [LinkedEntity("table", "products", match_type="exact", confidence=1.0)]
    phrases = [PhraseMatch("product names", "column", "products", "product_name", "exact", 1.0)]

    weights = RerankWeights()
    from backend.retrieval.reranker import Reranker
    reranker = Reranker(weights)
    result = reranker.rerank("List all product names.", retrieval, intent, linked, phrases)

    # Products should be ranked higher
    assert result.items[0].table == "products"
    print(f"  Reranked order: {[(item.table, item.column, item.score) for item in result.items]}")

    print("  All reranker tests passed!")


def test_relationship_filter():
    """Test relationship necessity filter."""
    print("Testing relationship filter...")

    filter_obj = RelationshipFilter(str(DB_PATH))

    from backend.retrieval.schema_retriever import RetrievedItem, RetrievalResult
    from backend.nlp.intent_classifier import IntentResult, QueryIntent
    from backend.nlp.schema_linker import LinkedEntity

    # Test case: "List all product names" - should NOT need JOIN
    items = [
        RetrievedItem("column", "col:products.product_name", "products", "product_name",
                      text="COLUMN: products.product_name", score=0.5, distance=0.5),
        RetrievedItem("relationship", "rel:sales->products", "sales", "product_id",
                      fk_source_table="sales", fk_source_column="product_id",
                      fk_target_table="products", fk_target_column="product_id",
                      text="RELATIONSHIP", score=0.3, distance=0.7),
    ]
    retrieval = RetrievalResult("List all product names.", 5, items, "")
    intent = IntentResult(QueryIntent.SELECT, False, False, False, False, False, 0.9)
    linked = [LinkedEntity("table", "products", match_type="exact", confidence=1.0),
              LinkedEntity("column", "products", "product_name", match_type="exact", confidence=1.0)]

    filtered, assessments = filter_obj.filter_relationships(
        "List all product names.", retrieval, intent, linked
    )

    # Relationship should be filtered out
    rel_items = [i for i in filtered.items if i.doc_type == "relationship"]
    assert len(rel_items) == 0
    print(f"  Simple SELECT: relationships kept = {len(rel_items)} (expected 0)")

    # Test case: "Show each sale with the product name sold" - SHOULD need JOIN
    items = [
        RetrievedItem("column", "col:sales.sale_id", "sales", "sale_id",
                      text="COLUMN: sales.sale_id", score=0.5, distance=0.5),
        RetrievedItem("column", "col:products.product_name", "products", "product_name",
                      text="COLUMN: products.product_name", score=0.5, distance=0.5),
        RetrievedItem("relationship", "rel:sales->products", "sales", "product_id",
                      fk_source_table="sales", fk_source_column="product_id",
                      fk_target_table="products", fk_target_column="product_id",
                      text="RELATIONSHIP", score=0.3, distance=0.7),
    ]
    retrieval = RetrievalResult("Show each sale with the product name sold.", 5, items, "")
    intent = IntentResult(QueryIntent.JOIN, True, False, False, False, False, 0.9)
    linked = [LinkedEntity("table", "sales", match_type="exact", confidence=1.0),
              LinkedEntity("table", "products", match_type="exact", confidence=1.0),
              LinkedEntity("column", "sales", "sale_id", match_type="exact", confidence=1.0),
              LinkedEntity("column", "products", "product_name", match_type="exact", confidence=1.0)]

    filtered, assessments = filter_obj.filter_relationships(
        "Show each sale with the product name sold.", retrieval, intent, linked
    )

    rel_items = [i for i in filtered.items if i.doc_type == "relationship"]
    assert len(rel_items) == 1
    print(f"  JOIN query: relationships kept = {len(rel_items)} (expected 1)")

    # Test case: "Which customers are from New York" - should NOT need sales JOIN
    items = [
        RetrievedItem("column", "col:customers.customer_name", "customers", "customer_name",
                      text="COLUMN: customers.customer_name", score=0.5, distance=0.5),
        RetrievedItem("column", "col:customers.city", "customers", "city",
                      text="COLUMN: customers.city", score=0.5, distance=0.5),
        RetrievedItem("relationship", "rel:sales->customers", "sales", "customer_id",
                      fk_source_table="sales", fk_source_column="customer_id",
                      fk_target_table="customers", fk_target_column="customer_id",
                      text="RELATIONSHIP", score=0.3, distance=0.7),
    ]
    retrieval = RetrievalResult("Which customers are from New York?", 5, items, "")
    intent = IntentResult(QueryIntent.WHERE, False, False, False, False, False, 0.9)
    linked = [LinkedEntity("table", "customers", match_type="exact", confidence=1.0),
              LinkedEntity("column", "customers", "city", match_type="exact", confidence=1.0),
              LinkedEntity("column", "customers", "customer_name", match_type="exact", confidence=1.0)]

    filtered, assessments = filter_obj.filter_relationships(
        "Which customers are from New York?", retrieval, intent, linked
    )

    rel_items = [i for i in filtered.items if i.doc_type == "relationship"]
    assert len(rel_items) == 0
    print(f"  WHERE single table: relationships kept = {len(rel_items)} (expected 0)")

    print("  All relationship filter tests passed!")


def test_sql_validator():
    """Test SQL structural validation."""
    print("Testing SQL validator...")

    # Valid simple SELECT
    result = validate_sql_structure(
        "SELECT product_name FROM products;",
        str(DB_PATH)
    )
    assert result.is_valid
    assert "products" in result.tables_used
    # Column may be bare or qualified
    assert any("product_name" in c for c in result.columns_used)
    print(f"  Valid SELECT: tables={result.tables_used}, joins={len(result.joins)}")

    # Valid JOIN
    result = validate_sql_structure(
        "SELECT s.sale_id, p.product_name FROM sales s JOIN products p ON s.product_id = p.product_id;",
        str(DB_PATH)
    )
    assert result.is_valid
    assert len(result.joins) == 1
    print(f"  Valid JOIN: tables={result.tables_used}, joins={len(result.joins)}")

    # Invalid table
    result = validate_sql_structure(
        "SELECT * FROM nonexistent;",
        str(DB_PATH)
    )
    assert not result.is_valid
    assert any(i.code == "UNKNOWN_TABLE" for i in result.issues)
    print(f"  Invalid table detected: {[i.code for i in result.issues]}")

    # Invalid column
    result = validate_sql_structure(
        "SELECT fake_column FROM products;",
        str(DB_PATH)
    )
    assert not result.is_valid
    assert any(i.code == "UNKNOWN_COLUMN" for i in result.issues)
    print(f"  Invalid column detected: {[i.code for i in result.issues]}")

    # Unnecessary JOIN detection with intent
    from backend.nlp.intent_classifier import classify_intent
    intent = classify_intent("List all product names.")
    result = validate_sql_structure(
        "SELECT p.product_name FROM products p JOIN sales s ON p.product_id = s.product_id;",
        str(DB_PATH),
        intent
    )
    assert any(i.code == "UNNECESSARY_JOIN" for i in result.issues)
    print(f"  Unnecessary JOIN warning: {[i.code for i in result.issues]}")

    print("  All SQL validator tests passed!")


def run_all_tests():
    """Run all L8.1 component tests."""
    print("=" * 60)
    print("L8.1 COMPONENT TESTS")
    print("=" * 60)

    test_intent_classifier()
    print()
    test_schema_linker()
    print()
    test_phrase_matcher()
    print()
    test_reranker()
    print()
    test_relationship_filter()
    print()
    test_sql_validator()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()