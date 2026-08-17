import os
import sys
import tempfile
from app.utils import (
    get_config_dir,
    save_config,
    get_config,
    save_savefiles_path,
    get_savefiles_path,
    get_env_file_path,
)


def test_get_config_dir():
    """Test that config directory is correctly determined based on OS"""
    config_dir = get_config_dir()
    system = sys.platform.lower()

    if system == "win32":
        assert (
            os.path.join(os.getcwd(), "test_appdata", "CrewAI-SheetsUI") == config_dir
        )
    elif system == "darwin":
        assert (
            os.path.join(
                os.getcwd(),
                "test_home",
                "Library",
                "Application Support",
                "CrewAI-SheetsUI",
            )
            == config_dir
        )
    else:  # Linux
        assert os.path.join(os.getcwd(), "test_config", "crewai-sheetsui") == config_dir


def test_save_and_get_config():
    """Test saving and retrieving configuration values"""
    test_key = "test_key"
    test_value = "test_value"

    # Save test value
    assert save_config(test_key, test_value)

    # Retrieve test value
    retrieved_value = get_config(test_key)
    assert retrieved_value == test_value

    # Test default value
    assert get_config("non_existent_key", "default") == "default"


def test_savefiles_path_operations():
    """Test saving and retrieving savefiles path"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test saving path
        test_path = os.path.join(temp_dir, "test_savefiles")
        save_savefiles_path(test_path)

        # Test retrieving path
        retrieved_path = get_savefiles_path()
        assert retrieved_path == test_path

        # Verify .env file was created
        env_path = get_env_file_path()
        assert os.path.exists(env_path)

        # Verify .env content
        with open(env_path, "r") as f:
            content = f.read()
            assert f'CREW_SAVEFILES_PATH="{test_path}"' in content


def test_savefiles_path_default():
    """Test default savefiles path when no path is set"""
    # Clear any existing config
    save_config("savefiles_path", None)

    # Remove .env file if it exists
    env_path = get_env_file_path()
    if os.path.exists(env_path):
        os.remove(env_path)

    # Get default path
    default_path = get_savefiles_path()

    if getattr(sys, "frozen", False):
        expected_base = os.path.dirname(sys.executable)
    else:
        expected_base = os.path.dirname(os.path.dirname(__file__))

    expected_path = os.path.join(expected_base, "savefiles")
    assert default_path == expected_path


def test_savefiles_path_persistence():
    """Test that savefiles path persists between calls"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save initial path
        initial_path = os.path.join(temp_dir, "initial")
        save_savefiles_path(initial_path)

        # Verify first save
        assert get_savefiles_path() == initial_path

        # Save new path
        new_path = os.path.join(temp_dir, "new")
        save_savefiles_path(new_path)

        # Verify path was updated
        assert get_savefiles_path() == new_path

        # Verify .env was updated
        with open(get_env_file_path(), "r") as f:
            content = f.read()
            assert f'CREW_SAVEFILES_PATH="{new_path}"' in content


def test_ensure_signing_keys_generates_both_when_absent():
    """Both signing keys are generated when the env file has neither."""
    from app.utils import ensure_signing_keys

    with tempfile.TemporaryDirectory() as tmp_dir:
        env_path = os.path.join(tmp_dir, ".env")

        ensure_signing_keys(env_path=env_path)

        with open(env_path) as env_file:
            lines = env_file.read().splitlines()
        secret_line = [line for line in lines if line.startswith("SECRET_KEY=")]
        jwt_line = [line for line in lines if line.startswith("JWT_SECRET=")]
        assert len(secret_line) == 1
        assert len(jwt_line) == 1
        assert len(secret_line[0].split("=", 1)[1]) >= 50
        assert len(jwt_line[0].split("=", 1)[1]) >= 50
        assert secret_line[0] != jwt_line[0].replace("JWT_SECRET", "SECRET_KEY")


def test_ensure_signing_keys_is_idempotent():
    """A second call leaves an already-generated key byte-identical."""
    from app.utils import ensure_signing_keys

    with tempfile.TemporaryDirectory() as tmp_dir:
        env_path = os.path.join(tmp_dir, ".env")

        ensure_signing_keys(env_path=env_path)
        with open(env_path) as env_file:
            first = env_file.read()
        ensure_signing_keys(env_path=env_path)
        with open(env_path) as env_file:
            second = env_file.read()

        assert first == second


def test_ensure_signing_keys_preserves_other_lines_and_replaces_blanks():
    """Unrelated lines survive, and a blank key entry is treated as missing."""
    from app.utils import ensure_signing_keys

    with tempfile.TemporaryDirectory() as tmp_dir:
        env_path = os.path.join(tmp_dir, ".env")
        with open(env_path, "w") as env_file:
            env_file.write('CREW_SAVEFILES_PATH="/tmp/savefiles"\nSECRET_KEY=\n')

        ensure_signing_keys(env_path=env_path)

        with open(env_path) as env_file:
            lines = env_file.read().splitlines()
        assert 'CREW_SAVEFILES_PATH="/tmp/savefiles"' in lines
        secret_lines = [line for line in lines if line.startswith("SECRET_KEY=")]
        assert len(secret_lines) == 1
        assert secret_lines[0] != "SECRET_KEY="
