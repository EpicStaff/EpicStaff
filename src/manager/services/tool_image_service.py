import os

import docker.errors

from helpers.logger import logger
from services.build_tool import ToolDockerImageBuilder
from repositories.import_tool_data_repository import ImportToolDataRepository

import docker
from docker.models.images import Image
from docker.models.containers import Container
from docker.client import DockerClient


class ToolImageService:
    client: DockerClient = docker.client.from_env()

    def __init__(self, import_tool_data_repository: ImportToolDataRepository):
        self.import_tool_data_repository = import_tool_data_repository

    def build_image(self, image_name: str) -> Image:

        import_tool_data = self.import_tool_data_repository.get_import_class_data(
            image_name=image_name
        )
        logger.info(f"Import data retrieved for image: {image_name}")

        tdib: ToolDockerImageBuilder = ToolDockerImageBuilder(
            tool_dict=import_tool_data.tool_dict,
            import_list=import_tool_data.dependencies,
        )

        image = tdib.build_tool_image(image_name=import_tool_data.image_name)
        logger.info(
            f"Image built successfully with name: {import_tool_data.image_name}"
        )
        return image

    def pull_from_dockerhub(self, image_name: str) -> Image | None:
        repo_host = os.getenv("DOCKERHUB_PROFILE_NAME")
        dockerhub_image_name = f"{repo_host}/tools:{image_name}"

        pulled_image = None
        try:
            pulled_image = self.client.images.pull(dockerhub_image_name)
            logger.info(f"Image {dockerhub_image_name} pulled successfully.")
        except docker.errors.ImageNotFound as e:
            logger.warning(f"Image {dockerhub_image_name} not found: {e}")

        if pulled_image:
            pulled_image.tag(image_name, force=True)
            logger.info(f"Image tagged locally with name: {image_name}")
            pulled_image = self.client.images.get(image_name)
            self.client.images.remove(image=dockerhub_image_name)
            return pulled_image
        return None

    def get_or_build_tool_alias(self, tool_alias: str) -> Image:

        image_name = self.import_tool_data_repository.find_image_name_by_tool_alias(
            tool_alias=tool_alias
        )
        image_list = [img for img in self.client.images.list() if f'{image_name}:latest' in img.tags]

        if image_list:
            logger.info(f"Image found locally for alias {tool_alias}: {image_name}")
            return image_list[0]
        else:
            logger.info(f"No local image found for alias {tool_alias}.")

        pull_tool = os.environ.get("PULL_TOOL", "False").lower() in {"true", "1"}
        if pull_tool:
            logger.info(
                "PULL_TOOL variable set to true. Attempting to pull from DockerHub."
            )

            image = self.pull_from_dockerhub(image_name)
            if image:
                return image

            logger.info(f"Image for alias {tool_alias} not found on DockerHub.")

        logger.info(f"Building new image.")
        return self.build_image(image_name=image_name)
