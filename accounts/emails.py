"""Envoi des emails de vérification (templates HTML + fallback texte)."""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

SUBJECTS = {
    "signup": "Votre code de vérification — Registre Contrôle",
    "password_reset": "Réinitialisation de votre mot de passe — Registre Contrôle",
}


def send_verification_email(user, verification_code):
    """Envoie le code à 6 chiffres par email (HTML + texte)."""
    purpose = verification_code.purpose
    context = {
        "user": user,
        "code": verification_code.code,
        "purpose": purpose,
        "ttl_minutes": settings.VERIFICATION_CODE_TTL_MINUTES,
    }
    subject = SUBJECTS.get(purpose, SUBJECTS["signup"])
    text_body = render_to_string("emails/verification_code.txt", context)
    html_body = render_to_string("emails/verification_code.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
