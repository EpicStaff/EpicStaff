from user_audit.context import user_action_context


class UserActionMiddleware:
    """Opens the user-action context around each Django request.

    Synchronous only, like `PluginRequestScopeMiddleware` before it: Django runs it in
    the view's own thread, so the context is visible to every save the view makes.
    """

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with user_action_context(request):
            return self.get_response(request)
