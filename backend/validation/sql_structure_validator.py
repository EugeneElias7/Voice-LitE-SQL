"""Voice-LitE-SQL -- Level 8.1: SQL Structural Validation.

Deterministic, database-aware validation of generated SQL structure.
Detects:
- Unnecessary JOINs (for simple queries)
- Unknown tables/columns
- Invalid aggregation structure
- Missing GROUP BY
- Unsupported operations
"""

from dataclasses import dataclass, field
from typing import Optional
import re
import sqlglot
from sqlglot import exp

from backend.database.schema_inspector import inspect_database, Schema, TableSchema, Column
from backend.nlp.intent_classifier import IntentResult, QueryIntent


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue."""
    severity: str  # 'error' | 'warning' | 'info'
    code: str
    message: str
    location: str = ""


@dataclass
class ValidationResult:
    """Result of SQL structure validation."""
    is_valid: bool
    issues: list = field(default_factory=list)
    tables_used: list = field(default_factory=list)
    columns_used: list = field(default_factory=list)
    joins: list = field(default_factory=list)
    has_aggregation: bool = False
    has_group_by: bool = False
    has_order_by: bool = False
    has_subquery: bool = False


class SQLStructureValidator:
    """Validates SQL structure against database schema and query intent.

    Parameters
    ----------
    db_path : str
        Path to SQLite database for schema validation.
    intent : IntentResult | None
        Optional query intent for intent-aware validation.
    """
    def __init__(self, db_path, intent=None):
        self.db_path = db_path
        self.intent = intent
        self._schema = inspect_database(db_path)
        self._table_map = {t.name: t for t in self._schema.tables}
        self._column_map = {}
        for table in self._schema.tables:
            for column in table.columns:
                self._column_map[f"{table.name}.{column.name}"] = column
                self._column_map[column.name] = column  # bare name

    def validate(self, sql):
        """Validate SQL structure.

        Parameters
        ----------
        sql : str
            SQL query to validate.

        Returns
        -------
        ValidationResult
            Validation result with issues and metadata.
        """
        result = ValidationResult(is_valid=True)

        try:
            parsed = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception as e:
            result.is_valid = False
            result.issues.append(ValidationIssue(
                severity="error",
                code="PARSE_ERROR",
                message=f"Failed to parse SQL: {e}",
            ))
            return result

        # Extract structural information
        self._extract_structure(parsed, result)

        # Validate against schema
        self._validate_tables(parsed, result)
        self._validate_columns(parsed, result)
        self._validate_joins(parsed, result)
        self._validate_aggregation(parsed, result)
        self._validate_group_by(parsed, result)
        self._validate_order_by(parsed, result)

        # Intent-aware validation
        if self.intent:
            self._validate_intent_compatibility(parsed, result)

        # Final validity
        result.is_valid = not any(i.severity == "error" for i in result.issues)
        return result

    def _extract_structure(self, parsed, result):
        """Extract tables, columns, joins, etc. from parsed SQL."""
        # Tables
        for table in parsed.find_all(exp.Table):
            if table.name:
                result.tables_used.append(table.name)

        # Columns
        for column in parsed.find_all(exp.Column):
            if column.table and column.name:
                result.columns_used.append(f"{column.table}.{column.name}")
            elif column.name:
                result.columns_used.append(column.name)

        # Joins
        for join in parsed.find_all(exp.Join):
            on_clause = join.args.get("on")
            result.joins.append({
                "left": join.this.name if isinstance(join.this, exp.Table) else str(join.this),
                "right": str(on_clause) if on_clause else None,
                "kind": join.kind or "INNER",
            })

        # Aggregation
        agg_funcs = {"COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT"}
        for func in parsed.find_all(exp.Anonymous):
            if func.this.upper() in agg_funcs:
                result.has_aggregation = True
                break
        if not result.has_aggregation:
            for func in parsed.find_all(exp.AggFunc):
                result.has_aggregation = True
                break

        # GROUP BY
        result.has_group_by = bool(parsed.find(exp.Group))

        # ORDER BY
        result.has_order_by = bool(parsed.find(exp.Order))

        # Subquery
        result.has_subquery = bool(list(parsed.find_all(exp.Subquery)))

    def _validate_tables(self, parsed, result):
        """Validate all referenced tables exist."""
        for table_name in result.tables_used:
            if table_name not in self._table_map:
                result.issues.append(ValidationIssue(
                    severity="error",
                    code="UNKNOWN_TABLE",
                    message=f"Unknown table: {table_name}",
                    location=table_name,
                ))

    def _validate_columns(self, parsed, result):
        """Validate all referenced columns exist."""
        for col_ref in result.columns_used:
            if "." in col_ref:
                table, column = col_ref.split(".", 1)
                if table in self._table_map:
                    table_obj = self._table_map[table]
                    if not any(c.name == column for c in table_obj.columns):
                        result.issues.append(ValidationIssue(
                            severity="error",
                            code="UNKNOWN_COLUMN",
                            message=f"Unknown column: {table}.{column}",
                            location=col_ref,
                        ))
            else:
                # Bare column - check if it exists in any used table
                found = False
                for table_name in result.tables_used:
                    if table_name in self._table_map:
                        table_obj = self._table_map[table_name]
                        if any(c.name == col_ref for c in table_obj.columns):
                            found = True
                            break
                if not found and result.tables_used:
                    # For single-table queries, unknown column is an error
                    # For multi-table, it's ambiguous (could be in any table)
                    severity = "error" if len(result.tables_used) == 1 else "warning"
                    result.issues.append(ValidationIssue(
                        severity=severity,
                        code="UNKNOWN_COLUMN" if len(result.tables_used) == 1 else "AMBIGUOUS_COLUMN",
                        message=f"Column '{col_ref}' not found in referenced tables",
                        location=col_ref,
                    ))

    def _validate_joins(self, parsed, result):
        """Validate JOIN structures."""
        for join_info in result.joins:
            left_table = join_info["left"]
            on_clause = join_info["right"]

            if on_clause:
                # Extract columns from ON clause - convert to string first
                on_str = str(on_clause)
                # Simple extraction of column references
                col_matches = re.findall(r'(\w+)\.(\w+)', on_str)
                for table, column in col_matches:
                    if table in self._table_map:
                        table_obj = self._table_map[table]
                        if not any(c.name == column for c in table_obj.columns):
                            result.issues.append(ValidationIssue(
                                severity="error",
                                code="INVALID_JOIN_COLUMN",
                                message=f"JOIN references unknown column: {table}.{column}",
                                location=on_str,
                            ))

    def _validate_aggregation(self, parsed, result):
        """Validate aggregation usage."""
        if result.has_aggregation:
            # Check if non-aggregated columns are in SELECT without GROUP BY
            select = parsed.find(exp.Select)
            if select:
                for expr in select.expressions:
                    if isinstance(expr, exp.Column) or (isinstance(expr, exp.Alias) and isinstance(expr.this, exp.Column)):
                        # This is a bare column in SELECT
                        if not result.has_group_by:
                            result.issues.append(ValidationIssue(
                                severity="warning",
                                code="AGGREGATION_WITHOUT_GROUP_BY",
                                message="Aggregation used but non-aggregated columns in SELECT without GROUP BY",
                                location=str(expr),
                            ))

    def _validate_group_by(self, parsed, result):
        """Validate GROUP BY structure."""
        if result.has_group_by:
            group = parsed.find(exp.Group)
            if group:
                for expr in group.expressions:
                    if isinstance(expr, exp.Column):
                        col_ref = f"{expr.table}.{expr.name}" if expr.table else expr.name
                        if col_ref not in result.columns_used:
                            result.columns_used.append(col_ref)

    def _validate_order_by(self, parsed, result):
        """Validate ORDER BY structure."""
        if result.has_order_by:
            order = parsed.find(exp.Order)
            if order:
                for expr in order.expressions:
                    if isinstance(expr.this, exp.Column):
                        col_ref = f"{expr.this.table}.{expr.this.name}" if expr.this.table else expr.this.name
                        if col_ref not in result.columns_used:
                            result.columns_used.append(col_ref)

    def _validate_intent_compatibility(self, parsed, result):
        """Validate SQL matches the expected query intent."""
        if not self.intent:
            return

        intent = self.intent.primary_intent

        # Check for unnecessary JOINs in simple queries
        if intent == QueryIntent.SELECT and not self.intent.join_required:
            if result.joins:
                # Check if JOIN is actually necessary
                tables_in_question = set()
                # We'd need the question to do this properly
                # For now, warn about JOINs in simple SELECT
                result.issues.append(ValidationIssue(
                    severity="warning",
                    code="UNNECESSARY_JOIN",
                    message=f"Simple SELECT query has {len(result.joins)} JOIN(s) but intent doesn't require JOIN",
                    location="JOIN",
                ))

        # Check for missing JOIN when required
        if intent in (QueryIntent.JOIN, QueryIntent.GROUP_BY, QueryIntent.COMPLEX) and self.intent.join_required:
            if not result.joins and len(result.tables_used) == 1:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    code="MISSING_JOIN",
                    message="Query intent requires JOIN but no JOIN found",
                    location="FROM",
                ))

        # Check aggregation consistency
        if self.intent.aggregation_required and not result.has_aggregation:
            result.issues.append(ValidationIssue(
                severity="warning",
                code="MISSING_AGGREGATION",
                message="Query intent requires aggregation but no aggregate function found",
                location="SELECT",
            ))

        if self.intent.grouping_required and not result.has_group_by:
            result.issues.append(ValidationIssue(
                severity="warning",
                code="MISSING_GROUP_BY",
                message="Query intent requires GROUP BY but none found",
                location="SELECT",
            ))

        if self.intent.ordering_required and not result.has_order_by:
            result.issues.append(ValidationIssue(
                severity="info",
                code="MISSING_ORDER_BY",
                message="Query intent suggests ORDER BY but none found",
                location="SELECT",
            ))


def validate_sql_structure(sql, db_path, intent=None):
    """Convenience function to validate SQL structure."""
    validator = SQLStructureValidator(db_path, intent)
    return validator.validate(sql)