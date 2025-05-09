import os

from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

from models.models import RunToolModel
from import_tool_data_builder import ImportToolDataBuilder

app = FastAPI()


tool_alias_dict = dict()


@app.get("/tool/list", status_code=200)
async def get_all_classes_data(tool_alias: str):
    itdb = ImportToolDataBuilder()
    itd = itdb.get_import_class_data(tool_alias)
    
    # TODO: Then we shall run container with tool 


@app.get("/tool/{tool_alias}/class-data", status_code=200)
async def get_class_data(tool_alias: str):
    return


@app.post("/tool/{tool_alias}/run", status_code=200)
async def run(tool_alias: str, run_model: RunToolModel):
    return


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, workers=1)
