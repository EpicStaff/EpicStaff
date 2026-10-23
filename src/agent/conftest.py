import os
import sys

# litellm otherwise fetches its price map from GitHub on import; tests price from the bundled copy.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# agent root → resolves `app.*`
_agent_root = os.path.dirname(os.path.abspath(__file__))
# src root → resolves `shared.*` (mirrors PYTHONPATH=/app/src in Docker)
_src_root = os.path.dirname(_agent_root)

for _path in (_src_root, _agent_root):
    if _path not in sys.path:
        sys.path.insert(0, _path)
