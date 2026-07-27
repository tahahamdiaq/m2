"""Badge compteur d'alertes/rappels affiché dans la navigation."""


def alerts_badge(request):
    if not request.user.is_authenticated:
        return {}
    from .services.alerts import get_all_alerts

    alerts = get_all_alerts()
    return {
        "nav_alert_count": len(alerts),
        "nav_has_alerte": any(a.is_alerte for a in alerts),
    }
