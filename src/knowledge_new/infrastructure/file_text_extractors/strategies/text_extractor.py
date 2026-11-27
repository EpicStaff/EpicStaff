from application.ports import AbstractFileTextExtractor
from infrastructure.processing_run import run_in_process
from loguru import logger


class FileTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        try:
            # utf-8-sig drops the byte order mark some editors write, so a JSON file
            # saved with one still parses.
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            logger.warning("UTF-8 decode failed, trying latin-1")
            return content.decode("latin-1")
