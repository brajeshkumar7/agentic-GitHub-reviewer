"""Exercise the real urllib adapter boundary without network access."""

from unittest.mock import Mock
from urllib.request import Request

import pytest

from research_agent.tools import url_fetch
from research_agent.tools.safe_url import UnsafeDestination


def test_https_handler_uses_context_without_removed_attribute(monkeypatch) -> None:
    handler = url_fetch._PublicHTTPSHandler()
    opened = Mock(return_value="response")
    monkeypatch.setattr(handler, "do_open", opened)
    request = Request("https://example.org")
    assert handler.https_open(request) == "response"
    opened.assert_called_once_with(
        url_fetch._PublicPinnedHTTPSConnection, request, context=handler._context
    )


def test_connection_pins_socket_and_preserves_tls_hostname(monkeypatch) -> None:
    lookup = Mock(return_value=["93.184.216.34"])
    raw_socket = Mock()
    connect = Mock(return_value=raw_socket)
    monkeypatch.setattr(url_fetch, "public_destination_addresses", lookup)
    monkeypatch.setattr(url_fetch.socket, "create_connection", connect)
    connection = url_fetch._PublicPinnedHTTPSConnection("example.org", timeout=4)
    assert connection._context.check_hostname is True
    wrap = Mock(return_value=Mock())
    monkeypatch.setattr(connection._context, "wrap_socket", wrap)
    connection.connect()
    lookup.assert_called_once_with("example.org", 443)
    connect.assert_called_once_with(("93.184.216.34", 443), 4, None)
    wrap.assert_called_once_with(raw_socket, server_hostname="example.org")


def test_connection_rejects_private_destination_before_socket(monkeypatch) -> None:
    connect = Mock()
    monkeypatch.setattr(url_fetch.socket, "create_connection", connect)
    connection = url_fetch._PublicPinnedHTTPSConnection("127.0.0.1", timeout=4)
    with pytest.raises(UnsafeDestination):
        connection.connect()
    connect.assert_not_called()
