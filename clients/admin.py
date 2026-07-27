from django.contrib import admin

from .models import Client, Visite


class VisiteInline(admin.TabularInline):
    model = Visite
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = [
        "nom", "numero_abonnement", "adresse", "status",
        "prochaine_1ere_visite", "prochaine_2eme_visite", "payement",
    ]
    list_filter = ["status", "payement", "decharge_facture"]
    search_fields = ["nom", "adresse", "numero_abonnement"]
    date_hierarchy = "prochaine_1ere_visite"
    inlines = [VisiteInline]


@admin.register(Visite)
class VisiteAdmin(admin.ModelAdmin):
    list_display = [
        "client", "date_visite", "rapport_inspecteurs",
        "date_remise_inspecteurs", "rapport_assistante", "date_remise_assistante",
        "date_paiement_facture", "date_decharge_facture",
    ]
    list_filter = ["rapport_inspecteurs", "rapport_assistante"]
    search_fields = ["client__nom", "client__numero_abonnement"]
    date_hierarchy = "date_visite"
