from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ClientFilterForm, ClientForm
from .models import Client
from .services.alerts import get_all_alerts, get_client_alerts
from .services.planning import (
    JOURS_FR,
    MOIS_FR,
    calendrier_mois,
    get_visites_prevues,
    repartition_par_mois,
)
from .services.visites import sync_visites


@login_required
def client_list(request):
    filter_form = ClientFilterForm(request.GET or None)
    queryset = filter_form.filter_queryset(Client.objects.all())

    paginator = Paginator(queryset, 15)
    page = paginator.get_page(request.GET.get("page"))

    # Alertes par client de la page courante (badge sur chaque ligne)
    rows = []
    for client in page.object_list:
        alerts = get_client_alerts(client)
        rows.append(
            {
                "client": client,
                "visite": client.visite_courante,
                "alerts": alerts,
                "has_alerte": any(a.is_alerte for a in alerts),
                "has_rappel": any(not a.is_alerte for a in alerts),
            }
        )

    # Conserver les filtres dans les liens de pagination
    query = request.GET.copy()
    query.pop("page", None)

    return render(
        request,
        "clients/client_list.html",
        {
            "filter_form": filter_form,
            "rows": rows,
            "page": page,
            "querystring": query.urlencode(),
            "total_count": paginator.count,
        },
    )


@login_required
def client_create(request):
    form = ClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, f"Client « {client.nom} » créé.")
        return redirect(client.get_absolute_url())
    return render(
        request,
        "clients/client_form.html",
        {"form": form, "client": None, "alerts": []},
    )


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    sync_visites(client)  # ouvre la fiche rapport d'une visite qui vient d'échoir
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, f"Client « {client.nom} » enregistré.")
        return redirect(client.get_absolute_url())
    return render(
        request,
        "clients/client_form.html",
        {"form": form, "client": client, "alerts": get_client_alerts(client)},
    )


@login_required
@require_POST
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    nom = client.nom
    client.delete()
    messages.info(request, f"Client « {nom} » supprimé.")
    return redirect("clients:client_list")


def _parse_jour(valeur, annee: int, mois: int):
    """Jour sélectionné dans le calendrier (« 2026-03-14 »), ou None."""
    if not valeur:
        return None
    try:
        jour = date.fromisoformat(valeur)
    except ValueError:
        return None
    return jour if (jour.year, jour.month) == (annee, mois) else None


@login_required
def planning_visites(request):
    """Tableau de bord des visites à venir, filtrable par année et par mois."""
    today = date.today()
    toutes = get_visites_prevues(today=today)

    # Années proposées au filtre : celles où des visites sont programmées
    annees = {v.date_visite.year for v in toutes} | {today.year}
    try:
        annee = int(request.GET.get("annee") or today.year)
    except ValueError:
        annee = today.year
    # Le calendrier se feuillette librement, même sur une année sans visite
    if not today.year - 50 <= annee <= today.year + 50:
        annee = today.year
    annees = sorted(annees | {annee})
    try:
        mois = int(request.GET.get("mois") or 0)  # 0 = tous les mois
    except ValueError:
        mois = 0
    if mois not in range(1, 13):
        mois = 0
    # Le calendrier affiche toujours un mois précis
    mois_calendrier = mois or (today.month if annee == today.year else 1)
    jour_filtre = _parse_jour(request.GET.get("jour"), annee, mois_calendrier)

    # Statistiques globales (indépendantes du filtre)
    fin_semaine = today + timedelta(days=7)
    fin_mois = today + timedelta(days=30)
    stats = {
        "total": len(toutes),
        "semaine": sum(1 for v in toutes if v.date_visite <= fin_semaine),
        "mois_30j": sum(1 for v in toutes if v.date_visite <= fin_mois),
        "imminentes": sum(1 for v in toutes if v.is_imminente),
        "cycle_1": sum(1 for v in toutes if v.cycle == 1),
        "cycle_2": sum(1 for v in toutes if v.cycle == 2),
    }

    # Répartition mensuelle de l'année sélectionnée (graphique)
    repartition = repartition_par_mois(toutes, annee)

    # Calendrier du mois affiché
    semaines = calendrier_mois(toutes, annee, mois_calendrier, today=today)

    # Liste filtrée
    visites = [v for v in toutes if v.date_visite.year == annee]
    if mois:
        visites = [v for v in visites if v.date_visite.month == mois]
    if jour_filtre:
        visites = [v for v in visites if v.date_visite == jour_filtre]

    # Navigation mois précédent / suivant
    precedent = date(annee, mois_calendrier, 1) - timedelta(days=1)
    suivant = date(annee, mois_calendrier, 28) + timedelta(days=7)

    return render(
        request,
        "clients/planning.html",
        {
            "visites": visites,
            "stats": stats,
            "repartition": repartition,
            "semaines": semaines,
            "jours_fr": JOURS_FR,
            "annees": annees,
            "annee": annee,
            "mois": mois,
            "mois_calendrier": mois_calendrier,
            "mois_calendrier_label": MOIS_FR[mois_calendrier - 1],
            "jour_filtre": jour_filtre,
            "precedent": precedent,
            "suivant": suivant,
            "mois_choices": list(enumerate(MOIS_FR, start=1)),
            "total_annee": sum(r["count"] for r in repartition),
        },
    )


@login_required
def alert_list(request):
    kind = request.GET.get("kind", "")  # '', 'rappel' ou 'alerte'
    cat = request.GET.get("cat", "")    # '', 'inspecteurs', 'assistante', 'visite'
    alerts = get_all_alerts()
    counts = {
        "all": len(alerts),
        "alerte": sum(1 for a in alerts if a.is_alerte),
        "rappel": sum(1 for a in alerts if not a.is_alerte),
        "inspecteurs": sum(1 for a in alerts if a.categorie == "inspecteurs"),
        "assistante": sum(1 for a in alerts if a.categorie == "assistante"),
        "visite": sum(1 for a in alerts if a.categorie == "visite"),
    }
    if kind in ("rappel", "alerte"):
        alerts = [a for a in alerts if a.kind == kind]
    if cat in ("inspecteurs", "assistante", "visite"):
        alerts = [a for a in alerts if a.categorie == cat]
    return render(
        request,
        "clients/alert_list.html",
        {"alerts": alerts, "kind": kind, "cat": cat, "counts": counts},
    )
