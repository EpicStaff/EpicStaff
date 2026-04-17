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

from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from tables.views.auth_views import (
    AuthMeView,
    TokenIntrospectView,
    ApiKeyValidateView,
    FirstSetupView,
    ResetUserView,
    SwaggerTokenView,
)
from .yasg import urlpatterns as doc_urls
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", AuthMeView.as_view(), name="auth_me"),
    path(
        "api/auth/introspect/", TokenIntrospectView.as_view(), name="token_introspect"
    ),
    path(
        "api/auth/api-key/validate/",
        ApiKeyValidateView.as_view(),
        name="api_key_validate",
    ),
    path("api/auth/first-setup/", FirstSetupView.as_view(), name="first_setup"),
    path("api/auth/reset-user/", ResetUserView.as_view(), name="reset_user"),
    path("api/auth/swagger-token/", SwaggerTokenView.as_view(), name="swagger_token"),
    path("api/", include("tables.urls")),
    path("ht/", include("health_check.urls")),
]

urlpatterns += doc_urls

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
