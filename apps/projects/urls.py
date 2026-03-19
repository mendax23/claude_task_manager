from django.urls import path
from . import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("create/", views.project_create, name="create"),
    path("<slug:slug>/", views.project_detail, name="detail"),
    path("<slug:slug>/suggest/", views.suggest_tasks, name="suggest"),
]
