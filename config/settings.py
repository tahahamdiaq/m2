"""
Django settings — Registre de suivi des clients (contrôle technique).

Configuration via variables d'environnement (.env) avec django-environ.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-secret-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "clients",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "clients.context_processors.alerts_badge",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base de données — PostgreSQL en cible, configurable par DATABASE_URL.
# Ex. : postgres://registre:registre@localhost:5432/registre
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    ),
}

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "clients:client_list"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = env("TIME_ZONE", default="Africa/Casablanca")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Emails
# En dev (par défaut) : backend console — les codes de vérification s'affichent
# dans le terminal du runserver, aucun compte SMTP nécessaire.
# En prod : EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# + renseigner les identifiants Gmail (mot de passe d'application) dans .env.
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="Registre Contrôle <no-reply@registre.local>"
)

# Paramètres du flux de vérification par code
VERIFICATION_CODE_TTL_MINUTES = 10   # durée de validité d'un code
VERIFICATION_MAX_ATTEMPTS = 5        # tentatives de saisie par code
VERIFICATION_RESEND_SECONDS = 60     # délai mini entre deux envois
# Comptes de test : la vérification par code est court-circuitée pour ces emails
VERIFICATION_BYPASS_EMAILS = [
    e.strip().lower()
    for e in env.list("VERIFICATION_BYPASS_EMAILS", default=["test@gmail.com"])
]
LOGIN_MAX_FAILURES = 5               # tentatives de connexion avant blocage
LOGIN_LOCKOUT_MINUTES = 15           # durée du blocage

# Port par défaut du runserver — dédié à ce projet pour ne pas entrer en
# conflit avec les autres projets locaux (8000, 8025, …). Surchargeable via
# RUNSERVER_PORT dans .env, ou ponctuellement : python manage.py runserver 8001
from django.core.management.commands.runserver import Command as _Runserver  # noqa: E402

_Runserver.default_port = env("RUNSERVER_PORT", default="8642")
