from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("clients/", views.client_list, name="client_list"),
    path("clients/nouveau/", views.client_create, name="client_create"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("clients/<int:pk>/supprimer/", views.client_delete, name="client_delete"),
    path("planning/", views.planning_visites, name="planning"),
    path("alertes/", views.alert_list, name="alert_list"),
]
