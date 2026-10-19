from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
import requests

from extract import api_client


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds + 1e-9  # Simulate waking just after the requested deadline.


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(api_client, "time", clock)
    return clock


@pytest.fixture
def client(clock, monkeypatch):
    client = api_client.RiotAPIClient("test-key")
    for method in (api_client.RiotAPIClient.get, api_client.RiotAPIClient.get_patch):
        monkeypatch.setattr(method.retry, "sleep", clock.sleep)
    yield client
    client.session.close()


def make_response(status=200, headers=None):
    response = requests.Response()
    response.status_code = status
    response.url = "https://na1.api.riotgames.com/test"
    response.headers.update({"X-App-Rate-Limit": "100:120,20:1"} if headers is None else headers)
    response._content = b'["16.20.1"]'
    return response


def call_client(client, method_name):
    if method_name == "get_patch":
        return client.get_patch()
    return client.get("https://na1.api.riotgames.com/test")


@pytest.mark.parametrize("pause_seconds", [14, 600])
def test_idle_credit_allows_one_request_and_preserves_the_refill_margin(clock, pause_seconds):
    bucket = api_client.TokenBucket(100, 120)
    assert bucket.consume()

    clock.sleep(pause_seconds)

    assert bucket.consume()
    assert not bucket.consume()
    assert bucket.time_until_available() == pytest.approx(120 / 99)
    clock.sleep(bucket.time_until_available())
    assert bucket.consume()


def test_client_keeps_steady_request_spacing_after_a_pause(clock):
    client = api_client.RiotAPIClient("test-key")
    try:
        client.buckets = client.setup_buckets("100:120,20:1")
        for bucket in client.buckets:
            assert bucket.consume()
        clock.sleep(14)
        start = clock.now
        sent = []
        for _ in range(110):
            client._acquire()
            sent.append(clock.now)
            clock.sleep(0.25)  # Response and local processing time contribute to refill.

        assert sum(timestamp < start + 120 for timestamp in sent) <= 100
        assert [later - earlier for earlier, later in zip(sent, sent[1:])] == pytest.approx([120 / 99] * 109)
    finally:
        client.session.close()


@pytest.mark.parametrize("method_name", ["get", "get_patch"])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_http_errors_fail_without_retry(client, clock, monkeypatch, method_name, status):
    response = make_response(status, headers={})
    send = Mock(return_value=response)
    monkeypatch.setattr(client.session, "get", send)

    with pytest.raises(requests.exceptions.HTTPError) as caught:
        call_client(client, method_name)

    assert caught.value.response is response
    assert send.call_count == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("method_name", ["get", "get_patch"])
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_http_errors_keep_exponential_backoff(client, clock, monkeypatch, method_name, status):
    send = Mock(side_effect=[make_response(status, headers={"Retry-After": "60"}), make_response()])
    monkeypatch.setattr(client.session, "get", send)

    call_client(client, method_name)

    assert send.call_count == 2
    assert clock.sleeps == [6]


@pytest.mark.parametrize("error_type", [requests.exceptions.Timeout, requests.exceptions.ConnectionError])
def test_transient_network_failure_can_recover(client, clock, monkeypatch, error_type):
    send = Mock(side_effect=[error_type("temporary network failure"), make_response()])
    monkeypatch.setattr(client.session, "get", send)

    assert client.get("https://na1.api.riotgames.com/test").status_code == 200
    assert send.call_count == 2
    assert clock.sleeps == [6]


@pytest.mark.parametrize("method_name", ["get", "get_patch"])
def test_retry_exhaustion_preserves_the_original_error(client, clock, monkeypatch, method_name):
    error = requests.exceptions.Timeout("network never recovered")
    send = Mock(side_effect=error)
    monkeypatch.setattr(client.session, "get", send)

    with pytest.raises(requests.exceptions.Timeout) as caught:
        call_client(client, method_name)

    assert caught.value is error
    assert send.call_count == 6
    assert clock.sleeps == [6, 12, 24, 48, 90]


def test_missing_initial_headers_stop_collection_without_retry(client, clock, monkeypatch):
    send = Mock(return_value=make_response(headers={}))
    monkeypatch.setattr(client.session, "get", send)

    with pytest.raises(RuntimeError, match="missing X-App-Rate-Limit"):
        client.get("https://na1.api.riotgames.com/test")

    assert send.call_count == 1
    assert clock.sleeps == []
    with pytest.raises(RuntimeError, match="not initialized"):
        client._acquire()


def test_concurrent_callers_wait_for_the_initial_response(client, monkeypatch):
    start = Barrier(4)
    initial_started = Event()
    another_started = Event()
    finish_initial = Event()

    def send(*args, **kwargs):
        if not initial_started.is_set():
            initial_started.set()
            assert finish_initial.wait(timeout=3)
        else:
            another_started.set()
        return make_response()

    monkeypatch.setattr(client.session, "get", send)

    def fetch():
        start.wait(timeout=3)
        return client.get("https://na1.api.riotgames.com/test")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch) for _ in range(4)]
        try:
            assert initial_started.wait(timeout=3)
            assert not another_started.wait(timeout=0.1)
        finally:
            finish_initial.set()
        assert all(future.result(timeout=3).status_code == 200 for future in futures)
