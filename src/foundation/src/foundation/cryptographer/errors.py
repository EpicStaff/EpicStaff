__all__ = [
    "CryptographerError",
    "DecodeDataError",
    "DecryptDataError",
    "EncodeDataError",
    "EncryptDataError",
    "RotateDataError",
]

class CryptographerError(Exception):
    pass


class EncryptDataError(CryptographerError):
    pass


class DecryptDataError(CryptographerError):
    pass


class RotateDataError(CryptographerError):
    pass


class EncodeDataError(CryptographerError):
    pass


class DecodeDataError(CryptographerError):
    pass
