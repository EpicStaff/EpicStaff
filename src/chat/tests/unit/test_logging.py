from common.logging import configure_logging
from loguru import logger


def test_tracebacks_do_not_print_local_variable_values(capsys):
    configure_logging("INFO")

    def fail():
        secret_value = "s3cr3t-token-value"
        raise RuntimeError(len(secret_value))

    try:
        fail()
    except RuntimeError:
        logger.exception("boom")

    stderr = capsys.readouterr().err
    assert "boom" in stderr
    assert "s3cr3t-token-value" not in stderr
