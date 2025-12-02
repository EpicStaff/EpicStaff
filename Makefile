# Makefile for managing Docker volume backups and image tags
# Use cmd.exe as the shell for executing .bat files on Windows
SHELL = cmd.exe

# IMPORTANT: This Makefile must be run from the project's root directory
# (the same directory this file is in).

# Define phony targets to ensure they run even if files with the same name exist
# These are aliases for the batch scripts.
.PHONY: backup apply-backup stash-tags apply-tags switch

# --- Volume Backups ---

# Usage: make backup
# Creates a .tar archive of the volume, named after the current branch.
backup:
	@echo "--- Creating Volume Backup ---"
	@.\\make_scripts\\backup.bat

# Usage: make apply-backup
# Stops services and restores volume data from the branch's backup file.
apply-backup:
	@echo "--- Applying Volume Backup ---"
	@.\\make_scripts\\apply_backup.bat

# --- Docker Image Tagging ---

# Usage: make stash-tags
# Tags images (e.g., 'crew') with the branch name (e.g., 'crew:my-branch').
stash-tags:
	@echo "--- Stashing Image Tags ---"
	@.\\make_scripts\\stash_tag_images.bat

# Usage: make apply-tags
# Re-tags images from the branch tag (e.g., 'crew:my-branch') back to the original (e.g., 'crew').
apply-tags:
	@echo "--- Applying Stashed Image Tags ---"
	@.\\make_scripts\\apply_tag_images.bat

# --- Full Environment Switching ---

# Usage: make switch b=<branch-name>
# Stashes, backs up, checks out, and applies the new branch's state.
switch:
	@echo "--- Switching Full Branch Environment ---"
	@.\\make_scripts\\switch_branch.bat $(b)