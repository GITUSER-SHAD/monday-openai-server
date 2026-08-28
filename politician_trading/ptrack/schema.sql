-- ---------------------------------------------------------------------------
-- Politician trading analysis warehouse (DuckDB)
--
-- Provenance rule: every fact-bearing table carries `source` and `source_url`
-- so any figure in the final report can be traced to the disclosure or price
-- series it came from.
--
-- Estimation rule: any column holding a dollar figure derived from a disclosed
-- RANGE is accompanied by its bounds and an is-estimate flag. No dollar figure
-- in this database is an exact reported amount.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS people (
    person_id            TEXT PRIMARY KEY,   -- stable slug, e.g. 'sen-cantwell-maria'
    bioguide_id          TEXT,               -- NULL for non-member filers (spouse etc.)
    full_name            TEXT NOT NULL,
    filer_name           TEXT,               -- name exactly as printed on the filing
    relation             TEXT NOT NULL,      -- self|spouse|dependent_child|joint|other_relative|unknown
    official_person_id   TEXT,               -- the member whose filing covers this person
    chamber              TEXT,               -- house|senate
    party                TEXT,
    state                TEXT,
    district             TEXT,
    term_start           DATE,
    term_end             DATE,
    source               TEXT NOT NULL,
    roster_source        TEXT,     -- which roster actually supplied the metadata
    source_url           TEXT,
    ingested_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id             TEXT PRIMARY KEY,
    person_id            TEXT NOT NULL,
    official_person_id   TEXT,
    owner_code           TEXT,       -- as disclosed: SP=spouse, DC=dependent child, JT=joint, SELF
    trade_date           DATE,
    disclosure_date      DATE,
    disclosure_lag_days  INTEGER,    -- disclosure_date - trade_date, calendar days
    ticker               TEXT,
    asset_name           TEXT,
    asset_type           TEXT,       -- equity|etf|option_call|option_put|short|other|unknown
    direction            TEXT,       -- long|short  (economic exposure to the underlying)
    side                 TEXT,       -- buy|sell|exchange|unknown
    sector               TEXT,
    sector_source        TEXT,       -- override|resolver|fallback

    -- Disclosed as a RANGE. amount_mid is an ESTIMATE, never a reported figure.
    amount_range_text    TEXT,
    amount_low           DOUBLE,
    amount_high          DOUBLE,     -- NULL for the open-ended top bracket
    amount_mid           DOUBLE,     -- ESTIMATE: (low+high)/2, or low when open-ended
    amount_is_estimate   BOOLEAN DEFAULT TRUE,
    amount_bound_open    BOOLEAN DEFAULT FALSE,

    option_strike        DOUBLE,     -- almost always NULL: not required on a PTR
    option_expiry        DATE,       -- almost always NULL

    filing_id            TEXT,
    source               TEXT NOT NULL,
    source_url           TEXT,
    raw                  TEXT        -- verbatim source record (JSON), for audit
);

CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT NOT NULL,
    date        DATE NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    adj_close   DOUBLE,   -- split- and dividend-adjusted; ALL return math uses this
    volume      DOUBLE,
    source      TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Sector -> benchmark ETF mapping (the `benchmarks` deliverable table).
-- Benchmark OHLC lives in `prices` alongside everything else.
CREATE TABLE IF NOT EXISTS benchmarks (
    sector            TEXT PRIMARY KEY,
    benchmark_ticker  TEXT NOT NULL,
    is_market_proxy   BOOLEAN DEFAULT FALSE,
    note              TEXT,
    source            TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    event_date   DATE NOT NULL,
    category     TEXT NOT NULL,   -- war|scandal|impeachment|trial|exec_death|legislation|fed_action|sector_news
    sectors      TEXT NOT NULL,   -- pipe-separated sector keys affected
    description  TEXT,
    source       TEXT NOT NULL,
    source_url   TEXT
);

CREATE TABLE IF NOT EXISTS trade_event_links (
    trade_id             TEXT NOT NULL,
    event_id             TEXT NOT NULL,
    matched_sector       TEXT,
    trading_days_before  INTEGER,   -- trading days from trade_date to event_date
    calendar_days_before INTEGER,
    PRIMARY KEY (trade_id, event_id)
);

-- ---------------------------------------------------------------------------
-- Derived tables (rebuilt by `ptrack analyze`)
-- ---------------------------------------------------------------------------

-- Buy/sell netting output: one row per matched or still-open lot.
-- Multiple disclosure lines in the same ticker by the same person are netted
-- FIFO into these positions rather than treated as independent trades.
CREATE TABLE IF NOT EXISTS positions (
    position_id        TEXT PRIMARY KEY,
    person_id          TEXT NOT NULL,
    ticker             TEXT,
    sector             TEXT,
    direction          TEXT,       -- long|short
    asset_type         TEXT,
    open_trade_id      TEXT NOT NULL,
    close_trade_id     TEXT,       -- NULL => still held (unrealized)
    open_date          DATE,
    close_date         DATE,       -- NULL => marked to the as-of date
    is_open            BOOLEAN,
    matched_amount_mid DOUBLE,     -- ESTIMATE: dollars of the lot that were matched
    open_amount_mid    DOUBLE,     -- ESTIMATE: full size of the opening lot
    is_partial_lot     BOOLEAN,    -- TRUE when this row closes only part of the lot
    open_amount_range  TEXT,
    close_amount_range TEXT,
    amount_is_estimate BOOLEAN DEFAULT TRUE,
    asset_group        TEXT,
    disclosure_date    DATE,
    disclosure_lag_days INTEGER
);

-- One row per position, with returns and benchmark-relative performance.
CREATE TABLE IF NOT EXISTS trade_metrics (
    position_id                 TEXT PRIMARY KEY,
    person_id                   TEXT NOT NULL,
    ticker                      TEXT,
    sector                      TEXT,
    direction                   TEXT,
    asset_type                  TEXT,
    open_date                   DATE,
    close_date                  DATE,
    disclosure_date             DATE,
    disclosure_lag_days         INTEGER,
    holding_days                INTEGER,
    is_open                     BOOLEAN,     -- TRUE => return is UNREALIZED
    return_basis                TEXT,        -- underlying_adjusted_close | underlying_proxy_for_option

    -- Metric 1: measures reporting lag only. NEVER used for ranking.
    disclosure_drift_pct        DOUBLE,

    -- Metric 2: the actual performance metric.
    position_return_pct         DOUBLE,      -- direction-adjusted
    spy_return_pct              DOUBLE,      -- identical window
    sector_etf                  TEXT,
    sector_etf_return_pct       DOUBLE,      -- identical window
    alpha_vs_spy                DOUBLE,      -- position_return - spy_return
    alpha_vs_sector_etf         DOUBLE,      -- position_return - sector_etf_return
    sector_benchmark_is_fallback BOOLEAN,

    est_amount_mid              DOUBLE,      -- ESTIMATE: matched slice
    est_open_amount_mid         DOUBLE,      -- ESTIMATE: full opening lot
    is_partial_lot              BOOLEAN,
    amount_range_text           TEXT,
    matched_event_id            TEXT,
    matched_event_days_before   INTEGER,
    price_data_complete         BOOLEAN
);

CREATE TABLE IF NOT EXISTS person_metrics (
    person_id                   TEXT PRIMARY KEY,
    full_name                   TEXT,
    relation                    TEXT,
    official_person_id          TEXT,
    chamber                     TEXT,
    party                       TEXT,
    state                       TEXT,

    trades_disclosed            INTEGER,   -- raw disclosure lines
    positions_analyzed          INTEGER,   -- after netting + price coverage
    positions_closed            INTEGER,
    positions_open              INTEGER,
    win_rate                    DOUBLE,
    win_rate_closed             DOUBLE,   -- excludes marked-to-market open positions
    mean_return_pct             DOUBLE,
    median_return_pct           DOUBLE,
    mean_alpha_vs_spy           DOUBLE,
    median_alpha_vs_spy         DOUBLE,
    mean_alpha_vs_sector_etf    DOUBLE,
    median_alpha_vs_sector_etf  DOUBLE,
    median_disclosure_lag_days  DOUBLE,
    median_disclosure_drift_pct DOUBLE,   -- lag metric; never used in ranking
    top_sector                  TEXT,
    sector_concentration_pct    DOUBLE,
    event_proximity_rate        DOUBLE,
    est_total_notional          DOUBLE,    -- ESTIMATE
    positions_dropped_no_prices INTEGER,  -- coverage, not hidden inside averages
    composite_score             DOUBLE,
    composite_score_normalized  DOUBLE,
    score_components_present    INTEGER,  -- how many of the 4 components were populated
    rank_composite              INTEGER,
    eligible_for_ranking        BOOLEAN
);

-- Free-form provenance/quality log written by every ingest + analyze run.
CREATE TABLE IF NOT EXISTS run_log (
    run_id      TEXT,
    stage       TEXT,
    ts          TIMESTAMP,
    level       TEXT,
    message     TEXT
);
