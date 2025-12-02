#!/bin/bash
# Run: docker login $(REGISTRY_DIR)
# Use email as a username
# Create a token on gitlab and use in as a password
REGISTRY_DIR="registry.gitlab.hysdev.com/sheetsui/crewai-sheetsui"

# Read image tag from file
if [ ! -f "./../image_tag.txt" ]; then
  echo "Error: image_tag.txt not found."
  exit 1
fi

IMAGE_TAG=$(cat ../image_tag.txt)


# Stop and remove all containers
echo "Stopping and removing all containers..."
docker ps -aq | xargs -r docker stop
docker ps -aq | xargs -r docker rm


# Pull Docker images
docker pull "$REGISTRY_DIR/django_app:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/manager:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/crew:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/frontend:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/sandbox:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/knowledge:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/realtime:$IMAGE_TAG"
docker pull "$REGISTRY_DIR/crewdb:$IMAGE_TAG"

# Tag Docker images
docker tag "$REGISTRY_DIR/django_app:$IMAGE_TAG" django_app
docker tag "$REGISTRY_DIR/manager:$IMAGE_TAG" manager
docker tag "$REGISTRY_DIR/crew:$IMAGE_TAG" crew
docker tag "$REGISTRY_DIR/frontend:$IMAGE_TAG" frontend
docker tag "$REGISTRY_DIR/sandbox:$IMAGE_TAG" sandbox
docker tag "$REGISTRY_DIR/knowledge:$IMAGE_TAG" knowledge
docker tag "$REGISTRY_DIR/realtime:$IMAGE_TAG" realtime
docker tag "$REGISTRY_DIR/crewdb:$IMAGE_TAG" crewdb

# Pause to view results
read -p "Press Enter to continue..."