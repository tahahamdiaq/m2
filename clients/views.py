from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ClientFilterForm, ClientForm
from .models import Client
from .services.alerts import get_all_alerts, get_client_alerts
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
