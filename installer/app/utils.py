import os
import platform
import re
import subprocess
from pathlib import Path
import sys
import textwrap

import json
import threading

def init_env_file(savefiles_path):
    """Initializes the .env file"""
    env_path = get_env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)  # Create directories
    env_path.touch(exist_ok=True)  # Create .env file if it doesn't exist

    with env_path.open("w", encoding="utf-8") as f:
        f.write(f'CREW_SAVEFILES_PATH="{savefiles_path}"\n')


def get_env_file_path():
    """Returns the path to .env whether bundled by PyInstaller or run normally"""
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent
    env_path = base_path / "app" / "static" / "run_program" / ".env"

    return env_path


def get_compose_file_path():
    """Returns the path to docker-compose.yaml whether bundled by PyInstaller or run normally"""
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent
    return base_path / "app" / "static" / "run_program" / "docker-compose.yaml"


def get_config_dir():
    """Get the appropriate configuration directory based on the OS"""
    system = platform.system().lower()

    if system == "windows":
        # Use AppData\Local for Windows
        return os.path.join(os.environ["LOCALAPPDATA"], "EpicStaff")
    elif system == "darwin":
        # Use Application Support for macOS
        return os.path.expanduser("~/Library/Application Support/EpicStaff")
    else:
        # Use XDG config for Linux
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return os.path.join(xdg_config, "epicstaff")
        return os.path.expanduser("~/.config/epicstaff")


def save_config(key, value):
    """Save configuration value using the appropriate method for the OS"""
    system = platform.system().lower()

    if system == "windows":
        import winreg

        try:
            # Create or open the registry key
            key_path = r"Software\EpicStaff"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key_handle:
                winreg.SetValueEx(key_handle, key, 0, winreg.REG_SZ, str(value))
            return True
        except Exception as e:
            print(f"Error saving to registry: {e}")
            return False
    else:
        try:
            # For Linux and macOS, use JSON file
            config_dir = get_config_dir()
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, "config.json")

            # Read existing config
            config = {}
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    config = json.load(f)

            # Update config
            config[key] = value

            # Write back to file
            with open(config_file, "w") as f:
                json.dump(config, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving config file: {e}")
            return False


def get_config(key, default=None):
    """Get configuration value using the appropriate method for the OS"""
    system = platform.system().lower()

    if system == "windows":
        import winreg

        try:
            # Try to read from registry
            key_path = r"Software\EpicStaff"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key_handle:
                value, _ = winreg.QueryValueEx(key_handle, key)
                print(
                    f"Getting from registry: {key_path} with key: {key} and value: {value}"
                )
                return value
        except Exception:
            return default
    else:
        try:
            # For Linux and macOS, read from JSON file
            config_dir = get_config_dir()
            config_file = os.path.join(config_dir, "config.json")

            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    config = json.load(f)
                    return config.get(key, default)
            return default
        except Exception:
            return default


def save_savefiles_path(savefiles_path: str):
    """Save the savefiles path to the appropriate storage"""
    if not os.path.exists(savefiles_path):
        return False

    # Save to both .env and system config

    env_path = get_env_file_path()
    print(f"Saving to .env file at: {env_path}")

    # Save to .env
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
    else:
        lines = []

    path_line = f'CREW_SAVEFILES_PATH="{savefiles_path}"\n'
    path_exists = False

    for i, line in enumerate(lines):
        if line.startswith("CREW_SAVEFILES_PATH="):
            lines[i] = path_line
            path_exists = True
            break

    if not path_exists:
        lines.append(path_line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Save to system config
    save_config("savefiles_path", savefiles_path)
    return True


def save_image_repository(image_repository: str):
    """Save the image repository to the appropriate storage"""
    allowed_regex = r"^[a-zA-Z0-9][a-zA-Z0-9_.\-\/]{1,127}$"
    if not image_repository or not re.match(allowed_regex, image_repository):
        print(f"Invalid image repository: {image_repository}")
        return False
    if not image_repository:
        return False

    lines = []

    path_line = f'IMAGE_REPOSITORY="{image_repository}"\n'
    path_exists = False

    for i, line in enumerate(lines):
        if line.startswith("IMAGE_REPOSITORY="):
            lines[i] = path_line
            path_exists = True
            break

    if not path_exists:
        lines.append(path_line)

    # Save to system config
    save_config("image_repository", image_repository)
    return True


def save_image_tag(image_tag: str):
    """Save the image tag to the appropriate storage"""
    allowed_regex = r"^[a-zA-Z0-9][a-zA-Z0-9_.\-\/]{1,127}$"
    if not image_tag or not re.match(allowed_regex, image_tag):
        return False

    if not image_tag:
        return False

    lines: list[str] = []

    path_line = f'IMAGE_TAG="{image_tag}"\n'
    path_exists = False

    for i, line in enumerate(lines):
        if line.startswith("IMAGE_TAG="):
            lines[i] = path_line
            path_exists = True
            break

    if not path_exists:
        lines.append(path_line)

    # Save to system config
    save_config("image_tag", image_tag)
    return True

def save_git_build_repository(git_build_repository: str):
    
    allowed_regex = r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-\/]{1,127}$"
    if not git_build_repository or not re.match(allowed_regex, git_build_repository):
        print(f"Invalid git_build_repository: {git_build_repository}")
        return False
    if not git_build_repository:
        return False

    lines = []

    path_line = f'GIT_BUILD_REPOSITORY="{git_build_repository}"\n'
    path_exists = False

    for i, line in enumerate(lines):
        if line.startswith("GIT_BUILD_REPOSITORY="):
            lines[i] = path_line
            path_exists = True
            break

    if not path_exists:
        lines.append(path_line)

    # Save to system config
    save_config("git_build_repository", git_build_repository)
    return True

def save_git_build_branch(git_build_branch: str):
    """Save the image tag to the appropriate storage"""
    allowed_regex = r"^[a-zA-Z0-9][a-zA-Z0-9_.\-\/]{1,127}$"
    if not git_build_branch or not re.match(allowed_regex, git_build_branch):
        return False

    if not git_build_branch:
        return False

    lines: list[str] = []

    path_line = f'GIT_BUILD_BRANCH="{git_build_branch}"\n'
    path_exists = False

    for i, line in enumerate(lines):
        if line.startswith("GIT_BUILD_BRANCH="):
            lines[i] = path_line
            path_exists = True
            break

    if not path_exists:
        lines.append(path_line)

    # Save to system config
    save_config("git_build_branch", git_build_branch)
    return True


def get_savefiles_path():
    """Get the savefiles path from the appropriate storage"""

    # If not in .env, try system config
    saved_path = get_config("savefiles_path")
    if saved_path and saved_path.lower() != "none":
        return saved_path

    # If not found anywhere, use default
    if getattr(sys, "frozen", False):
        default_path = os.path.dirname(sys.executable)
    else:
        default_path = os.path.dirname(os.path.dirname(__file__))

    return os.path.join(default_path, "savefiles")


def get_image_repository():
    """Get the image repository from the appropriate storage"""
    image_repository = get_config("image_repository")
    if image_repository and image_repository.lower() != "none":
        return image_repository
    return "epicstaff"


def get_image_tag():
    """Get the image tag from the appropriate storage"""
    image_tag = get_config("image_tag")
    if image_tag and image_tag.lower() != "none":
        return image_tag
    return "latest-main"

def get_git_build_branch():
    git_build_branch = get_config("git_build_branch")
    if git_build_branch and git_build_branch.lower() != "none":
        return git_build_branch
    return "main"

def get_git_build_repository():
    git_build_repository = get_config("git_build_repository")
    if git_build_repository and git_build_repository.lower() != "none":
        return git_build_repository
    return "https://github.com/EpicStaff/EpicStaff.git"

def _tk_dialog() -> str:
    """
    Opens a Tkinter “choose directory” dialog on the **current thread**
    and returns the selected path ('' if cancelled).
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()                 # Hide the root window
    root.attributes("-topmost", True)
    path = filedialog.askdirectory()
    root.destroy()
    return path


def select_folder() -> str | None:
    """
    Cross-platform folder picker that can be called **from any thread**.

    • On macOS, Tkinter **must** run in the main thread.  
      If we’re not on the main thread we launch a short-lived helper
      Python process that shows the dialog and prints the result.

    • On Windows/Linux the old “run Tkinter in another thread” trick
      still works, so we keep it for compatibility.

    Returns the chosen folder path, or '' / None if the user cancels.
    """
    # ---------- macOS special case ----------
    if platform.system() == "Darwin":
        if threading.current_thread() is threading.main_thread():
            return _tk_dialog()

        # ! We are on macOS but NOT on the main thread → spawn a helper
        helper = textwrap.dedent(
            r"""
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            print(filedialog.askdirectory() or "")
            root.destroy()
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            capture_output=True,
            text=True,
        )
        # Strip the trailing newline and return the path (may be empty)
        return completed.stdout.rstrip("\n")

    # ---------- Windows / Linux ----------
    if threading.current_thread() is threading.main_thread():
        return _tk_dialog()

    # Safe to run Tkinter in another thread on these OSes
    result = {"path": ""}

    def runner():
        result["path"] = _tk_dialog()

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    return result["path"]



