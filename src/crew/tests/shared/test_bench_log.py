import importlib
import io
import json
import logging
import sys

import pytest
from loguru import logger
from src.shared.bench_log import BENCH_LEVEL, add_bench_sink, without_bench
from utils import logger as crew_logger_module


@pytest.fixture(autouse=True)
def _restore_crew_sinks():
    original_excepthook = sys.excepthook
    yield
    importlib.reload(crew_logger_module)
    sys.excepthook = original_excepthook


def _service_sinks(level: str) -> io.StringIO:
    stream = io.StringIO()
    logger.remove()
    logger.add(stream, format="{time} {level} {message}", level=level, filter=without_bench())
    add_bench_sink(stream, level)
    return stream


def test_bench_line_is_one_json_object_with_kwargs_and_context():
    stream = _service_sinks("BENCH")
    with logger.contextualize(session_id=7):
        logger.log(BENCH_LEVEL, "bench {checkpoint}", checkpoint="node_start", node_name="Python 1")
    logger.info("normal line")

    lines = stream.getvalue().splitlines()
    bench_lines = [json.loads(line) for line in lines if line.startswith('{"bench"')]
    assert len(bench_lines) == 1
    assert bench_lines[0]["checkpoint"] == "node_start"
    assert bench_lines[0]["node_name"] == "Python 1"
    assert bench_lines[0]["session_id"] == 7
    assert isinstance(bench_lines[0]["ts"], float)
    assert any(line.endswith("INFO normal line") for line in lines)
    assert sum("node_start" in line for line in lines) == 1  # never duplicated into the normal sink


def test_info_level_prints_no_bench_line():
    stream = _service_sinks("INFO")
    logger.log(BENCH_LEVEL, "bench {checkpoint}", checkpoint="node_start")
    assert stream.getvalue() == ""


def test_bench_level_hides_debug_lines():
    stream = _service_sinks("BENCH")
    logger.debug("debug line")
    assert stream.getvalue() == ""


def test_numeric_level_and_inner_filter():
    stream = io.StringIO()
    logger.remove()
    logger.add(stream, format="{message}", level=0, filter=without_bench(lambda record: record["message"] != "drop"))
    assert add_bench_sink(stream, 0) is not None  # Django passes NOTSET as 0: everything, BENCH included
    logger.info("drop")
    logger.info("keep")
    logger.log(BENCH_LEVEL, "bench {checkpoint}", checkpoint="x")
    lines = stream.getvalue().splitlines()
    assert lines[0] == "keep"
    assert json.loads(lines[1])["checkpoint"] == "x"
    assert len(lines) == 2


def test_stdlib_knows_bench():
    assert logging.getLevelNamesMapping()["BENCH"] == BENCH_LEVEL
