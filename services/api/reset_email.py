import os

import resend
from resend.exceptions import ResendError


class EmailDeliveryError(RuntimeError):
    """El enlace de restablecimiento no se pudo entregar al proveedor de email.

    El mensaje nunca incluye el destinatario, el enlace ni la clave de Resend.
    """


def send_reset_email(email: str, link: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    if not api_key:
        raise EmailDeliveryError("RESEND_API_KEY no está configurada")
    resend.api_key = api_key
    try:
        resend.Emails.send({
            "from": sender,
            "to": [email],
            "subject": "Restablece tu contraseña de TrackFlow",
            "text": f"Abre este enlace para restablecer tu contraseña (válido durante 30 minutos):\n\n{link}\n\nSi no solicitaste este cambio, ignora este mensaje.",
        })
    except ResendError as error:
        # El mensaje del proveedor puede citar el destinatario: solo se conserva
        # el código y el tipo para diagnosticar.
        raise EmailDeliveryError(
            f"Resend rechazó el envío (código {error.code}, tipo {error.error_type})"
        ) from None
    except OSError as error:
        # requests.RequestException hereda de OSError: red, DNS o timeout.
        raise EmailDeliveryError(
            f"No se pudo conectar con Resend ({type(error).__name__})"
        ) from None
