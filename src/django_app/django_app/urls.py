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

from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView
from tables.views.auth_views import (
    AdminPasswordResetView,
    ApiKeyValidateView,
    FirstSetupView,
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ResetUserView,
    SseTicketView,
    SwaggerTokenView,
    TokenIntrospectView,
    WsTicketView,
)
from tables.views.permission_views import (
    MyPermissionsView,
    PermissionCatalogView,
)
from tables.views.user_profile_views import (
    PasswordChangeConfirmView,
    PasswordChangeRequestView,
    ProfileAvatarView,
    ProfileView,
)
from .yasg import urlpatterns as doc_urls
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("api/auth/sse-ticket/", SseTicketView.as_view(), name="sse_ticket"),
    path("api/auth/ws-ticket/", WsTicketView.as_view(), name="ws_ticket"),
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
    path(
        "api/auth/password-reset/request/",
        PasswordResetRequestView.as_view(),
        name="password_reset_request",
    ),
    path(
        "api/auth/password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "api/auth/admin/password-reset/",
        AdminPasswordResetView.as_view(),
        name="admin_password_reset",
    ),
    path("api/auth/swagger-token/", SwaggerTokenView.as_view(), name="swagger_token"),
    path("api/profile/", ProfileView.as_view(), name="profile"),
    path(
        "api/profile/avatar/",
        ProfileAvatarView.as_view(),
        name="profile_avatar",
    ),
    path(
        "api/profile/password-change/request/",
        PasswordChangeRequestView.as_view(),
        name="profile_password_change_request",
    ),
    path(
        "api/profile/password-change/confirm/",
        PasswordChangeConfirmView.as_view(),
        name="profile_password_change_confirm",
    ),
    path(
        "api/permissions/catalog/",
        PermissionCatalogView.as_view(),
        name="permissions_catalog",
    ),
    path(
        "api/permissions/me/",
        MyPermissionsView.as_view(),
        name="permissions_me",
    ),
    path("api/", include("tables.urls")),
    path("ht/", include("health_check.urls")),
]

urlpatterns += doc_urls

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
