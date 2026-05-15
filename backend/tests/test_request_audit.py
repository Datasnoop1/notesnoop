import argparse
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from request_audit import (
    audit_public_path,
    bot_family,
    client_type,
    parse_nginx_access_line,
    request_origin,
    route_kind_and_cbe,
)
from scripts.ingest_public_request_audit import event_to_row


def test_parse_googlebot_company_request():
    line = (
        '66.249.74.2 - - [14/May/2026:19:04:06 +0000] '
        '"GET /company/0407868469 HTTP/1.1" 200 16197 "-" '
        '"Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile '
        'Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" "-"'
    )

    event = parse_nginx_access_line(line)

    assert event is not None
    assert event.route_kind == "company_page"
    assert event.cbe == "0407868469"
    assert event.ua_family == "bot"
    assert event.device_type == "bot"
    assert event.bot_family == "googlebot"
    assert not event.is_rsc_prefetch


def test_parse_next_rsc_prefetch_keeps_referrer_path_only():
    line = (
        '5.23.167.7 - - [15/May/2026:07:22:55 +0000] '
        '"GET /company/0769417163?_rsc=ykx89 HTTP/2.0" 200 175 '
        '"https://datasnoop.be/search?q=cdm" '
        '"Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1" "-"'
    )

    event = parse_nginx_access_line(line)

    assert event is not None
    assert event.path == "/company/0769417163"
    assert event.route_kind == "company_page"
    assert event.cbe == "0769417163"
    assert event.is_rsc_prefetch
    assert event.referrer_path == "/search"
    assert event.ua_family == "safari"
    assert event.bot_family is None


def test_route_kind_for_company_api_subresources():
    assert route_kind_and_cbe("/api/companies/0407868469") == (
        "api_company",
        "0407868469",
        False,
    )
    assert route_kind_and_cbe("/api/companies/0407868469/structure") == (
        "api_company_structure",
        "0407868469",
        False,
    )


def test_request_origin_allows_only_known_values():
    assert request_origin({"x-datasnoop-request-origin": "next-ssr"}, "172.18.0.4") == "next-ssr"
    assert request_origin({"x-datasnoop-request-origin": "next-ssr"}, "8.8.8.8") == "direct"
    assert request_origin({"x-datasnoop-request-origin": "unexpected"}, "172.18.0.4") == "direct"
    assert request_origin({}) == "direct"


def test_audit_public_path_drops_query_string():
    assert audit_public_path({"x-datasnoop-public-path": "/company/0407868469?utm=test"}) == "/company/0407868469"


def test_client_type_flags_cloud_browser_and_ai_crawler():
    class Event:
        ua_family = "chrome"
        bot_family = None
        is_ai_crawler = False

    assert client_type(Event(), verified_bot=False, network_label="bc.googleusercontent.com") == "cloud_browser"

    class BotEvent:
        ua_family = "bot"
        bot_family = "gptbot"
        is_ai_crawler = True

    assert client_type(BotEvent(), verified_bot=False, network_label=None) == "ai_crawler"
    assert bot_family("Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.3)") == "gptbot"


def test_event_to_row_verify_bots_also_resolves_cloud_browser_network(monkeypatch):
    line = (
        '54.242.10.11 - - [15/May/2026:07:22:55 +0000] '
        '"GET /company/0769417163 HTTP/2.0" 200 175 "-" '
        '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" "-"'
    )
    event = parse_nginx_access_line(line)

    def fake_gethostbyaddr(ip):
        assert ip == "54.242.10.11"
        return ("ec2-54-242-10-11.compute-1.amazonaws.com", [], [ip])

    monkeypatch.setattr(socket, "gethostbyaddr", fake_gethostbyaddr)

    row = event_to_row(
        event,
        argparse.Namespace(verify_bots=True, resolve_network=False, label="test"),
        "test-salt",
    )

    assert row["client_network"] == "compute-1.amazonaws.com"
    assert row["client_type"] == "cloud_browser"
