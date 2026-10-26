"""The browser login protocol's fixed values, as EpicStaff's side of it uses them.

They mirror `plugin-sdk/contracts/login-protocol.json`, which the JS SDK, the platform callback
pages and the frontend read; a test keeps the two equal. Patterns are matched against a whole
value (`re.fullmatch`).
"""

PROTOCOL = 1

AUTHORIZE_PATH = "/api/auth/plugin-authorize/"
TOKEN_PATH = "/api/auth/plugin-token/"
CALLBACK_PATH = "/.well-known/epicstaff/callback.html"
SILENT_CALLBACK_PATH = "/.well-known/epicstaff/silent-callback.html"
LOGIN_CONTINUE_PATH = "/plugin-login"
CHOOSE_ORG_PATH = "/plugin-choose-org"

AUTHORIZE_PARAMETERS = (
    "plugin",
    "state",
    "code_challenge",
    "code_challenge_method",
    "org",
    "prompt",
)
CODE_CHALLENGE_METHOD = "S256"
PROMPT_NONE = "none"
PROMPT_VALUES = (PROMPT_NONE,)

LOGIN_REQUIRED = "login_required"
ACCESS_DENIED = "access_denied"
INTERACTION_REQUIRED = "interaction_required"
# The person may use the plugin once its upgrade, or their organization's, has finished.
TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
CALLBACK_ERRORS = (LOGIN_REQUIRED, ACCESS_DENIED, INTERACTION_REQUIRED, TEMPORARILY_UNAVAILABLE)

STATE_PATTERN = r"^[A-Za-z0-9_-]{43,128}$"
CODE_PATTERN = r"^[A-Za-z0-9_-]{43}$"
CODE_CHALLENGE_PATTERN = r"^[A-Za-z0-9_-]{43}$"
CODE_VERIFIER_PATTERN = r"^[A-Za-z0-9._~-]{43,128}$"
CONTINUE_PATTERN = r"^/api/auth/plugin-authorize/\?[A-Za-z0-9._~%=&+-]{1,4000}$"

CODE_TTL_SECONDS = 60
TOKEN_LIFETIME_SECONDS = 900
