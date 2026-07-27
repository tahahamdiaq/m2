from django.db import models
from django.urls import reverse

YES_NO = [("Oui", "Oui"), ("Non", "Non")]
REMIS = [("Remis", "Remis"), ("Non remis", "Non remis")]

# Les 10 spécialités contrôlées (code, libellé)
SPECIALITES = [
    ("EL", "Électricité"),
    ("SI", "Sécurité incendie"),
    ("APG", "Appareils à pression de gaz"),
    ("MCNA", "Machines et engins"),
    ("LEV", "Levage"),
    ("APV", "Appareils à pression de vapeur"),
    ("GAZ", "Gaz"),
    ("ASC", "Ascenseurs"),
    ("GE", "Groupe électrogène"),
    ("GEC", "Groupe électrogène de secours"),
]


class Client(models.Model):
    """Client suivi dans le registre de contrôle technique.

    Fréquence : contrôle annuel pour toutes les spécialités ; EL (électricité)
    est semestriel — d'où les deux cycles de visite espacés de 6 mois
    (1ère visite / 2ème visite), chacun revenant tous les ans.
    """

    class Status(models.TextChoices):
        ACTIF = "Actif", "Actif"
        NON_ACTIF = "Non Actif", "Non Actif"

    nom = models.CharField("Nom du client", max_length=255)
    adresse = models.CharField("Adresse (ville, quartier)", max_length=255)
    numero_abonnement = models.CharField(
        "N° d'abonnement", max_length=50, help_text="Format libre, ex. 113/2017"
    )
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.ACTIF
    )
    payement = models.CharField(
        "Paiement (facture sortie)", max_length=3, choices=YES_NO, default="Non"
    )
    decharge_facture = models.CharField(
        "Décharge facture", max_length=3, choices=YES_NO, default="Non"
    )

    # Spécialités (option A : booléens)
    spec_el = models.BooleanField("EL — Électricité", default=False)
    spec_si = models.BooleanField("SI — Sécurité incendie", default=False)
    spec_apg = models.BooleanField("APG — Appareils à pression de gaz", default=False)
    spec_mcna = models.BooleanField("MCNA — Machines et engins", default=False)
    spec_lev = models.BooleanField("LEV — Levage", default=False)
    spec_apv = models.BooleanField("APV — Appareils à pression de vapeur", default=False)
    spec_gaz = models.BooleanField("GAZ — Gaz", default=False)
    spec_asc = models.BooleanField("ASC — Ascenseurs", default=False)
    spec_ge = models.BooleanField("GE — Groupe électrogène", default=False)
    spec_gec = models.BooleanField("GEC — Groupe électrogène de secours", default=False)

    # Visites
    visite_initiale = models.DateField("Visite initiale", null=True, blank=True)
    derniere_1ere_visite = models.DateField("Dernière 1ère visite", null=True, blank=True)
    prochaine_1ere_visite = models.DateField("Prochaine 1ère visite", null=True, blank=True)
    derniere_2eme_visite = models.DateField("Dernière 2ème visite", null=True, blank=True)
    prochaine_2eme_visite = models.DateField("Prochaine 2ème visite", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "client"

    def __str__(self):
        return f"{self.nom} ({self.numero_abonnement})"

    def get_absolute_url(self):
        return reverse("clients:client_detail", args=[self.pk])

    @property
    def specialites_actives(self) -> list[tuple[str, str]]:
        """Liste (code, libellé) des spécialités cochées."""
        return [
            (code, label)
            for code, label in SPECIALITES
            if getattr(self, f"spec_{code.lower()}")
        ]

    def get_alerts(self):
        from .services.alerts import get_client_alerts

        return get_client_alerts(self)

    @property
    def visite_courante(self):
        """La visite la plus récente — son rapport est celui affiché/édité."""
        return self.visites.first()


class Visite(models.Model):
    """Une visite effectuée chez un client, avec le suivi de son rapport.

    À chaque nouvelle visite (date atteinte), une nouvelle fiche est créée
    avec un rapport « Non remis » : le suivi repart de zéro pour cette visite,
    et les fiches des visites précédentes restent en historique.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="visites"
    )
    date_visite = models.DateField("Date de la visite")
    rapport_inspecteurs = models.CharField(
        "Rapport inspecteurs", max_length=10, choices=REMIS, default="Non remis"
    )
    date_remise_inspecteurs = models.DateField(
        "Date remise rapport inspecteurs", null=True, blank=True
    )
    rapport_assistante = models.CharField(
        "Rapport assistante", max_length=10, choices=REMIS, default="Non remis"
    )
    date_remise_assistante = models.DateField(
        "Date remise rapport assistante", null=True, blank=True
    )
    date_paiement_facture = models.DateField(
        "Date paiement facture", null=True, blank=True
    )
    date_decharge_facture = models.DateField(
        "Date décharge facture", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_visite"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "date_visite"], name="visite_unique_par_date"
            )
        ]
        verbose_name = "visite"

    def __str__(self):
        return f"{self.client.nom} — visite du {self.date_visite:%d/%m/%Y}"
