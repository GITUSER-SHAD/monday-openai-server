"""Configuration loading. All tunables live in config/*.yaml, never in code."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_ROOT.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_DB = PROJECT_ROOT / "out" / "politician_trades.duckdb"
DEFAULT_OUT = PROJECT_ROOT / "out"


@dataclass(frozen=True)
class AmountBracket:
    text: str
    low: float
    high: float | None

    @property
    def is_open_ended(self) -> bool:
        return self.high is None

    @property
    def midpoint(self) -> float:
        """ESTIMATE. Open-ended top bracket has no midpoint; we use its floor."""
        if self.high is None:
            return self.low
        return (self.low + self.high) / 2.0


@dataclass
class Config:
    market_benchmark: str
    default_sector_etf: str
    sector_etfs: dict[str, str]
    brackets: list[AmountBracket]
    bracket_aliases: dict[str, str]
    sector_overrides: dict[str, str]
    scoring_formula: str
    weights: dict[str, float]
    min_trades_for_ranking: int
    top_trades_per_person: int
    top_trades_selection: str
    report_top_n: int
    # Benchmarking convention for short/put positions. See README.
    short_benchmark_mode: str = "long_benchmark"
    event_window_trading_days: int = 10
    config_dir: Path = field(default=CONFIG_DIR)

    def sector_etf_for(self, sector: str | None) -> tuple[str, bool]:
        """Return (benchmark_ticker, is_fallback)."""
        if sector and sector in self.sector_etfs:
            return self.sector_etfs[sector], False
        return self.default_sector_etf, True


def _load_yaml(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _load_sector_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open() as fh:
        rows = [ln for ln in fh if not ln.lstrip().startswith("#")]
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        sector = (row.get("sector") or "").strip()
        if ticker and sector:
            out[ticker] = sector
    return out


def load_config(config_dir: Path | str = CONFIG_DIR) -> Config:
    config_dir = Path(config_dir)
    bench = _load_yaml(config_dir / "benchmarks.yaml")
    amounts = _load_yaml(config_dir / "amount_ranges.yaml")
    scoring = _load_yaml(config_dir / "scoring.yaml")

    brackets = [
        AmountBracket(text=b["text"], low=float(b["low"]),
                      high=None if b.get("high") is None else float(b["high"]))
        for b in amounts.get("brackets", [])
    ]

    aliases: dict[str, str] = {}
    for canonical, alts in (amounts.get("aliases") or {}).items():
        for alt in alts:
            aliases[_norm_key(alt)] = canonical

    return Config(
        market_benchmark=bench.get("market_benchmark", "SPY"),
        default_sector_etf=bench.get("default_sector_etf", "SPY"),
        sector_etfs=dict(bench.get("sectors") or {}),
        brackets=brackets,
        bracket_aliases=aliases,
        sector_overrides=_load_sector_overrides(config_dir / "sector_overrides.csv"),
        scoring_formula=scoring.get("formula", ""),
        weights=dict(scoring.get("weights") or {}),
        min_trades_for_ranking=int(scoring.get("min_trades_for_ranking", 5)),
        top_trades_per_person=int(scoring.get("top_trades_per_person", 100)),
        top_trades_selection=scoring.get("top_trades_selection", "largest"),
        report_top_n=int(scoring.get("report_top_n", 150)),
        config_dir=config_dir,
    )


def _norm_key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())
