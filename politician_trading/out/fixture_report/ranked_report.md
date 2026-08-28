# Public-Disclosure Trading Analysis — Ranked Report

**Run:** `run-20260828T080210-a2b54b`  
**Prices as of:** 2024-12-31  
**People ranked:** top 150 by composite score (minimum 5 analysed positions to be eligible)

## How to read this report

- Every dollar figure is an **estimate**. Disclosures report amount *ranges*, never exact amounts; midpoints are used throughout and the range is carried beside the estimate.
- A sale can close only part of an earlier purchase. Where it does, the row shows the **matched slice**, which is smaller than the opening disclosure's range, and says so explicitly.
- Returns marked **UNREALIZED** are positions still held, marked to the as-of price. They are not booked gains.
- Returns for options are the **direction-adjusted move in the underlying**, not the option's profit and loss: a periodic transaction report discloses no strike and no expiry, so true option P&L is not derivable from public data.
- **Disclosure-window drift** is reported in its own column. It measures reporting lag only and is excluded from every ranking.
- **Event-proximity** flags are frequency statistics. They indicate that a position was opened shortly before a dated public event in the same sector. They are correlational, are sensitive to how often a person trades that sector at all, and are **not** evidence of knowledge, intent, or wrongdoing.
- Nothing here asserts illegality. These are public filings analysed statistically.

## Composite score formula

```
score = 0.4*mean_alpha_vs_spy + 0.3*win_rate + 0.2*median_alpha_vs_sector_etf + 0.1*event_proximity_rate
```

Raw components are shown for every person so the score can be recomputed by hand. Two caveats travel with it:

1. **Mixed units.** Alpha terms are return fractions (`0.08` = +8pp); win rate and event-proximity rate are bounded rates in `[0,1]`. Summing them makes one point of win rate worth a hundred points of alpha. The `composite_score_normalized` column re-weights each component by its percentile within the eligible cohort and is the fairer comparison.
2. **Event proximity is a positive term** in this formula, so trading near events raises the score. That is a specified weighting, not a finding about behaviour.

## Data sources

| Data | Source | Location |
|---|---|---|
| Trades / disclosures | synthetic-fixture | fixtures/make_fixture.py |
| Daily prices (adj. close) | local_csv:synthetic_prices.csv | synthetic_prices.csv |
| Officials roster | none (no roster matched) | n/a |
| Event timeline | synthetic-fixture | fixtures/make_fixture.py |

## Methodology settings

- Per-person metrics computed over each person's top 100 trades, selected by `largest`.
- Event proximity window: **10 trading days** before a sector-matched event.
- Short/put benchmark convention: `long_benchmark`.
- Buy/sell pairs in the same ticker by the same person are netted FIFO into positions; each disclosure line is *not* treated independently.
- Benchmarks (SPY and the sector ETF) are measured over the identical window as the position they are compared against.

## Coverage and data quality

| Measure | Value |
|---|---|
| Disclosure lines ingested | 480 |
| People on record | 32 |
| Positions after netting | 404 |
| Positions with complete price data | 404 (100.0%) |
| Positions still open (UNREALIZED) | 244 |
| Curated events | 30 |
| Trade-event links | 23 |
| People eligible for ranking | 28 |

### Data-quality notes

- 11 tickers had no price data, e.g. ['BITQ', 'GLD', 'IYT', 'KBE', 'XBI', 'XLB', 'XLC', 'XLI']
- 48 sales had no matching prior purchase on record (holdings pre-dating the disclosure history); excluded from returns
- 8 filer names did not match the roster (name formatting differs across sources), e.g. ['Synthetic Member Alpha', 'Synthetic Member Bravo', 'Synthetic Member Charlie', 'Synthetic Member Delta', 'Synthetic Member Echo']

## Ranked table — top 28

| # | Person | Chamber | Positions | Win rate | Mean alpha vs SPY | Median alpha vs sector | Event prox. | Median lag (d) | Score | Score (norm.) |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Synthetic Member Alpha (spouse) | senate | 16 | 68.8% | +34.0% | +9.2% | 6.2% | 52 | 0.367 | 0.904 |
| 2 | Synthetic Member Golf (spouse) | senate | 8 | 87.5% | -2.1% | +17.5% | 0.0% | 30 | 0.289 | 0.864 |
| 3 | Synthetic Member Charlie (joint) | house | 11 | 72.7% | +0.5% | +5.4% | 9.1% | 17 | 0.240 | 0.896 |
| 4 | Synthetic Member Alpha (joint) | senate | 6 | 66.7% | -10.5% | +9.7% | 0.0% | 41 | 0.177 | 0.718 |
| 5 | Synthetic Member Delta (spouse) | senate | 10 | 70.0% | -8.6% | -4.8% | 10.0% | 25 | 0.176 | 0.825 |
| 6 | Synthetic Member Golf | senate | 16 | 50.0% | +6.9% | -39.4% | 12.5% | 35 | 0.111 | 0.663 |
| 7 | Synthetic Member Charlie | house | 19 | 68.4% | -10.8% | -28.3% | 0.0% | 26 | 0.106 | 0.614 |
| 8 | Synthetic Member Delta | senate | 25 | 56.0% | -18.8% | -6.7% | 20.0% | 27 | 0.100 | 0.684 |
| 9 | Synthetic Member Foxtrot | house | 13 | 53.8% | -14.2% | -26.8% | 7.7% | 40 | 0.059 | 0.550 |
| 10 | Synthetic Member Hotel | house | 27 | 55.6% | -9.9% | -36.4% | 0.0% | 30 | 0.054 | 0.555 |
| 11 | Synthetic Member Echo (spouse) | house | 22 | 50.0% | -20.1% | -11.3% | 0.0% | 32 | 0.047 | 0.487 |
| 12 | Synthetic Member Alpha (dependent child) | senate | 13 | 53.8% | -13.4% | -35.4% | 7.7% | 39 | 0.045 | 0.536 |
| 13 | Synthetic Member Bravo (dependent child) | house | 12 | 33.3% | -9.3% | -20.3% | 16.7% | 48 | 0.039 | 0.539 |
| 14 | Synthetic Member Bravo | house | 25 | 56.0% | -27.7% | -12.5% | 4.0% | 22 | 0.036 | 0.527 |
| 15 | Synthetic Member Foxtrot (joint) | house | 6 | 33.3% | -2.6% | -33.3% | 0.0% | 51 | 0.023 | 0.471 |
| 16 | Synthetic Member Alpha | senate | 20 | 50.0% | -28.3% | -10.0% | 5.0% | 48 | 0.022 | 0.462 |
| 17 | Synthetic Member Golf (joint) | senate | 7 | 42.9% | -5.8% | -42.8% | 0.0% | 43 | 0.020 | 0.452 |
| 18 | Synthetic Member Echo | house | 24 | 45.8% | -27.3% | -13.1% | 8.3% | 40 | 0.010 | 0.457 |
| 19 | Synthetic Member Golf (dependent child) | senate | 15 | 40.0% | -19.1% | -18.7% | 0.0% | 41 | 0.006 | 0.393 |
| 20 | Synthetic Member Echo (joint) | house | 7 | 42.9% | +2.6% | -76.4% | 14.3% | 44 | 0.001 | 0.557 |
| 21 | Synthetic Member Delta (joint) | senate | 13 | 61.5% | -23.1% | -59.2% | 7.7% | 57 | -0.018 | 0.473 |
| 22 | Synthetic Member Charlie (spouse) | house | 9 | 44.4% | -42.1% | -22.7% | 0.0% | 38 | -0.080 | 0.330 |
| 23 | Synthetic Member Hotel (spouse) | house | 14 | 50.0% | -46.8% | -31.4% | 14.3% | 28 | -0.086 | 0.364 |
| 24 | Synthetic Member Hotel (dependent child) | house | 9 | 55.6% | -46.2% | -40.8% | 11.1% | 45 | -0.089 | 0.391 |
| 25 | Synthetic Member Foxtrot (spouse) | house | 13 | 15.4% | -45.2% | -11.4% | 7.7% | 44 | -0.150 | 0.298 |
| 26 | Synthetic Member Echo (dependent child) | house | 7 | 28.6% | -46.6% | -56.4% | 0.0% | 39 | -0.214 | 0.129 |
| 27 | Synthetic Member Charlie (dependent child) | house | 15 | 33.3% | -63.3% | -37.8% | 13.3% | 27 | -0.215 | 0.200 |
| 28 | Synthetic Member Bravo (spouse) | house | 9 | 44.4% | -54.2% | -78.7% | 0.0% | 30 | -0.241 | 0.159 |

## Person profiles

### 1. Synthetic Member Alpha (spouse)

*senate*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 21 | disclosure source |
| Positions analysed (after netting) | 16 | top 100 by largest |
| — closed / still held | 10 / 6 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 68.8% | share of analysed positions with a positive return |
| Mean return | +55.9% | direction-adjusted |
| Median return | +33.2% | direction-adjusted |
| Mean alpha vs SPY | +34.0% | identical window |
| Median alpha vs SPY | +6.7% | identical window |
| Mean alpha vs sector ETF | +19.7% | identical window |
| Median alpha vs sector ETF | +9.2% | identical window |
| Median disclosure lag | 52 days | trade date to disclosure date |
| Median disclosure-window drift | +2.1% | **lag metric only — not performance** |
| Sector concentration | 99.2% in `health_care` | share of ESTIMATED notional |
| Event-proximity rate | 6.2% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$50,619,507 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.367 (normalised 0.904) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2020-07-10 | 2022-10-25 | ~$75,000 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +405.3% | +393.1% | +344.7% | — |
| ZZGG | semiconductors | long | 2020-07-10 | 2024-07-09 | ~$92,000 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +147.8% | +92.1% | +36.2% | — |
| ZZGG | semiconductors | long | 2020-07-10 | 2024-01-25 | ~$8,000 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +113.5% | +76.6% | +33.3% | — |

### 2. Synthetic Member Golf (spouse)

*senate*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 8 | disclosure source |
| Positions analysed (after netting) | 8 | top 100 by largest |
| — closed / still held | 2 / 6 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 87.5% | share of analysed positions with a positive return |
| Mean return | +22.2% | direction-adjusted |
| Median return | +28.7% | direction-adjusted |
| Mean alpha vs SPY | -2.1% | identical window |
| Median alpha vs SPY | -0.3% | identical window |
| Mean alpha vs sector ETF | +0.7% | identical window |
| Median alpha vs sector ETF | +17.5% | identical window |
| Median disclosure lag | 30 days | trade date to disclosure date |
| Median disclosure-window drift | +5.0% | **lag metric only — not performance** |
| Sector concentration | 95.4% in `health_care` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$3,223,003 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.289 (normalised 0.864) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZFF | gold_mining | short | 2024-06-18 | still held (UNREALIZED) | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +27.9% | +27.2% | +59.3% | — |
| ZZEE | health_care | long | 2019-07-03 | 2019-12-30 | ~$175,000 (est.)<br/>opening disclosure: $1,000,001 - $5,000,000<br/>_partial exit: this slice of a ~$3,000,000 (est.) position_ | +14.9% | +13.9% | +20.1% | — |
| ZZEE | health_care | long | 2023-12-21 | still held (UNREALIZED) | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +29.4% | +13.7% | +38.1% | — |

### 3. Synthetic Member Charlie (joint)

*house*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 15 | disclosure source |
| Positions analysed (after netting) | 11 | top 100 by largest |
| — closed / still held | 7 / 4 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 72.7% | share of analysed positions with a positive return |
| Mean return | +7.5% | direction-adjusted |
| Median return | +4.6% | direction-adjusted |
| Mean alpha vs SPY | +0.5% | identical window |
| Median alpha vs SPY | +0.7% | identical window |
| Mean alpha vs sector ETF | +0.4% | identical window |
| Median alpha vs sector ETF | +5.4% | identical window |
| Median disclosure lag | 17 days | trade date to disclosure date |
| Median disclosure-window drift | +3.7% | **lag metric only — not performance** |
| Sector concentration | 44.2% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 9.1% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$279,504 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.240 (normalised 0.896) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2024-09-23 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +26.6% | +25.5% | +15.7% | — |
| ZZJJ | real_estate | long | 2023-05-01 | 2024-07-24 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +45.6% | +22.8% | +29.3% | — |
| ZZHH | utilities | long | 2023-06-26 | 2024-04-12 | ~$32,500 (est.)<br/>opening disclosure: $50,001 - $100,000<br/>_partial exit: this slice of a ~$75,000 (est.) position_ | +5.0% *(underlying proxy)* | +12.2% | -18.4% | — |

### 4. Synthetic Member Alpha (joint)

*senate*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 7 | disclosure source |
| Positions analysed (after netting) | 6 | top 100 by largest |
| — closed / still held | 2 / 4 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 66.7% | share of analysed positions with a positive return |
| Mean return | +9.8% | direction-adjusted |
| Median return | +9.3% | direction-adjusted |
| Mean alpha vs SPY | -10.5% | identical window |
| Median alpha vs SPY | +2.5% | identical window |
| Mean alpha vs sector ETF | +0.8% | identical window |
| Median alpha vs sector ETF | +9.7% | identical window |
| Median disclosure lag | 41 days | trade date to disclosure date |
| Median disclosure-window drift | +3.7% | **lag metric only — not performance** |
| Sector concentration | 57.0% in `defense` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$965,502 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.177 (normalised 0.718) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZCC | technology | long | 2021-03-05 | 2022-04-11 | ~$8,000 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +47.5% | +50.8% | +41.0% | — |
| ZZCC | technology | long | 2021-03-05 | still held (UNREALIZED) | ~$367,000 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +84.0% | +44.5% | +11.4% | — |
| ZZBB | defense | long | 2024-05-29 | still held (UNREALIZED) | ~$375,000 (est.)<br/>opening disclosure: $250,001 - $500,000 | +16.4% *(underlying proxy)* | +11.6% | +35.3% | — |

### 5. Synthetic Member Delta (spouse)

*senate*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 15 | disclosure source |
| Positions analysed (after netting) | 10 | top 100 by largest |
| — closed / still held | 5 / 5 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 70.0% | share of analysed positions with a positive return |
| Mean return | +12.2% | direction-adjusted |
| Median return | +13.5% | direction-adjusted |
| Mean alpha vs SPY | -8.6% | identical window |
| Median alpha vs SPY | +8.7% | identical window |
| Mean alpha vs sector ETF | -26.4% | identical window |
| Median alpha vs sector ETF | -4.8% | identical window |
| Median disclosure lag | 25 days | trade date to disclosure date |
| Median disclosure-window drift | -1.5% | **lag metric only — not performance** |
| Sector concentration | 73.4% in `defense` | share of ESTIMATED notional |
| Event-proximity rate | 10.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,281,505 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.176 (normalised 0.825) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZII | consumer_discretionary | long | 2020-04-30 | still held (UNREALIZED) | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +106.1% | +62.0% | +37.6% | — |
| ZZHH | utilities | long | 2020-05-11 | 2021-12-23 | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +21.1% | +22.4% | +23.9% | — |
| ZZII | consumer_discretionary | long | 2019-11-04 | 2024-01-01 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +51.9% | +18.3% | +7.7% | — |

### 6. Synthetic Member Golf

*senate*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 17 | disclosure source |
| Positions analysed (after netting) | 16 | top 100 by largest |
| — closed / still held | 4 / 12 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 50.0% | share of analysed positions with a positive return |
| Mean return | +35.4% | direction-adjusted |
| Median return | -0.7% | direction-adjusted |
| Mean alpha vs SPY | +6.9% | identical window |
| Median alpha vs SPY | -7.5% | identical window |
| Mean alpha vs sector ETF | -48.3% | identical window |
| Median alpha vs sector ETF | -39.4% | identical window |
| Median disclosure lag | 35 days | trade date to disclosure date |
| Median disclosure-window drift | -3.2% | **lag metric only — not performance** |
| Sector concentration | 51.2% in `real_estate` | share of ESTIMATED notional |
| Event-proximity rate | 12.5% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$2,195,506 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.111 (normalised 0.663) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2019-09-09 | 2022-12-01 | ~$8,000 (est.)<br/>opening disclosure: $500,001 - $1,000,000<br/>_partial exit: this slice of a ~$750,000 (est.) position_ | +283.5% | +271.6% | +185.4% | — |
| ZZGG | semiconductors | long | 2020-02-13 | still held (UNREALIZED) | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +210.0% *(underlying proxy)* | +156.4% | -96.5% | — |
| ZZAA | energy | long | 2022-01-19 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +97.7% *(underlying proxy)* | +53.6% | -20.0% | — |

### 7. Synthetic Member Charlie

*house*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 22 | disclosure source |
| Positions analysed (after netting) | 19 | top 100 by largest |
| — closed / still held | 6 / 13 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 68.4% | share of analysed positions with a positive return |
| Mean return | +16.3% | direction-adjusted |
| Median return | +8.4% | direction-adjusted |
| Mean alpha vs SPY | -10.8% | identical window |
| Median alpha vs SPY | -2.5% | identical window |
| Mean alpha vs sector ETF | -49.7% | identical window |
| Median alpha vs sector ETF | -28.3% | identical window |
| Median disclosure lag | 26 days | trade date to disclosure date |
| Median disclosure-window drift | -2.2% | **lag metric only — not performance** |
| Sector concentration | 56.8% in `financials` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,462,008 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.106 (normalised 0.614) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2019-05-09 | 2024-02-27 | ~$8,000 (est.)<br/>opening disclosure: $50,001 - $100,000<br/>_partial exit: this slice of a ~$75,000 (est.) position_ | +69.3% | +42.4% | -5.7% | — |
| ZZDD | financials | long | 2019-08-21 | still held (UNREALIZED) | ~$16,500 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +83.1% | +33.0% | -56.9% | — |
| ZZDD | financials | long | 2022-02-08 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +58.9% *(underlying proxy)* | +18.3% | +2.8% | — |

### 8. Synthetic Member Delta

*senate*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 29 | disclosure source |
| Positions analysed (after netting) | 25 | top 100 by largest |
| — closed / still held | 9 / 16 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 56.0% | share of analysed positions with a positive return |
| Mean return | +2.7% | direction-adjusted |
| Median return | +9.3% | direction-adjusted |
| Mean alpha vs SPY | -18.8% | identical window |
| Median alpha vs SPY | -11.2% | identical window |
| Mean alpha vs sector ETF | -32.8% | identical window |
| Median alpha vs sector ETF | -6.7% | identical window |
| Median disclosure lag | 27 days | trade date to disclosure date |
| Median disclosure-window drift | -0.3% | **lag metric only — not performance** |
| Sector concentration | 49.7% in `technology` | share of ESTIMATED notional |
| Event-proximity rate | 20.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$107,270,511 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.100 (normalised 0.684) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZFF | gold_mining | long | 2019-09-27 | 2023-01-26 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +65.8% | +38.5% | -33.6% | — |
| ZZCC | technology | long | 2020-07-13 | 2023-04-06 | ~$32,500 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +61.7% | +35.8% | -64.0% | `SYN-EV-030` (1d before) |
| ZZCC | technology | long | 2020-07-13 | 2024-02-05 | ~$8,000 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +72.0% | +31.4% | -119.9% | `SYN-EV-030` (1d before) |

### 9. Synthetic Member Foxtrot

*house*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 16 | disclosure source |
| Positions analysed (after netting) | 13 | top 100 by largest |
| — closed / still held | 3 / 10 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 53.8% | share of analysed positions with a positive return |
| Mean return | +16.5% | direction-adjusted |
| Median return | +16.8% | direction-adjusted |
| Mean alpha vs SPY | -14.2% | identical window |
| Median alpha vs SPY | -15.4% | identical window |
| Mean alpha vs sector ETF | -34.1% | identical window |
| Median alpha vs sector ETF | -26.8% | identical window |
| Median disclosure lag | 40 days | trade date to disclosure date |
| Median disclosure-window drift | -3.1% | **lag metric only — not performance** |
| Sector concentration | 98.2% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 7.7% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$50,952,507 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.059 (normalised 0.550) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2024-02-09 | still held (UNREALIZED) | ~$50,000,001 (est.)<br/>opening disclosure: over $50,000,000 | +94.0% | +82.9% | +92.6% | — |
| ZZGG | semiconductors | long | 2020-06-23 | still held (UNREALIZED) | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +111.4% | +62.8% | -113.4% | — |
| ZZDD | financials | short | 2024-05-14 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +28.4% *(underlying proxy)* | +21.1% | +21.6% | — |

### 10. Synthetic Member Hotel

*house*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 32 | disclosure source |
| Positions analysed (after netting) | 27 | top 100 by largest |
| — closed / still held | 12 / 15 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 55.6% | share of analysed positions with a positive return |
| Mean return | +17.3% | direction-adjusted |
| Median return | +4.6% | direction-adjusted |
| Mean alpha vs SPY | -9.9% | identical window |
| Median alpha vs SPY | -6.4% | identical window |
| Mean alpha vs sector ETF | -45.1% | identical window |
| Median alpha vs sector ETF | -36.4% | identical window |
| Median disclosure lag | 30 days | trade date to disclosure date |
| Median disclosure-window drift | +1.5% | **lag metric only — not performance** |
| Sector concentration | 97.2% in `real_estate` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$103,283,512 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.054 (normalised 0.555) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2019-09-10 | 2023-06-20 | ~$32,500 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +181.6% | +136.1% | +131.4% | — |
| ZZAA | energy | long | 2023-03-08 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +166.6% | +132.3% | +44.5% | — |
| ZZGG | semiconductors | long | 2019-09-10 | 2021-08-25 | ~$32,500 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +107.0% | +104.4% | +66.7% | — |

### 11. Synthetic Member Echo (spouse)

*house*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 25 | disclosure source |
| Positions analysed (after netting) | 22 | top 100 by largest |
| — closed / still held | 7 / 15 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 50.0% | share of analysed positions with a positive return |
| Mean return | +3.6% | direction-adjusted |
| Median return | +0.3% | direction-adjusted |
| Mean alpha vs SPY | -20.1% | identical window |
| Median alpha vs SPY | -16.3% | identical window |
| Mean alpha vs sector ETF | -31.5% | identical window |
| Median alpha vs sector ETF | -11.3% | identical window |
| Median disclosure lag | 32 days | trade date to disclosure date |
| Median disclosure-window drift | +3.4% | **lag metric only — not performance** |
| Sector concentration | 96.1% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$52,045,509 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.047 (normalised 0.487) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2022-04-25 | still held (UNREALIZED) | ~$49,992,000 (est.)<br/>opening disclosure: over $50,000,000<br/>_partial exit: this slice of a ~$50,000,001 (est.) position_ | +98.5% | +60.2% | -5.6% | — |
| ZZFF | gold_mining | short | 2024-02-07 | still held (UNREALIZED) | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +55.0% *(underlying proxy)* | +42.9% | +76.4% | — |
| ZZGG | semiconductors | short | 2019-08-23 | 2020-03-31 | ~$8,000 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +38.1% *(underlying proxy)* | +37.9% | +35.9% | — |

### 12. Synthetic Member Alpha (dependent child)

*senate*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 13 | disclosure source |
| Positions analysed (after netting) | 13 | top 100 by largest |
| — closed / still held | 6 / 7 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 53.8% | share of analysed positions with a positive return |
| Mean return | +7.0% | direction-adjusted |
| Median return | +7.0% | direction-adjusted |
| Mean alpha vs SPY | -13.4% | identical window |
| Median alpha vs SPY | -18.2% | identical window |
| Mean alpha vs sector ETF | -33.5% | identical window |
| Median alpha vs sector ETF | -35.4% | identical window |
| Median disclosure lag | 39 days | trade date to disclosure date |
| Median disclosure-window drift | +2.5% | **lag metric only — not performance** |
| Sector concentration | 79.6% in `consumer_discretionary` | share of ESTIMATED notional |
| Event-proximity rate | 7.7% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$446,504 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.045 (normalised 0.536) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZII | consumer_discretionary | long | 2020-06-12 | 2022-06-10 | ~$8,000 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +119.2% | +115.0% | +138.8% | — |
| ZZII | consumer_discretionary | long | 2020-06-12 | 2024-04-17 | ~$24,500 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +112.4% | +77.9% | +70.2% | — |
| ZZFF | gold_mining | long | 2021-08-20 | 2022-02-22 | ~$67,000 (est.)<br/>opening disclosure: $50,001 - $100,000<br/>_partial exit: this slice of a ~$75,000 (est.) position_ | +13.9% | +7.3% | -3.9% | — |

### 13. Synthetic Member Bravo (dependent child)

*house*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 14 | disclosure source |
| Positions analysed (after netting) | 12 | top 100 by largest |
| — closed / still held | 6 / 6 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 33.3% | share of analysed positions with a positive return |
| Mean return | +4.9% | direction-adjusted |
| Median return | -7.0% | direction-adjusted |
| Mean alpha vs SPY | -9.3% | identical window |
| Median alpha vs SPY | -17.7% | identical window |
| Mean alpha vs sector ETF | -25.5% | identical window |
| Median alpha vs sector ETF | -20.3% | identical window |
| Median disclosure lag | 48 days | trade date to disclosure date |
| Median disclosure-window drift | +1.7% | **lag metric only — not performance** |
| Sector concentration | 65.0% in `financials` | share of ESTIMATED notional |
| Event-proximity rate | 16.7% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,281,505 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.039 (normalised 0.539) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZDD | financials | long | 2019-09-20 | 2023-05-10 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +83.9% | +47.3% | +2.4% | — |
| ZZDD | financials | long | 2022-11-15 | 2023-05-10 | ~$750,000 (est.)<br/>opening disclosure: $500,001 - $1,000,000 | +39.8% | +22.0% | +35.9% | — |
| ZZAA | energy | long | 2024-08-01 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +13.8% | +14.0% | +22.9% | — |

### 14. Synthetic Member Bravo

*house*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 30 | disclosure source |
| Positions analysed (after netting) | 25 | top 100 by largest |
| — closed / still held | 10 / 15 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 56.0% | share of analysed positions with a positive return |
| Mean return | -5.6% | direction-adjusted |
| Median return | +4.8% | direction-adjusted |
| Mean alpha vs SPY | -27.7% | identical window |
| Median alpha vs SPY | -6.5% | identical window |
| Mean alpha vs sector ETF | -42.8% | identical window |
| Median alpha vs sector ETF | -12.5% | identical window |
| Median disclosure lag | 22 days | trade date to disclosure date |
| Median disclosure-window drift | +2.3% | **lag metric only — not performance** |
| Sector concentration | 64.8% in `semiconductors` | share of ESTIMATED notional |
| Event-proximity rate | 4.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$4,733,510 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.036 (normalised 0.527) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2019-05-22 | 2021-06-11 | ~$8,000 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +34.1% | +44.9% | -11.0% | — |
| ZZFF | gold_mining | short | 2023-02-28 | still held (UNREALIZED) | ~$375,000 (est.)<br/>opening disclosure: $250,001 - $500,000 | +77.0% | +42.7% | +93.9% | — |
| ZZFF | gold_mining | long | 2019-05-06 | 2022-05-16 | ~$32,500 (est.)<br/>opening disclosure: $50,001 - $100,000<br/>_partial exit: this slice of a ~$75,000 (est.) position_ | +33.3% | +30.5% | +2.9% | — |

### 15. Synthetic Member Foxtrot (joint)

*house*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 9 | disclosure source |
| Positions analysed (after netting) | 6 | top 100 by largest |
| — closed / still held | 2 / 4 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 33.3% | share of analysed positions with a positive return |
| Mean return | +12.9% | direction-adjusted |
| Median return | -6.4% | direction-adjusted |
| Mean alpha vs SPY | -2.6% | identical window |
| Median alpha vs SPY | -10.9% | identical window |
| Mean alpha vs sector ETF | -58.0% | identical window |
| Median alpha vs sector ETF | -33.3% | identical window |
| Median disclosure lag | 51 days | trade date to disclosure date |
| Median disclosure-window drift | -8.9% | **lag metric only — not performance** |
| Sector concentration | 94.4% in `consumer_discretionary` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$431,502 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.023 (normalised 0.471) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZII | consumer_discretionary | long | 2019-07-22 | 2022-04-11 | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +130.8% | +127.8% | +126.3% | — |
| ZZAA | energy | long | 2019-05-31 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +34.9% *(underlying proxy)* | -2.6% | -254.9% | — |
| ZZII | consumer_discretionary | long | 2024-10-14 | 2024-10-28 | ~$8,000 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | -6.8% | -5.6% | -11.6% | — |

### 16. Synthetic Member Alpha

*senate*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 23 | disclosure source |
| Positions analysed (after netting) | 20 | top 100 by largest |
| — closed / still held | 9 / 11 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 50.0% | share of analysed positions with a positive return |
| Mean return | +1.7% | direction-adjusted |
| Median return | +3.2% | direction-adjusted |
| Mean alpha vs SPY | -28.3% | identical window |
| Median alpha vs SPY | -15.1% | identical window |
| Mean alpha vs sector ETF | -47.7% | identical window |
| Median alpha vs sector ETF | -10.0% | identical window |
| Median disclosure lag | 48 days | trade date to disclosure date |
| Median disclosure-window drift | +1.0% | **lag metric only — not performance** |
| Sector concentration | 80.2% in `consumer_discretionary` | share of ESTIMATED notional |
| Event-proximity rate | 5.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$4,053,008 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.022 (normalised 0.462) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2022-06-22 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +108.4% | +68.4% | -2.8% | — |
| ZZAA | energy | long | 2024-05-21 | still held (UNREALIZED) | ~$175,000 (est.)<br/>opening disclosure: $100,001 - $250,000 | +33.0% | +27.5% | +45.2% | — |
| ZZAA | energy | long | 2020-09-17 | still held (UNREALIZED) | ~$24,500 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +83.3% | +18.0% | -72.5% | — |

### 17. Synthetic Member Golf (joint)

*senate*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 8 | disclosure source |
| Positions analysed (after netting) | 7 | top 100 by largest |
| — closed / still held | 3 / 4 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 42.9% | share of analysed positions with a positive return |
| Mean return | +27.6% | direction-adjusted |
| Median return | -0.7% | direction-adjusted |
| Mean alpha vs SPY | -5.8% | identical window |
| Median alpha vs SPY | -3.9% | identical window |
| Mean alpha vs sector ETF | -40.3% | identical window |
| Median alpha vs sector ETF | -42.8% | identical window |
| Median disclosure lag | 43 days | trade date to disclosure date |
| Median disclosure-window drift | +9.1% | **lag metric only — not performance** |
| Sector concentration | 64.6% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,173,502 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.020 (normalised 0.452) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2022-03-04 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +86.6% | +43.5% | -17.4% | — |
| ZZAA | energy | long | 2020-10-12 | still held (UNREALIZED) | ~$642,500 (est.)<br/>opening disclosure: $500,001 - $1,000,000<br/>_partial exit: this slice of a ~$750,000 (est.) position_ | +82.2% | +23.0% | -57.5% | — |
| ZZAA | energy | long | 2020-10-12 | 2024-08-22 | ~$75,000 (est.)<br/>opening disclosure: $500,001 - $1,000,000<br/>_partial exit: this slice of a ~$750,000 (est.) position_ | +67.8% | +11.8% | -86.5% | — |

### 18. Synthetic Member Echo

*house*  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 27 | disclosure source |
| Positions analysed (after netting) | 24 | top 100 by largest |
| — closed / still held | 9 / 15 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 45.8% | share of analysed positions with a positive return |
| Mean return | +3.8% | direction-adjusted |
| Median return | -2.2% | direction-adjusted |
| Mean alpha vs SPY | -27.3% | identical window |
| Median alpha vs SPY | -23.9% | identical window |
| Mean alpha vs sector ETF | -16.3% | identical window |
| Median alpha vs sector ETF | -13.1% | identical window |
| Median disclosure lag | 40 days | trade date to disclosure date |
| Median disclosure-window drift | -1.9% | **lag metric only — not performance** |
| Sector concentration | 42.3% in `financials` | share of ESTIMATED notional |
| Event-proximity rate | 8.3% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,040,510 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.010 (normalised 0.457) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZDD | financials | long | 2021-02-12 | 2023-10-20 | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +172.6% | +144.5% | +135.1% | — |
| ZZDD | financials | long | 2021-11-03 | 2024-06-12 | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +118.4% | +67.4% | +62.0% | `SYN-EV-003` (8d before) |
| ZZEE | health_care | long | 2023-08-23 | still held (UNREALIZED) | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +38.2% | +26.8% | +47.6% | `SYN-EV-012` (6d before) |

### 19. Synthetic Member Golf (dependent child)

*senate*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 21 | disclosure source |
| Positions analysed (after netting) | 15 | top 100 by largest |
| — closed / still held | 7 / 8 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 40.0% | share of analysed positions with a positive return |
| Mean return | -2.7% | direction-adjusted |
| Median return | -14.0% | direction-adjusted |
| Mean alpha vs SPY | -19.1% | identical window |
| Median alpha vs SPY | -15.7% | identical window |
| Mean alpha vs sector ETF | -16.4% | identical window |
| Median alpha vs sector ETF | -18.7% | identical window |
| Median disclosure lag | 41 days | trade date to disclosure date |
| Median disclosure-window drift | -0.5% | **lag metric only — not performance** |
| Sector concentration | 59.7% in `consumer_discretionary` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,296,006 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.006 (normalised 0.393) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZII | consumer_discretionary | long | 2020-01-30 | 2022-06-20 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +73.7% | +66.7% | +95.3% | — |
| ZZII | consumer_discretionary | long | 2022-11-15 | 2023-07-11 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +27.8% | +4.4% | +25.0% | — |
| ZZBB | defense | long | 2020-02-27 | 2020-05-04 | ~$8,000 (est.)<br/>opening disclosure: $100,001 - $250,000<br/>_partial exit: this slice of a ~$175,000 (est.) position_ | +2.2% | -0.8% | -17.1% | — |

### 20. Synthetic Member Echo (joint)

*house*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 9 | disclosure source |
| Positions analysed (after netting) | 7 | top 100 by largest |
| — closed / still held | 2 / 5 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 42.9% | share of analysed positions with a positive return |
| Mean return | +18.8% | direction-adjusted |
| Median return | -9.9% | direction-adjusted |
| Mean alpha vs SPY | +2.6% | identical window |
| Median alpha vs SPY | -8.1% | identical window |
| Mean alpha vs sector ETF | -54.3% | identical window |
| Median alpha vs sector ETF | -76.4% | identical window |
| Median disclosure lag | 44 days | trade date to disclosure date |
| Median disclosure-window drift | +3.2% | **lag metric only — not performance** |
| Sector concentration | 90.7% in `semiconductors` | share of ESTIMATED notional |
| Event-proximity rate | 14.3% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$3,773,504 (est.) | sum of disclosed-range midpoints |
| Composite score | 0.001 (normalised 0.557) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZGG | semiconductors | long | 2019-08-05 | 2022-03-04 | ~$3,000,000 (est.)<br/>opening disclosure: $1,000,001 - $5,000,000 | +171.2% | +168.5% | +102.6% | — |
| ZZGG | semiconductors | long | 2024-04-05 | still held (UNREALIZED) | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +8.1% | -5.6% | -87.6% | — |
| ZZDD | financials | long | 2022-10-03 | still held (UNREALIZED) | ~$175,000 (est.)<br/>opening disclosure: $100,001 - $250,000 | +37.8% *(underlying proxy)* | -6.6% | +7.8% | — |

### 21. Synthetic Member Delta (joint)

*senate*  
*Filed under a member disclosure as: **joint***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 15 | disclosure source |
| Positions analysed (after netting) | 13 | top 100 by largest |
| — closed / still held | 10 / 3 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 61.5% | share of analysed positions with a positive return |
| Mean return | +0.6% | direction-adjusted |
| Median return | +7.4% | direction-adjusted |
| Mean alpha vs SPY | -23.1% | identical window |
| Median alpha vs SPY | -18.5% | identical window |
| Mean alpha vs sector ETF | -87.4% | identical window |
| Median alpha vs sector ETF | -59.2% | identical window |
| Median disclosure lag | 57 days | trade date to disclosure date |
| Median disclosure-window drift | +1.5% | **lag metric only — not performance** |
| Sector concentration | 82.7% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 7.7% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$573,004 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.018 (normalised 0.473) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2021-03-11 | 2024-08-15 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +74.2% | +36.3% | -59.2% | — |
| ZZAA | energy | long | 2024-07-17 | still held (UNREALIZED) | ~$26,000 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +33.7% | +34.9% | +47.5% | — |
| ZZAA | energy | long | 2024-07-17 | 2024-08-15 | ~$349,000 (est.)<br/>opening disclosure: $250,001 - $500,000<br/>_partial exit: this slice of a ~$375,000 (est.) position_ | +19.0% | +22.0% | +30.1% | — |

### 22. Synthetic Member Charlie (spouse)

*house*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 9 | disclosure source |
| Positions analysed (after netting) | 9 | top 100 by largest |
| — closed / still held | 2 / 7 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 44.4% | share of analysed positions with a positive return |
| Mean return | -21.1% | direction-adjusted |
| Median return | -4.9% | direction-adjusted |
| Mean alpha vs SPY | -42.1% | identical window |
| Median alpha vs SPY | -25.7% | identical window |
| Mean alpha vs sector ETF | -67.6% | identical window |
| Median alpha vs sector ETF | -22.7% | identical window |
| Median disclosure lag | 38 days | trade date to disclosure date |
| Median disclosure-window drift | -0.9% | **lag metric only — not performance** |
| Sector concentration | 72.1% in `technology` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$4,181,504 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.080 (normalised 0.330) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZAA | energy | long | 2022-02-15 | still held (UNREALIZED) | ~$375,000 (est.)<br/>opening disclosure: $250,001 - $500,000 | +86.1% *(underlying proxy)* | +45.9% | -9.0% | — |
| ZZHH | utilities | short | 2023-12-05 | still held (UNREALIZED) | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +3.6% *(underlying proxy)* | -8.9% | -22.7% | — |
| ZZCC | technology | long | 2023-06-21 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | -4.9% | -13.2% | +4.5% | — |

### 23. Synthetic Member Hotel (spouse)

*house*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 17 | disclosure source |
| Positions analysed (after netting) | 14 | top 100 by largest |
| — closed / still held | 5 / 9 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 50.0% | share of analysed positions with a positive return |
| Mean return | -17.5% | direction-adjusted |
| Median return | -0.5% | direction-adjusted |
| Mean alpha vs SPY | -46.8% | identical window |
| Median alpha vs SPY | -7.8% | identical window |
| Mean alpha vs sector ETF | -73.0% | identical window |
| Median alpha vs sector ETF | -31.4% | identical window |
| Median disclosure lag | 28 days | trade date to disclosure date |
| Median disclosure-window drift | -1.6% | **lag metric only — not performance** |
| Sector concentration | 31.8% in `consumer_discretionary` | share of ESTIMATED notional |
| Event-proximity rate | 14.3% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,204,506 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.086 (normalised 0.364) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZDD | financials | long | 2022-12-13 | 2024-03-07 | ~$32,500 (est.)<br/>opening disclosure: $15,001 - $50,000 | +45.6% | +30.6% | +20.0% | — |
| ZZII | consumer_discretionary | long | 2019-12-24 | 2021-03-25 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +12.5% | +14.4% | +9.4% | — |
| ZZCC | technology | long | 2019-12-05 | 2019-12-13 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +4.6% | +5.2% | -4.7% | — |

### 24. Synthetic Member Hotel (dependent child)

*house*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 11 | disclosure source |
| Positions analysed (after netting) | 9 | top 100 by largest |
| — closed / still held | 2 / 7 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 55.6% | share of analysed positions with a positive return |
| Mean return | -13.6% | direction-adjusted |
| Median return | +2.1% | direction-adjusted |
| Mean alpha vs SPY | -46.2% | identical window |
| Median alpha vs SPY | -12.6% | identical window |
| Mean alpha vs sector ETF | -62.6% | identical window |
| Median alpha vs sector ETF | -40.8% | identical window |
| Median disclosure lag | 45 days | trade date to disclosure date |
| Median disclosure-window drift | -1.8% | **lag metric only — not performance** |
| Sector concentration | 57.0% in `energy` | share of ESTIMATED notional |
| Event-proximity rate | 11.1% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,315,004 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.089 (normalised 0.391) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZEE | health_care | long | 2020-02-21 | 2020-08-11 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | -2.5% | +6.4% | -18.3% | — |
| ZZJJ | real_estate | long | 2023-01-03 | still held (UNREALIZED) | ~$75,000 (est.)<br/>opening disclosure: $50,001 - $100,000 | +23.6% *(underlying proxy)* | -7.8% | +20.9% | — |
| ZZHH | utilities | long | 2023-07-18 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +2.1% | -10.2% | -29.1% | — |

### 25. Synthetic Member Foxtrot (spouse)

*house*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 16 | disclosure source |
| Positions analysed (after netting) | 13 | top 100 by largest |
| — closed / still held | 4 / 9 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 15.4% | share of analysed positions with a positive return |
| Mean return | -24.7% | direction-adjusted |
| Median return | -15.5% | direction-adjusted |
| Mean alpha vs SPY | -45.2% | identical window |
| Median alpha vs SPY | -26.7% | identical window |
| Mean alpha vs sector ETF | -36.9% | identical window |
| Median alpha vs sector ETF | -11.4% | identical window |
| Median disclosure lag | 44 days | trade date to disclosure date |
| Median disclosure-window drift | -8.7% | **lag metric only — not performance** |
| Sector concentration | 52.4% in `technology` | share of ESTIMATED notional |
| Event-proximity rate | 7.7% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$731,006 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.150 (normalised 0.298) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZCC | technology | long | 2021-05-18 | 2022-05-05 | ~$375,000 (est.)<br/>opening disclosure: $250,001 - $500,000 | +23.4% | +13.7% | +12.9% | — |
| ZZFF | gold_mining | long | 2024-08-21 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | -0.2% | -0.5% | +37.1% | — |
| ZZBB | defense | short | 2023-08-17 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +8.2% | -4.3% | -9.3% | — |

### 26. Synthetic Member Echo (dependent child)

*house*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 9 | disclosure source |
| Positions analysed (after netting) | 7 | top 100 by largest |
| — closed / still held | 6 / 1 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 28.6% | share of analysed positions with a positive return |
| Mean return | -18.7% | direction-adjusted |
| Median return | -20.2% | direction-adjusted |
| Mean alpha vs SPY | -46.6% | identical window |
| Median alpha vs SPY | -42.7% | identical window |
| Mean alpha vs sector ETF | -65.4% | identical window |
| Median alpha vs sector ETF | -56.4% | identical window |
| Median disclosure lag | 39 days | trade date to disclosure date |
| Median disclosure-window drift | +6.8% | **lag metric only — not performance** |
| Sector concentration | 100.0% in `defense` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$298,502 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.214 (normalised 0.129) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZBB | defense | long | 2019-07-24 | 2020-07-08 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +2.5% | +4.1% | -12.9% | — |
| ZZBB | defense | long | 2022-05-10 | 2023-09-04 | ~$32,500 (est.)<br/>opening disclosure: $50,001 - $100,000<br/>_partial exit: this slice of a ~$75,000 (est.) position_ | -19.4% | -35.2% | -37.2% | — |
| ZZBB | defense | short | 2020-05-21 | still held (UNREALIZED) | ~$175,000 (est.)<br/>opening disclosure: $100,001 - $250,000 | +14.8% *(underlying proxy)* | -35.4% | -56.4% | — |

### 27. Synthetic Member Charlie (dependent child)

*house*  
*Filed under a member disclosure as: **dependent_child***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 17 | disclosure source |
| Positions analysed (after netting) | 15 | top 100 by largest |
| — closed / still held | 6 / 9 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 33.3% | share of analysed positions with a positive return |
| Mean return | -31.8% | direction-adjusted |
| Median return | -29.8% | direction-adjusted |
| Mean alpha vs SPY | -63.3% | identical window |
| Median alpha vs SPY | -52.8% | identical window |
| Mean alpha vs sector ETF | -71.9% | identical window |
| Median alpha vs sector ETF | -37.8% | identical window |
| Median disclosure lag | 27 days | trade date to disclosure date |
| Median disclosure-window drift | +6.4% | **lag metric only — not performance** |
| Sector concentration | 63.5% in `gold_mining` | share of ESTIMATED notional |
| Event-proximity rate | 13.3% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$1,847,006 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.215 (normalised 0.200) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZEE | health_care | long | 2023-06-02 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +37.2% | +25.6% | +49.7% | — |
| ZZFF | gold_mining | long | 2019-03-28 | 2019-10-25 | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +5.6% | +12.9% | +25.6% | — |
| ZZEE | health_care | long | 2022-02-25 | still held (UNREALIZED) | ~$16,500 (est.)<br/>opening disclosure: $15,001 - $50,000<br/>_partial exit: this slice of a ~$32,500 (est.) position_ | +39.1% | -2.9% | +18.0% | — |

### 28. Synthetic Member Bravo (spouse)

*house*  
*Filed under a member disclosure as: **spouse***  

| Metric | Value | Basis |
|---|---|---|
| Disclosure lines on record | 9 | disclosure source |
| Positions analysed (after netting) | 9 | top 100 by largest |
| — closed / still held | 0 / 9 | held positions are marked to the as-of price (UNREALIZED) |
| Win rate | 44.4% | share of analysed positions with a positive return |
| Mean return | -17.6% | direction-adjusted |
| Median return | -3.7% | direction-adjusted |
| Mean alpha vs SPY | -54.2% | identical window |
| Median alpha vs SPY | -44.3% | identical window |
| Mean alpha vs sector ETF | -66.1% | identical window |
| Median alpha vs sector ETF | -78.7% | identical window |
| Median disclosure lag | 30 days | trade date to disclosure date |
| Median disclosure-window drift | +0.3% | **lag metric only — not performance** |
| Sector concentration | 98.1% in `technology` | share of ESTIMATED notional |
| Event-proximity rate | 0.0% | positions opened ≤10 trading days before a sector-matched event — **frequency statistic only** |
| Estimated total notional | ~$50,973,005 (est.) | sum of disclosed-range midpoints |
| Composite score | -0.241 (normalised 0.159) | formula above |

**Largest-alpha positions**

| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | Return | Alpha vs SPY | Alpha vs sector | Event flag |
|---|---|---|---|---|---|---:|---:|---:|---|
| ZZCC | technology | long | 2023-07-28 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +14.9% | +3.5% | +32.1% | — |
| ZZJJ | real_estate | long | 2024-03-19 | still held (UNREALIZED) | ~$750,000 (est.)<br/>opening disclosure: $500,001 - $1,000,000 | +11.1% | -3.0% | +13.7% | — |
| ZZCC | technology | long | 2019-11-28 | still held (UNREALIZED) | ~$8,000 (est.)<br/>opening disclosure: $1,001 - $15,000 | +35.9% | -12.2% | -83.6% | — |


---

_All figures derive from mandatory public disclosures and public price series. Dollar amounts are estimates from disclosed ranges. Performance and timing patterns are correlational and are not claims about conduct._