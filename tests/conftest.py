"""All tests are offline, including SDK tests. Fail closed on accidental sockets."""
import socket
import pytest

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.delenv(name, raising=False)
    def deny(*args, **kwargs):
        raise AssertionError('Tests must never access the network')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
