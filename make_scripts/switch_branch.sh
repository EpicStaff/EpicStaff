#!/bin/bash
set -e

NEW_BRANCH="$1"

if [ -z "$NEW_BRANCH" ]; then
    echo "ERROR: No branch name provided."
    echo "Usage: ./make_scripts/switch_branch.sh <branch-name>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "--- Switching full environment to branch: $NEW_BRANCH ---"
echo ""

# Step 1: Stash current image tags
echo "[Step 1/5] Stashing current image tags..."
"$SCRIPT_DIR/stash_tag_images.sh"
echo ""

# Step 2: Backup current volume data
echo "[Step 2/5] Backing up current volume data..."
"$SCRIPT_DIR/backup.sh"
echo ""

# Step 3: Switch branch
echo "[Step 3/5] Switching to branch $NEW_BRANCH..."
git checkout "$NEW_BRANCH"
echo ""

# Step 4: Apply new branch tags
echo "[Step 4/5] Applying new branch's image tags..."
"$SCRIPT_DIR/apply_tag_images.sh"
echo ""

# Step 5: Apply new branch backup
echo "[Step 5/5] Applying new branch's volume data..."
"$SCRIPT_DIR/apply_backup.sh"
echo ""

echo "Full environment switch to $NEW_BRANCH is complete."
