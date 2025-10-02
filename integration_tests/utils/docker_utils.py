from pathlib import Path
import subprocess

from loguru import logger


def docker_compose_up(project_dir):
    try:
        project_path = Path(project_dir).resolve()
        build_result = subprocess.run(
            ["docker", "compose", "build"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(build_result.stdout)

        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.exception(e.stderr)


def docker_compose_down(project_dir):
    try:
        project_path = Path(project_dir).resolve()
        result = subprocess.run(
            ["docker", "compose", "down"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.exception(e.stderr)    
