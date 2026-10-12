"""Planning des visites à venir.

Rien n'est stocké : la liste est recalculée à partir des dates de visite des
clients (2ème visite programmée et prochaines visites de chaque cycle). Une
visite est « à venir » tant que sa date n'est pas dépassée ; le jour J, elle
bascule dans le suivi des rapports (cf. services/alerts.py).
"""
import calendar
from dataclasses import dataclass
from datetime import date

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
JOURS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


@dataclass(frozen=True)
class VisitePrevue:
    client: object
    date_visite: date
    cycle: int      # 1 (1ère visite) ou 2 (2ème visite)
    jours: int      # jours restants avant la visite (négatif si en retard)
    retard_jours: int = 0   # > 0 : visite passée dont le suivi du rapport est en retard

    @property
    def is_retard(self) -> bool:
        return self.retard_jours > 0

    @property
    def cycle_label(self) -> str:
        return "1ère visite" if self.cycle == 1 else "2ème visite"

    @property
    def is_imminente(self) -> bool:
        """Dans les 10 jours : un rappel est déjà actif (cf. alerts type 5)."""
        return 0 <= self.jours <= 10


def get_visites_prevues(queryset=None, today: date | None = None) -> list[VisitePrevue]:
    """Toutes les visites programmées non encore effectuées, par date croissante."""
    from clients.models import Client

    if queryset is None:
        queryset = Client.objects.all()
    today = today or date.today()

    prevues: list[VisitePrevue] = []
    for client in queryset:
        cycles = [
            (1, client.derniere_1ere_visite),
            (1, client.prochaine_1ere_visite),
            (2, client.derniere_2eme_visite),
            (2, client.prochaine_2eme_visite),
        ]
        vues: set[date] = set()
        for cycle, d in cycles:
            if d and d >= today and d not in vues:
                vues.add(d)
                prevues.append(
                    VisitePrevue(
                        client=client,
                        date_visite=d,
                        cycle=cycle,
                        jours=(d - today).days,
                    )
                )
    prevues.sort(key=lambda v: (v.date_visite, v.client.nom))
    return prevues


def get_visites_en_retard(queryset=None, today: date | None = None) -> list[VisitePrevue]:
    """Visites passées dont le suivi du rapport est en retard (alerte rouge).

    Même définition du retard que la page Alertes (types 2 et 4) : le rapport
    inspecteurs ou assistante n'a pas été remis dans les délais. Les plus
    gros retards d'abord.
    """
    from clients.models import Client

    from .alerts import get_client_alerts

    if queryset is None:
        queryset = Client.objects.all()
    today = today or date.today()

    en_retard: list[VisitePrevue] = []
    for client in queryset:
        for alert in get_client_alerts(client, today=today):
            # retards de rapport seulement (pas la facturation)
            if not alert.is_alerte or alert.categorie not in ("inspecteurs", "assistante"):
                continue
            d = alert.date_visite
            cycle = 1 if d in (client.derniere_1ere_visite, client.prochaine_1ere_visite) else 2
            en_retard.append(
                VisitePrevue(
                    client=client,
                    date_visite=d,
                    cycle=cycle,
                    jours=(d - today).days,
                    retard_jours=max(alert.days, 1),
                )
            )
    en_retard.sort(key=lambda v: (-v.retard_jours, v.date_visite, v.client.nom))
    return en_retard


def paginer_par_jours(visites, numero_page, jours_par_page: int = 30):
    """Découpe `visites` (triées par date) en pages de `jours_par_page` dates
    distinctes ayant au moins une visite. Retourne (page, visites de la page)."""
    from django.core.paginator import Paginator

    dates = sorted({v.date_visite for v in visites})
    page = Paginator(dates, jours_par_page).get_page(numero_page)
    dates_page = set(page.object_list)
    return page, [v for v in visites if v.date_visite in dates_page]


def calendrier_mois(prevues, annee: int, mois: int, today: date | None = None) -> list[list[dict]]:
    """Grille du mois (semaines de 7 jours, lundi → dimanche).

    Chaque case porte les visites du jour, pour les colorer comme dans un
    calendrier d'agenda : une pastille par visite, teintée selon le cycle.
    """
    today = today or date.today()
    par_jour: dict[date, list] = {}
    for v in prevues:
        if v.date_visite.year == annee and v.date_visite.month == mois:
            par_jour.setdefault(v.date_visite, []).append(v)

    cal = calendar.Calendar(firstweekday=0)  # 0 = lundi
    semaines = []
    for semaine in cal.monthdatescalendar(annee, mois):
        cases = []
        for jour in semaine:
            visites = par_jour.get(jour, [])
            cases.append(
                {
                    "date": jour,
                    "numero": jour.day,
                    "dans_le_mois": jour.month == mois,
                    "is_today": jour == today,
                    "is_passe": jour < today,
                    "visites": visites,
                    "nb": len(visites),
                    "a_cycle_1": any(v.cycle == 1 for v in visites),
                    "a_cycle_2": any(v.cycle == 2 for v in visites),
                }
            )
        semaines.append(cases)
    return semaines


def repartition_par_mois(prevues, annee: int) -> list[dict]:
    """Compte les visites de `annee` mois par mois (pour le graphique)."""
    counts = [0] * 12
    for v in prevues:
        if v.date_visite.year == annee:
            counts[v.date_visite.month - 1] += 1
    maximum = max(counts) or 1
    return [
        {
            "mois": i + 1,
            "label": MOIS_FR[i],
            "count": counts[i],
            "pourcentage": round(counts[i] * 100 / maximum),
        }
        for i in range(12)
    ]
