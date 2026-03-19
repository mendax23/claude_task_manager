from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("projects/", include("apps.projects.urls")),
    path("providers/", include("apps.providers.urls")),
    path("scheduling/", include("apps.scheduling.urls")),
    path("api/", include("apps.tasks.api_urls")),
]
