import io
import wave

from django.core.files.uploadedfile import SimpleUploadedFile

WAV_HEADER_BYTES = 44


def wav_upload(audio: bytes = b"\x7f" * 16, name: str = "clip.wav") -> SimpleUploadedFile:
    """A real WAV file holding `audio` (8 kHz, mono, one byte per sample).

    Written by the standard library, not by realtime, so a test does not accept a file
    only because it was built the same way the validation reads it. Its size is
    WAV_HEADER_BYTES plus the length of `audio`.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(8000)
        wav_file.writeframes(audio)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="audio/wav")
