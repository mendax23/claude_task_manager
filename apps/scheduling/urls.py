from django.urls import path
from . import views

app_name = "scheduling"

urlpatterns = [
    path("", views.schedule_settings, name="settings"),
    path("budget/", views.budget_overview, name="budget"),
    path("budget/add/", views.budget_create, name="budget_create"),
    path("budget/<int:pk>/edit/", views.budget_edit, name="budget_edit"),
    path("toggle/", views.schedule_toggle, name="toggle"),
]
