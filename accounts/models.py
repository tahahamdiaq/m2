import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("L'adresse email est obligatoire.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Utilisateur du backoffice — identifié par email."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        ASSISTANTE = "assistante", "Assistante"
        INSPECTEUR = "inspecteur", "Inspecteur"

    email = models.EmailField("Adresse email", unique=True)
    full_name = models.CharField("Nom complet", max_length=255)
    role = models.CharField(
        "Rôle", max_length=20, choices=Role.choices, default=Role.ASSISTANTE
    )
    email_verified = models.BooleanField("Email vérifié", default=False)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    # Verrouillage léger après échecs de connexion répétés
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "utilisateur"

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    # --- Verrouillage connexion -------------------------------------------
    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def register_failed_login(self):
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= settings.LOGIN_MAX_FAILURES:
            self.locked_until = timezone.now() + timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
            self.failed_login_attempts = 0
        self.save(update_fields=["failed_login_attempts", "locked_until"])

    def reset_login_failures(self):
        if self.failed_login_attempts or self.locked_until:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_login_attempts", "locked_until"])


class EmailVerificationCode(models.Model):
    """Code à 6 chiffres, à usage unique, pour vérification email ou reset."""

    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Vérification d'inscription"
        PASSWORD_RESET = "password_reset", "Réinitialisation de mot de passe"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verification_codes",
    )
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "purpose", "is_used"])]

    def __str__(self):
        return f"{self.get_purpose_display()} — {self.user.email}"

    # --- Fabrique ----------------------------------------------------------
    @classmethod
    def issue(cls, user, purpose: str) -> "EmailVerificationCode":
        """Invalide les anciens codes du même usage et en émet un nouveau."""
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(
            is_used=True
        )
        return cls.objects.create(
            user=user,
            purpose=purpose,
            code=f"{secrets.randbelow(1_000_000):06d}",
            expires_at=timezone.now()
            + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES),
        )

    @classmethod
    def last_sent(cls, user, purpose: str):
        return (
            cls.objects.filter(user=user, purpose=purpose)
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def seconds_before_resend(cls, user, purpose: str) -> int:
        """Secondes restantes avant de pouvoir renvoyer un code (0 = ok)."""
        last = cls.last_sent(user, purpose)
        if not last:
            return 0
        elapsed = (timezone.now() - last.created_at).total_seconds()
        return max(0, int(settings.VERIFICATION_RESEND_SECONDS - elapsed))

    # --- Vérification ------------------------------------------------------
    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempts >= settings.VERIFICATION_MAX_ATTEMPTS

    @classmethod
    def verify(cls, user, purpose: str, submitted_code: str):
        """Vérifie un code. Retourne (ok: bool, error: str | None)."""
        active = (
            cls.objects.filter(user=user, purpose=purpose, is_used=False)
            .order_by("-created_at")
            .first()
        )
        if active is None:
            return False, "Aucun code actif. Demandez un nouveau code."
        if active.is_expired:
            return False, "Ce code a expiré. Demandez un nouveau code."
        if active.attempts_exhausted:
            return False, "Trop de tentatives. Demandez un nouveau code."

        active.attempts += 1
        if secrets.compare_digest(active.code, submitted_code.strip()):
            active.is_used = True
            active.save(update_fields=["attempts", "is_used"])
            return True, None
        active.save(update_fields=["attempts"])
        remaining = settings.VERIFICATION_MAX_ATTEMPTS - active.attempts
        if remaining <= 0:
            return False, "Trop de tentatives. Demandez un nouveau code."
        return False, f"Code incorrect. Il reste {remaining} tentative(s)."
