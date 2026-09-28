import os

import resend


def send_reset_email(email: str, link: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY no está configurada")
    resend.api_key = api_key
    resend.Emails.send({
        "from": sender,
        "to": [email],
        "subject": "Restablece tu contraseña de TrackFlow",
        "text": f"Abre este enlace para restablecer tu contraseña (válido durante 30 minutos):\n\n{link}\n\nSi no solicitaste este cambio, ignora este mensaje.",
    })