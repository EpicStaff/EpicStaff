import logging

from graphrag.logger.factory import LoggerFactory

# graphrag's own reporting types write a log file or an Azure blob. Its loggers already
# propagate to the root logger, which sends them to the container log, so this type adds a
# handler that writes nothing: no file under the read-only root, and no line printed twice.
PROPAGATE_ONLY_REPORTING = "propagate_only"

LoggerFactory().register(PROPAGATE_ONLY_REPORTING, lambda **_: logging.NullHandler())
