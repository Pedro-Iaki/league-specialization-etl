"""Rough request-time estimates for ordinary Riot development-key collection."""

# Assumed throughput, not a measured rate or a replacement for the API limiter.
REQUESTS_PER_MINUTE = 50
REQUEST_EFFICIENCY = 0.95


def get_eta_minutes(request_count: int) -> float:
    """Estimate remaining minutes at 50 requests/minute and 95% efficiency."""
    return request_count / (REQUESTS_PER_MINUTE * REQUEST_EFFICIENCY)
