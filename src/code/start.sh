#!/bin/bash
set -e

# The Instance Manager handles:
# - Skill file sync from image to savefiles
# - Directory structure creation (.my_epicstaff/flows,tools,projects)
# - Spawning/managing OpenCode instances on demand
# - Idle instance reaping

exec python instance_manager.py
