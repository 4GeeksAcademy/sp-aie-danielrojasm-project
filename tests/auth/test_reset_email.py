"""Envío del enlace de recuperación por Resend (`send_reset_email`).

El SDK se sustituye por un doble: se prueba qué decide nuestro código antes y
después de la llamada externa, no el servicio de Resend.
"""

from unittest.mock import patch

import pytest
from resend.exceptions import ResendError

from services.api.reset_email import EmailDeliveryError, send_reset_email

SEND = "services.api.reset_email.resend.Emails.send"
LINK = "https://backoffice.example/reset-password?token=secret-token"


def test_sends_link_to_the_user_from_configured_sender(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "soporte@trackflow.example")

    with patch(SEND) as send:
        send_reset_email("ana@example.com", LINK)

    message = send.call_args.args[0]
    assert message["to"] == ["ana@example.com"]
    assert message["from"] == "soporte@trackflow.example"
    assert LINK in message["text"]


def test_defaults_to_resend_onboarding_sender(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    with patch(SEND) as send:
        send_reset_email("ana@example.com", LINK)
    assert send.call_args.args[0]["from"] == "onboarding@resend.dev"


def test_missing_api_key_fails_without_calling_provider():
    with patch(SEND) as send, pytest.raises(EmailDeliveryError, match="RESEND_API_KEY"):
        send_reset_email("ana@example.com", LINK)
    send.assert_not_called()


def test_provider_rejection_hides_recipient_and_link(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    rejection = ResendError(
        code=403,
        error_type="validation_error",
        message="You can only send testing emails to ana@example.com",
        suggested_action="",
    )
    with patch(SEND, side_effect=rejection), pytest.raises(EmailDeliveryError) as error:
        send_reset_email("ana@example.com", LINK)

    message = str(error.value)
    assert "403" in message and "validation_error" in message  # útil para soporte
    assert "ana@example.com" not in message
    assert "secret-token" not in message
    # `from None`: la excepción original (con el email) no viaja encadenada al log.
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_network_failure_is_reported_as_delivery_error(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    with patch(SEND, side_effect=ConnectionError("dns failure")):
        with pytest.raises(EmailDeliveryError, match="ConnectionError"):
            send_reset_email("ana@example.com", LINK)
