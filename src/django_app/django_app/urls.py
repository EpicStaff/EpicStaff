"""
URL configuration for django_app project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from tables.views.audit_token_views import AuditTokenView
from tables.views.system_info_view import SystemInfoView
from user_audit.views import ServiceUserActionView

from .yasg import urlpatterns as doc_urls

urlpatterns = [
    path("", include("rbac.urls")),
    path("api/audit/token/", AuditTokenView.as_view(), name="audit_token"),
    path("api/system-info/", SystemInfoView.as_view(), name="system_info"),
    path(
        "api/internal/user-actions/",
        ServiceUserActionView.as_view(),
        name="internal-user-actions",
    ),
    path("api/", include("tables.urls")),
    path("api/ai-models/", include("ai_models.urls")),
    path("api/", include("agents.urls")),
    path("api/", include("proxies.urls")),
    path("ht/", include("health_check.urls")),
]

# With the plugin platform off, every plugin route is a plain 404.
if settings.PLUGINS_ENABLED:
    urlpatterns.append(path("", include("plugins.urls")))

urlpatterns += doc_urls

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    # MEDIA_ROOT is not served, even in debug: it holds voice recordings, which only their
    # organization may read, and a static route would hand them to anyone with the URL.
