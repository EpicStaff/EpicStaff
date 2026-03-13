import subprocess
import time
import os
from dotenv import load_dotenv

load_dotenv()


class DockerComputer:
    def get_environment(self):
        return "linux"

    def get_dimensions(self):
        return (1920, 1080)  # Default fallback; will be updated in __enter__.

    def __init__(
        self,
        container_name=None,
        image="ghcr.io/openai/browser_use_with_cua:latest",
        display=None,
        port_mapping=None,
    ):
        self.container_name = container_name or os.getenv(
            "CUA_CONTAINER_NAME", "browser_use_with_cua"
        )
        self.image = image
        self.display = display
        self.port_mapping = port_mapping
        self.display = display or os.getenv("DISPLAY", ":99")
        self.port_mapping = port_mapping
        # flag: if 1 — execute COMMANDS LOCALLY (in this same container), without docker exec
        self.use_local = os.getenv("CUA_USE_LOCAL", "1") == "1"

    def __enter__(self):
        # Local mode: don't touch docker at all
        if self.use_local:
            # Get display geometry locally via _exec
            geometry = self._exec(
                f"DISPLAY={self.display} xdotool getdisplaygeometry"
            ).strip()
            if geometry:
                w, h = geometry.split()
                self.dimensions = (int(w), int(h))
            else:
                self.dimensions = (1920, 1080)
            return self

        # Next — branch for docker mode
        try:
            result = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={self.container_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Docker CLI not found. Enable local mode (CUA_USE_LOCAL=1) "
                "or install docker inside the container and mount /var/run/docker.sock."
            )

        if not result.stdout.strip():
            raise RuntimeError(
                f"Container {self.container_name} is not running. Build and run with:\n"
                f"docker build -t {self.container_name} .\n"
                f"docker run --rm -it --name {self.container_name} "
                f"-p {self.port_mapping} -e DISPLAY={self.display} {self.container_name}"
            )

        geometry = self._exec(
            f"DISPLAY={self.display} xdotool getdisplaygeometry"
        ).strip()
        if geometry:
            w, h = geometry.split()
            self.dimensions = (int(w), int(h))
        else:
            self.dimensions = (1920, 1080)

        # print("Starting Docker container...")
        # # Run the container detached, removing it automatically when it stops
        # subprocess.check_call(
        #     [
        #         "docker",
        #         "run",
        #         "-d",
        #         "--rm",
        #         "--name",
        #         self.container_name,
        #         "-p",
        #         self.port_mapping,
        #         self.image,
        #     ]
        # )
        # # Give the container a moment to start
        # time.sleep(3)
        # print("Entering DockerComputer context")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # print("Stopping Docker container...")
        # subprocess.check_call(["docker", "stop", self.container_name])
        # print("Exiting DockerComputer context")
        pass

    # def _exec(self, cmd: str) -> str:
    #     """
    #     Run 'cmd' in the container.
    #     We wrap cmd in double quotes and escape any double quotes inside it,
    #     so spaces or quotes don't break the shell call.
    #     """
    #     # Escape any existing double quotes in cmd
    #     safe_cmd = cmd.replace('"', '\\"')

    #     # Then wrap the entire cmd in double quotes for `sh -c`
    #     docker_cmd = f'docker exec {self.container_name} sh -c "{safe_cmd}"'

    #     return subprocess.check_output(docker_cmd, shell=True).decode(
    #         "utf-8", errors="ignore"
    #      )
    def _exec(self, cmd: str) -> str:
        """Execute a command either locally or via docker exec (depending on the mode)."""
        safe_cmd = cmd.replace('"', '\\"')
        if self.use_local:
            # Locally in this same container
            return subprocess.check_output(f'sh -c "{safe_cmd}"', shell=True).decode(
                "utf-8", errors="ignore"
            )
        else:
            docker_cmd = f'docker exec {self.container_name} sh -c "{safe_cmd}"'
            return subprocess.check_output(docker_cmd, shell=True).decode(
                "utf-8", errors="ignore"
            )

    def screenshot(self) -> str:
        """
        Takes a screenshot with ImageMagick (import), returning base64-encoded PNG.
        Requires 'import'.
        """
        # cmd = (
        #     f"export DISPLAY={self.display} && "
        #     "import -window root /tmp/screenshot.png && "
        #     "base64 /tmp/screenshot.png"
        # )
        cmd = (
            f"export DISPLAY={self.display} && "
            "import -window root png:- | base64 -w 0"
        )

        return self._exec(cmd)

    def click(self, x: int, y: int, button: str = "left") -> None:
        button_map = {"left": 1, "middle": 2, "right": 3}
        b = button_map.get(button, 1)
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y} click {b}")

    def double_click(self, x: int, y: int) -> None:
        self._exec(
            f"DISPLAY={self.display} xdotool mousemove {x} {y} click --repeat 2 1"
        )

    def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        """
        For simple vertical scrolling: xdotool click 4 (scroll up) or 5 (scroll down).
        """
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")
        clicks = abs(scroll_y)
        button = 4 if scroll_y < 0 else 5
        for _ in range(clicks):
            self._exec(f"DISPLAY={self.display} xdotool click {button}")

    def type(self, text: str) -> None:
        """
        Type the given text via xdotool, preserving spaces and quotes.
        """
        # Escape single quotes in the user text: ' -> '\'\''
        safe_text = text.replace("'", "'\\''")
        # Then wrap everything in single quotes for xdotool
        cmd = f"DISPLAY={self.display} xdotool type -- '{safe_text}'"
        self._exec(cmd)

    def wait(self, ms: int = 1000) -> None:
        time.sleep(ms / 1000)

    def move(self, x: int, y: int) -> None:
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")

    def keypress(self, keys: list[str]) -> None:
        mapping = {
            "ENTER": "Return",
            "LEFT": "Left",
            "RIGHT": "Right",
            "UP": "Up",
            "DOWN": "Down",
            "ESC": "Escape",
            "SPACE": "space",
            "BACKSPACE": "BackSpace",
            "TAB": "Tab",
        }
        mapped_keys = [mapping.get(key, key) for key in keys]
        combo = "+".join(mapped_keys)
        self._exec(f"DISPLAY={self.display} xdotool key {combo}")

    def drag(self, path: list[dict[str, int]]) -> None:
        if not path:
            return
        start_x = path[0]["x"]
        start_y = path[0]["y"]
        self._exec(
            f"DISPLAY={self.display} xdotool mousemove {start_x} {start_y} mousedown 1"
        )
        for point in path[1:]:
            self._exec(
                f"DISPLAY={self.display} xdotool mousemove {point['x']} {point['y']}"
            )
        self._exec(f"DISPLAY={self.display} xdotool mouseup 1")

    def get_current_url(self):
        return None
