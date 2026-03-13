import json
import pytest
from dynamic_venv_executor_chain import DynamicVenvExecutorChain
from src.shared.models import CodeTaskData
from fixtures import *


@pytest.mark.asyncio
async def test_run_executor(
    executor_chain: DynamicVenvExecutorChain,
    get_formatted_time_with_short_uuid: str,
    clear_venvs_and_executions,
):
    test_code = """
def main(var1, var2):
    return var1+var2
"""
    test_func_kwargs = {"var1": 1, "var2": 2}
    test_execution_id = get_formatted_time_with_short_uuid
    code_task_data = CodeTaskData(
        venv_name="test_run_executor_venv",
        libraries=["python-dotenv", "requests", "pydantic"],
        code=test_code,
        execution_id=test_execution_id,
        entrypoint="main",
        func_kwargs=test_func_kwargs,
    )

    code_result_data = await executor_chain.run(
        venv_name=code_task_data.venv_name,
        libraries=code_task_data.libraries,
        code=code_task_data.code,
        execution_id=code_task_data.execution_id,
        entrypoint=code_task_data.entrypoint,
        func_kwargs=code_task_data.func_kwargs,
    )

    assert code_result_data.execution_id == test_execution_id
    assert code_result_data.returncode == 0
    assert json.loads(code_result_data.result_data) == 3
    assert code_result_data.stderr == ""
    assert code_result_data.stdout == ""


@pytest.mark.asyncio
async def test_run_executor_with_rapid_api(
    executor_chain: DynamicVenvExecutorChain,
    get_formatted_time_with_short_uuid: str,
    set_env_rapidapi_key: str,
    clear_venvs_and_executions,
):
    rapidapi_key = set_env_rapidapi_key
    test_code = """
import requests
import os
def get_weather(lat, lon, alt, start_date, end_date, rapidapi_key):

    url = "https://meteostat.p.rapidapi.com/point/monthly"
    querystring = {
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "start": start_date,
        "end": end_date
    }

    headers = {
        "x-rapidapi-host": "meteostat.p.rapidapi.com",
        "x-rapidapi-key": rapidapi_key,
    }

    # Make the GET request
    response = requests.get(url, headers=headers, params=querystring)
    
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": f"Failed to fetch data: {response.status_code}"}
"""
    test_code = test_code

    test_func_kwargs = {
        "lat": "52.5244",
        "lon": "13.4105",
        "alt": "43",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
        "rapidapi_key": rapidapi_key,
    }
    test_execution_id = get_formatted_time_with_short_uuid
    code_task_data = CodeTaskData(
        venv_name="get_weather",
        libraries=["requests"],
        code=test_code,
        execution_id=test_execution_id,
        entrypoint="get_weather",
        func_kwargs=test_func_kwargs,
    )

    code_result_data = await executor_chain.run(
        venv_name=code_task_data.venv_name,
        libraries=code_task_data.libraries,
        code=code_task_data.code,
        execution_id=code_task_data.execution_id,
        entrypoint=code_task_data.entrypoint,
        func_kwargs=code_task_data.func_kwargs,
    )

    assert code_result_data.execution_id == test_execution_id
    assert code_result_data.returncode == 0
    assert isinstance(json.loads(code_result_data.result_data), dict)
    assert code_result_data.stderr == ""
    assert code_result_data.stdout == ""


@pytest.mark.asyncio
async def test_run_executor_invalid_libraries(
    executor_chain: DynamicVenvExecutorChain,
    get_formatted_time_with_short_uuid: str,
    clear_venvs_and_executions,
):
    test_code = """
def main(var1, var2):
    return var1+var2
"""
    test_func_kwargs = {"var1": 1, "var2": 2}
    test_execution_id = get_formatted_time_with_short_uuid
    code_task_data = CodeTaskData(
        venv_name="test_run_executor_invalid_libraries_venv",
        libraries=["some-invalid-lib", "112214142124241"],
        code=test_code,
        execution_id=test_execution_id,
        entrypoint="main",
        func_kwargs=test_func_kwargs,
    )

    code_result_data = await executor_chain.run(
        venv_name=code_task_data.venv_name,
        libraries=code_task_data.libraries,
        code=code_task_data.code,
        execution_id=code_task_data.execution_id,
        entrypoint=code_task_data.entrypoint,
        func_kwargs=code_task_data.func_kwargs,
    )

    assert code_result_data.execution_id == test_execution_id
    assert code_result_data.returncode == 1
    assert code_result_data.result_data is None
    assert code_result_data.stderr != ""


@pytest.mark.asyncio
async def test_run_executor_invalid_code(
    executor_chain: DynamicVenvExecutorChain,
    get_formatted_time_with_short_uuid: str,
    clear_venvs_and_executions,
):
    test_code = """
def main(var1, var2):
    retur
"""
    test_func_kwargs = {"var1": 1, "var2": 2}
    test_execution_id = get_formatted_time_with_short_uuid
    code_task_data = CodeTaskData(
        venv_name="test_run_executor_invalid_code_venv",
        libraries=[],
        code=test_code,
        execution_id=test_execution_id,
        entrypoint="main",
        func_kwargs=test_func_kwargs,
    )

    code_result_data = await executor_chain.run(
        venv_name=code_task_data.venv_name,
        libraries=code_task_data.libraries,
        code=code_task_data.code,
        execution_id=code_task_data.execution_id,
        entrypoint=code_task_data.entrypoint,
        func_kwargs=code_task_data.func_kwargs,
    )

    assert code_result_data.execution_id == test_execution_id
    assert code_result_data.returncode == 1
    assert code_result_data.result_data is None
    assert code_result_data.stderr != ""


@pytest.mark.asyncio
async def test_run_executor_invalid_kwargs(
    executor_chain: DynamicVenvExecutorChain,
    get_formatted_time_with_short_uuid: str,
    clear_venvs_and_executions,
):
    test_code = """
def main(var1, var2):
    return var1 + var2
"""
    test_func_kwargs = {"var1": 1, "invalid": 2}
    test_execution_id = get_formatted_time_with_short_uuid
    code_task_data = CodeTaskData(
        venv_name="test_run_executor_invalid_code_venv",
        libraries=[],
        code=test_code,
        execution_id=test_execution_id,
        entrypoint="main",
        func_kwargs=test_func_kwargs,
    )

    code_result_data = await executor_chain.run(
        venv_name=code_task_data.venv_name,
        libraries=code_task_data.libraries,
        code=code_task_data.code,
        execution_id=code_task_data.execution_id,
        entrypoint=code_task_data.entrypoint,
        func_kwargs=code_task_data.func_kwargs,
    )

    assert code_result_data.execution_id == test_execution_id
    assert code_result_data.returncode == 1
    assert code_result_data.result_data is None
    assert code_result_data.stderr != ""
