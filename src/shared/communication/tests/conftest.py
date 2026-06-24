import sys
from pathlib import Path

# src/shared is the import root — `communication` is a top-level package from there.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
