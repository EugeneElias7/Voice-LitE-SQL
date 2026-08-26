"""Voice-LitE-SQL -- Level 4: evaluation metrics."""

import statistics


def compute_metrics(evaluations):
    """Overall metrics from a list of QueryEvaluation objects."""
    total = len(evaluations)

    def rate(count):
        return round((count / total), 4) if total else 0.0

    generated = sum(1 for e in evaluations if e.generation_success)
    executed = sum(1 for e in evaluations if e.execution_success)
    correct = sum(1 for e in evaluations if e.correctness)
    latencies = [e.execution_time_ms for e in evaluations if e.execution_success]

    return {
        "total_questions": total,
        "generation_success_rate": rate(generated),
        "execution_success_rate": rate(executed),
        "execution_accuracy": rate(correct),
        "sql_execution_error_rate": rate(total - executed),
        "average_execution_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "median_execution_latency_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
    }


def metrics_by_category(evaluations):
    """Metrics grouped by question category (SELECT, WHERE, JOIN, ...)."""
    grouped = {}
    for evaluation in evaluations:
        grouped.setdefault(evaluation.category or "unknown", []).append(evaluation)
    return {
        category: compute_metrics(evals)
        for category, evals in sorted(grouped.items())
    }
