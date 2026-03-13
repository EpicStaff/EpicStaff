import os
import time
from typing import Any
import docker.types
import requests
from requests import HTTPError, RequestException

import docker
from docker.types import Mount
from docker.models.images import Image
from docker.models.containers import Container

from models.models import RunToolParamsModel
from repositories.import_tool_data_repository import (
    ImportToolDataRepository,
)
from services.tool_image_service import ToolImageService
from helpers.logger import logger


class ToolContainerService:
    docker_client = docker.client.from_env()

    def __init__(
        self,
        tool_image_service: ToolImageService,
        import_tool_data_repository: ImportToolDataRepository,
    ):
        self.tool_image_service = tool_image_service
        self.import_tool_data_repository = import_tool_data_repository

        manager_container = self.docker_client.containers.get("manager_container")
        network_settings = manager_container.attrs["NetworkSettings"]
        self.network_name = list(network_settings["Networks"].keys())[0]

    def post_data_with_retry(self, url, json, retries=30, delay=3):
        if json is None:
            json = dict()

        for attempt in range(retries):
            try:
                logger.debug(f"Attempt {attempt + 1} to fetch data from URL: {url}")
                resp = requests.post(url, json=json)
                if resp.status_code == 200:
                    logger.info(f"Data fetched successfully from URL: {url}")
                    return resp
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed on attempt {attempt + 1}: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
        logger.error(f"Failed to fetch data after {retries} attempts for URL: {url}")
        raise Exception(f"Failed to fetch data after {retries} attempts.")

    def find_running_containers_by_image_name(self, image_name) -> list[Container]:
        containers = self.docker_client.containers.list(
            filters={"ancestor": image_name}
        )
        logger.info(
            f"Found {len(containers)} running container(s) for image name: {image_name}"
        )
        return containers

    def get_running_tool(self, tool_alias: str) -> Container | None:
        logger.debug(f"Getting running container for tool alias: {tool_alias}")
        image_name = self.import_tool_data_repository.find_image_name_by_tool_alias(
            tool_alias=tool_alias
        )
        list_containers = self.find_running_containers_by_image_name(image_name)
        if not list_containers:
            logger.info(f"No running container found for tool alias: {tool_alias}")
            return None
        logger.info(f"Found running container for tool alias: {tool_alias}")
        return list_containers[0]

    def request_class_data(
        self, tool_alias: str, tool_init_configuration: dict[str, Any] | None
    ) -> dict:
        container = self.get_running_tool(tool_alias=tool_alias)
        if not container:
            logger.info(
                f"Container not found for tool alias {tool_alias}, starting a new container."
            )
            container = self.run_container_by_tool_alias(tool_alias=tool_alias)

        response = self.post_data_with_retry(
            f"http://{container.name}:8000/tool/{tool_alias}/class-data/",
            json=tool_init_configuration,
        )
        return response.json()

    def request_run_tool(
        self, tool_alias: str, run_tool_params_model: RunToolParamsModel
    ) -> dict:
        container = self.get_running_tool(tool_alias=tool_alias)
        if not container:
            logger.info(
                f"Container not found for tool alias {tool_alias}, starting a new container."
            )
            container = self.run_container_by_tool_alias(tool_alias=tool_alias)

        try:
            response = requests.post(
                url=f"http://{container.name}:8000/tool/{tool_alias}/run",
                json=run_tool_params_model.model_dump(),
            )
            response.raise_for_status()
            logger.info(f"Tool run requested successfully for tool alias: {tool_alias}")
            return response.json()
        except HTTPError as e:
            logger.error(f"HTTP error occurred while running tool {tool_alias}: {e}")
            raise RuntimeError(
                f"HTTP error occurred while running tool {tool_alias}: {e}"
            )
        except RequestException as e:
            logger.error(f"Request error occurred while running tool {tool_alias}: {e}")
            raise RuntimeError(
                f"Request error occurred while running tool {tool_alias}: {e}"
            )

    def run_container_by_tool_alias(self, tool_alias):
        logger.debug(f"Running container for tool alias: {tool_alias}")
        image = self.tool_image_service.get_or_build_tool_alias(tool_alias=tool_alias)
        return self.run_container(image=image)

    def run_container(
        self, image: Image, container_name=None, port: int = 0
    ) -> Container:
        if container_name is None:
            container_name = image.tags[-1].split(":")[0]

        # Remove any existing container with the same name
        for container in self.docker_client.containers.list(all=True):
            if container.name == container_name:
                logger.info(f"Removing existing container with name: {container_name}")
                container.remove(force=True)
                break

        # Run new container
        container_tool = self.docker_client.containers.run(
            image=image,
            ports={"8000/tcp": port},
            network=self.network_name,
            detach=True,
            name=container_name,
            labels={"com.docker.compose.project": "epicstaff-tools"},
            environment={"SAVE_FILE_PATH": "/home/user/root/app/savefiles"},
            mounts=[
                Mount(
                    # TODO: remove, crew_config is deprecated
                    source="crew_config",
                    target="/home/user/root/app/env_config/",
                ),
                Mount(
                    source=os.environ.get("CREW_SAVEFILES_PATH", "/c/savefiles"),
                    target="/home/user/root/app/savefiles/",
                    type="bind",
                ),
            ],
        )

        logger.info(f"Container {container_name} started successfully.")
        return container_tool
