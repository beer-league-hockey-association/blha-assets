"""GitHub API sessions that ride out GitHub's brief hiccups.

GitHub's API now and then answers one request with a 500, 502 or 503, or drops
the connection, and the next request a second later works. The scheduler makes
about twenty calls every 15 minutes, so before these retries, one bad answer a
day failed a whole scheduler run and set off the outside monitor.

- Reads (GET) are retried up to three times with a short pause.
- Writes (POST, such as starting a workflow) are retried only when the
  connection failed before the request was sent. A write that reached GitHub
  and got an error back is never repeated, because GitHub may have acted on it.
  The scheduler doesn't need to repeat it anyway: a job that didn't start is
  still due at the next check.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Answers that mean "GitHub is having a moment", not "this request is wrong".
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def add_retries(session: requests.Session, *, backoff_factor: float = 1.5) -> requests.Session:
    """Make session retry GitHub's brief hiccups (see the module docstring)."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        other=0,
        backoff_factor=backoff_factor,  # pauses of 0, 3 and 6 seconds
        status_forcelist=TRANSIENT_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,  # hand back the last answer; raise_for_status() reports it
        respect_retry_after_header=False,  # never sleep a minute inside a 3-minute job
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def status_of(exc: BaseException) -> int | None:
    """The HTTP status behind an error, if there is one."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) is not None:
        return int(response.status_code)
    status = getattr(exc, "status", None)
    return int(status) if isinstance(status, int) else None


def is_transient(exc: BaseException) -> bool:
    """True when the error is GitHub having a moment rather than a real problem.

    Real problems (a bad token, a missing workflow, a malformed request) are
    4xx answers other than 429 and are never treated as transient.
    """
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return status_of(exc) in TRANSIENT_STATUSES


def describe(exc: BaseException) -> str:
    """A short description for a log line, e.g. "HTTP 502" or "connection dropped"."""
    status = status_of(exc)
    if status is not None:
        return f"HTTP {status}"
    if isinstance(exc, requests.Timeout):
        return "timed out"
    if isinstance(exc, requests.ConnectionError):
        return "connection dropped"
    return type(exc).__name__
