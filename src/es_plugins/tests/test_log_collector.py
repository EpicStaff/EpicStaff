import asyncio
import io
import os

from src.shared.models.plugin_nodes import MAX_LOG_LINE_LENGTH, MAX_LOG_TAIL_LINES

from es_plugins.logs.log_collector import (
    MAX_BYTES_PER_SECOND,
    MAX_LINE_BYTES,
    MAX_LINES_PER_SECOND,
    LogCollector,
    RotatingLogFile,
)


class StoppedClock:
    """A clock that moves only when the test says so."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def collector_in(tmp_path, clock=None, **log_file_options):
    echo = io.StringIO()
    options = {"clock": clock} if clock else {}
    collector = LogCollector(
        "weather", RotatingLogFile(tmp_path / "logs", **log_file_options), echo, **options
    )
    return collector, echo


async def feed(collector: LogCollector, data: bytes) -> None:
    """Write `data` into a pipe while the collector reads it, as a plugin process would."""
    read_end, write_end = os.pipe()

    def write_and_close() -> None:
        with os.fdopen(write_end, "wb") as writer:
            writer.write(data)

    writing = asyncio.create_task(asyncio.to_thread(write_and_close))
    await collector.collect(read_end)
    await writing


async def test_each_line_goes_to_the_file_the_agents_stdout_and_the_tail(tmp_path):
    collector, echo = collector_in(tmp_path)

    await feed(collector, b"INFO: started\r\nGET /api/ping 200\nno newline at the end")
    collector.close()

    assert (tmp_path / "logs" / "current.log").read_bytes() == (
        b"INFO: started\nGET /api/ping 200\nno newline at the end\n"
    )
    assert echo.getvalue().splitlines() == [
        "[weather] INFO: started",
        "[weather] GET /api/ping 200",
        "[weather] no newline at the end",
    ]
    assert collector.tail == ["INFO: started", "GET /api/ping 200", "no newline at the end"]


async def test_the_tail_keeps_the_last_200_lines_of_at_most_1000_characters(tmp_path):
    collector, _ = collector_in(tmp_path)
    lines = [f"line {number}" for number in range(MAX_LOG_TAIL_LINES + 50)]

    await feed(collector, ("\n".join(lines) + "\n" + "x" * 5000 + "\n").encode())

    assert len(collector.tail) == MAX_LOG_TAIL_LINES
    assert collector.tail[0] == f"line {51}"
    assert collector.tail[-1] == "x" * MAX_LOG_LINE_LENGTH


async def test_the_tail_survives_a_restart_of_the_process(tmp_path):
    collector, _ = collector_in(tmp_path)

    await feed(collector, b"first run crashed\n")
    await feed(collector, b"second run\n")

    assert collector.tail == ["first run crashed", "second run"]


async def test_an_endless_line_is_cut_into_pieces(tmp_path):
    collector, _ = collector_in(tmp_path)

    await feed(collector, b"y" * (MAX_LINE_BYTES * 2 + 10))

    log = (tmp_path / "logs" / "current.log").read_bytes().split(b"\n")
    assert [len(piece) for piece in log if piece] == [MAX_LINE_BYTES, MAX_LINE_BYTES, 10]


def test_the_log_rotates_at_its_cap_and_keeps_three_files(tmp_path):
    log_file = RotatingLogFile(tmp_path / "logs", max_bytes=100, kept_files=3)

    log_file.write_lines([f"{number:02d} {'.' * 20}".encode() for number in range(30)])
    log_file.close()

    files = sorted(path.name for path in (tmp_path / "logs").iterdir())
    assert files == ["current.log", "current.log.1", "current.log.2"]
    assert all((tmp_path / "logs" / name).stat().st_size <= 100 for name in files)
    assert (tmp_path / "logs" / "current.log").read_text().splitlines()[-1].startswith("29 ")


async def test_lines_over_the_rate_budget_are_dropped_and_counted_in_the_next_accepted_line(
    tmp_path,
):
    clock = StoppedClock()
    collector, echo = collector_in(tmp_path, clock=clock)
    flood = [f"flood {number}" for number in range(MAX_LINES_PER_SECOND + 300)]

    await feed(collector, ("\n".join(flood) + "\n").encode())
    clock.now += 1.0
    await feed(collector, b"after the second\n")
    collector.close()

    written = (tmp_path / "logs" / "current.log").read_text().splitlines()
    assert written[:MAX_LINES_PER_SECOND] == flood[:MAX_LINES_PER_SECOND]
    assert written[MAX_LINES_PER_SECOND:] == [
        "[es_plugins] dropped 300 line(s) over the log rate limit",
        "after the second",
    ]
    assert echo.getvalue().splitlines()[-2:] == [
        "[weather] [es_plugins] dropped 300 line(s) over the log rate limit",
        "[weather] after the second",
    ]
    assert collector.tail[-2:] == [
        "[es_plugins] dropped 300 line(s) over the log rate limit",
        "after the second",
    ]


async def test_the_byte_budget_drops_output_even_in_few_lines_and_the_count_is_written_at_exit(
    tmp_path,
):
    clock = StoppedClock()
    collector, _ = collector_in(tmp_path, clock=clock)
    piece = b"z" * MAX_LINE_BYTES
    pieces_per_second = MAX_BYTES_PER_SECOND // MAX_LINE_BYTES

    await feed(collector, b"\n".join([piece] * (pieces_per_second + 4)) + b"\n")
    collector.close()

    written = (tmp_path / "logs" / "current.log").read_bytes().split(b"\n")
    assert written[:pieces_per_second] == [piece] * pieces_per_second
    assert written[pieces_per_second:] == [
        b"[es_plugins] dropped 4 line(s) over the log rate limit",
        b"",
    ]
