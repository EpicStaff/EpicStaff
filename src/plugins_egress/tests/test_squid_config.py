"""squid.conf, the ranges file, the error pages, the entrypoint and the Dockerfile agree."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQUID_CONF = (ROOT / "squid.conf").read_text()
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()

PRIVATE_RANGES = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "224.0.0.0/3",
    "::/128",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
]
REFUSAL_PAGES = {
    "ERR_ONLY_CONNECT": "CONNECT",
    "ERR_PORT_NOT_ALLOWED": "SSL_ports",
    "ERR_HOST_NOT_ALLOWED": "reason_host_not_allowed",
    "ERR_PRIVATE_DST": "to_private",
}


def directives(name: str) -> list[str]:
    """The values of every `name` line of squid.conf, in order, comments left out."""
    values = []
    for line in SQUID_CONF.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        directive, _, value = line.partition(" ")
        if directive == name:
            values.append(value)
    return values


def test_http_access_is_in_exactly_this_order():
    assert directives("http_access") == [
        "deny !CONNECT",
        "deny !SSL_ports",
        "deny !authenticated",
        "deny !plugin_hosts reason_host_not_allowed",
        "deny to_private",
        "allow plugin_hosts",
        "deny all",
    ]


def test_the_host_line_ends_with_a_marker_acl_that_does_not_depend_on_authentication():
    assert "reason_host_not_allowed src all" in directives("acl")
    assert "plugin_hosts external plugin_hosts" in directives("acl")


def test_each_refusal_has_a_page_of_its_own():
    assert directives("deny_info") == [f"{page} {acl}" for page, acl in REFUSAL_PAGES.items()]
    assert directives("error_directory") == ["/etc/squid/errors"]


@pytest.mark.parametrize("page", REFUSAL_PAGES)
def test_a_refusal_page_carries_its_name_a_sentence_and_the_host_only(page):
    text = (ROOT / "errors" / page).read_text()

    assert re.fullmatch(rf"<html><body><p>{page}: [^<>%]*%H[^<>%]*\.</p></body></html>\n", text)


def test_every_page_in_errors_is_one_of_the_refusals():
    assert sorted(path.name for path in (ROOT / "errors").iterdir()) == sorted(REFUSAL_PAGES)


def test_proxy_credentials_are_bcrypt_lines_squid_checks_again_every_30_seconds():
    assert directives("auth_param") == [
        "basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/policy/passwords",
        "basic children 16 startup=4 idle=2 queue-size=32 on-persistent-overload=ERR",
        "basic realm plugins-egress",
        "basic credentialsttl 30 seconds",
        "basic casesensitive on",
    ]
    assert "authenticated proxy_auth REQUIRED" in directives("acl")


def test_the_host_helper_gets_the_user_and_the_host_and_its_answers_live_30_seconds():
    assert directives("external_acl_type") == [
        "plugin_hosts ttl=30 negative_ttl=30 children-max=4 children-startup=1 children-idle=1 "
        "queue-size=16 %ul %DST /usr/local/bin/plugin_host_acl /etc/squid/policy/hosts.json"
    ]


def test_a_flood_of_wrong_passwords_never_stops_squid():
    """Squid's default for a password check queue overloaded for 3 minutes is to exit."""
    (children,) = [value for value in directives("auth_param") if value.startswith("basic children ")]

    assert "on-persistent-overload=ERR" in children.split()
    assert "queue-size=32" in children.split()


def test_both_helpers_have_an_explicit_queue():
    (helper,) = directives("external_acl_type")

    assert "queue-size=16" in helper.split()
    # Squid 7.6 refuses on-persistent-overload here; a full queue refuses the request instead.
    assert "on-persistent-overload" not in helper


def test_only_port_443_and_connect_are_allowed():
    assert "CONNECT method CONNECT" in directives("acl")
    assert "SSL_ports port 443" in directives("acl")


def test_private_destinations_come_from_the_ranges_file():
    assert 'to_private dst "/etc/squid/private_ranges.txt"' in directives("acl")
    assert (ROOT / "private_ranges.txt").read_text().splitlines() == PRIVATE_RANGES


def test_logs_name_the_plugin_and_never_a_header():
    (logformat,) = directives("logformat")
    assert logformat.startswith("plugin ")
    assert "user=%un" in logformat
    # %>h, %<h and %{Name}>h are request or reply headers, Proxy-Authorization among them.
    assert not re.search(r"[<>]h|\{", logformat)
    assert directives("access_log") == ["stdio:/dev/stdout plugin"]
    assert directives("cache_log") == ["stdio:/dev/stderr"]
    assert directives("strip_query_terms") == ["on"]
    assert directives("debug_options") == ["ALL,1"]


def test_nothing_is_cached_or_stored():
    assert directives("cache") == ["deny all"]
    assert directives("cache_dir") == []
    assert directives("memory_pools") == ["off"]


def test_the_configuration_includes_nothing_else():
    assert directives("include") == []


def test_the_firewall_reads_the_same_ranges_file_squid_does():
    assert "RANGES=/etc/squid/private_ranges.txt" in ENTRYPOINT
    assert re.search(r"^COPY squid\.conf private_ranges\.txt /etc/squid/$", DOCKERFILE, re.MULTILINE)


def test_the_firewall_allows_loopback_replies_and_dns_then_refuses_each_range():
    rules = re.findall(r'"\$tables" -A "\$CHAIN" (.+)', ENTRYPOINT)

    assert rules == [
        "-o lo -j ACCEPT",
        "-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
        "-p udp --dport 53 -j ACCEPT",
        "-p tcp --dport 53 -j ACCEPT",
        '-d "$range" -j REJECT',
    ]


def test_the_entrypoint_reads_no_setting_from_its_environment():
    """No lab knob: every variable the entrypoint uses, it sets itself."""
    used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", ENTRYPOINT))
    set_here = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=", ENTRYPOINT, re.MULTILINE))
    loop_variables = set(re.findall(r"\bfor ([A-Za-z_][A-Za-z0-9_]*) in\b", ENTRYPOINT))

    assert used - set_here - loop_variables == set()


def test_squid_starts_with_setuid_and_setgid_only():
    assert 'SQUID_PRIVILEGES="--inh-caps=-all --ambient-caps=-all --bounding-set=-all,+setuid,+setgid"' in ENTRYPOINT
    assert ENTRYPOINT.rstrip().endswith("exec setpriv $SQUID_PRIVILEGES squid -N -f /etc/squid/squid.conf")


def test_the_image_installs_the_helper_where_squid_conf_names_it():
    assert "COPY --chmod=0755 plugin_host_acl.py /usr/local/bin/plugin_host_acl" in DOCKERFILE
    assert re.search(r"^FROM alpine:3\.23@sha256:[0-9a-f]{64}$", DOCKERFILE, re.MULTILINE)
    assert "squid~7.6" in DOCKERFILE
