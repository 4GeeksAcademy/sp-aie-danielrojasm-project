import csv
import io
import unittest

from services.api.incidents_analyzer import (
    REQUIRED_COLUMNS,
    InvalidCsvError,
    analyze_csv,
    result_rows,
)


def make_row(incident_id: str, status: str = "OPEN", score: str = "") -> dict[str, str]:
    row = {column: "" for column in REQUIRED_COLUMNS}
    row.update(
        {
            "incident_id": incident_id,
            "date": "2026-09-01",
            "country": "US",
            "customer_type": "B2C",
            "tracking_number": "TRACK12345",
            "carrier": "UPS",
            "category": "LOST_PARCEL",
            "description": "Package is missing",
            "status": status,
            "customer_email": "internal-test@example.test",
            "satisfaction_score": score,
        }
    )
    return row


def encode_rows(rows: list[dict[str, str]]) -> io.StringIO:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[*REQUIRED_COLUMNS, "satisfaction_score"],
    )
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return output


class IncidentAnalyzerTests(unittest.TestCase):
    def test_excludes_invalid_rows_and_counts_each_triggered_rule(self) -> None:
        duplicate = make_row("TRF-000001")
        invalid_category_and_carrier = make_row("TRF-000004")
        invalid_category_and_carrier.update({"country": "ES", "category": "OTHER"})
        rows = [
            make_row("TRF-000001"),
            duplicate,
            make_row("TRF-000002", status="CLOSED"),
            make_row("TRF-000003", score="6"),
            invalid_category_and_carrier,
        ]

        summary = analyze_csv(encode_rows(rows))

        self.assertEqual(summary["total_records"], 5)
        self.assertEqual(summary["valid_records"], 1)
        self.assertEqual(summary["invalid_records"], 4)
        breakdown = summary["invalid_breakdown"]
        self.assertEqual(breakdown["duplicate_incident_id"]["count"], 1)
        self.assertEqual(breakdown["closed_without_score"]["count"], 1)
        self.assertEqual(breakdown["satisfaction_score"]["count"], 1)
        self.assertEqual(breakdown["category"]["count"], 1)
        self.assertEqual(breakdown["carrier_country"]["count"], 1)
        self.assertEqual(summary["categories"]["LOST_PARCEL"]["count"], 1)

        exported_values = " ".join(str(value) for row in result_rows(summary) for value in row)
        self.assertNotIn("internal-test@example.test", exported_values)

    def test_rejects_malformed_csv(self) -> None:
        headers = [*REQUIRED_COLUMNS, "satisfaction_score"]
        malformed = io.StringIO(",".join(headers) + "\n" + ",".join(["value"] * (len(headers) - 1)) + ',"unfinished')
        with self.assertRaises(InvalidCsvError):
            analyze_csv(malformed)


if __name__ == "__main__":
    unittest.main()