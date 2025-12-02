#!/bin/bash

# Set temp file and target directory
ZIP_URL="https://github.com/EpicStaff/EpicStaff/archive/refs/heads/main.zip"
TMP_ZIP="epicstaff.zip"
EXTRACTED_DIR="EpicStaff-main"
SRC_DIR="$EXTRACTED_DIR/run_program"
TARGET_DIR="run_program"

# Download the ZIP archive of the main branch
echo "Downloading ZIP archive..."
curl -L -o "$TMP_ZIP" "$ZIP_URL"

# Extract only the run_program folder
echo "Extracting run_program folder..."
unzip -q "$TMP_ZIP" "$SRC_DIR/*"

# Create local run_program directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Merge extracted files into existing run_program
cp -r "$SRC_DIR/"* "$TARGET_DIR/"

# Clean up
rm -rf "$EXTRACTED_DIR" "$TMP_ZIP"

echo "✅ run_program folder merged successfully into ./$TARGET_DIR"
