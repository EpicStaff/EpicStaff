import os
from pathlib import Path
import yaml


def load_env_from_yaml_config(yaml_config_path):
    loaded = False
    try:
        with open(Path(yaml_config_path).resolve()) as f:
            cfg: dict = yaml.load(f, Loader=yaml.FullLoader)
        for k, v in cfg["constants"].items():
            os.environ[k] = v
        loaded = True
    except Exception as e:
        print(e)

    return loaded
