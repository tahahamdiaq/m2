"""Données de démonstration : un compte de test vérifié + des clients types.

Usage : python manage.py seed_demo
Le compte de test (email déjà vérifié, aucun email nécessaire) :
    email : test@registre.local  /  mot de passe : Test-Registre-2025
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from clients.models import Client, Visite

TEST_EMAIL = "test@registre.local"
TEST_PASSWORD = "Test-Registre-2025"


class Command(BaseCommand):
    help = "Crée un compte de test vérifié et des clients de démonstration."

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=TEST_EMAIL,
            defaults={
                "full_name": "Compte Test",
                "email_verified": True,
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(TEST_PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f"Compte de test créé : {TEST_EMAIL} / {TEST_PASSWORD} (email déjà vérifié)"
            ))
        else:
            self.stdout.write(f"Compte de test déjà présent : {TEST_EMAIL}")

        if Client.objects.exists():
            self.stdout.write("Des clients existent déjà — seed des clients ignoré.")
            return

        today = date.today()
        monday_gap = timedelta(days=today.weekday())  # lundi de cette semaine

        demo = [
            # Rappel type 1 : visite avant-hier, rapport inspecteurs non remis
            dict(
                nom="Hôtel Atlas Palace", adresse="Marrakech, Guéliz",
                numero_abonnement="113/2017", status="Actif", payement="Oui",
                decharge_facture="Oui", spec_el=True, spec_si=True, spec_asc=True,
                derniere_1ere_visite=today - timedelta(days=2),
                prochaine_1ere_visite=today - timedelta(days=2) + timedelta(days=365),
            ),
            # Alerte type 2 : visite il y a 3 semaines, rapport toujours non remis
            dict(
                nom="Clinique Al Amal", adresse="Casablanca, Maarif",
                numero_abonnement="87/2019", status="Actif", payement="Non",
                decharge_facture="Non", spec_el=True, spec_gaz=True, spec_ge=True,
                derniere_1ere_visite=today - timedelta(days=21),
            ),
            # Rappel type 3 : inspecteurs remis il y a 5 jours, assistante en attente
            dict(
                nom="Usine Textile du Nord", adresse="Tanger, Zone franche",
                numero_abonnement="204/2020", status="Actif", payement="Oui",
                decharge_facture="Non", spec_el=True, spec_apv=True, spec_lev=True,
                spec_mcna=True,
                derniere_1ere_visite=today - timedelta(days=12),
                visite=dict(
                    rapport_inspecteurs="Remis",
                    date_remise_inspecteurs=today - timedelta(days=5),
                ),
            ),
            # Alerte type 4 : inspecteurs remis il y a 20 jours, assistante en retard
            dict(
                nom="Résidence Les Palmiers", adresse="Rabat, Agdal",
                numero_abonnement="45/2016", status="Actif", payement="Non",
                decharge_facture="Non", spec_asc=True, spec_si=True,
                derniere_1ere_visite=today - timedelta(days=30),
                visite=dict(
                    rapport_inspecteurs="Remis",
                    date_remise_inspecteurs=today - timedelta(days=20),
                ),
            ),
            # Rien à signaler : tout est remis
            dict(
                nom="Supermarché Marjane Hay Riad", adresse="Rabat, Hay Riad",
                numero_abonnement="309/2021", status="Actif", payement="Oui",
                decharge_facture="Oui", spec_el=True, spec_si=True, spec_gec=True,
                derniere_1ere_visite=today - timedelta(days=40),
                visite=dict(
                    rapport_inspecteurs="Remis",
                    date_remise_inspecteurs=today - timedelta(days=35),
                    rapport_assistante="Remis",
                ),
            ),
            # Client inactif sans visite
            dict(
                nom="Garage Mécanique Express", adresse="Fès, Ville nouvelle",
                numero_abonnement="12/2015", status="Non Actif", payement="Non",
                decharge_facture="Non", spec_apg=True,
            ),
        ]
        for data in demo:
            visite_data = data.pop("visite", None)
            client = Client.objects.create(**data)
            if client.derniere_1ere_visite:
                Visite.objects.create(
                    client=client,
                    date_visite=client.derniere_1ere_visite,
                    **(visite_data or {}),
                )
        self.stdout.write(self.style.SUCCESS(f"{len(demo)} clients de démonstration créés."))
        self.stdout.write(f"(rappel : lundi de cette semaine = {today - monday_gap})")
