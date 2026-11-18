"""Records what users do through the API and sends it to the auditor's user-actions domain.

Not a Django app: it owns no models. `UserActionMiddleware` opens a context per request;
capture code calls `record_user_action`, which queues one `UserActionEvent` on commit.
"""
