from django.urls import include, path
from rest_framework.routers import DefaultRouter

from rbac.views.api_keys import (
    ProfileApiKeyDetailView,
    ProfileApiKeyRevokeView,
    ProfileApiKeysView,
)
from rbac.views.api_keys_admin import ApiKeyAdminViewSet
from rbac.views.auth import (
    AdminPasswordResetView,
    ApiKeyValidateView,
    CookieTokenRefreshView,
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
from rbac.views.memberships import MembershipAdminViewSet
from rbac.views.organizations import OrganizationAdminViewSet
from rbac.views.permissions import (
    MyOrgsPermissionsView,
    MyPermissionsView,
    PermissionCatalogView,
)
from rbac.views.profile import (
    PasswordChangeConfirmView,
    PasswordChangeRequestView,
    ProfileAvatarView,
    ProfileView,
)
from rbac.views.roles import RoleAdminViewSet
from rbac.views.users import UserAdminViewSet

admin_router = DefaultRouter()
admin_router.register(r"organizations", OrganizationAdminViewSet, basename="admin-organization")
admin_router.register(r"users", UserAdminViewSet, basename="admin-user")
admin_router.register(r"roles", RoleAdminViewSet, basename="admin-role")
admin_router.register(r"api-keys", ApiKeyAdminViewSet, basename="admin-api-key")

urlpatterns = [
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/refresh/", CookieTokenRefreshView.as_view(), name="refresh"),
    path("api/auth/sse-ticket/", SseTicketView.as_view(), name="sse_ticket"),
    path("api/auth/ws-ticket/", WsTicketView.as_view(), name="ws_ticket"),
    path("api/auth/introspect/", TokenIntrospectView.as_view(), name="token_introspect"),
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
        "api/profile/api-keys/",
        ProfileApiKeysView.as_view(),
        name="profile_api_keys",
    ),
    path(
        "api/profile/api-keys/<int:key_id>/",
        ProfileApiKeyDetailView.as_view(),
        name="profile_api_key_detail",
    ),
    path(
        "api/profile/api-keys/<int:key_id>/revoke/",
        ProfileApiKeyRevokeView.as_view(),
        name="profile_api_key_revoke",
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
    path(
        "api/permissions/me/orgs/",
        MyOrgsPermissionsView.as_view(),
        name="permissions_me_orgs",
    ),
    path(
        "api/admin/memberships/",
        MembershipAdminViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-memberships",
    ),
    path(
        "api/admin/memberships/assignable-users/",
        MembershipAdminViewSet.as_view({"get": "assignable_users"}),
        name="admin-memberships-assignable-users",
    ),
    path(
        "api/admin/memberships/<int:pk>/",
        MembershipAdminViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="admin-membership-detail",
    ),
    path("api/admin/", include(admin_router.urls)),
]
