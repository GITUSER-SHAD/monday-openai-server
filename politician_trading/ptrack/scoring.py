"""Composite ranking score.

The formula lives in config/scoring.yaml and is echoed verbatim into every
report so the number can be audited. Raw components are always carried
alongside the score — the score never replaces them.

    score = 0.4*mean_alpha_vs_spy
          + 0.3*win_rate
          + 0.2*median_alpha_vs_sector_etf
          + 0.1*event_proximity_rate

Two properties of this formula that a reader must know, and which the report
states rather than buries:

1. MIXED UNITS. Alpha terms are return fractions (0.08 = +8 percentage points);
   win rate and event-proximity rate are bounded rates in [0,1]. Adding them
   means one point of win rate is worth as much as 100 points of alpha. The
   rank-normalised variant below removes that distortion by converting each
   component to its percentile within the eligible cohort before weighting.

2. EVENT PROXIMITY IS NOT PERFORMANCE. It enters the score as a positive term,
   so a person who trades near events scores higher. Proximity is a base-rate
   artefact as much as anything else, and it is neither evidence of misconduct
   nor of skill. It is included because the specification calls for it; it is
   reported separately as a frequency statistic, which is the only reading it
   supports.
"""

from __future__ import annotations

import pandas as pd

COMPONENTS = (
    "mean_alpha_vs_spy",
    "win_rate",
    "median_alpha_vs_sector_etf",
    "event_proximity_rate",
)


def formula_text(weights: dict[str, float]) -> str:
    return " + ".join(f"{weights.get(c, 0.0):g}*{c}" for c in COMPONENTS)


def compute_scores(person_metrics: pd.DataFrame, weights: dict[str, float],
                   min_trades: int) -> pd.DataFrame:
    """Add composite_score, composite_score_normalized, rank and eligibility.

    A person below `min_trades` analysed positions is scored but marked
    ineligible and excluded from the ranking: a 100% win rate over two trades is
    noise, and letting it top a leaderboard would be the single easiest way to
    make this whole analysis misleading.
    """
    if person_metrics is None or person_metrics.empty:
        return person_metrics

    df = person_metrics.copy()
    for component in COMPONENTS:
        if component not in df.columns:
            df[component] = None

    df["eligible_for_ranking"] = df["positions_analyzed"] >= min_trades

    # Raw weighted sum. Missing components contribute 0 and are counted so the
    # report can say how much of a score was actually populated.
    filled = df[list(COMPONENTS)].astype(float)
    df["score_components_present"] = filled.notna().sum(axis=1)
    df["composite_score"] = sum(
        filled[c].fillna(0.0) * float(weights.get(c, 0.0)) for c in COMPONENTS
    )

    # Rank-normalised variant: each component -> percentile within the eligible
    # cohort, then the same weights. Comparable across components by construction.
    eligible = df[df["eligible_for_ranking"]]
    if len(eligible) > 1:
        pct = eligible[list(COMPONENTS)].astype(float).rank(pct=True, na_option="keep")
        normalized = sum(pct[c].fillna(0.5) * float(weights.get(c, 0.0))
                         for c in COMPONENTS)
        df.loc[eligible.index, "composite_score_normalized"] = normalized
    else:
        df["composite_score_normalized"] = None

    df["rank_composite"] = None
    mask = df["eligible_for_ranking"]
    if mask.any():
        ranks = (df.loc[mask, "composite_score"]
                 .rank(ascending=False, method="min").astype(int))
        df.loc[mask, "rank_composite"] = ranks

    return df.sort_values(
        ["eligible_for_ranking", "composite_score"], ascending=[False, False]
    ).reset_index(drop=True)
