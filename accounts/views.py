from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .emails import send_verification_email
from .forms import (
    ForgotPasswordForm,
    LoginForm,
    ResetPasswordForm,
    SignupForm,
    VerifyCodeForm,
)
from .models import EmailVerificationCode, User

PENDING_USER_SESSION_KEY = "pending_verification_user_id"
RESET_USER_SESSION_KEY = "password_reset_user_id"


def _issue_and_send(user, purpose):
    code = EmailVerificationCode.issue(user, purpose)
    send_verification_email(user, code)


def _bypass_verification(email: str) -> bool:
    """Compte de test : pas de code de vérification à saisir."""
    return email.lower() in settings.VERIFICATION_BYPASS_EMAILS


def _get_pending_user(request, session_key):
    user_id = request.session.get(session_key)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


# ---------------------------------------------------------------------------
# Inscription + vérification email
# ---------------------------------------------------------------------------
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("clients:client_list")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        # Un compte non vérifié avec le même email est réutilisé (ré-inscription)
        user = User.objects.filter(email__iexact=data["email"]).first()
        if user is None:
            user = User(email=data["email"])
        user.full_name = data["full_name"]
        user.email_verified = False
        user.set_password(data["password1"])
        user.save()

        if _bypass_verification(user.email):
            user.email_verified = True
            user.save(update_fields=["email_verified"])
            login(request, user)
            messages.success(
                request, f"Bienvenue, {user.full_name} ! Votre compte est activé."
            )
            return redirect("clients:client_list")

        _issue_and_send(user, EmailVerificationCode.Purpose.SIGNUP)
        request.session[PENDING_USER_SESSION_KEY] = user.pk
        messages.info(request, "Un code de vérification vous a été envoyé par email.")
        return redirect("accounts:verify_email")

    return render(request, "auth/signup.html", {"form": form})


def verify_email_view(request):
    user = _get_pending_user(request, PENDING_USER_SESSION_KEY)
    if user is None:
        messages.error(request, "Session de vérification introuvable. Reconnectez-vous.")
        return redirect("accounts:login")

    form = VerifyCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ok, error = EmailVerificationCode.verify(
            user, EmailVerificationCode.Purpose.SIGNUP, form.cleaned_data["code"]
        )
        if ok:
            user.email_verified = True
            user.save(update_fields=["email_verified"])
            del request.session[PENDING_USER_SESSION_KEY]
            login(request, user)
            messages.success(request, f"Bienvenue, {user.full_name} ! Votre compte est activé.")
            return redirect("clients:client_list")
        form.add_error("code", error)

    return render(
        request,
        "auth/verify_email.html",
        {
            "form": form,
            "email": user.email,
            "resend_wait": EmailVerificationCode.seconds_before_resend(
                user, EmailVerificationCode.Purpose.SIGNUP
            ),
            "resend_url": reverse("accounts:resend_code"),
        },
    )


@require_POST
def resend_code_view(request):
    user = _get_pending_user(request, PENDING_USER_SESSION_KEY)
    if user is None:
        return redirect("accounts:login")

    wait = EmailVerificationCode.seconds_before_resend(
        user, EmailVerificationCode.Purpose.SIGNUP
    )
    if wait > 0:
        messages.error(
            request, f"Veuillez patienter {wait} seconde(s) avant de renvoyer un code."
        )
    else:
        _issue_and_send(user, EmailVerificationCode.Purpose.SIGNUP)
        messages.success(request, "Un nouveau code vous a été envoyé.")
    return redirect("accounts:verify_email")


# ---------------------------------------------------------------------------
# Connexion / déconnexion
# ---------------------------------------------------------------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect("clients:client_list")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        password = form.cleaned_data["password"]
        user = User.objects.filter(email__iexact=email).first()

        if user and user.is_locked:
            minutes = max(
                1, int((user.locked_until - timezone.now()).total_seconds() // 60)
            )
            form.add_error(
                None,
                f"Compte temporairement bloqué suite à trop de tentatives. "
                f"Réessayez dans {minutes} minute(s).",
            )
        else:
            authenticated = authenticate(request, username=email, password=password)
            if authenticated is None:
                if user:
                    user.register_failed_login()
                form.add_error(None, "Email ou mot de passe incorrect.")
            elif not authenticated.email_verified and _bypass_verification(
                authenticated.email
            ):
                # Compte de test : vérification court-circuitée
                authenticated.email_verified = True
                authenticated.save(update_fields=["email_verified"])
                authenticated.reset_login_failures()
                login(request, authenticated)
                return redirect("clients:client_list")
            elif not authenticated.email_verified:
                # Email non vérifié → renvoi automatique d'un code + page de saisie
                authenticated.reset_login_failures()
                if EmailVerificationCode.seconds_before_resend(
                    authenticated, EmailVerificationCode.Purpose.SIGNUP
                ) == 0:
                    _issue_and_send(authenticated, EmailVerificationCode.Purpose.SIGNUP)
                request.session[PENDING_USER_SESSION_KEY] = authenticated.pk
                messages.info(
                    request,
                    "Votre email n'est pas encore vérifié. Un code vient de vous être envoyé.",
                )
                return redirect("accounts:verify_email")
            else:
                authenticated.reset_login_failures()
                login(request, authenticated)
                return redirect("clients:client_list")

    return render(request, "auth/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Vous êtes déconnecté(e).")
    return redirect("accounts:login")


# ---------------------------------------------------------------------------
# Mot de passe oublié
# ---------------------------------------------------------------------------
def forgot_password_view(request):
    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        user = User.objects.filter(email__iexact=email, email_verified=True).first()
        if user:
            wait = EmailVerificationCode.seconds_before_resend(
                user, EmailVerificationCode.Purpose.PASSWORD_RESET
            )
            if wait == 0:
                _issue_and_send(user, EmailVerificationCode.Purpose.PASSWORD_RESET)
            request.session[RESET_USER_SESSION_KEY] = user.pk
        # Message identique que le compte existe ou non (pas de fuite d'info)
        messages.info(
            request,
            "Si un compte existe avec cette adresse, un code de réinitialisation a été envoyé.",
        )
        return redirect("accounts:reset_password")

    return render(request, "auth/forgot_password.html", {"form": form})


def reset_password_view(request):
    user = _get_pending_user(request, RESET_USER_SESSION_KEY)
    if user is None:
        messages.error(request, "Commencez par saisir votre adresse email.")
        return redirect("accounts:forgot_password")

    form = ResetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ok, error = EmailVerificationCode.verify(
            user,
            EmailVerificationCode.Purpose.PASSWORD_RESET,
            form.cleaned_data["code"],
        )
        if ok:
            user.set_password(form.cleaned_data["password1"])
            user.reset_login_failures()
            user.save()
            del request.session[RESET_USER_SESSION_KEY]
            messages.success(
                request, "Mot de passe réinitialisé. Vous pouvez vous connecter."
            )
            return redirect("accounts:login")
        form.add_error("code", error)

    return render(request, "auth/reset_password.html", {"form": form, "email": user.email})
