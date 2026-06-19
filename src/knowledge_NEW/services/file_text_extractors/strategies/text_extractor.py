from loguru import logger

from error_handler import handle_error
from errors import FileTextExtractingError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class FileTextExtractor(AbstractFileTextExtractor):
    """Decoding-based text extractor for plain-text files."""

    @run_in_process
    def extract(self, content: bytes) -> str:
        """Decode `content` as UTF-8, falling back to latin-1.

        Raises:
            FileTextExtractingError: If the content cannot be decoded.
        """
        with handle_error(Exception, FileTextExtractingError, self):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decode failed, trying latin-1")
                return content.decode("latin-1")
