from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerificationCode, User

PURPOSE = EmailVerificationCode.Purpose.SIGNUP


class EmailVerificationCodeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@exemple.com", password="S3cret!pass", full_name="Test User"
        )

    def test_issue_genere_un_code_a_6_chiffres(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        self.assertRegex(code.code, r"^\d{6}$")
        self.assertFalse(code.is_used)
        self.assertGreater(code.expires_at, timezone.now())

    def test_issue_invalide_les_anciens_codes(self):
        old = EmailVerificationCode.issue(self.user, PURPOSE)
        EmailVerificationCode.issue(self.user, PURPOSE)
        old.refresh_from_db()
        self.assertTrue(old.is_used)

    def test_verify_bon_code(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        ok, error = EmailVerificationCode.verify(self.user, PURPOSE, code.code)
        self.assertTrue(ok)
        self.assertIsNone(error)
        code.refresh_from_db()
        self.assertTrue(code.is_used)  # usage unique

    def test_verify_code_deja_utilise(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        EmailVerificationCode.verify(self.user, PURPOSE, code.code)
        ok, error = EmailVerificationCode.verify(self.user, PURPOSE, code.code)
        self.assertFalse(ok)

    def test_verify_mauvais_code_incremente_les_tentatives(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        ok, error = EmailVerificationCode.verify(self.user, PURPOSE, "000000")
        self.assertFalse(ok)
        code.refresh_from_db()
        self.assertEqual(code.attempts, 1)

    def test_verify_code_expire(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        code.expires_at = timezone.now() - timedelta(minutes=1)
        code.save()
        ok, error = EmailVerificationCode.verify(self.user, PURPOSE, code.code)
        self.assertFalse(ok)
        self.assertIn("expiré", error)

    def test_verify_bloque_apres_5_tentatives(self):
        code = EmailVerificationCode.issue(self.user, PURPOSE)
        for _ in range(5):
            EmailVerificationCode.verify(self.user, PURPOSE, "000000")
        # Même le bon code est refusé après épuisement des tentatives
        ok, error = EmailVerificationCode.verify(self.user, PURPOSE, code.code)
        self.assertFalse(ok)
        self.assertIn("tentatives", error)

    def test_throttle_renvoi_60_secondes(self):
        EmailVerificationCode.issue(self.user, PURPOSE)
        wait = EmailVerificationCode.seconds_before_resend(self.user, PURPOSE)
        self.assertGreater(wait, 0)
        self.assertLessEqual(wait, 60)


class SignupFlowTests(TestCase):
    def test_signup_envoie_un_code_et_redirige(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "full_name": "Amina Berrada",
                "email": "amina@exemple.com",
                "password1": "Registre2025!",
                "password2": "Registre2025!",
            },
        )
        self.assertRedirects(response, reverse("accounts:verify_email"))
        user = User.objects.get(email="amina@exemple.com")
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("amina@exemple.com", mail.outbox[0].to)

    def test_verification_active_le_compte_et_connecte(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "full_name": "Amina Berrada",
                "email": "amina@exemple.com",
                "password1": "Registre2025!",
                "password2": "Registre2025!",
            },
        )
        user = User.objects.get(email="amina@exemple.com")
        code = EmailVerificationCode.last_sent(user, PURPOSE)
        response = self.client.post(
            reverse("accounts:verify_email"), {"code": code.code}
        )
        self.assertRedirects(response, reverse("clients:client_list"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_mauvais_code_affiche_une_erreur(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "full_name": "Amina Berrada",
                "email": "amina@exemple.com",
                "password1": "Registre2025!",
                "password2": "Registre2025!",
            },
        )
        response = self.client.post(
            reverse("accounts:verify_email"), {"code": "000000"}
        )
        self.assertContains(response, "Code incorrect")


class VerificationBypassTests(TestCase):
    """Compte de test (test@gmail.com) : aucun code de vérification à saisir."""

    def test_signup_compte_de_test_connecte_directement(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "full_name": "Compte Test",
                "email": "test@gmail.com",
                "password1": "Registre2025!",
                "password2": "Registre2025!",
            },
        )
        self.assertRedirects(response, reverse("clients:client_list"))
        user = User.objects.get(email="test@gmail.com")
        self.assertTrue(user.email_verified)
        self.assertEqual(len(mail.outbox), 0)  # aucun code envoyé

    def test_login_compte_de_test_non_verifie_connecte_directement(self):
        User.objects.create_user(
            email="test@gmail.com",
            password="Registre2025!",
            full_name="Compte Test",
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "test@gmail.com", "password": "Registre2025!"},
        )
        self.assertRedirects(response, reverse("clients:client_list"))
        user = User.objects.get(email="test@gmail.com")
        self.assertTrue(user.email_verified)
        self.assertEqual(len(mail.outbox), 0)


class LoginFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="verifie@exemple.com",
            password="Registre2025!",
            full_name="Vérifiée",
            email_verified=True,
        )

    def test_login_ok(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "verifie@exemple.com", "password": "Registre2025!"},
        )
        self.assertRedirects(response, reverse("clients:client_list"))

    def test_login_non_verifie_redirige_vers_verification(self):
        User.objects.create_user(
            email="nonverifie@exemple.com",
            password="Registre2025!",
            full_name="Non Vérifiée",
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "nonverifie@exemple.com", "password": "Registre2025!"},
        )
        self.assertRedirects(response, reverse("accounts:verify_email"))
        self.assertEqual(len(mail.outbox), 1)  # renvoi automatique du code

    def test_lockout_apres_5_echecs(self):
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"email": "verifie@exemple.com", "password": "mauvais"},
            )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)
        # Même le bon mot de passe est refusé pendant le blocage
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "verifie@exemple.com", "password": "Registre2025!"},
        )
        self.assertContains(response, "bloqué")

    def test_backoffice_protege(self):
        response = self.client.get(reverse("clients:client_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset@exemple.com",
            password="AncienPass2025!",
            full_name="Reset User",
            email_verified=True,
        )

    def test_flux_complet_de_reinitialisation(self):
        self.client.post(
            reverse("accounts:forgot_password"), {"email": "reset@exemple.com"}
        )
        self.assertEqual(len(mail.outbox), 1)
        code = EmailVerificationCode.last_sent(
            self.user, EmailVerificationCode.Purpose.PASSWORD_RESET
        )
        response = self.client.post(
            reverse("accounts:reset_password"),
            {
                "code": code.code,
                "password1": "NouveauPass2025!",
                "password2": "NouveauPass2025!",
            },
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NouveauPass2025!"))

    def test_email_inconnu_meme_message(self):
        response = self.client.post(
            reverse("accounts:forgot_password"),
            {"email": "inconnu@exemple.com"},
            follow=True,
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "Si un compte existe")
