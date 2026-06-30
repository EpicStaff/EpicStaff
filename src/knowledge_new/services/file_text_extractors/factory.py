from enums import FileExtensionEnum
from errors import UnsupportedError
from services.file_text_extractors import strategies
from services.file_text_extractors.base import AbstractFileTextExtractor

_STRATEGIES: dict[FileExtensionEnum, type[AbstractFileTextExtractor]] = {
    FileExtensionEnum.CSV: strategies.CSVTextExtractor,
    FileExtensionEnum.DOCX: strategies.DOCXTextExtractor,
    FileExtensionEnum.HTML: strategies.HTMLTextExtractor,
    FileExtensionEnum.JSON: strategies.FileTextExtractor,
    FileExtensionEnum.MD: strategies.FileTextExtractor,
    FileExtensionEnum.PDF: strategies.PDFTextExtractor,
    FileExtensionEnum.TXT: strategies.FileTextExtractor,
}


def build_file_text_extractor(extension: FileExtensionEnum) -> AbstractFileTextExtractor:
    """Create the text extractor registered for `extension`.

    Args:
        extension: File extension selecting the extractor implementation.

    Raises:
        UnsupportedError: If `extension` has no registered extractor.
    """
    if extension not in _STRATEGIES:
        raise UnsupportedError(that="extension", got=extension)
    return _STRATEGIES[extension]()
