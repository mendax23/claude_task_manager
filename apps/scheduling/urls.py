from django.urls import path
from . import views

app_name = "scheduling"

urlpatterns = [
    path("", views.schedule_settings, name="settings"),
    path("budget/", views.budget_overview, name="budget"),
    path("toggle/", views.schedule_toggle, name="toggle"),
]
