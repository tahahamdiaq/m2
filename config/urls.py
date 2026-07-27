from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="clients:client_list", permanent=False)),
    path("", include("accounts.urls")),
    path("", include("clients.urls")),
]
