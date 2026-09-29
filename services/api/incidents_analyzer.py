from collections import Counter
from typing import TextIO

from packages.shared.incidents.csv_validation import (
    CATEGORIES,
    COUNTRIES,
    INVALID_REASONS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    STATUSES,
    InvalidCsvError,
    iter_validated_rows,
)


__all__ = [
    "INVALID_REASONS",
    "OPTIONAL_COLUMNS",
    "REQUIRED_COLUMNS",
    "InvalidCsvError",
    "analyze_csv",
    "result_rows",
]


def analyze_csv(stream: TextIO) -> dict[str, object]:
    """Validate and aggregate a CSV stream without retaining customer records."""
    total_records = 0
    valid_records = 0
    invalid_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    satisfaction_counts: Counter[int] = Counter()
    satisfaction_total = 0
    scored_closed = 0
    closed_records = 0

    for _, row, issues in iter_validated_rows(stream):
        total_records += 1
        if issues:
            invalid_counts.update(issues)
            continue

        valid_records += 1
        category = (row.get("category") or "").strip()
        status = (row.get("status") or "").strip()
        country = (row.get("country") or "").strip()
        category_counts[category] += 1
        status_counts[status] += 1
        country_counts[country] += 1

        if status == "CLOSED":
            closed_records += 1
            score = int((row.get("satisfaction_score") or "").strip())
            scored_closed += 1
            satisfaction_total += score
            satisfaction_counts[score] += 1

    if total_records == 0:
        raise InvalidCsvError("El CSV no contiene registros.")

    def breakdown(values: tuple[str, ...], counts: Counter) -> dict[str, dict[str, float | int]]:
        return {
            value: {
                "count": counts[value],
                "percentage": round(counts[value] / valid_records * 100, 1) if valid_records else 0.0,
            }
            for value in values
        }

    return {
        "total_records": total_records,
        "valid_records": valid_records,
        "invalid_records": total_records - valid_records,
        "invalid_breakdown": {
            key: {"label": label, "count": invalid_counts[key]}
            for key, label in INVALID_REASONS.items()
        },
        "categories": breakdown(CATEGORIES, category_counts),
        "statuses": breakdown(STATUSES, status_counts),
        "countries": breakdown(COUNTRIES, country_counts),
        "closed_incidents": closed_records,
        "scored_closed_incidents": scored_closed,
        "average_satisfaction": round(satisfaction_total / scored_closed, 2) if scored_closed else None,
        "satisfaction_scores": {
            str(score): satisfaction_counts[score] for score in range(1, 6)
        },
    }


def result_rows(summary: dict[str, object]) -> list[tuple[str, str | int | float]]:
    """Return aggregate-only CSV rows; never includes source record values."""
    rows: list[tuple[str, str | int | float]] = [
        ("total_records", summary["total_records"]),
        ("valid_records", summary["valid_records"]),
        ("invalid_records", summary["invalid_records"]),
    ]
    invalid_breakdown = summary["invalid_breakdown"]
    assert isinstance(invalid_breakdown, dict)
    for key, item in invalid_breakdown.items():
        rows.append((f"invalid_{key}", item["count"]))

    for section in ("categories", "statuses", "countries"):
        values = summary[section]
        assert isinstance(values, dict)
        for name, item in values.items():
            rows.append((f"{section}_{name}_count", item["count"]))
            rows.append((f"{section}_{name}_percentage", item["percentage"]))

    rows.extend(
        [
            ("closed_incidents", summary["closed_incidents"]),
            ("scored_closed_incidents", summary["scored_closed_incidents"]),
            ("average_satisfaction", summary["average_satisfaction"] or ""),
        ]
    )
    scores = summary["satisfaction_scores"]
    assert isinstance(scores, dict)
    rows.extend((f"satisfaction_score_{score}", count) for score, count in scores.items())
    return rows