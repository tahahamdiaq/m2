from datetime import date, timedelta

from django.test import TestCase

from .forms import ClientForm
from .models import Client, Visite
from .services.alerts import (
    get_all_alerts,
    get_client_alerts,
    next_monday_deadline,
)
from .services.visites import sync_visites


def make_client(**kwargs):
    defaults = {
        "nom": "Société Test",
        "adresse": "Casablanca, Maarif",
        "numero_abonnement": "113/2017",
    }
    defaults.update(kwargs)
    return Client.objects.create(**defaults)


def make_visite(client, date_visite, **kwargs):
    return Visite.objects.create(client=client, date_visite=date_visite, **kwargs)


class NextMondayDeadlineTests(TestCase):
    """La date limite est le lundi de la semaine suivant la visite."""

    def test_visite_un_lundi(self):
        # Lundi 2 juin 2025 → lundi suivant 9 juin
        self.assertEqual(next_monday_deadline(date(2025, 6, 2)), date(2025, 6, 9))

    def test_visite_un_mercredi(self):
        # Mercredi 4 juin 2025 → lundi 9 juin
        self.assertEqual(next_monday_deadline(date(2025, 6, 4)), date(2025, 6, 9))

    def test_visite_un_samedi(self):
        # Samedi 7 juin 2025 → lundi 9 juin
        self.assertEqual(next_monday_deadline(date(2025, 6, 7)), date(2025, 6, 9))

    def test_visite_un_dimanche(self):
        # Dimanche 8 juin 2025 (fin de semaine ISO) → lundi 9 juin (lendemain)
        self.assertEqual(next_monday_deadline(date(2025, 6, 8)), date(2025, 6, 9))

    def test_resultat_toujours_un_lundi(self):
        for offset in range(14):
            deadline = next_monday_deadline(date(2025, 6, 2) + timedelta(days=offset))
            self.assertEqual(deadline.weekday(), 0)


class SyncVisitesTests(TestCase):
    """Ouverture automatique des fiches de visite aux dates échues."""

    def test_cree_une_fiche_pour_une_visite_passee(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        sync_visites(client, today=date(2025, 6, 6))
        self.assertEqual(client.visites.count(), 1)
        visite = client.visites.get()
        self.assertEqual(visite.date_visite, date(2025, 6, 4))
        self.assertEqual(visite.rapport_inspecteurs, "Non remis")

    def test_pas_de_fiche_pour_une_visite_future(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        sync_visites(client, today=date(2025, 6, 6))
        self.assertEqual(client.visites.count(), 1)  # la 2ème visite n'a pas eu lieu

    def test_ouvre_la_2eme_visite_quand_sa_date_arrive(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        sync_visites(client, today=date(2025, 12, 5))
        self.assertEqual(client.visites.count(), 2)
        self.assertEqual(client.visite_courante.date_visite, date(2025, 12, 4))

    def test_idempotent(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        sync_visites(client, today=date(2025, 6, 6))
        sync_visites(client, today=date(2025, 6, 7))
        self.assertEqual(client.visites.count(), 1)


class RapportInspecteursAlertTests(TestCase):
    """Étape A — rappel type 1 / alerte type 2 sur le rapport inspecteurs."""

    def test_rappel_type_1_avant_echeance(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))  # limite : 9 juin
        alerts = get_client_alerts(client, today=date(2025, 6, 6))
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.type, 1)
        self.assertEqual(alert.kind, "rappel")
        self.assertEqual(alert.date_visite, date(2025, 6, 4))
        self.assertEqual(alert.days, 3)
        self.assertIn("Société Test", alert.message)
        self.assertIn("dans 3 jour(s)", alert.message)

    def test_rappel_le_jour_de_l_echeance(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        alerts = get_client_alerts(client, today=date(2025, 6, 9))
        self.assertEqual(alerts[0].type, 1)
        self.assertEqual(alerts[0].days, 0)

    def test_alerte_type_2_apres_echeance(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        alerts = get_client_alerts(client, today=date(2025, 6, 12))
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.type, 2)
        self.assertEqual(alert.kind, "alerte")
        self.assertEqual(alert.days, 3)  # 12 - 9 juin
        self.assertIn("retard de 3 jour(s)", alert.message)

    def test_visite_un_dimanche_alerte_des_mardi(self):
        # Visite dimanche 8 juin → limite lundi 9 juin → retard dès le 10
        client = make_client(derniere_1ere_visite=date(2025, 6, 8))
        alerts = get_client_alerts(client, today=date(2025, 6, 10))
        self.assertEqual(alerts[0].type, 2)
        self.assertEqual(alerts[0].days, 1)

    def test_pas_d_alerte_si_rapport_remis(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 5),
            rapport_assistante="Remis",
        )
        self.assertEqual(get_client_alerts(client, today=date(2025, 6, 20)), [])

    def test_pas_d_alerte_sans_date_de_visite(self):
        client = make_client()
        self.assertEqual(get_client_alerts(client, today=date(2025, 6, 20)), [])


class RapportAssistanteAlertTests(TestCase):
    """Étape B — rappel type 3 / alerte type 4, déclenchés par la remise."""

    def _client_avec_remise(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),  # limite : 25 juin
        )
        return client

    def test_rappel_type_3_dans_les_15_jours(self):
        client = self._client_avec_remise()
        alerts = get_client_alerts(client, today=date(2025, 6, 20))
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.type, 3)
        self.assertEqual(alert.kind, "rappel")
        self.assertEqual(alert.days, 5)
        self.assertIn("dans 5 jour(s)", alert.message)

    def test_alerte_type_4_apres_15_jours(self):
        client = self._client_avec_remise()
        alerts = get_client_alerts(client, today=date(2025, 6, 30))
        self.assertEqual(alerts[0].type, 4)
        self.assertEqual(alerts[0].kind, "alerte")
        self.assertEqual(alerts[0].days, 5)  # 30 - 25 juin

    def test_pas_d_etape_b_si_inspecteurs_non_remis(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            date_remise_inspecteurs=date(2025, 6, 10),  # incohérent mais défensif
        )
        alerts = get_client_alerts(client, today=date(2025, 6, 20))
        self.assertTrue(all(a.type in (1, 2) for a in alerts))

    def test_etape_b_disparait_quand_assistante_remet(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
            rapport_assistante="Remis",
        )
        self.assertEqual(get_client_alerts(client, today=date(2025, 6, 30)), [])


class NouvelleVisiteReinitialiseTests(TestCase):
    """Une nouvelle visite ouvre un nouveau rapport ; l'ancien part en historique."""

    def test_les_alertes_portent_sur_la_visite_courante(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        # Rapport de la 1ère visite entièrement remis
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
            rapport_assistante="Remis",
        )
        # La 2ème visite vient d'avoir lieu → nouveau rapport, nouvelles alertes
        alerts = get_client_alerts(client, today=date(2025, 12, 20))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].type, 2)
        self.assertEqual(alerts[0].date_visite, date(2025, 12, 4))

    def test_l_ancien_rapport_reste_en_historique(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
            rapport_assistante="Remis",
        )
        get_client_alerts(client, today=date(2025, 12, 20))  # déclenche le sync
        self.assertEqual(client.visites.count(), 2)
        ancienne = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(ancienne.rapport_inspecteurs, "Remis")
        self.assertEqual(client.visite_courante.rapport_inspecteurs, "Non remis")

    def test_get_all_alerts_trie_les_alertes_en_premier(self):
        make_client(nom="En retard", derniere_1ere_visite=date(2025, 1, 8))
        make_client(nom="Dans les temps", derniere_1ere_visite=date(2025, 6, 6))
        alerts = get_all_alerts(today=date(2025, 6, 6))
        self.assertEqual(alerts[0].kind, "alerte")
        self.assertEqual(alerts[-1].kind, "rappel")


class VisiteAVenirAlertTests(TestCase):
    """Type 5 — rappel à partir de 10 jours avant une visite programmée."""

    def _client_a_jour(self):
        """Client dont le rapport de la visite courante est entièrement remis."""
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
            rapport_assistante="Remis",
        )
        return client

    def test_rappel_avant_la_2eme_visite(self):
        client = self._client_a_jour()
        alerts = get_client_alerts(client, today=date(2025, 11, 28))
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.type, 5)
        self.assertEqual(alert.kind, "rappel")
        self.assertEqual(alert.days, 6)
        self.assertIn("il reste 6 jour(s)", alert.message)
        self.assertIn("04/12/2025", alert.message)

    def test_demarre_exactement_10_jours_avant(self):
        client = self._client_a_jour()
        alerts = get_client_alerts(client, today=date(2025, 11, 24))
        self.assertEqual([a.type for a in alerts], [5])
        self.assertEqual(alerts[0].days, 10)

    def test_rien_a_plus_de_10_jours(self):
        client = self._client_a_jour()
        self.assertEqual(get_client_alerts(client, today=date(2025, 11, 23)), [])

    def test_le_jour_de_la_visite_bascule_sur_le_suivi_rapport(self):
        # Le jour J, plus de rappel « à venir » : la fiche rapport s'ouvre
        # et le suivi type 1 prend le relais
        client = self._client_a_jour()
        alerts = get_client_alerts(client, today=date(2025, 12, 4))
        self.assertEqual([a.type for a in alerts], [1])
        self.assertEqual(alerts[0].date_visite, date(2025, 12, 4))

    def test_rappel_pour_une_prochaine_visite(self):
        client = make_client(prochaine_1ere_visite=date(2025, 12, 10))
        alerts = get_client_alerts(client, today=date(2025, 12, 5))
        self.assertEqual([a.type for a in alerts], [5])
        self.assertEqual(alerts[0].days, 5)


class ClientFormRapportTests(TestCase):
    """Édition du rapport de la visite courante via le formulaire client."""

    def base_data(self, client, **overrides):
        data = {
            "nom": client.nom,
            "adresse": client.adresse,
            "numero_abonnement": client.numero_abonnement,
            "status": client.status,
            "payement": client.payement,
            "decharge_facture": client.decharge_facture,
            "derniere_1ere_visite": client.derniere_1ere_visite,
            "rapport_inspecteurs": "Non remis",
            "rapport_assistante": "Non remis",
            "rapport_visite_date": client.derniere_1ere_visite,
        }
        data.update(overrides)
        return data

    def test_passage_a_remis_enregistre_la_date_du_jour(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(client, date(2025, 6, 4))
        form = ClientForm(
            self.base_data(client, rapport_inspecteurs="Remis"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.rapport_inspecteurs, "Remis")
        self.assertEqual(visite.date_remise_inspecteurs, date.today())

    def test_retour_a_non_remis_efface_la_date(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
        )
        form = ClientForm(self.base_data(client), instance=client)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.rapport_inspecteurs, "Non remis")
        self.assertIsNone(visite.date_remise_inspecteurs)

    def test_remis_stable_ne_change_pas_la_date(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
        )
        form = ClientForm(
            self.base_data(client, rapport_inspecteurs="Remis"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.date_remise_inspecteurs, date(2025, 6, 10))

    def test_assistante_remis_enregistre_la_date_du_jour(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
        )
        form = ClientForm(
            self.base_data(
                client, rapport_inspecteurs="Remis", rapport_assistante="Remis"
            ),
            instance=client,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.rapport_assistante, "Remis")
        self.assertEqual(visite.date_remise_assistante, date.today())

    def test_assistante_non_remis_efface_la_date(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(
            client, date(2025, 6, 4),
            rapport_inspecteurs="Remis",
            date_remise_inspecteurs=date(2025, 6, 10),
            rapport_assistante="Remis",
            date_remise_assistante=date(2025, 6, 20),
        )
        form = ClientForm(
            self.base_data(client, rapport_inspecteurs="Remis"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.rapport_assistante, "Non remis")
        self.assertIsNone(visite.date_remise_assistante)

    def test_decharge_oui_sans_date_prend_la_date_du_jour(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(client, date(2025, 6, 4))
        form = ClientForm(
            self.base_data(client, decharge_facture="Oui"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.date_decharge_facture, date.today())

    def test_decharge_oui_avec_date_saisie(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(client, date(2025, 6, 4))
        form = ClientForm(
            self.base_data(
                client, decharge_facture="Oui", date_decharge_facture="2025-06-18"
            ),
            instance=client,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.date_decharge_facture, date(2025, 6, 18))

    def test_decharge_facture_non_efface_la_date(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4), decharge_facture="Oui"
        )
        make_visite(
            client, date(2025, 6, 4), date_decharge_facture=date(2025, 6, 15)
        )
        form = ClientForm(
            self.base_data(client, decharge_facture="Non"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertIsNone(visite.date_decharge_facture)

    def test_paiement_oui_avec_date_saisie(self):
        client = make_client(derniere_1ere_visite=date(2025, 6, 4))
        make_visite(client, date(2025, 6, 4))
        form = ClientForm(
            self.base_data(
                client, payement="Oui", date_paiement_facture="2025-06-12"
            ),
            instance=client,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(visite.date_paiement_facture, date(2025, 6, 12))

    def test_paiement_non_efface_la_date(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4), payement="Oui"
        )
        make_visite(
            client, date(2025, 6, 4), date_paiement_facture=date(2025, 6, 12)
        )
        form = ClientForm(
            self.base_data(client, payement="Non"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        visite = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertIsNone(visite.date_paiement_facture)

    def test_statuts_appliques_a_la_visite_affichee_pas_a_la_nouvelle(self):
        # Une nouvelle visite a démarré entre l'affichage et la soumission :
        # les statuts postés vont à la visite qui était affichée
        client = make_client(
            derniere_1ere_visite=date(2025, 6, 4),
            derniere_2eme_visite=date(2025, 12, 4),
        )
        make_visite(client, date(2025, 6, 4))
        form = ClientForm(
            self.base_data(client, rapport_inspecteurs="Remis"), instance=client
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()  # le sync ouvre aussi la fiche de la visite du 4 décembre
        ancienne = client.visites.get(date_visite=date(2025, 6, 4))
        self.assertEqual(ancienne.rapport_inspecteurs, "Remis")
        courante = client.visite_courante
        self.assertEqual(courante.date_visite, date(2025, 12, 4))
        self.assertEqual(courante.rapport_inspecteurs, "Non remis")


class ClientFormCoherenceDatesTests(TestCase):
    def form_with_dates(self, **dates):
        data = {
            "nom": "X", "adresse": "Y", "numero_abonnement": "1/2025",
            "status": "Actif", "payement": "Non", "decharge_facture": "Non",
        }
        data.update(dates)
        return ClientForm(data)

    def test_toutes_les_dates_calculees_depuis_la_1ere_visite(self):
        form = self.form_with_dates(derniere_1ere_visite="2025-01-15")
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2025, 7, 15))
        self.assertEqual(saved.prochaine_1ere_visite, date(2026, 1, 15))
        self.assertEqual(saved.prochaine_2eme_visite, date(2026, 7, 15))

    def test_valeurs_saisies_dans_les_champs_calcules_ignorees(self):
        # Champs calculés : les valeurs postées sont simplement écrasées
        form = self.form_with_dates(
            derniere_1ere_visite="2025-01-15",
            derniere_2eme_visite="2025-08-01",
            prochaine_1ere_visite="2026-02-15",
            prochaine_2eme_visite="2026-08-01",
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2025, 7, 15))
        self.assertEqual(saved.prochaine_1ere_visite, date(2026, 1, 15))
        self.assertEqual(saved.prochaine_2eme_visite, date(2026, 7, 15))

    def test_fin_de_mois_ajustee(self):
        # 31 août + 6 mois → 28 février (jour ramené à la fin du mois)
        form = self.form_with_dates(derniere_1ere_visite="2025-08-31")
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2026, 2, 28))
        self.assertEqual(saved.prochaine_2eme_visite, date(2027, 2, 28))

    def test_sans_1ere_visite_tout_reste_vide(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 1, 15),
            derniere_2eme_visite=date(2025, 7, 15),
            prochaine_1ere_visite=date(2026, 1, 15),
            prochaine_2eme_visite=date(2026, 7, 15),
        )
        form = ClientForm(
            {
                "nom": client.nom, "adresse": client.adresse,
                "numero_abonnement": client.numero_abonnement,
                "status": client.status, "payement": client.payement,
                "decharge_facture": client.decharge_facture,
                # Dernière 1ère visite effacée → toutes les dates repartent à vide
            },
            instance=client,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertIsNone(saved.derniere_2eme_visite)
        self.assertIsNone(saved.prochaine_1ere_visite)
        self.assertIsNone(saved.prochaine_2eme_visite)

    def test_enregistrement_ouvre_la_fiche_de_visite(self):
        form = self.form_with_dates(derniere_1ere_visite="2025-01-15")
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(
            saved.visites.filter(date_visite=date(2025, 1, 15)).exists()
        )
