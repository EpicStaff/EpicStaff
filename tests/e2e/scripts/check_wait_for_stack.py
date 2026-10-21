"""Self-check for the container classification in wait_for_stack.py (no stack needed).

    python tests/e2e/scripts/check_wait_for_stack.py

Not named test_*: pytest under tests/e2e would run the stack bootstrap first.
"""

from wait_for_stack import classify_containers


def container(service: str, state: str, health: str = "", exit_code: int = 0) -> dict:
    return {"Service": service, "State": state, "Health": health, "ExitCode": exit_code}


def main() -> None:
    ready = [
        container("crewdb", "running", "healthy"),
        container("crew", "running"),
        container("storage-init", "exited"),
    ]
    assert classify_containers(ready).passed

    starting = classify_containers([*ready[1:], container("crewdb", "running", "starting")])
    assert not starting.passed and not starting.fatal, starting

    assert not classify_containers([]).passed

    for crashed in (
        container("crew", "restarting", exit_code=1),
        container("storage-init", "exited", exit_code=6),
        container("crewdb", "running", "unhealthy"),
        container("sandbox", "dead"),
    ):
        result = classify_containers([*ready, crashed])
        assert result.fatal and crashed["Service"] in result.detail, (crashed, result)

    print("ok")


if __name__ == "__main__":
    main()
