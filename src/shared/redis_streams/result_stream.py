def agent_result_stream(prefix: str, correlation_id: str) -> str:
    """Name of the result stream dedicated to one agent run.

    Crew and agent both derive it from the run's ``correlation_id`` so a
    waiter only ever reads its own run's envelopes, and the agent never
    publishes to a stream name taken from the request payload.
    """
    return f"{prefix}:{correlation_id}"
