from rbac.access.principals import is_pinned_org_principal
from rest_framework.throttling import SimpleRateThrottle


class NotifyEmailThrottle(SimpleRateThrottle):
    """
    Throttle for POST /api/notify/email/ (NotifyEmailView, driven by
    notification_tool / channel='email').

    Unlike LoginThrottle/PasswordResetRequestThrottle -- which serve
    anonymous flows and key on `<ip>|<email>` -- this endpoint requires auth,
    so the bucket key is the authenticated caller's user id. That caps how
    many emails a single account (human or a leaked/prompt-injected API key)
    can send regardless of which IP the request comes from, which is the
    relevant abuse vector here: an authenticated agent using this endpoint as
    a mail relay to spam arbitrary external addresses. Rate is driven by the
    `notify_email` scope (default 10/hour, env var
    `DJANGO_NOTIFY_EMAIL_THROTTLE_RATE`).

    A pinned principal has no user id; it is keyed on its own
    `rate_limit_key`. The view refuses plugin credentials before throttling,
    so this only keeps the key well-defined.
    """

    scope = "notify_email"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if is_pinned_org_principal(user):
            ident = user.rate_limit_key
        elif user is not None and user.is_authenticated:
            ident = str(user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class TransferJobCreateThrottle(SimpleRateThrottle):
    """
    Throttle for starting transfer jobs, one bucket for all of them: every export
    job (each `POST .../export-jobs/` and `POST /api/graphs/{id}/partial-export-jobs/`)
    and import uploads (`POST /api/graphs/import-jobs/`,
    `POST /api/source-collections/import-jobs/`).

    The unfinished-job limit caps how many jobs run at once; this caps how
    fast one caller can start them, since a job that fails fast frees its slot
    at once. Keyed on the caller's user id, so a personal API key shares its
    owner's bucket. Rate is driven by the `transfer_job_create` scope (env var
    `DJANGO_TRANSFER_JOB_CREATE_THROTTLE_RATE`).

    A pinned principal has no user id; it is keyed on its own
    `rate_limit_key`. The view refuses it after throttling, so this only keeps
    the key well-defined.
    """

    scope = "transfer_job_create"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if is_pinned_org_principal(user):
            ident = user.rate_limit_key
        elif getattr(user, "pk", None) is not None and user.is_authenticated:
            ident = str(user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
