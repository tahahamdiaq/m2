from django import forms
from django.contrib.auth import password_validation

from .models import User

INPUT_CLASSES = (
    "w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-800 placeholder-slate-400 focus:border-[#17293D] "
    "focus:outline-none focus:ring-2 focus:ring-[#17293D]/20"
)


class SignupForm(forms.Form):
    full_name = forms.CharField(
        label="Nom complet",
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "Ex. Fatima Zahra Idrissi"}
        ),
    )
    email = forms.EmailField(
        label="Adresse email",
        widget=forms.EmailInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "vous@exemple.com"}
        ),
    )
    password1 = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
    )
    password2 = forms.CharField(
        label="Confirmation du mot de passe",
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email, email_verified=True).exists():
            raise forms.ValidationError("Un compte existe déjà avec cette adresse email.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
        elif p1:
            password_validation.validate_password(p1)
        return cleaned


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Adresse email",
        widget=forms.EmailInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "vous@exemple.com"}
        ),
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
    )


class VerifyCodeForm(forms.Form):
    code = forms.RegexField(
        label="Code de vérification",
        regex=r"^\d{6}$",
        error_messages={"invalid": "Le code est composé de 6 chiffres."},
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES
                + " text-center font-mono text-2xl tracking-[0.5em]",
                "placeholder": "••••••",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "maxlength": "6",
            }
        ),
    )


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        label="Adresse email",
        widget=forms.EmailInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "vous@exemple.com"}
        ),
    )


class ResetPasswordForm(VerifyCodeForm):
    password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
    )
    password2 = forms.CharField(
        label="Confirmation du nouveau mot de passe",
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
    )

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
        elif p1:
            password_validation.validate_password(p1)
        return cleaned
