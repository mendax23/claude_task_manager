from django.urls import path
from . import views

app_name = "providers"

urlpatterns = [
    path("", views.provider_list, name="list"),
    path("create/", views.provider_create, name="create"),
    path("<int:pk>/edit/", views.provider_edit, name="edit"),
    path("<int:pk>/delete/", views.provider_delete, name="delete"),
    path("<int:pk>/health/", views.health_check, name="health_check"),
]
