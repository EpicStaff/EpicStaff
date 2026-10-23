"""Every app menu path the manifest accepts is a path the frame protocol accepts, already in its
canonical spelling.

EpicStaff opens a menu item by sending its path to the app as `nav.navigate`, and highlights the
item whose path the app reports back in `nav.changed`. A menu path outside the protocol's grammar
could never be sent, and one the protocol spells differently would never be highlighted.
"""

import json
import re
import string

import pytest
from pydantic import ValidationError

from conftest import REPO_ROOT
from epicstaff_plugin.contracts.manifest import MAX_NAVIGATION_PATH_LENGTH, NavigationItem

FRAME_PROTOCOL = json.loads((REPO_ROOT / "plugin-sdk" / "contracts" / "frame-protocol.json").read_text(encoding="utf-8"))
NAV_PATH_PATTERN = re.compile(FRAME_PROTOCOL["nav_path_pattern"])
MAX_NAV_PATH_LENGTH = FRAME_PROTOCOL["limits"]["max_nav_path_length"]
CANONICAL_VECTORS = FRAME_PROTOCOL["canonical_vectors"]

ACCEPTED_MENU_PATHS = [
    "/",
    "/projects",
    "/a/b-c_d.e~f",
    "/Projects/2026/Q4",
    "/.../a..b/.c/d.",
    "/" + string.ascii_letters + string.digits + "-._~",
    "/" + "/".join(["p"] * 128),
    "/" + "p" * (MAX_NAVIGATION_PATH_LENGTH - 1),
]


def menu_accepts(path: str) -> bool:
    try:
        NavigationItem.model_validate({"label": "Page", "path": path, "icon": "icons/page.svg"})
    except ValidationError:
        return False
    return True


def protocol_accepts(path: str) -> bool:
    return len(path) <= MAX_NAV_PATH_LENGTH and NAV_PATH_PATTERN.fullmatch(path) is not None


@pytest.mark.parametrize("path", ACCEPTED_MENU_PATHS)
def test_an_accepted_menu_path_is_a_frame_protocol_path(path):
    assert menu_accepts(path)
    assert protocol_accepts(path)


def test_the_longest_menu_path_fits_the_protocol():
    assert MAX_NAVIGATION_PATH_LENGTH <= MAX_NAV_PATH_LENGTH


@pytest.mark.parametrize("character", [chr(code) for code in range(0x20, 0x7F)])
def test_no_character_the_menu_accepts_is_outside_the_protocol(character):
    path = f"/a{character}b"

    if menu_accepts(path):
        assert protocol_accepts(path)


@pytest.mark.parametrize(
    "vector",
    [vector for vector in CANONICAL_VECTORS if vector["canonical"] is None],
    ids=lambda vector: repr(vector["path"]),
)
def test_a_path_the_protocol_refuses_is_refused_as_a_menu_path(vector):
    assert not menu_accepts(vector["path"])


@pytest.mark.parametrize(
    "vector",
    [vector for vector in CANONICAL_VECTORS if menu_accepts(vector["path"])],
    ids=lambda vector: vector["path"],
)
def test_a_menu_path_is_already_in_its_canonical_spelling(vector):
    assert vector["canonical"] == vector["path"]


def test_the_canonical_vectors_include_menu_paths():
    # Guards the test above against passing vacuously if the vectors change.
    assert {"/", "/forecast"} <= {vector["path"] for vector in CANONICAL_VECTORS if menu_accepts(vector["path"])}
