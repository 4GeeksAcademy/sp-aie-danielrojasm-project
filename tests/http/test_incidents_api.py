import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.main import app


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED_SPEC = importlib.util.spec_from_file_location(
    "seed_incidents", REPOSITORY_ROOT / "scripts" / "seed_incidents.py"
)
assert SEED_SPEC and SEED_SPEC.loader
seed_incidents = importlib.util.module_from_spec(SEED_SPEC)
SEED_SPEC.loader.exec_module(seed_incidents)

VALID_INCIDENT = {
    "title": "Palé con cajas aplastadas en muelle 3",
    "description": "Se detecta un palé dañado al descargar el camión de la mañana.",
    "category": "warehouse_incident",
    "origin": "branch",
    "branch": "zaragoza_warehouse",
}


class IncidentsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        os.environ["AUTH_DB_PATH"] = os.path.join(self.temp_directory.name, "auth.json")
        os.environ["INCIDENTS_DB_PATH"] = os.path.join(
            self.temp_directory.name, "incidents.json"
        )
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-characters"
        self.client = TestClient(app, raise_server_exceptions=False)
        self.client.post(
            "/users",
            json={"email": "ana@example.com", "password": "correct-password"},
        )
        token = self.client.post(
            "/auth/login",
            json={"email": "ana@example.com", "password": "correct-password"},
        ).json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"

    def tearDown(self) -> None:
        self.client.close()
        self.temp_directory.cleanup()
        for variable in ("AUTH_DB_PATH", "INCIDENTS_DB_PATH", "JWT_SECRET_KEY"):
            os.environ.pop(variable, None)

    def create(self, **overrides: str) -> dict[str, object]:
        response = self.client.post("/api/incidents", json={**VALID_INCIDENT, **overrides})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def field_errors(self, response) -> dict[str, str]:
        self.assertEqual(response.status_code, 400, response.text)
        return {item["field"]: item["message"] for item in response.json()["errors"]}

    def test_empty_database_returns_empty_list_and_zero_metrics(self) -> None:
        self.assertEqual(self.client.get("/api/incidents").json(), [])
        summary = self.client.get("/api/incidents/summary").json()
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["by_status"]["open"], 0)
        self.assertEqual(set(summary["by_branch"]), {
            "central", "la_warehouse", "la_office", "zaragoza_warehouse", "zaragoza_office",
        })
        self.assertTrue(all(value == 0 for value in summary["by_category"].values()))

    def test_create_sets_defaults_timestamps_and_reporter(self) -> None:
        incident = self.create()
        self.assertEqual(incident["status"], "open")
        self.assertEqual(incident["reported_by"], "ana@example.com")
        self.assertEqual(incident["created_at"], incident["updated_at"])
        detail = self.client.get(f"/api/incidents/{incident['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["title"], VALID_INCIDENT["title"])

    def test_create_reports_each_invalid_field(self) -> None:
        payload = {**VALID_INCIDENT, "title": "   ", "category": "broken_truck"}
        del payload["branch"]
        errors = self.field_errors(self.client.post("/api/incidents", json=payload))
        self.assertEqual(set(errors), {"title", "category", "branch"})
        self.assertIn("obligatorio", errors["branch"])
        self.assertIn("lost_parcel", errors["category"])

    def test_create_rejects_non_open_initial_status(self) -> None:
        errors = self.field_errors(
            self.client.post("/api/incidents", json={**VALID_INCIDENT, "status": "resolved"})
        )
        self.assertIn("status", errors)

    def test_missing_incident_returns_404(self) -> None:
        self.assertEqual(self.client.get("/api/incidents/999").status_code, 404)
        response = self.client.patch("/api/incidents/999/status", json={"status": "in_progress"})
        self.assertEqual(response.status_code, 404)

    def test_status_lifecycle(self) -> None:
        incident_id = self.create()["id"]
        url = f"/api/incidents/{incident_id}/status"

        self.field_errors(self.client.patch(url, json={"status": "resolved"}))
        self.field_errors(self.client.patch(url, json={"status": "open"}))

        progressed = self.client.patch(url, json={"status": "in_progress"})
        self.assertEqual(progressed.status_code, 200)
        self.assertEqual(progressed.json()["status"], "in_progress")
        self.assertGreaterEqual(progressed.json()["updated_at"], progressed.json()["created_at"])

        self.assertEqual(self.client.patch(url, json={"status": "resolved"}).status_code, 200)
        errors = self.field_errors(self.client.patch(url, json={"status": "discarded"}))
        self.assertIn("final", errors["status"])

    def test_filters_and_invalid_filter_value(self) -> None:
        self.create()
        self.create(origin="internal", branch="central", category="system_failure")
        self.assertEqual(len(self.client.get("/api/incidents?origin=internal").json()), 1)
        self.assertEqual(
            len(self.client.get("/api/incidents?branch=zaragoza_warehouse&status=open").json()), 1
        )
        self.assertEqual(self.client.get("/api/incidents?category=lost_parcel").json(), [])
        errors = self.field_errors(self.client.get("/api/incidents?status=closed"))
        self.assertIn("status", errors)

    def test_requires_authentication(self) -> None:
        del self.client.headers["Authorization"]
        self.assertEqual(self.client.get("/api/incidents").status_code, 401)
        self.assertEqual(self.client.get("/api/incidents/summary").status_code, 401)

    def test_unhandled_error_returns_generic_500(self) -> None:
        with patch(
            "services.api.routes.incidents.get_incidents_db",
            side_effect=RuntimeError("disk exploded at /secret/path"),
        ), self.assertLogs("trackflow.api", level="ERROR"):
            response = self.client.get("/api/incidents")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)
        self.assertNotIn("Traceback", response.text)

    def test_other_routes_keep_422(self) -> None:
        response = self.client.post("/users", json={"email": "not-an-email"})
        self.assertEqual(response.status_code, 422)

    def test_seed_is_idempotent_and_matches_expected_totals(self) -> None:
        csv_path = REPOSITORY_ROOT / "scripts" / "incidents-trackflow.csv"
        first = seed_incidents.seed(csv_path)
        second = seed_incidents.seed(csv_path)
        self.assertEqual((first["inserted"], len(first["rejected"])), (95, 5))
        self.assertEqual((second["inserted"], second["already_imported"]), (0, 95))

        summary = self.client.get("/api/incidents/summary").json()
        self.assertEqual(summary["total"], 95)
        self.assertEqual(
            {key: value for key, value in summary["by_status"].items() if value},
            {"open": 29, "resolved": 52, "discarded": 14},
        )
        self.assertEqual(
            {key: value for key, value in summary["by_category"].items() if value},
            {"lost_parcel": 14, "carrier_issue": 45, "delivery_failure": 19, "returns_issue": 17},
        )
        self.assertEqual(summary["by_origin"]["customer"], 95)


if __name__ == "__main__":
    unittest.main()
