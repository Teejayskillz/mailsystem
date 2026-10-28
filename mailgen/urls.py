from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Personal Email Generator — administration"
admin.site.site_title = "Email Generator admin"
admin.site.index_title = "Administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("generator.urls")),
]

handler404 = "generator.views.error_404"
handler500 = "generator.views.error_500"
