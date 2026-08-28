"""Source protocol and the fallback runner.

Every category of data has an ordered list of sources. `run_chain` tries them in
order and returns the first that yields rows, recording exactly which source
answered so the report can cite it per figure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Protocol

import pandas as pd

USER_AGENT = os.environ.get(
    "PTRACK_USER_AGENT",
    "ptrack/0.1 (public-disclosure research; contact via repository)",
)
HTTP_TIMEOUT = int(os.environ.get("PTRACK_HTTP_TIMEOUT", "60"))


class SourceUnavailable(RuntimeError):
    """Raised when a source cannot be reached or returns nothing usable.

    Distinguishes 'this source is down / blocked / retired' from 'this source
    answered and the answer was empty', which are different data-quality facts.
    """


@dataclass
class FetchResult:
    """Rows plus the provenance needed to cite them."""

    data: pd.DataFrame
    source: str
    source_url: str
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None and not self.data.empty


class Source(Protocol):
    name: str
    url: str

    def fetch(self, **kwargs) -> FetchResult: ...


@dataclass
class ChainOutcome:
    result: FetchResult | None
    attempts: list[tuple[str, str]]      # (source name, outcome message)

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.ok

    def summary(self) -> str:
        return "; ".join(f"{name}: {msg}" for name, msg in self.attempts)


def run_chain(sources: list[Callable[[], FetchResult]], labels: list[str],
              logger: Callable[[str, str], None] | None = None) -> ChainOutcome:
    """Try each source in order; return the first that produces rows.

    Never silently substitutes one source for another: the attempt log records
    every failure and is written to run_log by the caller.
    """
    attempts: list[tuple[str, str]] = []
    for label, fetch in zip(labels, sources):
        try:
            result = fetch()
        except SourceUnavailable as exc:
            attempts.append((label, f"unavailable ({exc})"))
            if logger:
                logger("WARN", f"source '{label}' unavailable: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - a broken source must not kill the run
            attempts.append((label, f"error ({type(exc).__name__}: {exc})"))
            if logger:
                logger("WARN", f"source '{label}' errored: {type(exc).__name__}: {exc}")
            continue
        if result.ok:
            attempts.append((label, f"ok ({len(result.data)} rows)"))
            if logger:
                logger("INFO", f"source '{label}' returned {len(result.data)} rows")
            return ChainOutcome(result=result, attempts=attempts)
        attempts.append((label, "reachable but returned 0 rows"))
        if logger:
            logger("WARN", f"source '{label}' reachable but empty")
    return ChainOutcome(result=None, attempts=attempts)


def http_get(url: str, **kwargs):
    """requests.get with the project's UA and timeout, raising SourceUnavailable."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise SourceUnavailable("requests is not installed") from exc

    headers = {"User-Agent": USER_AGENT}
    headers.update(kwargs.pop("headers", {}) or {})
    try:
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"{url}: {type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        raise SourceUnavailable(f"{url}: HTTP {resp.status_code}")
    return resp
