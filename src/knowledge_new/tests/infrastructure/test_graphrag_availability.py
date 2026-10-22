"""GraphRAG availability is decided from the x86 `flags` line of /proc/cpuinfo.

ARM kernels (Apple-silicon Docker VMs, ARM servers) report a `Features` line instead.
Those hosts must not be refused for lacking AVX2, an x86-only flag. An amd64 container
emulated on an Apple-silicon Mac sees the same ARM cpuinfo.
"""

import pytest

from infrastructure.graphrag import availability

X86_WITH_AVX2 = "processor\t: 0\nflags\t\t: fpu sse sse2 avx avx2 fma\n"
X86_WITHOUT_AVX2 = "processor\t: 0\nflags\t\t: fpu sse sse2 avx\n"
ARM64 = (
    "processor\t: 0\n"
    "BogoMIPS\t: 48.00\n"
    "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics asimddp\n"
    "CPU implementer\t: 0x61\n"
)


@pytest.mark.parametrize(
    ("cpuinfo", "expected"),
    [
        (X86_WITH_AVX2, True),
        (X86_WITHOUT_AVX2, False),
        (ARM64, True),
        ("", True),
    ],
    ids=["x86-avx2", "x86-no-avx2", "arm64", "empty"],
)
def test_availability_from_cpuinfo(tmp_path, monkeypatch, cpuinfo, expected):
    cpuinfo_file = tmp_path / "cpuinfo"
    cpuinfo_file.write_text(cpuinfo, encoding="utf-8")
    monkeypatch.setattr(availability, "_CPUINFO_PATH", str(cpuinfo_file))

    assert availability.detect_graphrag_availability() is expected


def test_unreadable_cpuinfo_keeps_graphrag_available(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "_CPUINFO_PATH", str(tmp_path / "missing"))

    assert availability.detect_graphrag_availability() is True
