from enums import FileExtensionEnum
from errors import UnsupportedError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.file_text_extractors import strategies


_STRATEGIES: dict[FileExtensionEnum, type[AbstractFileTextExtractor]] = {
    FileExtensionEnum.CSV: strategies.CSVTextExtractor,
    FileExtensionEnum.DOCX: strategies.DOCXTextExtractor,
    FileExtensionEnum.HTML: strategies.HTMLTextExtractor,
    FileExtensionEnum.JSON: strategies.FileTextExtractor,
    FileExtensionEnum.MD: strategies.FileTextExtractor,
    FileExtensionEnum.PDF: strategies.PDFTextExtractor,
    FileExtensionEnum.TXT: strategies.FileTextExtractor,
}


def build_file_text_extractor(
    extension: FileExtensionEnum,
) -> AbstractFileTextExtractor:
    """Build the extractor registered for `extension`.

    Args:
        extension: File extension to build an extractor for.

    Returns:
        An extractor instance for `extension`.

    Raises:
        UnsupportedError: If no strategy is registered for `extension`.
    """
    if extension not in _STRATEGIES:
        raise UnsupportedError("extension", extension)
    return _STRATEGIES[extension]()
