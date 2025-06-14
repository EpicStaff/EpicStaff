import os
from dotenv import load_dotenv
from fastapi import FastAPI
from base_models import Callable
from models.models import (
    RunToolParamsModel,
    ClassDataResponseModel,
    RunToolResponseModel,
)
from utils import get_tool_data, run_tool, init_tool_classes
from pickle_encode import obj_to_txt
import uvicorn
from loguru import logger

app = FastAPI()

tool_alias_class_dict = init_tool_classes()


@app.get(
    "/tool/{tool_alias}/class-data/",
    status_code=200,
    response_model=ClassDataResponseModel,
)
def get_class_data(tool_alias: str):
    tool_data = get_tool_data(tool_alias_class_dict[tool_alias]())
    txt = obj_to_txt(tool_data)
    return ClassDataResponseModel(classdata=txt)


@app.post(
    "/tool/{tool_alias}/run", status_code=200, response_model=RunToolResponseModel
)
def run(tool_alias: str, run_tool_params_model: RunToolParamsModel):
    logger.debug(
        f"tool/{tool_alias}/run \nrun_tool_params_model: {run_tool_params_model}"
    )
    result = run_tool(
        tool_alias_class_dict[tool_alias],
        run_tool_params_model.run_args,
        run_tool_params_model.run_kwargs,
    )

    return RunToolResponseModel(data=result)


if __name__ == "__main__":
    tool_alias_class_dict = init_tool_classes()

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, workers=1)
