from django.contrib import admin
from django.urls import include, path

from accounts.views import home

admin.site.site_header = "ERIMS Administration"
admin.site.site_title = "ERIMS Admin"
admin.site.index_title = "Emergency Resource & Inventory Management"

urlpatterns = [
    path("", home, name="home"),
    path("accounts/", include("django.contrib.auth.urls")),  # login, logout, password change
    path("admin/", admin.site.urls),
]
