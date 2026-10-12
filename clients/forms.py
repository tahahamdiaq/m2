from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django import forms

from .models import REMIS, Client
from .services.alerts import ASSISTANTE_DELAY_DAYS, next_monday_deadline
from .services.visites import sync_visites

TEXT_INPUT = (
    "w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-800 focus:border-[#17293D] focus:outline-none "
    "focus:ring-2 focus:ring-[#17293D]/20"
)
DATE_INPUT = TEXT_INPUT + " font-mono"
SELECT_INPUT = TEXT_INPUT
CHECKBOX_INPUT = (
    "h-4 w-4 rounded border-slate-300 text-[#1F7A6C] focus:ring-[#1F7A6C]"
)

SPEC_FIELDS = [
    "spec_el", "spec_si", "spec_apg", "spec_mcna", "spec_lev",
    "spec_apv", "spec_gaz", "spec_asc", "spec_ge", "spec_gec",
]

DATE_FIELDS = [
    "visite_initiale",
    "derniere_1ere_visite", "prochaine_1ere_visite",
    "derniere_2eme_visite", "prochaine_2eme_visite",
]


class ClientForm(forms.ModelForm):
    # Suivi du rapport de la visite courante (fiche Visite, pas le client)
    rapport_inspecteurs = forms.ChoiceField(
        label="Rapport inspecteurs", choices=REMIS, required=False
    )
    # Échéances calculées (lecture seule) ; les dates de remise exactes sont
    # saisies à la main une fois le rapport passé à « Remis »
    deadline_inspecteurs = forms.DateField(
        label="Deadline rapport inspecteurs", required=False, disabled=True
    )
    date_remise_inspecteurs = forms.DateField(
        label="Date exacte de remise (inspecteurs)", required=False
    )
    rapport_assistante = forms.ChoiceField(
        label="Rapport assistante", choices=REMIS, required=False
    )
    deadline_assistante = forms.DateField(
        label="Deadline rapport assistante", required=False, disabled=True
    )
    date_remise_assistante = forms.DateField(
        label="Date exacte de remise (assistante)", required=False
    )
    date_paiement_facture = forms.DateField(
        label="Date paiement facture", required=False
    )
    date_decharge_facture = forms.DateField(
        label="Date décharge facture", required=False
    )
    # Date de la visite dont le rapport est affiché (fiabilise l'enregistrement
    # si une nouvelle visite démarre entre l'affichage et la soumission)
    rapport_visite_date = forms.DateField(
        required=False, widget=forms.HiddenInput
    )

    class Meta:
        model = Client
        fields = [
            "nom", "adresse", "numero_abonnement", "status",
            "payement", "decharge_facture",
            *SPEC_FIELDS,
            *DATE_FIELDS,
        ]
        widgets = {
            "nom": forms.TextInput(attrs={"class": TEXT_INPUT}),
            "adresse": forms.TextInput(attrs={"class": TEXT_INPUT}),
            "numero_abonnement": forms.TextInput(
                attrs={"class": TEXT_INPUT + " font-mono", "placeholder": "113/2017"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in DATE_FIELDS:
            self.fields[name].widget = forms.DateInput(
                attrs={"type": "date", "class": DATE_INPUT}, format="%Y-%m-%d"
            )
        for name in SPEC_FIELDS:
            self.fields[name].widget.attrs["class"] = CHECKBOX_INPUT
        for name in [
            "status", "payement", "decharge_facture",
            "rapport_inspecteurs", "rapport_assistante",
        ]:
            self.fields[name].widget.attrs["class"] = SELECT_INPUT
        for name in [
            "deadline_inspecteurs", "deadline_assistante",
            "date_remise_inspecteurs", "date_remise_assistante",
            "date_paiement_facture", "date_decharge_facture",
        ]:
            self.fields[name].widget = forms.DateInput(
                attrs={"type": "date", "class": DATE_INPUT}, format="%Y-%m-%d"
            )
        # Toutes les dates de la chaîne sont pré-calculées dans clean() mais
        # modifiables (décalages de planning) sous contrainte de l'écart minimum.

        # Suivi du rapport : pré-rempli depuis la visite courante
        visite = self.instance.visite_courante if self.instance.pk else None
        if visite is not None:
            self.fields["rapport_inspecteurs"].initial = visite.rapport_inspecteurs
            self.fields["deadline_inspecteurs"].initial = next_monday_deadline(
                visite.date_visite
            )
            self.fields["date_remise_inspecteurs"].initial = visite.date_remise_inspecteurs
            if visite.date_remise_inspecteurs:
                self.fields["deadline_assistante"].initial = (
                    visite.date_remise_inspecteurs
                    + timedelta(days=ASSISTANTE_DELAY_DAYS)
                )
            self.fields["rapport_assistante"].initial = visite.rapport_assistante
            self.fields["date_remise_assistante"].initial = visite.date_remise_assistante
            self.fields["date_paiement_facture"].initial = visite.date_paiement_facture
            self.fields["date_decharge_facture"].initial = visite.date_decharge_facture
            self.fields["rapport_visite_date"].initial = visite.date_visite
        else:
            self.fields["rapport_inspecteurs"].disabled = True
            self.fields["rapport_assistante"].disabled = True

    # --- Calcul automatique des dates de visite (règles métier) ------------
    # Chaîne : dernière 1ère -> dernière 2ème -> prochaine 1ère -> prochaine 2ème,
    # chaque maillon à +6 mois par défaut (relativedelta gère les fins de mois).
    # Une date saisie à la main est conservée si l'écart est d'au moins 6 mois
    # avec la précédente, et sert de point de départ aux suivantes.
    def clean(self):
        cleaned = super().clean()
        self._check_facture_apres_rapport_assistante(cleaned)
        d1 = cleaned.get("derniere_1ere_visite")
        d2 = cleaned.get("derniere_2eme_visite")
        p1 = cleaned.get("prochaine_1ere_visite")
        p2 = cleaned.get("prochaine_2eme_visite")
        inst = self.instance
        six = relativedelta(months=6)

        if d1 is None:
            cleaned["derniere_2eme_visite"] = None
            cleaned["prochaine_1ere_visite"] = None
            cleaned["prochaine_2eme_visite"] = None
            return cleaned

        d1_changed = d1 != inst.derniere_1ere_visite
        d2_changed = d2 != inst.derniere_2eme_visite
        if d2 is None or (d1_changed and not d2_changed):
            d2 = d1 + six
            d2_changed = True
        upstream_changed = d1_changed or d2_changed

        # Prochaine 1ère : vide ou amont modifié -> calculée ; sinon saisie conservée
        p1_changed = p1 != inst.prochaine_1ere_visite
        if p1 is None or (upstream_changed and not p1_changed):
            p1 = d2 + six
            p1_changed = True
        elif p1_changed and p1 < d2 + six:
            self.add_error(
                "prochaine_1ere_visite",
                f"Doit être au moins 6 mois après la dernière 2ème visite "
                f"(à partir du {d2 + six:%d/%m/%Y}).",
            )

        # Prochaine 2ème : même logique, relative à la prochaine 1ère
        p2_changed = p2 != inst.prochaine_2eme_visite
        if p2 is None or ((upstream_changed or p1_changed) and not p2_changed):
            p2 = p1 + six
        elif p2_changed and p2 < p1 + six:
            self.add_error(
                "prochaine_2eme_visite",
                f"Doit être au moins 6 mois après la prochaine 1ère visite "
                f"(à partir du {p1 + six:%d/%m/%Y}).",
            )

        cleaned["derniere_2eme_visite"] = d2
        cleaned["prochaine_1ere_visite"] = p1
        cleaned["prochaine_2eme_visite"] = p2
        return cleaned

    # --- Facture : jamais avant la remise du rapport assistante -------------
    def _check_facture_apres_rapport_assistante(self, cleaned):
        visite = self.instance.visite_courante if self.instance.pk else None
        if visite is None or cleaned.get("rapport_assistante") != "Remis":
            return
        remise = (
            cleaned.get("date_remise_assistante")
            or visite.date_remise_assistante
            or date.today()
        )
        for statut_field, date_field, label in [
            ("payement", "date_paiement_facture", "de paiement"),
            ("decharge_facture", "date_decharge_facture", "de décharge"),
        ]:
            saisie = cleaned.get(date_field)
            if cleaned.get(statut_field) == "Oui" and saisie and saisie < remise:
                self.add_error(
                    date_field,
                    f"La date {label} de la facture ne peut pas être avant la "
                    f"remise du rapport assistante ({remise:%d/%m/%Y}).",
                )

    # --- Enregistrement : client + rapport de la visite courante -----------
    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            sync_visites(instance)
            self._save_rapport(instance)
        return instance

    def _save_rapport(self, client):
        """Applique les statuts de rapport à la visite qui était affichée."""
        target_date = self.cleaned_data.get("rapport_visite_date")
        if not target_date:
            return
        visite = client.visites.filter(date_visite=target_date).first()
        if visite is None:
            return
        new_insp = self.cleaned_data.get("rapport_inspecteurs") or "Non remis"
        new_assist = self.cleaned_data.get("rapport_assistante") or "Non remis"
        # « Remis » : la date exacte de remise saisie est conservée ; sans saisie,
        # on garde la date déjà enregistrée, sinon la date du jour (démarre le
        # délai de 15 jours pour l'assistante)
        if new_insp == "Remis":
            visite.date_remise_inspecteurs = (
                self.cleaned_data.get("date_remise_inspecteurs")
                or visite.date_remise_inspecteurs
                or date.today()
            )
        else:
            visite.date_remise_inspecteurs = None
        if new_assist == "Remis":
            visite.date_remise_assistante = (
                self.cleaned_data.get("date_remise_assistante")
                or visite.date_remise_assistante
                or date.today()
            )
        else:
            visite.date_remise_assistante = None
        # Paiement / décharge facture : dates modifiables, conservées sur la
        # visite courante ; « Oui » sans date saisie → date du jour
        for statut_field, date_field in [
            ("payement", "date_paiement_facture"),
            ("decharge_facture", "date_decharge_facture"),
        ]:
            if self.cleaned_data.get(statut_field) == "Oui":
                saisie = self.cleaned_data.get(date_field)
                setattr(visite, date_field, saisie or date.today())
            else:
                setattr(visite, date_field, None)
        visite.rapport_inspecteurs = new_insp
        visite.rapport_assistante = new_assist
        visite.save()


class ClientFilterForm(forms.Form):
    """Filtres du tableau des clients (formulaire GET)."""

    FILTER_INPUT = (
        "w-full rounded border border-slate-300 bg-white px-3 py-1.5 text-sm "
        "text-slate-800 placeholder-slate-400 focus:border-[#17293D] "
        "focus:outline-none focus:ring-2 focus:ring-[#17293D]/20"
    )

    q_nom = forms.CharField(
        required=False,
        label="Client",
        widget=forms.TextInput(
            attrs={"class": FILTER_INPUT, "placeholder": "Nom du client…"}
        ),
    )
    q_adresse = forms.CharField(
        required=False,
        label="Adresse",
        widget=forms.TextInput(
            attrs={"class": FILTER_INPUT, "placeholder": "Ville, quartier…"}
        ),
    )
    q_abonnement = forms.CharField(
        required=False,
        label="N° abonnement",
        widget=forms.TextInput(
            attrs={"class": FILTER_INPUT + " font-mono", "placeholder": "113/2017…"}
        ),
    )
    status = forms.ChoiceField(
        required=False,
        label="Status",
        choices=[("", "Tous"), ("Actif", "Actif"), ("Non Actif", "Non Actif")],
        widget=forms.Select(attrs={"class": FILTER_INPUT}),
    )

    def filter_queryset(self, queryset):
        if not self.is_valid():
            return queryset
        data = self.cleaned_data
        if data.get("q_nom"):
            queryset = queryset.filter(nom__icontains=data["q_nom"])
        if data.get("q_adresse"):
            queryset = queryset.filter(adresse__icontains=data["q_adresse"])
        if data.get("q_abonnement"):
            queryset = queryset.filter(numero_abonnement__icontains=data["q_abonnement"])
        if data.get("status"):
            queryset = queryset.filter(status=data["status"])
        return queryset
