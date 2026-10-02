from core import config


def test_code_execution_channels_configured():
    assert config.CODE_EXEC_CHANNEL
    assert config.CODE_RESULT_CHANNEL
