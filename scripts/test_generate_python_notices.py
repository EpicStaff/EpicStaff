"""Unit tests for scripts/generate-python-notices.py (standard library unittest only).

Run from the repo root:  python -m unittest scripts/test_generate_python_notices.py
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent / "generate-python-notices.py"
spec = importlib.util.spec_from_file_location("generate_python_notices", SCRIPT_PATH)
generate_python_notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate_python_notices)


def write_dist_info(site_packages: Path, metadata: str, files: dict[str, str]) -> None:
    dist_info = site_packages / "Fake_Pkg-1.2.3.dist-info"
    for relative_path, text in files.items():
        (dist_info / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (dist_info / relative_path).write_text(text, encoding="utf-8")
    (dist_info / "METADATA").write_text(metadata, encoding="utf-8")


class DeclaredLicenseTextsTest(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.venv_dir = Path(temporary_directory.name)
        self.site_packages = self.venv_dir / "lib" / "python3.12" / "site-packages"

    def test_reads_every_declared_file_in_metadata_order_without_notice(self):
        write_dist_info(
            self.site_packages,
            "Metadata-Version: 2.4\n"
            "Name: Fake_Pkg\n"
            "Version: 1.2.3\n"
            "License-File: LICENSES/Apache-2.0.txt\n"
            "License-File: BUILD_LICENSES/freetype.txt\n"
            "License-File: BUILD_LICENSES/libjpeg_turbo.ijg\n"
            "License-File: NOTICE\n"
            "\n",
            {
                "licenses/LICENSES/Apache-2.0.txt": "Apache text\n",
                "licenses/BUILD_LICENSES/freetype.txt": "The FreeType Project LICENSE\n",
                "licenses/BUILD_LICENSES/libjpeg_turbo.ijg": "Independent JPEG Group\n",
                "licenses/NOTICE": "Notice text\n",
            },
        )

        texts = generate_python_notices.declared_license_texts(self.venv_dir)

        self.assertEqual(
            texts,
            {
                ("fake-pkg", "1.2.3"): (
                    "── LICENSES/Apache-2.0.txt ──\n\nApache text\n\n"
                    "── BUILD_LICENSES/freetype.txt ──\n\nThe FreeType Project LICENSE\n\n"
                    "── BUILD_LICENSES/libjpeg_turbo.ijg ──\n\nIndependent JPEG Group"
                )
            },
        )

    def test_single_declared_file_at_dist_info_root_is_returned_without_header(self):
        write_dist_info(
            self.site_packages,
            "Metadata-Version: 2.1\nName: fake-pkg\nVersion: 1.2.3\nLicense-File: COPYING\n\n",
            {"COPYING": "Copying text\n"},
        )

        texts = generate_python_notices.declared_license_texts(self.venv_dir)

        self.assertEqual(texts, {("fake-pkg", "1.2.3"): "Copying text"})

    def test_package_with_only_notice_or_no_declared_files_is_absent(self):
        write_dist_info(
            self.site_packages,
            "Metadata-Version: 2.4\nName: fake-pkg\nVersion: 1.2.3\nLicense-File: NOTICE.txt\n\n",
            {"licenses/NOTICE.txt": "Notice text\n"},
        )

        self.assertEqual(generate_python_notices.declared_license_texts(self.venv_dir), {})

    def test_lowercase_notice_is_kept_because_pip_licenses_only_matches_uppercase(self):
        write_dist_info(
            self.site_packages,
            "Metadata-Version: 2.4\nName: fake-pkg\nVersion: 1.2.3\nLicense-File: notice.txt\n\n",
            {"licenses/notice.txt": "Lowercase notice\n"},
        )

        texts = generate_python_notices.declared_license_texts(self.venv_dir)

        self.assertEqual(texts, {("fake-pkg", "1.2.3"): "Lowercase notice"})

    def test_package_with_unreadable_declared_file_falls_back_to_pip_licenses(self):
        outside = self.venv_dir / "secret.txt"
        outside.write_text("must never be published\n", encoding="utf-8")
        for declared in ["BUILD_LICENSES/missing.txt", "../../../../../secret.txt", str(outside)]:
            with self.subTest(declared=declared):
                write_dist_info(
                    self.site_packages,
                    "Metadata-Version: 2.4\nName: fake-pkg\nVersion: 1.2.3\n"
                    f"License-File: LICENSE\nLicense-File: {declared}\n\n",
                    {"licenses/LICENSE": "License text\n"},
                )

                self.assertEqual(generate_python_notices.declared_license_texts(self.venv_dir), {})


if __name__ == "__main__":
    unittest.main()
