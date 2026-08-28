# How to Run This Tool (Step by Step)

These instructions assume you have never used a terminal before.
Follow them in order and you will get a ranked report of politician
stock-trading performance on your own computer.

---

## Step 1 — Install Python

You need Python 3.10 or newer.

**Mac:**
1. Open the App Store and search for **Xcode** — install it (it is free).
   This gives you basic developer tools.
2. Open **Terminal** (press Cmd + Space, type "Terminal", hit Enter).
3. Paste this line and press Enter:
   ```
   brew install python
   ```
   If it says "brew: command not found", install Homebrew first by pasting
   this line and pressing Enter:
   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Then run `brew install python` again.

**Windows:**
1. Go to https://www.python.org/downloads/
2. Click the big yellow "Download Python 3.x" button.
3. Run the installer. **Important:** check the box that says
   "Add Python to PATH" before clicking Install.

To confirm Python is installed, type this in Terminal (Mac) or
Command Prompt (Windows) and press Enter:
```
python3 --version
```
You should see something like `Python 3.12.4`. On Windows you may
need to type `python --version` instead (no "3").

---

## Step 2 — Download the Project

1. Open Terminal (Mac) or Command Prompt (Windows).
2. Paste these lines one at a time, pressing Enter after each:

   ```
   git clone https://github.com/GITUSER-SHAD/politician-trading-analysis.git
   cd politician-trading-analysis/politician_trading
   ```

   If `git` is not recognized:
   - **Mac:** It will prompt you to install developer tools — say yes,
     wait for it to finish, then try again.
   - **Windows:** Download Git from https://git-scm.com/download/win,
     install it (accept all defaults), close and reopen Command Prompt,
     then try again.

---

## Step 3 — Install the Required Libraries

Still in your terminal, paste this and press Enter:

```
pip install -r requirements.txt
```

On Mac you may need `pip3` instead of `pip`:
```
pip3 install -r requirements.txt
```

This downloads the handful of tools the project needs (pandas, duckdb,
yfinance, etc.). It may take a minute.

---

## Step 4 — Check Which Data Sources Work

Run the diagnostic command:

```
python3 -m ptrack doctor
```

(On Windows, use `python -m ptrack doctor` if `python3` does not work.)

This checks every data source and tells you which ones are reachable.
You should see several "OK" lines. The important ones are:

- **At least one trade source** (Stock Watcher, CapitolTrades, or
  QuiverQuant) needs to say OK.
- **At least one price source** (yfinance is the default) needs to
  say OK.

If a source says UNAVAILABLE, the tool automatically tries the next
one in line — you only have a problem if *all* trade sources or *all*
price sources fail.

---

## Step 5 — Run the Full Analysis

This one command does everything — downloads disclosures, fetches
stock prices, calculates returns, and writes the report:

```
python3 -m ptrack all
```

It will take several minutes (it is downloading thousands of stock
prices). When it finishes, it prints the file paths where your
results were saved.

---

## Step 6 — Find Your Results

After the run finishes, look in the **out/** folder. You will find:

| File | What It Is |
|------|-----------|
| `ranked_report.md` | The main report — a ranked list of officials by trading performance, with individual trade details. Open it in any text editor or drag it into your browser. |
| `person_rankings.csv` | Spreadsheet-friendly version of the rankings. Open it in Excel or Google Sheets. |
| `trade_details.csv` | Every individual trade with return, benchmark comparison, and disclosure lag. Open in Excel or Google Sheets. |
| `ptrack.duckdb` | The database file with all the raw data. You do not need to open this. |

The markdown report (ranked_report.md) is the one to read. It shows:
- Each politician's overall score and rank
- Their average returns vs. the market
- How often they beat the market
- How quickly they disclosed their trades
- Their top individual trades

---

## Optional: Add an Events File

If you want to check whether politicians traded near major public
events (like a defense bill or an energy regulation), create a file
called `events.csv` with these columns:

```
date,sector,headline,source_url
2023-03-10,defense,Pentagon announces new fighter jet contract,https://...
2024-01-15,energy,EPA proposes new emission rules,https://...
```

Then run:
```
python3 -m ptrack all --events events.csv
```

The report will flag any trades that happened within 10 trading days
before a matching event in the same sector.

---

## Optional: Use Your Own Data Files

If you already have trade disclosures or price data as CSV files
(maybe exported from another tool), you can feed them in directly:

```
python3 -m ptrack all --local-trades my_trades.csv --local-prices my_prices.csv
```

The trade CSV needs columns: `filer_name`, `ticker`, `asset_name`,
`tx_type`, `tx_date`, `amount`, `owner`.

The price CSV needs columns: `ticker`, `date`, `adj_close`.

---

## Troubleshooting

**"python3: command not found"**
→ Try `python` instead of `python3`. On Windows this is normal.

**"pip: command not found"**
→ Try `pip3` instead of `pip`, or `python3 -m pip install -r requirements.txt`.

**"No module named ptrack"**
→ Make sure you are inside the `politician_trading` folder. Run
`cd politician_trading` if you are in the top-level project folder.

**"Ingest produced no trades"**
→ Run `python3 -m ptrack doctor` to see which sources are reachable.
If everything says UNAVAILABLE, your internet connection or firewall
may be blocking the data sources.

**"yfinance: No data found"**
→ Yahoo Finance occasionally rate-limits requests. Wait a few minutes
and try again, or set an Alpha Vantage API key (free at
https://www.alphavantage.co/support/#api-key) by running:
```
export ALPHA_VANTAGE_KEY=your_key_here
python3 -m ptrack all
```
On Windows, use `set ALPHA_VANTAGE_KEY=your_key_here` instead of `export`.

---

## What the Numbers Mean (Quick Guide)

- **Alpha vs SPY**: How much better (or worse) the person's trades did
  compared to the overall stock market (the S&P 500). Positive = beat
  the market. Shown as a percentage.

- **Alpha vs Sector ETF**: Same idea, but compared to the specific
  industry they traded in. A defense-stock trader is compared to the
  defense index, not the whole market.

- **Win Rate**: What fraction of their closed trades beat the market.
  0.60 means 60% of trades beat the market.

- **Disclosure Drift**: How many days between when the trade happened
  and when it was publicly reported. The law requires reporting within
  45 days.

- **Event Proximity Rate**: What fraction of their trades were opened
  shortly before a relevant public event in the same sector. Higher is
  more noteworthy (but not proof of anything).

- **Composite Score**: A single number combining all the above.
  Higher = more noteworthy trading pattern. It is a summary statistic,
  not a guilt score.

- **~$15,001 (est.)**: Dollar amounts with a tilde (~) and "(est.)"
  are midpoint estimates. Politicians report ranges ("$1,001–$15,000"),
  not exact amounts, so every dollar figure is an educated guess within
  the reported range.
