import os

# EST-3285 4.2c: optional run-level token budget hard stop.
# Global fallback used when a session does not carry a per-run override
# (see GraphSessionManagerService.run_session / SessionData.initial_state
# reserved key "__token_budget__"). None (default) means "no limit" —
# the feature is fully inert unless TOKEN_BUDGET is set or a run explicitly
# opts in, so existing runs are byte-for-byte unchanged.
_raw_token_budget = os.environ.get("TOKEN_BUDGET")
DEFAULT_TOKEN_BUDGET: int | None = int(_raw_token_budget) if _raw_token_budget else None
