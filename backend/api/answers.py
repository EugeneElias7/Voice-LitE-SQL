"""Voice-LitE-SQL -- Deterministic natural-language answer formatter.

Builds a human-friendly answer from the real PipelineResult without
using the LLM. The database is the source of truth.
"""

from __future__ import annotations

import re
from typing import Any

from backend.pipeline.pipeline_result import PipelineResult


AGG_FUNCS = ("COUNT", "SUM", "AVG", "MIN", "MAX")


def _detect_agg_and_group(sql: str) -> dict[str, Any]:
    """Extract aggregate function, target column, table, and GROUP BY from SQL."""
    sql_upper = sql.upper()
    result: dict[str, Any] = {
        "agg": None,
        "column": None,
        "table": None,
        "group_by": None,
        "is_star": False,
    }

    # Find aggregate function
    for func in AGG_FUNCS:
        match = re.search(rf"{func}\s*\(\s*([^)]+)\s*\)", sql_upper)
        if match:
            result["agg"] = func
            result["column"] = match.group(1).strip()
            result["is_star"] = result["column"] == "*"
            break

    # Find FROM table
    from_match = re.search(r"FROM\s+([\w_]+)", sql_upper)
    if from_match:
        result["table"] = from_match.group(1).lower()

    # Find GROUP BY
    group_match = re.search(r"GROUP BY\s+([\w_, ]+)", sql_upper)
    if group_match:
        result["group_by"] = group_match.group(1).strip().lower()

    return result


def _humanize(text: str) -> str:
    """Convert snake_case or camelCase to Title Case words."""
    if not text:
        return ""
    # Replace underscores with spaces
    text = text.replace("_", " ")
    # Insert space before capital letters (camelCase)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Title case each word
    return " ".join(w.capitalize() for w in text.split())


def _format_number(n: Any) -> str:
    """Format number with commas, handle None."""
    if n is None:
        return "N/A"
    try:
        f = float(n)
        if f == int(f):
            return f"{int(f):,}"
        return f"{f:,.2f}"
    except (ValueError, TypeError):
        return str(n)


def build_answer(result: PipelineResult) -> dict[str, Any]:
    """Build a deterministic answer object from PipelineResult."""
    sql = result.final_sql or (result.generation.generated_sql if result.generation else "")
    rows = result.final_result_rows or (result.execution.rows if result.execution else [])
    cols = result.execution.columns if result.execution else []

    if not sql or not rows:
        return {
            "kind": "empty",
            "primary": None,
            "unit_label": None,
            "natural": "No results returned.",
            "summary": "No data",
            "sql": sql,
        }

    # Single row, single column = KPI (COUNT, SUM, AVG, MIN, MAX)
    if len(rows) == 1 and len(cols) == 1:
        val = rows[0].get(cols[0])
        agg_info = _detect_agg_and_group(sql)
        agg = agg_info["agg"]
        table = agg_info["table"]
        column = agg_info["column"]

        if agg == "COUNT":
            label = _humanize(table) if table else "Records"
            natural = f"There are {_format_number(val)} {label.lower()} in the database."
        elif agg == "SUM":
            label = _humanize(column) if column else (_humanize(table) if table else "Total")
            natural = f"Total {label.lower()} is {_format_number(val)}."
        elif agg == "AVG":
            label = _humanize(column) if column else (_humanize(table) if table else "Value")
            natural = f"The average {label.lower()} is {_format_number(val)}."
        elif agg == "MAX":
            label = _humanize(column) if column else (_humanize(table) if table else "Value")
            natural = f"The highest {label.lower()} is {_format_number(val)}."
        elif agg == "MIN":
            label = _humanize(column) if column else (_humanize(table) if table else "Value")
            natural = f"The lowest {label.lower()} is {_format_number(val)}."
        else:
            label = _humanize(cols[0])
            natural = f"Result: {_format_number(val)} {label.lower()}."
            agg = "VALUE"

        return {
            "kind": "kpi",
            "primary": val,
            "unit_label": label,
            "natural": natural,
            "summary": f"{_format_number(val)} {label}",
            "sql": sql,
            "agg": agg,
        }

    # Multiple rows with GROUP BY = grouped result
    if len(rows) > 1 and result.nlp and result.nlp.intent.get("grouping_required"):
        # Try to extract group column and value column
        group_col = None
        val_col = None
        for c in cols:
            c_upper = c.upper()
            if any(f in c_upper for f in AGG_FUNCS):
                val_col = c
            else:
                group_col = c

        if group_col and val_col:
            # Find the "top" row (first row after ordering, assuming DESC)
            top = rows[0]
            group_val = top.get(group_col)
            val = top.get(val_col)
            label = _humanize(group_col)
            natural = f"{group_val} has the highest {_humanize(val_col).lower()} with {_format_number(val)}."
            return {
                "kind": "grouped",
                "primary": val,
                "unit_label": str(group_val),
                "natural": natural,
                "summary": f"{group_val}: {_format_number(val)}",
                "sql": sql,
                "group_col": group_col,
                "val_col": val_col,
            }

    # General list/table result
    row_count = len(rows)
    table = _detect_agg_and_group(sql).get("table")
    label = _humanize(table) if table else "records"
    natural = f"I found {_format_number(row_count)} {label.lower()}."

    return {
        "kind": "table",
        "primary": row_count,
        "unit_label": label,
        "natural": natural,
        "summary": f"{_format_number(row_count)} {label}",
        "sql": sql,
    }