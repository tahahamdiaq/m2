from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import ClientForm
from .models import Client, Visite
from .services.alerts import (
    get_all_alerts,
    get_client_alerts,
    next_monday_deadline,
)
from .services.planning import (
    calendrier_mois,
    get_visites_prevues,
    repartition_par_mois,
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


class PlanningVisitesTests(TestCase):
    """Liste des visites à venir et répartition mensuelle."""

    def test_collecte_les_dates_futures_seulement(self):
        make_client(
            derniere_1ere_visite=date(2025, 6, 4),    # passée → ignorée
            derniere_2eme_visite=date(2025, 12, 4),   # à venir
            prochaine_1ere_visite=date(2026, 6, 4),
            prochaine_2eme_visite=date(2026, 12, 4),
        )
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        self.assertEqual(
            [v.date_visite for v in prevues],
            [date(2025, 12, 4), date(2026, 6, 4), date(2026, 12, 4)],
        )

    def test_cycles_et_jours_restants(self):
        make_client(
            derniere_2eme_visite=date(2025, 7, 11),
            prochaine_1ere_visite=date(2026, 1, 15),
        )
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        self.assertEqual(prevues[0].cycle, 2)
        self.assertEqual(prevues[0].jours, 10)
        self.assertTrue(prevues[0].is_imminente)
        self.assertEqual(prevues[1].cycle, 1)
        self.assertFalse(prevues[1].is_imminente)

    def test_dates_en_double_comptees_une_fois(self):
        # Un client sans historique peut avoir deux champs à la même date
        make_client(
            derniere_2eme_visite=date(2026, 3, 10),
            prochaine_2eme_visite=date(2026, 3, 10),
        )
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        self.assertEqual(len(prevues), 1)

    def test_tri_par_date_puis_nom(self):
        make_client(nom="Zenith", prochaine_1ere_visite=date(2026, 1, 10))
        make_client(nom="Alpha", prochaine_1ere_visite=date(2026, 1, 10))
        make_client(nom="Beta", prochaine_1ere_visite=date(2026, 1, 5))
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        self.assertEqual([v.client.nom for v in prevues], ["Beta", "Alpha", "Zenith"])

    def test_repartition_par_mois(self):
        make_client(nom="A", prochaine_1ere_visite=date(2026, 3, 10))
        make_client(nom="B", prochaine_1ere_visite=date(2026, 3, 20))
        make_client(nom="C", prochaine_1ere_visite=date(2026, 9, 1))
        make_client(nom="D", prochaine_1ere_visite=date(2027, 3, 1))
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        rep = repartition_par_mois(prevues, 2026)
        self.assertEqual(len(rep), 12)
        self.assertEqual(rep[2]["count"], 2)      # mars
        self.assertEqual(rep[2]["pourcentage"], 100)
        self.assertEqual(rep[8]["count"], 1)      # septembre
        self.assertEqual(rep[8]["pourcentage"], 50)
        self.assertEqual(rep[0]["count"], 0)      # janvier

    def test_calendrier_marque_les_jours_avec_visite(self):
        make_client(nom="A", prochaine_1ere_visite=date(2026, 3, 10))
        make_client(nom="B", prochaine_2eme_visite=date(2026, 3, 10))
        make_client(nom="C", prochaine_2eme_visite=date(2026, 3, 24))
        prevues = get_visites_prevues(today=date(2025, 7, 1))
        semaines = calendrier_mois(prevues, 2026, 3, today=date(2025, 7, 1))

        cases = {c["date"]: c for s in semaines for c in s}
        jour_mixte = cases[date(2026, 3, 10)]
        self.assertEqual(jour_mixte["nb"], 2)
        self.assertTrue(jour_mixte["a_cycle_1"])
        self.assertTrue(jour_mixte["a_cycle_2"])

        jour_cycle2 = cases[date(2026, 3, 24)]
        self.assertEqual(jour_cycle2["nb"], 1)
        self.assertFalse(jour_cycle2["a_cycle_1"])

        self.assertEqual(cases[date(2026, 3, 11)]["nb"], 0)

    def test_calendrier_semaines_commencent_lundi(self):
        semaines = calendrier_mois([], 2026, 3, today=date(2026, 3, 1))
        for semaine in semaines:
            self.assertEqual(len(semaine), 7)
            self.assertEqual(semaine[0]["date"].weekday(), 0)   # lundi
            self.assertEqual(semaine[-1]["date"].weekday(), 6)  # dimanche

    def test_calendrier_marque_jours_hors_mois_et_aujourdhui(self):
        semaines = calendrier_mois([], 2026, 3, today=date(2026, 3, 15))
        cases = {c["date"]: c for s in semaines for c in s}
        self.assertTrue(cases[date(2026, 3, 15)]["is_today"])
        self.assertTrue(cases[date(2026, 3, 15)]["dans_le_mois"])
        # 1er mars 2026 est un dimanche → la grille commence en février
        self.assertFalse(cases[date(2026, 2, 23)]["dans_le_mois"])

    def test_page_planning_filtre_par_mois(self):
        User = get_user_model()
        User.objects.create_user(
            email="planning@exemple.com", password="Registre2025!",
            full_name="Test", email_verified=True,
        )
        self.client.login(email="planning@exemple.com", password="Registre2025!")
        futur = date.today() + timedelta(days=60)
        make_client(nom="Client Planning", prochaine_1ere_visite=futur)
        response = self.client.get(
            reverse("clients:planning"),
            {"annee": futur.year, "mois": futur.month},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client Planning")

    def test_page_planning_filtre_par_jour(self):
        User = get_user_model()
        User.objects.create_user(
            email="jour@exemple.com", password="Registre2025!",
            full_name="Test", email_verified=True,
        )
        self.client.login(email="jour@exemple.com", password="Registre2025!")
        futur = date.today() + timedelta(days=60)
        make_client(nom="Client Du Jour", prochaine_1ere_visite=futur)
        make_client(nom="Client Autre Jour", prochaine_1ere_visite=futur + timedelta(days=1))
        response = self.client.get(
            reverse("clients:planning"),
            {"annee": futur.year, "mois": futur.month, "jour": futur.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["visites"]), 1)
        self.assertEqual(response.context["visites"][0].client.nom, "Client Du Jour")

    def test_page_planning_annee_sans_visite_reste_navigable(self):
        User = get_user_model()
        User.objects.create_user(
            email="nav@exemple.com", password="Registre2025!",
            full_name="Test", email_verified=True,
        )
        self.client.login(email="nav@exemple.com", password="Registre2025!")
        cible = date.today().year + 5
        response = self.client.get(reverse("clients:planning"), {"annee": cible})
        self.assertEqual(response.context["annee"], cible)


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
        # Prochaines visites : champs calculés, les valeurs postées sont écrasées
        form = self.form_with_dates(
            derniere_1ere_visite="2025-01-15",
            prochaine_1ere_visite="2026-02-15",
            prochaine_2eme_visite="2026-08-01",
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2025, 7, 15))
        self.assertEqual(saved.prochaine_1ere_visite, date(2026, 1, 15))
        self.assertEqual(saved.prochaine_2eme_visite, date(2026, 7, 15))

    def test_2eme_visite_saisie_manuellement_est_conservee(self):
        # Décalage de planning : la date saisie prime sur le calcul par défaut
        form = self.form_with_dates(
            derniere_1ere_visite="2025-01-15",
            derniere_2eme_visite="2025-08-01",
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2025, 8, 1))
        # La prochaine 2ème visite suit la date saisie, pas le défaut
        self.assertEqual(saved.prochaine_2eme_visite, date(2026, 8, 1))
        self.assertEqual(saved.prochaine_1ere_visite, date(2026, 1, 15))

    def test_2eme_visite_videe_revient_au_defaut(self):
        client = make_client(
            derniere_1ere_visite=date(2025, 1, 15),
            derniere_2eme_visite=date(2025, 8, 1),
        )
        form = ClientForm(
            {
                "nom": client.nom, "adresse": client.adresse,
                "numero_abonnement": client.numero_abonnement,
                "status": client.status, "payement": client.payement,
                "decharge_facture": client.decharge_facture,
                "derniere_1ere_visite": "2025-01-15",
                # 2ème visite laissée vide → recalcul 1ère visite + 6 mois
            },
            instance=client,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.derniere_2eme_visite, date(2025, 7, 15))

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
