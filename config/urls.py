from django.contrib import admin
from django.urls import include, path

from fuel.views import route_map

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", route_map, name="home"),
    path("api/", include("fuel.urls")),
]
