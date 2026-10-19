import pytest

from extract import api_client


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds + 1e-9  # Simulate waking just after the requested deadline.


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(api_client, "time", clock)
    return clock


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
