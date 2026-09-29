import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from resend.exceptions import ResendError

from services.api.main import app
from services.api.reset_email import EmailDeliveryError, send_reset_email


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        os.environ["AUTH_DB_PATH"] = os.path.join(self.temp_directory.name, "auth.json")
        os.environ["SUPPLIERS_DB_PATH"] = os.path.join(self.temp_directory.name, "suppliers.json")
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-characters"
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_directory.cleanup()
        for variable in ("AUTH_DB_PATH", "SUPPLIERS_DB_PATH", "JWT_SECRET_KEY", "RESEND_API_KEY"):
            os.environ.pop(variable, None)

    def test_validation_errors_never_echo_submitted_values(self) -> None:
        response = self.client.post(
            "/users", json={"email": "owner@example.com", "password": "secret7"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret7", response.text)
        self.assertNotIn('"input"', response.text)
        [error] = response.json()["detail"]
        self.assertEqual(error["loc"], ["body", "password"])
        self.assertEqual(error["msg"], "Debe tener al menos 8 caracteres.")

        reset = self.client.post(
            "/auth/reset-password", json={"token": "leaked-token", "new_password": "x"}
        )
        self.assertNotIn("leaked-token", reset.text)

    def test_invalid_email_and_custom_validator_messages_are_readable(self) -> None:
        response = self.client.post("/users", json={"email": "no-at-sign", "password": "long-enough"})
        self.assertEqual(response.json()["detail"][0]["msg"], "Introduce un email válido.")

    def test_missing_jwt_secret_is_a_server_error_not_bad_credentials(self) -> None:
        del os.environ["JWT_SECRET_KEY"]
        with self.assertLogs("trackflow.api", level="ERROR"):
            response = self.client.get(
                "/auth/me", headers={"Authorization": "Bearer anything"}
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("JWT_SECRET_KEY", response.text)

    def test_email_delivery_error_hides_recipient_and_link(self) -> None:
        os.environ["RESEND_API_KEY"] = "re_test"
        provider_error = ResendError(
            code=403,
            error_type="validation_error",
            message="You can only send testing emails to owner@example.com",
            suggested_action="",
        )
        with patch("services.api.reset_email.resend.Emails.send", side_effect=provider_error):
            with self.assertRaises(EmailDeliveryError) as raised:
                send_reset_email("owner@example.com", "https://example.test/reset?token=abc")
        self.assertNotIn("owner@example.com", str(raised.exception))
        self.assertNotIn("token", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_network_failure_to_email_provider_is_wrapped(self) -> None:
        os.environ["RESEND_API_KEY"] = "re_test"
        with patch(
            "services.api.reset_email.resend.Emails.send",
            side_effect=ConnectionError("dns failure"),
        ):
            with self.assertRaises(EmailDeliveryError):
                send_reset_email("owner@example.com", "https://example.test/reset")


if __name__ == "__main__":
    unittest.main()
