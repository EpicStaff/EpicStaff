"""Entry point of `epicstaff-plugin`.

Exit codes: 0 ok (for `dev`: stopped), 1 validation failed (for `dev`: could not start), 2 usage
error.
"""

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from epicstaff_plugin.cli.backend_wheels import DEFAULT_PLATFORMS
from epicstaff_plugin.cli.development import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    develop,
    development_host,
    development_port,
)
from epicstaff_plugin.cli.keygen import keygen
from epicstaff_plugin.cli.output import EXIT_USAGE, UsageError, print_error
from epicstaff_plugin.cli.pack import pack
from epicstaff_plugin.cli.schema import schema
from epicstaff_plugin.cli.sign import sign
from epicstaff_plugin.cli.validate import validate
from epicstaff_plugin.cli.verify import verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epicstaff-plugin",
        description="Validate, package and sign EpicStaff plugins, and run a backend for development.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    validate_command = commands.add_parser(
        "validate", help="check a plugin source directory or a built .esplugin package"
    )
    validate_command.add_argument("target", type=Path, help="source directory or .esplugin file")
    validate_command.add_argument(
        "--spa-dir", type=Path, help="the built single-page app to check with a source directory"
    )

    pack_command = commands.add_parser("pack", help="build a deterministic .esplugin package")
    pack_command.add_argument("source", type=Path, help="plugin source directory")
    pack_command.add_argument("--spa-dir", type=Path, help="the built single-page app")
    pack_command.add_argument(
        "--key", type=Path, help="unencrypted minisign secret key to sign with"
    )
    pack_command.add_argument("--out", type=Path, required=True, help="package file to write")
    pack_command.add_argument(
        "--download-wheels",
        action="store_true",
        help="download a wheel of every backend/requirements.lock entry for each --platform",
    )
    pack_command.add_argument(
        "--platform",
        action="append",
        default=[],
        dest="platforms",
        metavar="TAG",
        help=(
            "Linux wheel platform to download for; repeat for more "
            f"(default: {' and '.join(DEFAULT_PLATFORMS)})"
        ),
    )
    pack_command.add_argument(
        "--local-wheel",
        action="append",
        default=[],
        dest="local_wheels",
        type=Path,
        metavar="WHEEL",
        help="a wheel no index has (such as a local epicstaff-plugin build) to add and pin; repeat for more",
    )

    keygen_command = commands.add_parser("keygen", help="create a signing key pair")
    keygen_command.add_argument(
        "--out", type=Path, required=True, help="path prefix; writes <prefix>.key and <prefix>.pub"
    )

    sign_command = commands.add_parser("sign", help="add or replace a package's signature")
    sign_command.add_argument("package", type=Path, help=".esplugin file")
    sign_command.add_argument(
        "--key", type=Path, required=True, help="unencrypted minisign secret key"
    )

    verify_command = commands.add_parser(
        "verify", help="say whether a package installs as trusted or untrusted"
    )
    verify_command.add_argument("package", type=Path, help=".esplugin file")
    verify_command.add_argument(
        "--trusted-key",
        action="append",
        default=[],
        metavar="NAME:PUBLIC_KEY",
        help="a key to trust, as in PLUGINS_TRUSTED_SIGNING_KEYS; repeat for more",
    )

    schema_command = commands.add_parser("schema", help="write the manifest JSON Schema")
    schema_command.add_argument("--out", type=Path, required=True, help="file to write")

    dev_command = commands.add_parser(
        "dev",
        help="serve a plugin's backend from its source, for EpicStaff's plugin development mode",
    )
    dev_command.add_argument("source", type=Path, help="plugin source directory")
    dev_command.add_argument(
        "--runtime-file",
        type=Path,
        required=True,
        metavar="FILE",
        help="the development runtime file downloaded from EpicStaff; keep it outside the source",
    )
    dev_command.add_argument(
        "--port",
        type=development_port,
        metavar="PORT",
        default=DEFAULT_PORT,
        help=f"port to serve the backend on, 1024-65535 (default: {DEFAULT_PORT})",
    )
    dev_command.add_argument(
        "--host",
        type=development_host,
        metavar="ADDRESS",
        default=DEFAULT_HOST,
        help=f"address to listen on: an IP address or localhost (default: {DEFAULT_HOST})",
    )
    dev_command.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="do not restart the backend when backend/src changes",
    )
    dev_command.add_argument(
        "--database-url",
        metavar="URL",
        help="postgresql:// URL of a local database the backend gets as DATABASE_URL",
    )
    dev_command.add_argument(
        "--apply-migrations",
        action="store_true",
        help="apply database/migrations/ to the --database-url database before starting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code (argparse exits with 2 on bad usage itself)."""
    arguments = build_parser().parse_args(argv)
    try:
        match arguments.command:
            case "validate":
                return validate(arguments.target, arguments.spa_dir)
            case "pack":
                return pack(
                    arguments.source,
                    arguments.spa_dir,
                    arguments.key,
                    arguments.out,
                    download_wheels=arguments.download_wheels,
                    platforms=arguments.platforms,
                    local_wheel_paths=arguments.local_wheels,
                )
            case "keygen":
                return keygen(arguments.out)
            case "sign":
                return sign(arguments.package, arguments.key)
            case "verify":
                return verify(arguments.package, arguments.trusted_key)
            case "schema":
                return schema(arguments.out)
            case "dev":
                return develop(
                    arguments.source,
                    arguments.runtime_file,
                    port=arguments.port,
                    host=arguments.host,
                    reload=arguments.reload,
                    database_url=arguments.database_url,
                    apply_migrations=arguments.apply_migrations,
                )
    except UsageError as error:
        print_error(str(error))
        return EXIT_USAGE
    raise AssertionError(f"unhandled command {arguments.command}")


def run() -> NoReturn:
    sys.exit(main())
