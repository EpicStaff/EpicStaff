#!/bin/bash

# Get the current absolute path
CURRENT_PATH=$(pwd)

# Replace '\' with '/' (not needed in Bash, but keeping for compatibility)
TARGET_PATH="${CURRENT_PATH}/savefiles/"

# Write to manager.env
echo "CREW_SAVEFILES_PATH=\"$TARGET_PATH\"" > ./../.env

# Print confirmation
echo "Path saved to manager.env: $TARGET_PATH"