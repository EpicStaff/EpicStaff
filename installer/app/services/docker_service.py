from __future__ import annotations
from abc import ABC, abstractmethod

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import platform
from queue import Empty, Queue
import shutil
import tempfile
import threading
import docker
from docker.errors import DockerException
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Generator, Literal
import os
import time
import stat

from flask_socketio import emit
from app.utils import (
    get_env_file_path,
    get_git_build_branch,
    get_git_build_repository,
    get_savefiles_path,
    get_compose_file_path,
    get_image_repository,
    get_image_tag,
)


class StateException(Exception):
    """Custom exception for state-related errors in DockerService."""

    pass


class State(ABC):
    STATE_NAME: str = "base"

    def get_state_name(self) -> str:
        return self.STATE_NAME

    @property
    def docker_service(self) -> DockerService:
        return self._docker_service

    @docker_service.setter
    def docker_service(self, docker_service: DockerService) -> None:
        self._docker_service = docker_service

    def stop_container(self, container_id: str) -> None:
        """Stop a specific container by ID"""
        raise StateException("cannot stop container in current state")

    def restart_container(self, container_id: str) -> None:
        """Restart a specific container by ID"""
        raise StateException("cannot restart container in current state")

    def update_images(self) -> Generator[str, None, None]:
        """Updates Docker images from the registry"""
        raise StateException("cannot update immages in current state")

    def run_project(
        self, savefiles_path: str | None = None
    ) -> Generator[str, None, None]:
        """Runs Docker Compose with automatic .env and volume creation"""
        raise StateException("cannot run project in current state")

    def stop_project(self) -> None:
        """Stop and remove all containers from allowed projects"""
        raise StateException("cannot stop project in current state")


class DefaultState(State):
    STATE_NAME = "default"

    def stop_container(self, container_id: str) -> None:
        self._docker_service.transition_to(StopContainerState())
        self._docker_service.stop_container(container_id)

    def restart_container(self, container_id: str) -> None:
        self._docker_service.transition_to(StopContainerState())
        self._docker_service.restart_container(container_id)

    def update_images(
        self, mode: Literal["pull", "build"]
    ) -> Generator[str, None, None]:
        self._docker_service.transition_to(UpdateImagesState())
        yield from self._docker_service.update_images(mode=mode)

    def run_project(
        self, savefiles_path: str | None = None
    ) -> Generator[str, None, None]:
        self._docker_service.transition_to(ManageProjectState())
        yield from self.docker_service.run_project(savefiles_path=savefiles_path)

    def stop_project(self) -> None:
        self._docker_service.transition_to(ManageProjectState())
        self.docker_service.stop_project()


class StopContainerState(State):
    STATE_NAME = "stop_container"

    def stop_container(self, container_id: str) -> None:
        """Stop a specific container if it belongs to allowed projects"""
        try:
            container = self.docker_service.client.containers.get(container_id)
            if self.docker_service._is_allowed_container(container):
                container.stop()
            else:
                raise ValueError("Container is not part of allowed projects")
        except docker.errors.DockerException as e:
            raise RuntimeError(f"Failed to stop container: {str(e)}")
        finally:
            self.docker_service.transition_to(DefaultState())

    def restart_container(self, container_id: str) -> None:
        try:
            container = self.docker_service.client.containers.get(container_id)
            if self.docker_service._is_allowed_container(container):
                container.restart()
            else:
                raise ValueError("Container is not part of allowed projects")
        except docker.errors.DockerException as e:
            raise RuntimeError(f"Failed to restart container: {str(e)}")

        finally:
            self.docker_service.transition_to(DefaultState())


class UpdateImagesState(State):
    STATE_NAME = "update_images"

    def __init__(self):
        self.update_process_list: list[subprocess.Popen] = []
        self.terminate_update_images_flag = False
        self.update_images_started = False

    def terminate(self):
        """Terminate the update process if it is running"""
        self.terminate_update_images_flag = True
        if self.update_process_list:
            for process in self.update_process_list:
                if process and process.poll() is None:
                    process.terminate()
        
        self.update_process_list = []
        self.update_images_started = False

    def _clone_git_and_build_images(self) -> Generator[str, None, None]:
        image_build_configs = {
            "django_app": {"dockerfile": "src/django_app/Dockerfile.dj", "context": "src/django_app"},
            "manager": {"dockerfile": "src/manager/Dockerfile.man", "context": "src"},
            "crew": {"dockerfile": "src/crew/Dockerfile.crew", "context": "src"},
            "frontend": {"dockerfile": "frontend/Dockerfile.fe", "context": "frontend"},
            "sandbox": {"dockerfile": "src/sandbox/Dockerfile.sandbox", "context": "src"},
            "knowledge": {
                "dockerfile": "src/knowledge/Dockerfile.knowledge",
                "context": "src/knowledge",
            },
            "realtime": {
                "dockerfile": "src/realtime/Dockerfile.realtime",
                "context": "src/realtime",
            },
            "crewdb": {"dockerfile": "src/crewdb/Dockerfile.crewdb", "context": "src/crewdb"},
        }

        # Use the branch from the original code
        branch = get_git_build_branch()
        # repo_url = "https://gitlab.hysdev.com/sheetsui/crewai-sheetsui.git"
        repo_url = get_git_build_repository()
        tmp_repo_path = None  # Initialize to None for cleanup in finally block
        try:
            # 1. Create a temporary directory
            tmp_repo_path = Path(tempfile.mkdtemp(prefix="docker_build_repo_"))
            yield f"[INFO] Cloning repository to temporary directory: {tmp_repo_path}\n"

            # 2. Clone the repository into the temporary directory
            # Git will handle authentication (e.g., via credential manager, SSH agent, or prompts if interactive)
            clone_command = f'git clone -b {branch} {repo_url} "{tmp_repo_path}"'
            yield from self._run_script(clone_command, prefix="git clone")

            # Basic check to see if cloning was successful
            if not tmp_repo_path.is_dir() or not any(tmp_repo_path.iterdir()):
                yield "[ERROR] Git clone failed or resulted in an empty directory. Cannot proceed with build.\n"
                self.docker_service.transition_to(DefaultState())
                return

            # Stop and remove all containers (existing code)
            container_ids = subprocess.check_output(
                "docker ps -a -q", shell=True, text=True
            ).splitlines()
            for cid in container_ids:
                if cid.strip():
                    yield from self._run_script(
                        f"docker stop {cid}", prefix="stop"
                    )
                    yield from self._run_script(
                        f"docker rm {cid}", prefix="rm"
                    )

            # For capturing outputs from all parallel builds
            output_queue = Queue()

            def run_build(image_name, config):
                if self.terminate_update_images_flag:
                    output_queue.put(f"[{image_name}] Terminated before building.\n")
                    return

                # Construct the command using local paths relative to the cloned repo root
                dockerfile_full_path = tmp_repo_path / config["dockerfile"]
                context_full_path = tmp_repo_path / config["context"]

                # Ensure paths are strings for subprocess.Popen
                command = f'docker build -t {image_name} -f "{dockerfile_full_path}" "{context_full_path}"'
                for line in self._run_script(command, prefix=image_name):
                    output_queue.put(line)

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(run_build, name, cfg)
                    for name, cfg in image_build_configs.items()
                ]

                # Read from the queue while builds are running
                finished = False
                while not finished:
                    try:
                        line = output_queue.get(timeout=0.5)
                        yield line
                    except Empty:
                        if all(f.done() for f in futures):
                            finished = True
        except Exception as e:
            yield f"[CRITICAL ERROR] Failed during image update process: {e}\n"
        finally:
            # Clean up the temporary directory
            if tmp_repo_path and tmp_repo_path.exists():
                yield f"[INFO] Cleaning up temporary directory: {tmp_repo_path}\n"
                try:
                    def handle_remove_readonly(func, path, exc_info):
                        if not os.access(path, os.W_OK):
                            os.chmod(path, stat.S_IWRITE)
                            func(path)
                        else:
                            raise
                    shutil.rmtree(tmp_repo_path, onexc=handle_remove_readonly)
                except OSError as e:
                    yield f"[WARNING] Failed to remove temporary directory {tmp_repo_path}: {e}\n"
            self.update_images_started = (
                False  # Reset flag regardless of success/failure
            )

    def _pull_docker_images(self) -> Generator[str, None, None]:
        """Updates Docker images from the registry"""

        images = [
            "django_app",
            "manager",
            "crew",
            "frontend",
            "sandbox",
            "knowledge",
            "realtime",
            "crewdb",
        ]

        registry_dir = get_image_repository()
        image_tag = get_image_tag()
        # Stop and remove all containers
        container_ids = subprocess.check_output(
            "docker ps -a -q", shell=True, text=True
        ).splitlines()
        for cid in container_ids:
            if cid.strip():
                yield from self._run_script(f"docker stop {cid}", prefix="stop")
                yield from self._run_script(f"docker rm {cid}", prefix="rm")

        # Pull and tag new images
        for image in images:
            if self.terminate_update_images_flag:
                yield "Update images process was terminated.\n"
                self.update_images_started = False
                return

            full_image = f"{registry_dir}/{image}:{image_tag}"
            yield from self._run_script(f"docker pull {full_image}", prefix=image)
            yield from self._run_script(
                f"docker tag {full_image} {image}", prefix=image
            )

    def update_images(
        self, mode: Literal["pull", "build"]
    ) -> Generator[str, None, None]:
        """Updates Docker images by cloning the repo locally first."""

        try:
            if self.update_images_started:
                self.terminate()

            self.update_images_started = True
            self.terminate_update_images_flag = False
            if mode == "build":
                yield from self._clone_git_and_build_images()
            elif mode == "pull":
                yield from self._pull_docker_images()
            else:
                yield "[ERROR] Invalid mode for update_images. Use 'pull' or 'build'.\n"
            self.terminate_update_images_flag = False
            self.update_images_started = False
        except Exception as e:
            yield f"[CRITICAL ERROR] Failed during image update process: {e}\n"
        finally:
            self.docker_service.transition_to(DefaultState())

    def stop_project(self) -> None:
        """Stop update"""
        self.terminate()
        self.docker_service.transition_to(DefaultState())


    def _run_script(
        self, path: str, prefix: str = ""
    ) -> Generator[str, None, None]:
        """Runs a script and yields its output in real time"""
        try:

            process = subprocess.Popen(
                path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True,
                bufsize=1,
            )
            self.update_process_list.append(process)

            if process.stdout is None:
                yield f"[{prefix}] Failed to capture output of: {path}\n"
                return

            for line in process.stdout:
                yield f"[{prefix}] {line.rstrip()}\n"

            process.stdout.close()
            process.wait()

        except Exception as e:
            yield f"[{prefix}] Error running script '{path}': {e}\n"


class ManageProjectState(State):
    STATE_NAME = "manage_project"

    def __init__(self):
        self.up_process = None

    def run_project(
        self, savefiles_path: str | None = None
    ) -> Generator[str, None, None]:
        """Runs Docker Compose with automatic .env and volume creation"""
        # Get savefiles path from config or use provided one
        if savefiles_path is None:
            savefiles_path = get_savefiles_path()

        # Convert path to forward slashes for Docker
        target_path = str(Path(savefiles_path).absolute()).replace("\\", "/")

        # Create savefiles directory
        savefiles_dir = Path(savefiles_path)
        savefiles_dir.mkdir(exist_ok=True)

        # Always rewrite .env with current path
        env_path = get_env_file_path()
        with env_path.open("w", encoding="utf-8") as f:
            f.write(f'CREW_SAVEFILES_PATH="{target_path}"\n')
        yield f".env updated at: {env_path} with path: {target_path}\n"

        # Create Docker volumes
        volumes = ["crew_config", "crew_pgdata", "sandbox_venvs", "sandbox_executions"]
        for line in self.docker_service.create_volumes(volumes):
            yield line

        # Check container status
        docker_compose_path = get_compose_file_path()
        running_services = self.docker_service.get_running_services(docker_compose_path)
        all_services = self.docker_service.get_all_services(docker_compose_path)

        if set(running_services) == set(all_services):
            yield "All containers are already running. Nothing to do.\n"
            return

        # Run missing/stopped containers
        yield f"Using compose file: {docker_compose_path}\n"
        yield from self._up_services(docker_compose_path)

        self.docker_service.transition_to(DefaultState())

    def stop_project(self) -> None:
        """Stop and remove all containers from allowed projects using threads"""
        if self.up_process is not None:
            # If an up process is running, we need to terminate it first
            self.up_process.terminate()
            self.up_process = None

        def stop_and_remove(container):
            try:
                container.stop()
                container.remove()
            except Exception as e:
                print(f"Error removing container {container.name}: {e}")

        try:
            containers = self.docker_service.client.containers.list(all=True)
            threads = []
            for container in containers:
                if self.docker_service._is_allowed_container(container):
                    t = threading.Thread(target=stop_and_remove, args=(container,))
                    t.start()
                    threads.append(t)

            for t in threads:
                t.join()
        except Exception as e:
            raise RuntimeError(f"Failed to stop project: {str(e)}")
        finally:
            self.docker_service.transition_to(DefaultState())
            self.up_process = None

    def _up_services(self, compose_file_path: Path) -> Generator[str, None, None]:
        """Start services defined in compose file and return SSE-compatible lines."""
        cmd = (
            f'docker compose -f "{compose_file_path}" '
            f'--project-name "epicstaff" up -d'  # keep -d so the call returns quickly
        )

        try:
            self.up_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge stderr → stdout
                text=True,
            )
            for line in iter(self.up_process.stdout.readline, ""):
                yield f"{line.rstrip()}\n"
            self.up_process.stdout.close()

        except subprocess.CalledProcessError as e:
            error_lines = [f"Error starting services (exit {e.returncode}):\n\n"]
            if e.stdout:
                error_lines += [f"{ln}\n\n" for ln in e.stdout.splitlines()]
            return error_lines
        finally:
            # Ensure we clean up the process reference
            self.update_process = None


class DockerService:
    def __init__(self, state: State | None = None):
        self.ALLOWED_PROJECTS = ["epicstaff", "epicstaff-tools"]
        self._client = None
        if state is None:
            state = DefaultState()

        self._state = state
        self._state.docker_service = self

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = self._get_docker_client()
        return self._client

    def transition_to(self, state: State):

        self._state = state
        self._state.docker_service = self
        try:
            emit("state", {"state": self.get_state_name()})
        except Exception as e:
            print(f"Error emitting state change: {e}")
        pass

    def run_project(self, savefiles_path=None):
        """Runs Docker Compose with automatic .env and volume creation"""

        yield from self._state.run_project(savefiles_path)

    def stop_container(self, container_id: str) -> None:
        """Stop a specific container if it belongs to allowed projects"""
        self._state.stop_container(container_id)

    def update_images(
        self, mode: Literal["pull", "build"]
    ) -> Generator[str, None, None]:
        """Updates Docker images"""
        yield from self._state.update_images(mode=mode)

    def restart_container(self, container_id: str) -> None:
        """Restart a specific container if it belongs to allowed projects"""
        self._state.restart_container(container_id)

    def stop_project(self) -> None:
        """Stop and remove all containers from allowed projects using threads"""
        self._state.stop_project()

    def get_containers(self) -> List[Dict]:
        """Get list of containers from allowed projects"""
        try:
            containers = self.client.containers.list(all=True)
            container_statuses = []

            for container in containers:
                if self._is_allowed_container(container):
                    state: dict = container.attrs.get("State", {})
                    started_at = state.get("StartedAt", None)
                    health = state.get("Health", {}).get(
                        "Status"
                    )  # e.g., 'healthy', 'unhealthy', or None
                    container_statuses.append(
                        {
                            "name": container.name,
                            "status": container.status,
                            "health": health,
                            "id": container.id[:12],
                            "ports": container.ports,
                            "started_at": started_at,
                            "project": container.labels.get(
                                "com.docker.compose.project", "unknown"
                            ),
                        }
                    )

            return container_statuses
        except docker.errors.DockerException as e:
            raise RuntimeError(f"Docker error: {str(e)}")

    def get_healthy_containers(self) -> List[str]:
        """Get list of healthy containers from allowed projects"""
        try:
            containers = self.client.containers.list()
            healthy_containers = []

            for container in containers:
                if (
                    self._is_allowed_container(container)
                    and container.attrs.get("State", {}).get("Health", {}).get("Status")
                    == "healthy"
                ):
                    healthy_containers.append(container.name)

            return healthy_containers
        except Exception as e:
            print(f"Error checking container health: {e}")
            return []

    def get_state_name(self) -> str:
        """Get the current state name"""
        return self._state.get_state_name()

    def _get_docker_host_from_context(self) -> str | None:
        """Fetch Docker host from the current context."""
        try:
            result = subprocess.run(
                ["docker", "context", "inspect"],
                capture_output=True,
                check=True,
                text=True,
            )
            contexts = json.loads(result.stdout)
            if contexts and isinstance(contexts, list):
                docker_endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
                return docker_endpoint
        except (
            subprocess.CalledProcessError,
            KeyError,
            IndexError,
            json.JSONDecodeError,
        ):
            return None

    def _get_docker_client(self) -> docker.DockerClient:
        """Initialize Docker client using context or fallbacks."""
        # Try from_env first (uses DOCKER_HOST if set)
        try:
            return docker.from_env()
        except DockerException:
            pass

        # Try from docker context
        docker_host = self._get_docker_host_from_context()
        if docker_host:
            try:
                return docker.DockerClient(base_url=docker_host)
            except DockerException:
                pass

        raise RuntimeError(
            "Could not connect to the Docker daemon using from_env or context."
        )

    def _is_allowed_container(
        self, container: docker.models.containers.Container
    ) -> bool:
        """Check if container belongs to allowed projects using Docker Compose labels"""
        labels = container.labels
        project = labels.get("com.docker.compose.project", "").lower()
        return project in self.ALLOWED_PROJECTS

    def _run_compose_command(self, compose_file_path: Path, command: str) -> List[str]:
        """Run a docker compose command and return its output as a list of lines"""
        try:
            result = subprocess.run(
                f'docker compose -f "{compose_file_path}" {command}',
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().splitlines()
        except subprocess.CalledProcessError as e:
            print(f"Error running docker compose command: {e}")
            return []

    def get_running_services(self, compose_file_path: Path) -> List[str]:
        """Get list of running services from compose file"""
        return self._run_compose_command(
            compose_file_path, "ps --status=running --services"
        )

    def get_all_services(self, compose_file_path: Path) -> List[str]:
        """Get list of all services defined in compose file"""
        return self._run_compose_command(compose_file_path, "config --services")

    def create_volumes(self, volumes: List[str]) -> List[str]:
        """Create Docker volumes if they don't exist"""
        output_lines = []
        for volume_name in volumes:
            try:
                self.client.volumes.create(name=volume_name)
                output_lines.append(f"Created volume {volume_name}\n\n")
            except docker.errors.APIError as e:
                if "already exists" in str(e):
                    output_lines.append(f"Volume {volume_name} already exists\n\n")
                else:
                    output_lines.append(
                        f"Error creating volume {volume_name}: {str(e)}\n\n"
                    )
        return output_lines

    def monitor_events(self, callback):
        """Monitor Docker events for allowed containers and call callback with container statuses"""
        try:
            for event in self.client.events(decode=True):
                if event["Type"] == "container":
                    # Get all container statuses when any container changes
                    container_statuses = self.get_containers()
                    callback(container_statuses)
        except Exception as e:
            print(f"Error monitoring Docker events: {e}")
            # Try to reconnect after a short delay
            time.sleep(5)
            self.monitor_events(callback)

    def check_docker_installed(self) -> tuple[bool, bool]:
        """Checks if Docker and Docker Compose are installed"""
        docker = shutil.which("docker") is not None
        compose = shutil.which("docker-compose") is not None or docker
        return docker, compose

    def ensure_docker_running(self):
        docker_ok, _ = self.check_docker_installed()
        if not docker_ok:
            print("Docker is not installed. Attempting to install...")
            if not self._install_docker():
                print("Docker installation failed. Please install Docker manually.")
                return False

        if not self._is_docker_running():
            print("Docker is installed but not running. Trying to start Docker...")
            if not self._try_start_docker():
                print("Failed to start Docker. Please start Docker manually.")
                return False

        print("Docker is running.")
        return True

    def _is_docker_running(self):
        try:
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    def _wait_for_docker(self, timeout: float = 300.0, interval: float = 0.5) -> bool:
        """Wait for Docker to be running, up to `timeout` seconds."""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if self._is_docker_running():
                return True
            time.sleep(interval)
        return False

    def _try_start_docker(self):
        system = platform.system()

        if system == "Windows":
            # Start Docker Desktop on Windows
            subprocess.Popen(
                ["C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Darwin":
            # Start Docker Desktop on macOS
            subprocess.Popen(
                ["open", "-a", "Docker"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Linux":
            # Try to start the Docker daemon on Linux
            try:
                subprocess.run(["sudo", "systemctl", "start", "docker"], check=True)
            except subprocess.CalledProcessError:
                return False

        # Wait for Docker to be responsive
        return self._wait_for_docker()

    def _install_docker(self):
        system = platform.system()
        try:
            if system == "Linux":
                print("Attempting to install Docker...")
                subprocess.run(
                    [
                        "bash",
                        "-c",
                        "curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh",
                    ],
                    check=True,
                )
                return True
            else:
                print("Automatic installation not supported on this OS.")
                return False
        except Exception:
            return False
