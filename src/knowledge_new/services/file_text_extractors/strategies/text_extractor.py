from loguru import logger
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class FileTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("UTF-8 decode failed, trying latin-1")
            return content.decode("latin-1")
