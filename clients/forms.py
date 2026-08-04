from datetime import date

from dateutil.relativedelta import relativedelta
from django import forms

from .models import REMIS, Client
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
    date_remise_inspecteurs = forms.DateField(
        label="Date remise rapport inspecteurs", required=False, disabled=True
    )
    rapport_assistante = forms.ChoiceField(
        label="Rapport assistante", choices=REMIS, required=False
    )
    date_remise_assistante = forms.DateField(
        label="Date remise rapport assistante", required=False, disabled=True
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
            "date_remise_inspecteurs", "date_remise_assistante",
            "date_paiement_facture", "date_decharge_facture",
        ]:
            self.fields[name].widget = forms.DateInput(
                attrs={"type": "date", "class": DATE_INPUT}, format="%Y-%m-%d"
            )
        # Les prochaines visites sont calculées automatiquement dans clean().
        # La dernière 2ème visite est pré-calculée (1ère visite + 6 mois) mais
        # reste modifiable pour couvrir les décalages de planning.
        self.fields["prochaine_1ere_visite"].disabled = True
        self.fields["prochaine_2eme_visite"].disabled = True

        # Suivi du rapport : pré-rempli depuis la visite courante
        visite = self.instance.visite_courante if self.instance.pk else None
        if visite is not None:
            self.fields["rapport_inspecteurs"].initial = visite.rapport_inspecteurs
            self.fields["date_remise_inspecteurs"].initial = visite.date_remise_inspecteurs
            self.fields["rapport_assistante"].initial = visite.rapport_assistante
            self.fields["date_remise_assistante"].initial = visite.date_remise_assistante
            self.fields["date_paiement_facture"].initial = visite.date_paiement_facture
            self.fields["date_decharge_facture"].initial = visite.date_decharge_facture
            self.fields["rapport_visite_date"].initial = visite.date_visite
        else:
            self.fields["rapport_inspecteurs"].disabled = True
            self.fields["rapport_assistante"].disabled = True

    # --- Calcul automatique des dates de visite (règles métier) ------------
    def clean(self):
        cleaned = super().clean()
        d1 = cleaned.get("derniere_1ere_visite")
        # 2ème visite : par défaut 6 mois après la 1ère, mais une date saisie
        # manuellement (décalage de planning) est conservée telle quelle
        d2 = cleaned.get("derniere_2eme_visite")
        if d2 is None and d1:
            d2 = d1 + relativedelta(months=6)
        elif d1 is None:
            d2 = None
        cleaned["derniere_2eme_visite"] = d2
        cleaned["prochaine_1ere_visite"] = (
            d1 + relativedelta(years=1) if d1 else None
        )
        cleaned["prochaine_2eme_visite"] = (
            d2 + relativedelta(years=1) if d2 else None
        )
        return cleaned

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
        if new_insp == "Remis" and visite.rapport_inspecteurs != "Remis":
            # Passage à « Remis » → démarre le délai de 15 jours
            visite.date_remise_inspecteurs = date.today()
        elif new_insp != "Remis":
            # Retour à « Non remis » → on efface la date de remise
            visite.date_remise_inspecteurs = None
        if new_assist == "Remis" and visite.rapport_assistante != "Remis":
            visite.date_remise_assistante = date.today()
        elif new_assist != "Remis":
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
