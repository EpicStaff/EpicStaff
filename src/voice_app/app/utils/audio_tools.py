import audioop
import base64
import struct
import numpy as np


def mulaw_to_pcm16(audio_chunk: bytes) -> bytes:
    """Convert 8-bit mu-law to 16-bit PCM"""
    return audioop.ulaw2lin(audio_chunk, 2)


def pcm16_to_mulaw(pcm_chunk: bytes) -> bytes:
    """Convert 16-bit PCM back to mu-law"""
    return audioop.lin2ulaw(pcm_chunk, 2)


def float_to_16bit_pcm(float32_array):
    clipped = [max(-1.0, min(1.0, x)) for x in float32_array]
    pcm16 = b"".join(struct.pack("<h", int(x * 32767)) for x in clipped)
    return pcm16


def base64_encode_audio(float32_array):
    pcm_bytes = float_to_16bit_pcm(float32_array)
    encoded = base64.b64encode(pcm_bytes).decode("ascii")
    return encoded


def float32_to_mulaw(signal: np.ndarray, quantization_channels: int = 256) -> bytes:
    """
    Converts float32 (-1..1) to 8-bit mu-law (Twilio compatible).
    Returns bytes.
    """
    # Clip signal to [-1, 1]
    signal = np.clip(signal, -1.0, 1.0)

    # mu-law parameter
    mu = quantization_channels - 1

    # Apply mu-law
    magnitude = np.log1p(mu * np.abs(signal)) / np.log1p(mu)
    signal_mu = np.sign(signal) * magnitude

    # Quantize to range [0, 255]
    signal_quantized = ((signal_mu + 1) / 2 * mu + 0.5).astype(np.uint8)

    return signal_quantized.tobytes()
