"""Systematic Trading Application"""

import os
import json
import math
import logging
import logging.config
import logging.handlers
import pathlib
from collections import deque
from datetime import datetime, date, timedelta
from datetime import time as dt_time
from typing import Optional, override
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from systrade.feed import AlpacaLiveStockFeed
from systrade.broker import AlpacaBroker
from systrade.strategy import Strategy
from systrade.data import BarData, ExecutionReport
from systrade.engine import Engine

# instantiate logger
logger = logging.getLogger(__name__)

# --- LOGGER CONFIG ---
# Verbose dictionary-type config for custom logger.
# Config file found in: /config/logger/config.json
# (source: youtube.com/mCoding)
def setup_logging():
    config_file = pathlib.Path("config/logger/config.json")
    with open(config_file) as f_in:
        config = json.load(f_in)
    logging.config.dictConfig(config)

# ANSI escape codes for color-coded logs
red       = "\033[31m"
green     = "\033[32m"
yellow    = "\033[33m"
blue      = "\033[34m"
hl_red    = "\033[41m"
hl_green  = "\033[42m"
hl_yellow = "\033[43m"
hl_blue   = "\033[44m"
reset     = "\033[0m"


# ===============================================
#        ---- Buy and Hold Strategy ----
# ===============================================
# It's in the name. _It will not sell_.
# Could also be called the diamond hands strategy
class LongStrategy(Strategy):
    """
    Buy and hold. "Go long" strategy
    """
    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.history: list[float] = []
        self.trading_records: list[dict] = []
        logger.info(f"Long Strategy initialized for {self.symbol}")

    @override
    def on_start(self) -> None:
        """Subscribe to the symbol on strategy start"""
        self.subscribe(self.symbol)

    # this will just buy when it gets its first price
    @override
    def on_data(self, data: BarData) -> None:
        """Processes incoming 1-minute bars live."""
        self.current_time = data.as_of

        if self.symbol in data.symbols():
            bar = data[self.symbol]
            price = bar.close

            logger.info(f"Processing bar for {self.symbol} at {data.as_of}: Close={price}")

            # 30% buffer for daytrading
            #-------------------------
            # If you are marked by alpaca as a pattern daytrader,
            #+they will nerf your buying power so this is added
            #+to skirt that.
            qty = math.floor((self.portfolio.buying_power() * 0.70) / price)
            if qty > 0:
                self.post_market_order(self.symbol, quantity=qty)
                logger.info(f"{hl_green}Buy signal! Posting market order for {qty} shares of {self.symbol}{reset}")
                self.order_pending = True
                self._record_trade("BUY", qty, price)
            else:
                logger.warning(f"{yellow}Quantity calculated as 0. Buying Power: {self.portfolio.buying_power()}{reset}")

            # add price to tracking log
            self.history.append(price)

    @override
    def on_execution(self, report: ExecutionReport) -> None:
        """Called on an order update"""
        log_report = report.__dict__.copy()
        log_report['fill_timestamp_iso'] = report.fill_timestamp.isoformat()
        logger.info(f"Notified of execution: {log_report}")
        self.trading_records.append(log_report)

    def _record_trade(self, side, qty, price):
        """Helper to save a simple record locally."""
        record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': self.symbol,
            'side': side,
            'quantity': qty,
            'price': price
        }
        with open("trading_results.json", "a") as f:
            f.write(json.dumps(record) + "\n")


# =============================================
#    -------  Momentum strategy -----------
# =============================================
# This is the strategy that's most developed in
#+the repo. You can edit this one for ease, or
#+anything else to your liking. Just make sure
#+it runs.
class MomentumStrategy(Strategy):
    """
    Momentum strategy with long/short support.
    """
    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.history: list[float] = []
        self.trading_records: list[dict] = []
        logger.info(f"Momentum Strategy initialized for {self.symbol}")

    @override
    def on_start(self) -> None:
        """Subscribe to the symbol on strategy start"""
        self.subscribe(self.symbol)

    @override
    def on_data(self, data: BarData) -> None:
        """Processes incoming 1-minute bars live."""
        self.current_time = data.as_of

        if self.symbol in data.symbols():
            bar = data[self.symbol]
            price = bar.close

            logger.info(f"Processing bar for {self.symbol} at {data.as_of}: Close={price}")

            if len(self.history) >= 2:
                buy_signal = price > self.history[-1] > self.history[-2]
                sell_signal = price < self.history[-1] < self.history[-2]

                holding = self.portfolio.is_invested_in(self.symbol)

                # this block will open a long position
                if buy_signal and not holding:
                    logger.debug(f"{blue}Buying Power={self.portfolio.buying_power()}, Invested={self.portfolio.is_invested_in(self.symbol)}{reset}")
                    qty = math.floor((self.portfolio.buying_power() * 0.70) / price)
                    if qty > 0:
                        self.post_market_order(self.symbol, quantity=qty)
                        logger.info(f"{hl_green}Buy signal! Posting market order for {qty} shares of {self.symbol}{reset}")
                        self.order_pending = True
                        self._record_trade("BUY", qty, price)
                    else:
                        logger.warning(f"{yellow}Quantity calculated as 0. Buying Power: {self.portfolio.buying_power()}{reset}")

                # this block will open a short position
                elif sell_signal and not holding:
                    logger.debug(f"{blue}Buying Power={self.portfolio.buying_power()}, Invested={self.portfolio.is_invested_in(self.symbol)}{reset}")
                    qty = math.floor((self.portfolio.buying_power() * 0.70) / price)
                    if qty > 0:
                        self.post_market_order(self.symbol, quantity=-qty)
                        logger.info(f"{hl_red}Sell signal! Posting market order for {qty} shares of {self.symbol}{reset}")
                        self.order_pending = True
                        self._record_trade("SELL", qty, price)
                    else:
                        logger.warning(f"{yellow}Quantity calculated as 0. Buying Power: {self.portfolio.buying_power()}{reset}")

                # this block will close a short position
                elif buy_signal and holding:
                    logger.debug(f"{blue}Buying Power={self.portfolio.buying_power()}, Invested={self.portfolio.is_invested_in(self.symbol)}{reset}")
                    pos = self.portfolio.position(self.symbol)
                    logger.info(f"{hl_yellow}Buy signal! Closing short position of {pos.qty} shares of {self.symbol}{reset}")
                    self.post_market_order(self.symbol, quantity=pos.qty)
                    self.order_pending = True
                    self._record_trade("BUY", pos.qty, price)

                # this block will close a long position
                elif sell_signal and holding:
                    logger.debug(f"{blue}Buying Power={self.portfolio.buying_power()}, Invested={self.portfolio.is_invested_in(self.symbol)}{reset}")
                    pos = self.portfolio.position(self.symbol)
                    logger.info(f"{hl_blue}Sell signal! Closing long position of {pos.qty} shares of {self.symbol}{reset}")
                    self.post_market_order(self.symbol, quantity=-pos.qty)
                    self.order_pending = True
                    self._record_trade("SELL", pos.qty, price)

            # add price to tracking log
            self.history.append(price)

    @override
    def on_execution(self, report: ExecutionReport) -> None:
        """Called on an order update"""
        log_report = report.__dict__.copy()
        log_report['fill_timestamp_iso'] = report.fill_timestamp.isoformat()
        logger.info(f"Notified of execution: {log_report}")
        self.trading_records.append(log_report)

    def _record_trade(self, side, qty, price):
        """Helper to save a simple record locally."""
        record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': self.symbol,
            'side': side,
            'quantity': qty,
            'price': price
        }
        with open("trading_results.json", "a") as f:
            f.write(json.dumps(record) + "\n")


# =============================================
#  --- Event Driven Strategy ---
# =============================================
# Two-sleeve long-only event-driven equity system.
#
#  Sleeve A  Pre-Earnings Momentum
#            Enters at 10:15 AM for stocks reporting in 1–3 trading days.
#            Exits at 15:55 the trading day before earnings.
#
#  Sleeve B  Post-Earnings Drift
#            Enters at 10:30 AM the morning after an earnings report when the
#            opening gap is +2%–+8% and above VWAP.
#            Exits 2 trading days later.
#
#  Risk      ATR(14)+Morning-Low stop loss, max 4 positions,
#            50% gross exposure cap, 4%/5% drawdown kill switches.
class EventDrivenStrategy(Strategy):

    # ── Time constants (all comparisons done in America/New_York) ─────────
    _EST             = ZoneInfo("America/New_York")
    _MORNING_START   = dt_time(9, 30)
    _MORNING_LOW_END = dt_time(10, 15)   # morning-low window closes here
    _SLEEVE_A_TIME   = dt_time(10, 15)   # sleeve A evaluated at exactly this bar
    _SLEEVE_B_TIME   = dt_time(10, 30)   # sleeve B evaluated at exactly this bar
    _SLEEVE_A_EXIT   = dt_time(15, 55)   # sleeve A sells at or after this time

    # ── Strategy parameters ───────────────────────────────────────────────
    _SMA_PERIOD        = 20
    _ATR_PERIOD        = 14
    _ATR_STOP_MULT     = 1.5    # stop = entry - 1.5 × ATR(14)
    _POSITION_SIZE_PCT = 0.15   # 15% of portfolio equity per trade
    _MAX_POSITIONS     = 4
    _GROSS_LIMIT_NORM  = 0.50   # 50% gross exposure cap (normal)
    _GROSS_LIMIT_KL1   = 0.25   # 25% gross exposure cap (after kill level 1)
    _KL1_THRESHOLD     = 0.04   # 4% drawdown from start → level-1 kill switch
    _KL2_THRESHOLD     = 0.05   # 5% drawdown from start → level-2 kill switch

    # ─────────────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        super().__init__()

        # ── Static datasets (loaded once at startup) ──────────────────────
        self._earnings:  pd.DataFrame     = self._load_earnings()
        self._estimates: dict[str, float] = self._load_estimates()
        self._iv_map:    dict[str, float] = self._load_iv_map()

        # ── Per-symbol rolling daily history ──────────────────────────────
        # Populated via day-rollover; deques are capped at the lookback period.
        self._daily_closes: dict[str, deque] = {}  # last SMA_PERIOD daily closes
        self._daily_trs:    dict[str, deque] = {}  # last ATR_PERIOD true ranges

        # ── Per-symbol session reference values ───────────────────────────
        self._prev_close:    dict[str, float] = {}  # previous session's close
        self._session_open:  dict[str, float] = {}  # today's first bar open (for gap)
        self._session_high:  dict[str, float] = {}  # today's running high (for TR)
        self._session_low:   dict[str, float] = {}  # today's running low  (for TR)
        self._last_price:    dict[str, float] = {}  # most recent close
        self._last_bar_date: dict[str, date]  = {}  # date of last processed bar

        # ── Intraday accumulators (zeroed on day rollover) ─────────────────
        self._cum_pv:      dict[str, float] = {}  # Σ (typical_price × volume)
        self._cum_vol:     dict[str, float] = {}  # Σ volume
        self._morning_low: dict[str, float] = {}  # min(low) from 9:30 to 10:15

        # ── Position tracking ─────────────────────────────────────────────
        # _positions:       confirmed open positions
        #   schema: {sleeve, qty, entry_price, entry_time, stop_price, exit_date}
        # _pending_entries: buy orders submitted but not yet filled
        #   schema: {sleeve, qty, estimated_price, exit_date,
        #            atr_at_entry, morning_low_at_entry}
        # _pending_exits:   set of symbols with an open sell order awaiting fill
        self._positions:       dict[str, dict] = {}
        self._pending_entries: dict[str, dict] = {}
        self._pending_exits:   set[str]        = set()

        # ── Daily flags ───────────────────────────────────────────────────
        self._sleeve_a_done: bool          = False
        self._sleeve_b_done: bool          = False
        self._current_date:  Optional[date] = None

        # ── Kill-switch state ─────────────────────────────────────────────
        # _starting_equity is set once in on_start and never updated.
        self._starting_equity: float = 0.0
        self._kill_level1:     bool  = False  # tighten exposure limit
        self._kill_level2:     bool  = False  # liquidate all + halt permanently

        logger.info(
            f"EventDrivenStrategy initialized — "
            f"{len(self._earnings)} earnings events, "
            f"{len(self._estimates)} scored symbols, "
            f"{len(self._iv_map)} IV data points."
        )

    # ══════════════════════════════════════════════════════════════════════
    # CSV loaders
    # ══════════════════════════════════════════════════════════════════════

    def _load_earnings(self) -> pd.DataFrame:
        """
        Load earnings_calendar.csv.
        Required columns: symbol, report_date, time  ('AMC' or 'BMO')
        """
        path = pathlib.Path("earnings_calendar.csv")
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path.resolve()}. "
                "Run build_datasets.py first."
            )
        df = pd.read_csv(path)
        missing = {"symbol", "report_date", "time"} - set(df.columns)
        if missing:
            raise ValueError(f"earnings_calendar.csv missing columns: {missing}")
        df["symbol"]      = df["symbol"].str.strip().str.upper()
        df["time"]        = df["time"].str.strip().str.upper()
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        logger.info(f"Loaded earnings_calendar.csv: {len(df)} events.")
        return df

    def _load_estimates(self) -> dict[str, float]:
        """
        Load estimates.csv.
        Required columns: symbol, event_score_percentile  (decimal [0, 1] or [0, 100])
        """
        path = pathlib.Path("estimates.csv")
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path.resolve()}. "
                "Provide estimates.csv with columns: symbol, event_score_percentile."
            )
        df = pd.read_csv(path)
        missing = {"symbol", "event_score_percentile"} - set(df.columns)
        if missing:
            raise ValueError(f"estimates.csv missing columns: {missing}")
        df["symbol"]              = df["symbol"].str.strip().str.upper()
        df["event_score_percentile"] = df["event_score_percentile"].astype(float)
        # Normalise to [0, 1] if data was provided as percentage values
        if df["event_score_percentile"].max() > 1.5:
            df["event_score_percentile"] /= 100.0
            logger.info("event_score_percentile normalised from [0, 100] → [0, 1].")
        estimates = dict(zip(df["symbol"], df["event_score_percentile"]))
        logger.info(f"Loaded estimates.csv: {len(estimates)} symbols.")
        return estimates

    def _load_iv_map(self) -> dict[str, float]:
        """
        Load options_data.csv.
        Required columns: symbol, implied_move_pct  (decimal, e.g. 0.05 = 5%)
        """
        path = pathlib.Path("options_data.csv")
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path.resolve()}. "
                "Run build_datasets.py first."
            )
        df = pd.read_csv(path)
        missing = {"symbol", "implied_move_pct"} - set(df.columns)
        if missing:
            raise ValueError(f"options_data.csv missing columns: {missing}")
        df["symbol"] = df["symbol"].str.strip().str.upper()
        iv_map = dict(zip(df["symbol"], df["implied_move_pct"].astype(float)))
        logger.info(f"Loaded options_data.csv: {len(iv_map)} symbols.")
        return iv_map

    # ══════════════════════════════════════════════════════════════════════
    # Strategy hooks
    # ══════════════════════════════════════════════════════════════════════

    @override
    def on_start(self) -> None:
        symbols = self._earnings["symbol"].unique().tolist()
        for sym in symbols:
            self.subscribe(sym)

        # Record starting equity once — used as the baseline for all
        # drawdown calculations throughout the competition run.
        try:
            self._starting_equity = self.portfolio.value()
        except Exception as e:
            logger.error(f"{hl_red}Could not fetch starting equity: {e}{reset}")

        logger.info(
            f"{hl_green}EventDrivenStrategy started.  "
            f"Starting equity: ${self._starting_equity:,.2f}  |  "
            f"Watching {len(symbols)} symbols: {symbols}{reset}"
        )

    @override
    def on_data(self, data: BarData) -> None:
        self.current_time = data.as_of

        # ── Timezone normalisation ─────────────────────────────────────────
        as_of = data.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=ZoneInfo("UTC"))
        now_est:  datetime = as_of.astimezone(self._EST)
        today:    date     = now_est.date()
        bar_time: dt_time  = now_est.timetz().replace(tzinfo=None)

        # ── Permanent kill-switch gate (level 2) ───────────────────────────
        if self._kill_level2:
            return

        # ── Daily flag reset ───────────────────────────────────────────────
        if today != self._current_date:
            self._sleeve_a_done = False
            self._sleeve_b_done = False
            self._current_date  = today
            logger.debug(f"New trading day: {today}")

        # ── Per-symbol state updates ───────────────────────────────────────
        for symbol, bar in data.bars():
            self._update_symbol(symbol, bar, today, bar_time)

        # ── Kill-switch evaluation (one portfolio API call per bar) ────────
        self._check_kill_switches()
        if self._kill_level2:
            return

        # ── Continuous exit processing ─────────────────────────────────────
        # Order: stop-loss check (priority 1) → sleeve-scheduled exits
        self._process_exits(today, bar_time)

        # ── Sleeve A entries: fires once at exactly 10:15 AM ──────────────
        if bar_time == self._SLEEVE_A_TIME and not self._sleeve_a_done:
            self._sleeve_a_done = True
            self._run_sleeve_a(today, data)

        # ── Sleeve B entries: fires once at exactly 10:30 AM ──────────────
        if bar_time == self._SLEEVE_B_TIME and not self._sleeve_b_done:
            self._sleeve_b_done = True
            self._run_sleeve_b(today, data)

    @override
    def on_execution(self, report: ExecutionReport) -> None:
        symbol    = report.order.symbol
        order_qty = report.order.quantity
        fill_px   = report.last_price
        fill_qty  = report.last_quantity

        log_report = report.__dict__.copy()
        log_report["fill_timestamp_iso"] = report.fill_timestamp.isoformat()
        logger.debug(f"Execution report: {log_report}")

        if order_qty > 0:
            # ── Buy fill: move from pending_entries → confirmed positions ──
            pending = self._pending_entries.pop(symbol, None)
            if pending is None:
                logger.warning(
                    f"{yellow}Buy fill for {symbol} with no matching pending entry.{reset}"
                )
                return

            # Recompute stop with the actual fill price
            atr           = pending.get("atr_at_entry")
            morning_low_e = pending.get("morning_low_at_entry", fill_px)
            stop_price    = self._compute_stop(fill_px, atr, morning_low_e)
            stop_basis    = (
                "ATR" if (atr is not None and fill_px - self._ATR_STOP_MULT * atr >= morning_low_e)
                else "morning-low"
            )

            self._positions[symbol] = {
                "sleeve":      pending["sleeve"],
                "qty":         int(fill_qty),
                "entry_price": fill_px,
                "entry_time":  report.fill_timestamp,
                "stop_price":  stop_price,
                "exit_date":   pending.get("exit_date"),
            }
            logger.info(
                f"{hl_green}BUY FILLED [{pending['sleeve']}]: {symbol}  "
                f"qty={int(fill_qty)}  fill=${fill_px:.2f}  "
                f"stop=${stop_price:.2f} ({stop_basis}-based){reset}"
            )

        elif order_qty < 0:
            # ── Sell fill: clean up position ───────────────────────────────
            pos = self._positions.pop(symbol, None)
            self._pending_exits.discard(symbol)
            if pos is not None:
                pnl_pct = (fill_px - pos["entry_price"]) / pos["entry_price"]
                color   = hl_green if pnl_pct >= 0 else hl_red
                logger.info(
                    f"{color}SELL FILLED [{pos['sleeve']}]: {symbol}  "
                    f"qty={int(abs(fill_qty))}  fill=${fill_px:.2f}  "
                    f"entry=${pos['entry_price']:.2f}  pnl={pnl_pct:+.2%}{reset}"
                )

        self._record_trade(
            side="BUY" if order_qty > 0 else "SELL",
            symbol=symbol,
            qty=abs(fill_qty),
            price=fill_px,
            source="execution_report",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Per-symbol state management
    # ══════════════════════════════════════════════════════════════════════

    def _update_symbol(
        self, symbol: str, bar, today: date, bar_time: dt_time
    ) -> None:
        """
        Called for every (symbol, bar) pair in each on_data packet.
        Handles first-encounter initialisation, day rollover, and all
        intraday accumulator updates (VWAP, session H/L, morning low).
        """
        # ── First time we see this symbol ─────────────────────────────────
        if symbol not in self._last_bar_date:
            self._daily_closes[symbol] = deque(maxlen=self._SMA_PERIOD)
            self._daily_trs[symbol]    = deque(maxlen=self._ATR_PERIOD)
            self._reset_intraday(symbol, bar)

        # ── Day rollover: new calendar date detected for this symbol ───────
        elif self._last_bar_date[symbol] < today:
            self._roll_day(symbol, bar)

        # ── VWAP accumulator: typical price (HLC/3) × volume ──────────────
        if not (np.isnan(bar.high) or np.isnan(bar.low) or np.isnan(bar.close)):
            tp  = (bar.high + bar.low + bar.close) / 3.0
            vol = bar.volume if not np.isnan(bar.volume) else 0.0
            self._cum_pv[symbol]  += tp  * vol
            self._cum_vol[symbol] += vol

        # ── Session high / low ─────────────────────────────────────────────
        if not np.isnan(bar.high):
            self._session_high[symbol] = max(self._session_high[symbol], bar.high)
        if not np.isnan(bar.low):
            self._session_low[symbol]  = min(self._session_low[symbol],  bar.low)

        # ── Morning low: track lowest bar.low from 9:30 AM to 10:15 AM ────
        low = bar.low if not np.isnan(bar.low) else bar.close
        if self._MORNING_START <= bar_time <= self._MORNING_LOW_END:
            self._morning_low[symbol] = min(self._morning_low[symbol], low)

        self._last_price[symbol]    = bar.close
        self._last_bar_date[symbol] = today

    def _reset_intraday(self, symbol: str, bar) -> None:
        """Zero all intraday accumulators. Called on first encounter and rollover."""
        open_px = bar.open if not np.isnan(bar.open) else bar.close
        self._cum_pv[symbol]       = 0.0
        self._cum_vol[symbol]      = 0.0
        self._morning_low[symbol]  = float("inf")
        self._session_high[symbol] = bar.high if not np.isnan(bar.high) else bar.close
        self._session_low[symbol]  = bar.low  if not np.isnan(bar.low)  else bar.close
        self._session_open[symbol] = open_px

    def _roll_day(self, symbol: str, bar) -> None:
        """
        Called when the first bar of a new trading day arrives for a symbol.

        1. Appends the closed session's close to the SMA(20) buffer.
        2. Computes the True Range for the closed session and appends it to
           the ATR(14) buffer (requires at least one prior session close).
        3. Promotes the closed session's values to the 'prev_*' references.
        4. Resets all intraday accumulators for the new session.
        """
        closed_close = self._last_price[symbol]
        closed_high  = self._session_high[symbol]
        closed_low   = self._session_low[symbol]

        # Append to SMA buffer
        self._daily_closes[symbol].append(closed_close)

        # True Range requires the previous session's close
        prior_close = self._prev_close.get(symbol)
        if prior_close is not None:
            tr = max(
                closed_high - closed_low,
                abs(closed_high - prior_close),
                abs(closed_low  - prior_close),
            )
            self._daily_trs[symbol].append(tr)
            atr_display = f"{self._atr14(symbol):.4f}" if self._atr14(symbol) else "building…"
            logger.debug(
                f"[ATR] {symbol}  "
                f"TR={tr:.4f}  ATR14={atr_display}  "
                f"SMA20={'ready' if len(self._daily_closes[symbol]) >= self._SMA_PERIOD else 'building…'}"
            )

        # Promote to prev references
        self._prev_close[symbol] = closed_close

        # Reset intraday for the new session
        self._reset_intraday(symbol, bar)
        logger.debug(f"Day rolled → {symbol}  prev_close={closed_close:.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # Indicator helpers
    # ══════════════════════════════════════════════════════════════════════

    def _sma20(self, symbol: str) -> Optional[float]:
        closes = self._daily_closes.get(symbol)
        if closes is None or len(closes) < self._SMA_PERIOD:
            return None
        return float(np.mean(closes))

    def _atr14(self, symbol: str) -> Optional[float]:
        trs = self._daily_trs.get(symbol)
        if trs is None or len(trs) < self._ATR_PERIOD:
            return None
        return float(np.mean(trs))

    def _vwap(self, symbol: str) -> Optional[float]:
        vol = self._cum_vol.get(symbol, 0.0)
        if vol == 0.0:
            return None
        return self._cum_pv[symbol] / vol

    # ══════════════════════════════════════════════════════════════════════
    # Entry logic
    # ══════════════════════════════════════════════════════════════════════

    def _run_sleeve_a(self, today: date, data: BarData) -> None:
        """
        Sleeve A — Pre-Earnings Momentum (10:15 AM).

        For each symbol with earnings 1-3 trading days out:
          - event_score_percentile >= 0.90
          - price > SMA(20)
          - price > live VWAP
        Buy 15% of portfolio equity. Exit at 15:55 the day before earnings.
        """
        logger.info(f"{blue}[SLEEVE A] 10:15 AM evaluation...{reset}")
        evaluated = 0

        for _, row in self._earnings.iterrows():
            symbol      = row["symbol"]
            report_date = row["report_date"]

            days_away = int(np.busday_count(today, report_date))
            if not (1 <= days_away <= 3):
                continue
            evaluated += 1

            if not self._is_available(symbol):
                logger.debug(f"[SLEEVE A] {symbol} already in portfolio. Skip.")
                continue

            bar   = data.get(symbol)
            price = bar.close if bar is not None else self._last_price.get(symbol)
            if price is None:
                logger.warning(f"[SLEEVE A] No price for {symbol}. Skip.")
                continue

            # ── event_score_percentile >= 0.90 ──────────────────────────────
            score = self._estimates.get(symbol)
            if score is None or score < 0.90:
                logger.debug(
                    f"[SLEEVE A] {symbol}  score={score if score is not None else 'N/A'} "
                    f"< 0.90. Skip."
                )
                continue

            # ── price > SMA(20) ─────────────────────────────────────────────
            sma = self._sma20(symbol)
            if sma is None:
                logger.debug(
                    f"[SLEEVE A] {symbol}  SMA20 not ready "
                    f"({len(self._daily_closes.get(symbol, []))} days). Skip."
                )
                continue
            if price <= sma:
                logger.debug(
                    f"[SLEEVE A] {symbol}  price={price:.2f} ≤ SMA20={sma:.2f}. Skip."
                )
                continue

            # ── price > VWAP ────────────────────────────────────────────────
            vwap = self._vwap(symbol)
            if vwap is None:
                logger.debug(f"[SLEEVE A] {symbol}  VWAP not ready. Skip.")
                continue
            if price <= vwap:
                logger.debug(
                    f"[SLEEVE A] {symbol}  price={price:.2f} ≤ VWAP={vwap:.2f}. Skip."
                )
                continue

            # ── Portfolio limits ────────────────────────────────────────────
            if not self._can_enter(symbol):
                continue

            # ── Sizing, stop, exit date ─────────────────────────────────────
            qty = self._compute_qty(price)
            if qty <= 0:
                logger.warning(
                    f"{yellow}[SLEEVE A] {symbol}  qty=0 at price={price:.2f}. Skip.{reset}"
                )
                continue

            atr         = self._atr14(symbol)
            morning_low = self._morning_low.get(symbol, float("inf"))
            stop_price  = self._compute_stop(price, atr, morning_low)
            # Exit the trading day immediately before the earnings date
            exit_date   = self._prev_trading_day(report_date)

            # ── Submit order ────────────────────────────────────────────────
            self.post_market_order(symbol, quantity=qty)
            self._pending_entries[symbol] = {
                "sleeve":               "A",
                "qty":                  qty,
                "estimated_price":      price,
                "exit_date":            exit_date,
                "atr_at_entry":         atr,
                "morning_low_at_entry": morning_low if morning_low != float("inf") else price,
            }
            logger.info(
                f"{hl_green}[SLEEVE A] ENTRY ▶ {symbol}  "
                f"price=${price:.2f}  SMA20=${sma:.2f}  VWAP=${vwap:.2f}  "
                f"score={score:.2f}  days_to_earnings={days_away}  "
                f"exit={exit_date}  stop=${stop_price:.2f}  qty={qty}{reset}"
            )
            self._record_trade(
                "BUY", symbol, qty, price,
                sleeve="A", stop=round(stop_price, 4),
                exit_date=str(exit_date), score=round(score, 4),
            )

        logger.info(f"[SLEEVE A] Done. {evaluated} candidates evaluated.")

    def _run_sleeve_b(self, today: date, data: BarData) -> None:
        """
        Sleeve B — Post-Earnings Drift (10:30 AM).

        For each symbol that reported earnings AMC yesterday or BMO today:
          - event_score_percentile >= 0.50
          - Opening gap in [+2%, +8%]
          - current price > live VWAP
        Buy 15% of portfolio equity. Exit 2 trading days after entry.
        """
        logger.info(f"{blue}[SLEEVE B] 10:30 AM evaluation...{reset}")
        yesterday  = self._prev_trading_day(today)
        evaluated  = 0

        for _, row in self._earnings.iterrows():
            symbol      = row["symbol"]
            report_date = row["report_date"]
            report_time = row["time"]

            is_amc_yesterday = (report_date == yesterday and report_time == "AMC")
            is_bmo_today     = (report_date == today     and report_time == "BMO")
            if not (is_amc_yesterday or is_bmo_today):
                continue
            evaluated += 1

            if not self._is_available(symbol):
                logger.debug(f"[SLEEVE B] {symbol} already in portfolio. Skip.")
                continue

            bar   = data.get(symbol)
            price = bar.close if bar is not None else self._last_price.get(symbol)
            if price is None:
                logger.warning(f"[SLEEVE B] No price for {symbol}. Skip.")
                continue

            # ── event_score_percentile >= 0.50 ──────────────────────────────
            score = self._estimates.get(symbol)
            if score is None or score < 0.50:
                logger.debug(
                    f"[SLEEVE B] {symbol}  score={score if score is not None else 'N/A'} "
                    f"< 0.50. Skip."
                )
                continue

            # ── Opening gap: (session_open − prev_close) / prev_close ───────
            # gap must be strictly between +2% and +8%
            prev_close   = self._prev_close.get(symbol)
            session_open = self._session_open.get(symbol)
            if prev_close is None or prev_close <= 0 or session_open is None:
                logger.warning(
                    f"{yellow}[SLEEVE B] {symbol}  missing prev_close or session_open "
                    f"(prev_close={prev_close}, session_open={session_open}). Skip.{reset}"
                )
                continue
            gap = (session_open - prev_close) / prev_close
            if not (0.02 <= gap <= 0.08):
                logger.debug(
                    f"[SLEEVE B] {symbol}  gap={gap:+.2%} outside [+2%, +8%]. Skip."
                )
                continue

            # ── current price > VWAP ────────────────────────────────────────
            vwap = self._vwap(symbol)
            if vwap is None:
                logger.debug(f"[SLEEVE B] {symbol}  VWAP not ready. Skip.")
                continue
            if price <= vwap:
                logger.debug(
                    f"[SLEEVE B] {symbol}  price={price:.2f} ≤ VWAP={vwap:.2f}. Skip."
                )
                continue

            # ── Portfolio limits ────────────────────────────────────────────
            if not self._can_enter(symbol):
                continue

            # ── Sizing and stop ─────────────────────────────────────────────
            qty = self._compute_qty(price)
            if qty <= 0:
                logger.warning(
                    f"{yellow}[SLEEVE B] {symbol}  qty=0 at price={price:.2f}. Skip.{reset}"
                )
                continue

            atr         = self._atr14(symbol)
            morning_low = self._morning_low.get(symbol, float("inf"))
            stop_price  = self._compute_stop(price, atr, morning_low)
            implied_mv  = self._iv_map.get(symbol, "N/A")

            # ── Submit order ────────────────────────────────────────────────
            self.post_market_order(symbol, quantity=qty)
            self._pending_entries[symbol] = {
                "sleeve":               "B",
                "qty":                  qty,
                "estimated_price":      price,
                "exit_date":            None,  # time-based: 2 trading days
                "atr_at_entry":         atr,
                "morning_low_at_entry": morning_low if morning_low != float("inf") else price,
            }
            logger.info(
                f"{hl_green}[SLEEVE B] ENTRY ▶ {symbol}  "
                f"price=${price:.2f}  gap={gap:+.2%}  VWAP=${vwap:.2f}  "
                f"score={score:.2f}  implied_move={implied_mv}  "
                f"stop=${stop_price:.2f}  qty={qty}{reset}"
            )
            self._record_trade(
                "BUY", symbol, qty, price,
                sleeve="B", stop=round(stop_price, 4),
                gap=round(gap, 6), score=round(score, 4),
                implied_move=implied_mv,
            )

        logger.info(f"[SLEEVE B] Done. {evaluated} candidates evaluated.")

    def _is_available(self, symbol: str) -> bool:
        """True if symbol has no open, pending, or exiting position."""
        return (
            symbol not in self._positions
            and symbol not in self._pending_entries
            and symbol not in self._pending_exits
        )

    def _can_enter(self, symbol: str) -> bool:
        """
        Returns True only if both portfolio limits are satisfied:
          1. Fewer than MAX_POSITIONS confirmed + pending positions.
          2. Adding a new 15%-sized position would not exceed the gross limit.
        """
        total_open = len(self._positions) + len(self._pending_entries)
        if total_open >= self._MAX_POSITIONS:
            logger.info(
                f"{yellow}Position limit ({self._MAX_POSITIONS}) reached "
                f"({total_open} open). Skipping {symbol}.{reset}"
            )
            return False

        limit       = self._exposure_limit()
        current_exp = self._gross_exposure_pct()
        if current_exp + self._POSITION_SIZE_PCT > limit:
            logger.info(
                f"{yellow}Gross exposure {current_exp:.1%} + {self._POSITION_SIZE_PCT:.0%} "
                f"would exceed {limit:.0%} limit. Skipping {symbol}.{reset}"
            )
            return False

        return True

    def _compute_qty(self, price: float) -> int:
        """Target 15% of portfolio equity; round down to whole shares."""
        try:
            equity = self.portfolio.value()
        except Exception:
            return 0
        if equity <= 0 or price <= 0:
            return 0
        return math.floor((equity * self._POSITION_SIZE_PCT) / price)

    def _compute_stop(
        self,
        entry_price: float,
        atr: Optional[float],
        morning_low: float,
    ) -> float:
        """
        Returns the tighter (higher) of:
          a) entry_price - 1.5 × ATR(14)
          b) the morning low (9:30–10:15 AM)

        If neither is available, falls back to a 5% hard stop.
        """
        candidates: list[float] = []
        if atr is not None:
            candidates.append(entry_price - self._ATR_STOP_MULT * atr)
        if morning_low != float("inf") and morning_low < entry_price:
            candidates.append(morning_low)
        # max() picks the higher (tighter) stop
        return max(candidates) if candidates else entry_price * 0.95

    # ══════════════════════════════════════════════════════════════════════
    # Exit and risk management
    # ══════════════════════════════════════════════════════════════════════

    def _process_exits(self, today: date, bar_time: dt_time) -> None:
        """
        Runs on every bar. Evaluates all confirmed open positions in order:
          1. Stop-loss (highest priority — checked first, exits immediately)
          2. Sleeve A scheduled exit (15:55 on exit_date)
          3. Sleeve B time exit (2 trading days after entry)
        """
        for symbol in list(self._positions.keys()):
            if symbol in self._pending_exits:
                continue

            pos   = self._positions[symbol]
            price = self._last_price.get(symbol)
            if price is None:
                continue

            # ── 1. Stop loss ───────────────────────────────────────────────
            if price <= pos["stop_price"]:
                pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
                logger.warning(
                    f"{hl_red}STOP LOSS [{pos['sleeve']}]: {symbol}  "
                    f"price=${price:.2f} ≤ stop=${pos['stop_price']:.2f}  "
                    f"pnl={pnl_pct:+.2%}{reset}"
                )
                self._exit_position(symbol, price, "STOP_LOSS")
                continue

            # ── 2. Sleeve A: exit at 15:55 on exit_date ───────────────────
            if pos["sleeve"] == "A":
                exit_date = pos.get("exit_date")
                if exit_date and today == exit_date and bar_time >= self._SLEEVE_A_EXIT:
                    logger.info(
                        f"{hl_yellow}[SLEEVE A] PRE-EARNINGS EXIT: {symbol}  "
                        f"price=${price:.2f}  exit_date={exit_date}{reset}"
                    )
                    self._exit_position(symbol, price, "SLEEVE_A_PREEARNINGS")

            # ── 3. Sleeve B: exit after 2 trading days ─────────────────────
            elif pos["sleeve"] == "B":
                entry_date   = pos["entry_time"].date()
                trading_days = int(np.busday_count(entry_date, today))
                if trading_days >= 2:
                    logger.info(
                        f"{hl_blue}[SLEEVE B] DRIFT EXIT: {symbol}  "
                        f"price=${price:.2f}  "
                        f"{trading_days} trading days since entry ({entry_date}){reset}"
                    )
                    self._exit_position(symbol, price, "SLEEVE_B_DRIFT")

    def _exit_position(self, symbol: str, price: float, reason: str) -> None:
        """Submit a full market sell for the position. Marks as pending exit."""
        pos = self._positions.get(symbol)
        if pos is None:
            return
        qty = pos["qty"]
        self.post_market_order(symbol, quantity=-qty)
        self._pending_exits.add(symbol)
        self._record_trade("SELL", symbol, qty, price, reason=reason)

    def _check_kill_switches(self) -> None:
        """
        Compares current portfolio equity against _starting_equity.

        Level 1 — 4% drawdown:
          Tightens the gross exposure limit from 50% to 25%.
          No forced liquidation; existing positions are held.

        Level 2 — 5% drawdown:
          Immediately liquidates ALL open positions.
          Permanently halts all future entries (on_data returns early).
          Logs a CRITICAL alert.

        Both switches are one-way: once activated they are never reset.
        """
        if self._starting_equity <= 0:
            return
        try:
            current_equity = self.portfolio.value()
        except Exception as e:
            logger.warning(f"{yellow}Could not fetch equity for kill-switch check: {e}{reset}")
            return

        drawdown = (self._starting_equity - current_equity) / self._starting_equity

        # Level 2 takes priority; also implicitly activates level 1
        if not self._kill_level2 and drawdown >= self._KL2_THRESHOLD:
            self._kill_level2 = True
            self._kill_level1 = True
            logger.critical(
                f"{hl_red}"
                f"▶▶▶ KILL SWITCH LEVEL 2 ◀◀◀  "
                f"Drawdown={drawdown:.2%}  "
                f"Equity=${current_equity:,.2f}  "
                f"Start=${self._starting_equity:,.2f}  "
                f"LIQUIDATING ALL POSITIONS AND HALTING ALL FUTURE ENTRIES."
                f"{reset}"
            )
            self._liquidate_all("KL2_DRAWDOWN_5PCT")
            return

        if not self._kill_level1 and drawdown >= self._KL1_THRESHOLD:
            self._kill_level1 = True
            logger.warning(
                f"{hl_yellow}"
                f"▶▶ KILL SWITCH LEVEL 1 ◀◀  "
                f"Drawdown={drawdown:.2%}  "
                f"Equity=${current_equity:,.2f}  "
                f"Gross exposure limit reduced: {self._GROSS_LIMIT_NORM:.0%} → {self._GROSS_LIMIT_KL1:.0%}."
                f"{reset}"
            )

    def _liquidate_all(self, reason: str) -> None:
        """Exit every confirmed open position. Called by kill-switch level 2."""
        count = 0
        for symbol in list(self._positions.keys()):
            if symbol not in self._pending_exits:
                price = self._last_price.get(symbol, self._positions[symbol]["entry_price"])
                self._exit_position(symbol, price, reason)
                count += 1
        logger.critical(
            f"{hl_red}LIQUIDATION: {count} sell orders submitted. Reason: {reason}{reset}"
        )

    # ══════════════════════════════════════════════════════════════════════
    # Portfolio helpers
    # ══════════════════════════════════════════════════════════════════════

    def _gross_exposure_pct(self) -> float:
        """
        (market value of confirmed positions + estimated value of pending entries)
        / portfolio equity.
        """
        try:
            equity = self.portfolio.value()
        except Exception:
            return 0.0
        if equity <= 0:
            return 0.0

        confirmed_val = sum(
            p["qty"] * self._last_price.get(sym, p["entry_price"])
            for sym, p in self._positions.items()
        )
        pending_val = sum(
            p["qty"] * self._last_price.get(sym, p["estimated_price"])
            for sym, p in self._pending_entries.items()
        )
        return (confirmed_val + pending_val) / equity

    def _exposure_limit(self) -> float:
        return self._GROSS_LIMIT_KL1 if self._kill_level1 else self._GROSS_LIMIT_NORM

    # ══════════════════════════════════════════════════════════════════════
    # Utilities
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _prev_trading_day(d: date) -> date:
        """Most recent weekday strictly before d (does not skip holidays)."""
        prev = d - timedelta(days=1)
        while prev.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            prev -= timedelta(days=1)
        return prev

    def _record_trade(
        self, side: str, symbol: str, qty: float, price: float, **extra
    ) -> None:
        """Append a structured trade record to trading_results.json."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "strategy":  "EventDriven",
            "symbol":    symbol,
            "side":      side,
            "quantity":  qty,
            "price":     price,
            **extra,
        }
        with open("trading_results.json", "a") as f:
            f.write(json.dumps(record) + "\n")


def main():
    setup_logging()
    logger.info("Starting Systrade Event-Driven Trading Application...")

    if not os.getenv("ALPACA_API_KEY"):
        logger.error(f"{hl_red}ALPACA_API_KEY not set. Exiting.{reset}")
        return
    if not os.getenv("ALPACA_API_SECRET"):
        logger.error(f"{hl_red}ALPACA_API_SECRET not set. Exiting.{reset}")
        return

    feed     = AlpacaLiveStockFeed()
    broker   = AlpacaBroker()
    strategy = EventDrivenStrategy()

    # NOTE: starting_cash is used for local portfolio accounting only.
    # Live order sizing uses portfolio.value() which queries Alpaca directly.
    starting_cash = 1_000_000
    engine = Engine(feed=feed, broker=broker, strategy=strategy, cash=starting_cash)

    logger.info("Engine initialized. Starting run...")
    try:
        engine.run()
        logger.info("Engine run completed successfully.")
    except KeyboardInterrupt:
        logger.info("Trading interrupted by user. Stopping engine.")
    except Exception as e:
        logger.error(
            f"{hl_red}An unexpected error occurred: {e}{reset}",
            exc_info=True,
        )

    logger.info("Application stopped.")


if __name__ == "__main__":
    main()
