"""Ouverture automatique des fiches de visite.

Dès qu'une date de visite est atteinte (dernière 1ère ou 2ème visite),
une fiche `Visite` est créée avec un rapport « Non remis » : le suivi
du rapport redémarre pour cette visite, et les fiches précédentes
restent en historique sur la page du client.
"""
from datetime import date


def sync_visites(client, today: date | None = None) -> None:
    """Crée les fiches manquantes pour les visites déjà effectuées."""
    today = today or date.today()
    dates = {
        d
        for d in (client.derniere_1ere_visite, client.derniere_2eme_visite)
        if d and d <= today
    }
    for d in dates:
        client.visites.get_or_create(date_visite=d)
