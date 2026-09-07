"""Root URL configuration."""

from django.urls import include, path

urlpatterns = [
    path("", include("redemption.api.urls")),
]
