import sys
import traceback

from loguru import logger

MAX_LOG_LENGTH = 200


def truncate_filter(record):
    msg = record["message"].replace("\r", "").replace("\n", "\\n")
    # Audit records (logger.bind(audit=True)) must reach the log whole; the
    # code emitting them bounds their size itself.
    if len(msg) > MAX_LOG_LENGTH and not record["extra"].get("audit"):
        msg = msg[:MAX_LOG_LENGTH] + "..."
    record["message"] = msg
    return True


logger.remove()
logger.add(sys.stdout, format="{time} {level} {message}", level="INFO", filter=truncate_filter)
# logger.add("logs/file.log", rotation="1 MB", compression="zip")
# TODO: setup saving and rotating log files with DEBUG level logs


def log_exception(exc_type, exc_value, exc_traceback):
    formatted_traceback = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logger.opt(exception=exc_value).exception(formatted_traceback)


sys.excepthook = log_exception
