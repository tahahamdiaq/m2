"""Calcul dynamique des rappels et alertes de suivi des rapports.

Rien n'est stocké en base : les alertes sont recalculées à chaque affichage à
partir de la visite courante du client (la plus récente). Dès qu'un champ
concerné est mis à jour (ex. rapport marqué « Remis »), l'alerte disparaît au
calcul suivant. Quand une nouvelle visite démarre, une nouvelle fiche de
rapport est ouverte et le suivi (et ses alertes) repart de zéro pour elle.

Règles :
  Étape A — Rapport inspecteurs
    Référence  : date de la visite courante
    Date limite: le lundi de la semaine SUIVANT la visite (quel que soit le
                 jour de la visite — un dimanche, la limite est le lendemain)
    → type 1 (rappel) tant que la limite n'est pas dépassée
    → type 2 (alerte) au-delà

  Étape B — Rapport assistante (uniquement si rapport inspecteurs « Remis »)
    Référence  : date_remise_inspecteurs
    Date limite: référence + 15 jours
    → type 3 (rappel) dans les 15 jours, type 4 (alerte) au-delà

  Étape C — Facturation (uniquement si rapport assistante « Remis »)
    Référence  : date_remise_assistante
    Date limite: référence + 15 jours, pour le paiement ET pour la décharge
                 de la facture (chacun suivi séparément, tant que sa date
                 n'est pas renseignée sur la visite)
    → type 6 / 8 (rappel paiement / décharge) dans les 15 jours
    → type 7 / 9 (alerte paiement / décharge) au-delà

  Visite à venir
    → type 5 (rappel) à partir de 10 jours avant chaque visite programmée
      (2ème visite à venir, prochaines visites) : « il reste X jour(s) »
"""
from dataclasses import dataclass
from datetime import date, timedelta

ASSISTANTE_DELAY_DAYS = 15
FACTURE_DELAY_DAYS = 15
VISITE_REMINDER_DAYS = 10

KIND_RAPPEL = "rappel"
KIND_ALERTE = "alerte"


@dataclass(frozen=True)
class Alert:
    client_id: int
    client_nom: str
    date_visite: date   # visite concernée par le rapport
    type: int           # 1..4 (cf. règles ci-dessus)
    kind: str           # 'rappel' ou 'alerte'
    message: str
    deadline: date
    days: int           # jours restants (rappel) ou jours de retard (alerte)

    @property
    def is_alerte(self) -> bool:
        return self.kind == KIND_ALERTE

    @property
    def visite_label(self) -> str:
        return f"visite du {self.date_visite:%d/%m/%Y}"

    # Catégorie (et sa couleur) : inspecteurs / assistante / visite à venir
    @property
    def categorie(self) -> str:
        return {1: "inspecteurs", 2: "inspecteurs",
                3: "assistante", 4: "assistante",
                5: "visite",
                6: "facturation", 7: "facturation",
                8: "facturation", 9: "facturation"}[self.type]

    @property
    def categorie_label(self) -> str:
        return {"inspecteurs": "Inspecteurs", "assistante": "Assistante",
                "visite": "Visite à venir",
                "facturation": "Facturation"}[self.categorie]

    @property
    def couleur(self) -> str:
        """Couleur Tailwind de la catégorie (fond et étiquette ; la gravité
        reste rouge pour les alertes, ambre pour les rappels)."""
        return {"inspecteurs": "bleu", "assistante": "rose",
                "visite": "sarcelle", "facturation": "marine"}[self.categorie]


def next_monday_deadline(visit_date: date) -> date:
    """Le lundi de la semaine suivant `visit_date`.

    Visite un lundi → lundi suivant (+7 j) ; visite un dimanche → lendemain.
    """
    return visit_date + timedelta(days=7 - visit_date.weekday())


def _inspecteurs_alert(client, visite, today: date):
    deadline = next_monday_deadline(visite.date_visite)
    if today <= deadline:
        days = (deadline - today).days
        return Alert(
            client_id=client.pk,
            client_nom=client.nom,
            date_visite=visite.date_visite,
            type=1,
            kind=KIND_RAPPEL,
            message=(
                "Il faut rendre le rapport et l'avis de passage à l'assistante. "
                f"Il s'agit du Client {client.nom} dans {days} jour(s)"
            ),
            deadline=deadline,
            days=days,
        )
    days = (today - deadline).days
    return Alert(
        client_id=client.pk,
        client_nom=client.nom,
        date_visite=visite.date_visite,
        type=2,
        kind=KIND_ALERTE,
        message=(
            "Retard dans le rendu du rapport et l'avis de passage du client "
            f"{client.nom}, retard de {days} jour(s)"
        ),
        deadline=deadline,
        days=days,
    )


def _assistante_alert(client, visite, today: date):
    deadline = visite.date_remise_inspecteurs + timedelta(days=ASSISTANTE_DELAY_DAYS)
    if today <= deadline:
        days = (deadline - today).days
        return Alert(
            client_id=client.pk,
            client_nom=client.nom,
            date_visite=visite.date_visite,
            type=3,
            kind=KIND_RAPPEL,
            message=f"Il faut rendre le rapport du Client {client.nom} dans {days} jour(s)",
            deadline=deadline,
            days=days,
        )
    days = (today - deadline).days
    return Alert(
        client_id=client.pk,
        client_nom=client.nom,
        date_visite=visite.date_visite,
        type=4,
        kind=KIND_ALERTE,
        message=(
            f"Retard dans le rendu du rapport du Client {client.nom}, "
            f"retard de {days} jour(s)"
        ),
        deadline=deadline,
        days=days,
    )


def _facture_alerts(client, visite, today: date) -> list[Alert]:
    """Étape C — paiement et décharge de la facture, 15 jours après la remise
    du rapport assistante."""
    deadline = visite.date_remise_assistante + timedelta(days=FACTURE_DELAY_DAYS)
    alerts = []
    for date_field, nom, type_rappel in [
        ("date_paiement_facture", "le paiement de la facture", 6),
        ("date_decharge_facture", "la décharge de la facture", 8),
    ]:
        if getattr(visite, date_field):
            continue
        if today <= deadline:
            days = (deadline - today).days
            alerts.append(Alert(
                client_id=client.pk, client_nom=client.nom,
                date_visite=visite.date_visite, type=type_rappel,
                kind=KIND_RAPPEL,
                message=(
                    f"Il faut régler {nom} du Client {client.nom} "
                    f"dans {days} jour(s)"
                ),
                deadline=deadline, days=days,
            ))
        else:
            days = (today - deadline).days
            alerts.append(Alert(
                client_id=client.pk, client_nom=client.nom,
                date_visite=visite.date_visite, type=type_rappel + 1,
                kind=KIND_ALERTE,
                message=(
                    f"Retard sur {nom} du Client {client.nom}, "
                    f"retard de {days} jour(s)"
                ),
                deadline=deadline, days=days,
            ))
    return alerts


def _upcoming_visit_alerts(client, today: date) -> list[Alert]:
    """Type 5 — rappel à partir de 10 jours avant chaque visite programmée."""
    upcoming = {
        d
        for d in (
            client.derniere_1ere_visite,
            client.derniere_2eme_visite,
            client.prochaine_1ere_visite,
            client.prochaine_2eme_visite,
        )
        if d and today < d <= today + timedelta(days=VISITE_REMINDER_DAYS)
    }
    alerts = []
    for d in sorted(upcoming):
        days = (d - today).days
        alerts.append(
            Alert(
                client_id=client.pk,
                client_nom=client.nom,
                date_visite=d,
                type=5,
                kind=KIND_RAPPEL,
                message=(
                    f"Visite à venir : il reste {days} jour(s) avant la visite "
                    f"du {d:%d/%m/%Y} du Client {client.nom}"
                ),
                deadline=d,
                days=days,
            )
        )
    return alerts


def get_client_alerts(client, today: date | None = None) -> list[Alert]:
    """Alertes/rappels actifs du client : rapport de la visite courante
    et visites à venir."""
    from .visites import sync_visites

    today = today or date.today()
    sync_visites(client, today=today)

    alerts: list[Alert] = _upcoming_visit_alerts(client, today)

    visite = client.visites.first()
    if visite is None or visite.date_visite > today:
        return alerts

    # Étape A — rapport inspecteurs
    if visite.rapport_inspecteurs != "Remis":
        alerts.append(_inspecteurs_alert(client, visite, today))
    # Étape B — rapport assistante (seulement si inspecteurs remis)
    if (
        visite.rapport_inspecteurs == "Remis"
        and visite.date_remise_inspecteurs
        and visite.rapport_assistante != "Remis"
    ):
        alerts.append(_assistante_alert(client, visite, today))
    # Étape C — facturation (seulement si rapport assistante remis)
    if visite.rapport_assistante == "Remis" and visite.date_remise_assistante:
        alerts.extend(_facture_alerts(client, visite, today))
    return alerts


def get_all_alerts(queryset=None, today: date | None = None) -> list[Alert]:
    """Alertes/rappels actifs de tous les clients, alertes d'abord."""
    from clients.models import Client

    if queryset is None:
        queryset = Client.objects.all()
    all_alerts: list[Alert] = []
    for client in queryset:
        all_alerts.extend(get_client_alerts(client, today=today))
    # Alertes (retard) avant rappels, puis plus gros retard / échéance proche
    all_alerts.sort(key=lambda a: (0 if a.is_alerte else 1, -a.days if a.is_alerte else a.days))
    return all_alerts
