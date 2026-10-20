"""Entry point of `epicstaff-plugin`. Exit codes: 0 ok, 1 validation failed, 2 usage error."""

import argparse
import sys
from pathlib import Path
from typing import NoReturn

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
        description="Validate, package and sign EpicStaff plugins.",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code (argparse exits with 2 on bad usage itself)."""
    arguments = build_parser().parse_args(argv)
    try:
        match arguments.command:
            case "validate":
                return validate(arguments.target, arguments.spa_dir)
            case "pack":
                return pack(arguments.source, arguments.spa_dir, arguments.key, arguments.out)
            case "keygen":
                return keygen(arguments.out)
            case "sign":
                return sign(arguments.package, arguments.key)
            case "verify":
                return verify(arguments.package, arguments.trusted_key)
            case "schema":
                return schema(arguments.out)
    except UsageError as error:
        print_error(str(error))
        return EXIT_USAGE
    raise AssertionError(f"unhandled command {arguments.command}")


def run() -> NoReturn:
    sys.exit(main())
