"""Systematic Trading Application"""

import os
import json
import math
import logging
import logging.config
import logging.handlers
import pathlib
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
#  --- Post-Earnings Announcement Drift ---
# =============================================
# Enters long positions the morning after an earnings
# surprise where the opening gap exceeds the options-
# implied move, then exits 2 trading days later.
class PEADStrategy(Strategy):
    """
    Post-Earnings Announcement Drift (PEAD) strategy with IV filter.

    Entry logic (9:30-9:45 AM EST, day of/after earnings):
      - Symbol reported AMC yesterday OR BMO today
      - Opening gap = (current_price - prev_close) / prev_close
      - Gap > implied_move_pct from options_data.csv  →  buy 10% of buying power

    Exit logic:
      - Close the entire position 2 trading days after entry
    """

    _ENTRY_START = dt_time(9, 30)
    _ENTRY_END   = dt_time(9, 45)
    _EST         = ZoneInfo("America/New_York")

    def __init__(self) -> None:
        super().__init__()

        # Load static datasets — raises clearly if files are missing/malformed
        self._earnings: pd.DataFrame      = self._load_earnings()
        self._iv_map:   dict[str, float]  = self._load_iv_map()

        # Per-symbol price tracking
        # prev_close: last known price from the previous trading session
        # last_price: most recent bar price (used to roll prev_close forward)
        # last_bar_date: date of the last bar received per symbol
        self._prev_close:    dict[str, float] = {}
        self._last_price:    dict[str, float] = {}
        self._last_bar_date: dict[str, date]  = {}

        # Entry/exit state
        self._entry_times:   dict[str, datetime] = {}  # entry timestamp per symbol
        self._pending_exits: set[str]            = set()  # symbols with an open exit order

        # Per-day deduplication: prevents re-evaluating a symbol multiple
        # times within the same 9:30–9:45 entry window
        self._fired_today:  set[str]       = set()
        self._current_date: Optional[date] = None

        logger.info(
            f"PEAD Strategy initialized. "
            f"{len(self._earnings)} earnings events across "
            f"{self._earnings['symbol'].nunique()} symbols."
        )

    # ------------------------------------------------------------------
    # CSV loaders
    # ------------------------------------------------------------------

    def _load_earnings(self) -> pd.DataFrame:
        """
        Load earnings_calendar.csv from the working directory.
        Expected columns: symbol, report_date, time  (time = 'AMC' or 'BMO')
        """
        path = pathlib.Path("earnings_calendar.csv")
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path.resolve()}. "
                "Place earnings_calendar.csv in the working directory."
            )
        df = pd.read_csv(path)
        required = {"symbol", "report_date", "time"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"earnings_calendar.csv is missing required columns: {missing}. "
                f"Found: {set(df.columns)}"
            )
        df["symbol"]      = df["symbol"].str.strip().str.upper()
        df["time"]        = df["time"].str.strip().str.upper()
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        logger.info(f"Loaded earnings calendar: {len(df)} events.")
        return df

    def _load_iv_map(self) -> dict[str, float]:
        """
        Load options_data.csv from the working directory.
        Expected columns: symbol, implied_move_pct
        implied_move_pct should be expressed as a decimal (e.g. 0.05 = 5%).
        """
        path = pathlib.Path("options_data.csv")
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path.resolve()}. "
                "Place options_data.csv in the working directory."
            )
        df = pd.read_csv(path)
        required = {"symbol", "implied_move_pct"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"options_data.csv is missing required columns: {missing}. "
                f"Found: {set(df.columns)}"
            )
        df["symbol"] = df["symbol"].str.strip().str.upper()
        iv_map = dict(zip(df["symbol"], df["implied_move_pct"].astype(float)))
        logger.info(f"Loaded IV data for {len(iv_map)} symbols.")
        return iv_map

    # ------------------------------------------------------------------
    # Strategy hooks
    # ------------------------------------------------------------------

    @override
    def on_start(self) -> None:
        """Subscribe to every symbol that appears in the earnings calendar."""
        symbols = self._earnings["symbol"].unique().tolist()
        for sym in symbols:
            self.subscribe(sym)
        logger.info(f"Subscribed to {len(symbols)} symbols: {symbols}")

    @override
    def on_data(self, data: BarData) -> None:
        self.current_time = data.as_of

        # Normalise to timezone-aware EST for all time comparisons
        as_of = data.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=ZoneInfo("UTC"))
        now_est:  datetime = as_of.astimezone(self._EST)
        today:    date     = now_est.date()
        bar_time: dt_time  = now_est.timetz().replace(tzinfo=None)  # naive time for comparison

        # Reset daily state when the trading date changes
        if self._current_date != today:
            self._fired_today.clear()
            self._current_date = today
            logger.debug(f"New trading day detected: {today}")

        for symbol, bar in data.bars():
            price = bar.close

            # --- Roll prev_close forward on day boundary ---
            # When the first bar of a new trading day arrives, save the last
            # price seen during the previous session as the previous close.
            prev_date = self._last_bar_date.get(symbol)
            if prev_date is not None and prev_date < today:
                self._prev_close[symbol] = self._last_price[symbol]
                logger.debug(
                    f"Day rollover {symbol}: prev_close={self._prev_close[symbol]:.4f} "
                    f"(from {prev_date})"
                )

            # Update rolling price trackers
            self._last_price[symbol]    = price
            self._last_bar_date[symbol] = today

            # --- Check exit (runs every bar for active positions) ---
            self._check_exit(symbol, price, now_est)

            # --- Check entry (only within the 9:30–9:45 AM window) ---
            in_entry_window = self._ENTRY_START <= bar_time <= self._ENTRY_END
            if (
                in_entry_window
                and symbol not in self._fired_today
                and not self.portfolio.is_invested_in(symbol)
            ):
                self._check_entry(symbol, price, today, now_est)

    @override
    def on_execution(self, report: ExecutionReport) -> None:
        """Called when any order is filled. Cleans up exit state for sells."""
        log_report = report.__dict__.copy()
        log_report["fill_timestamp_iso"] = report.fill_timestamp.isoformat()
        logger.info(f"Execution report: {log_report}")

        symbol = report.order.symbol
        # A negative order quantity means we sold — clean up tracking state
        if report.order.quantity < 0:
            self._pending_exits.discard(symbol)
            self._entry_times.pop(symbol, None)
            logger.info(
                f"{hl_yellow}PEAD EXIT confirmed: {symbol} filled "
                f"{report.last_quantity} @ {report.last_price:.2f}{reset}"
            )

        self._record_trade(
            side="SELL" if report.order.quantity < 0 else "BUY",
            symbol=symbol,
            qty=abs(report.last_quantity),
            price=report.last_price,
            source="execution_report",
        )

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _check_entry(
        self,
        symbol: str,
        price: float,
        today: date,
        now_est: datetime,
    ) -> None:
        """
        Evaluate the PEAD entry signal for a single symbol.
        Marks symbol in _fired_today regardless of outcome to prevent
        repeated checks within the same 9:30–9:45 window.
        """
        # Always mark fired so we only evaluate once per day per symbol
        self._fired_today.add(symbol)

        yesterday = self._prev_trading_day(today)

        # Does this symbol have a qualifying earnings event?
        events = self._earnings[self._earnings["symbol"] == symbol]
        qualifying = events[
            ((events["report_date"] == yesterday) & (events["time"] == "AMC")) |
            ((events["report_date"] == today)     & (events["time"] == "BMO"))
        ]
        if qualifying.empty:
            return  # no earnings event, nothing to do

        # Validate previous close
        prev_close = self._prev_close.get(symbol)
        if prev_close is None:
            logger.warning(
                f"{yellow}[PEAD] No previous close recorded for {symbol}. "
                f"Cannot calculate opening gap — skipping entry.{reset}"
            )
            return
        if prev_close <= 0:
            logger.warning(
                f"{yellow}[PEAD] Invalid prev_close={prev_close} for {symbol}. "
                f"Skipping entry.{reset}"
            )
            return

        # Validate IV data
        implied_move = self._iv_map.get(symbol)
        if implied_move is None:
            logger.warning(
                f"{yellow}[PEAD] No implied_move_pct found for {symbol}. "
                f"Skipping entry.{reset}"
            )
            return

        gap = (price - prev_close) / prev_close

        logger.info(
            f"[PEAD] Earnings signal check — {symbol}: "
            f"price={price:.4f}  prev_close={prev_close:.4f}  "
            f"gap={gap:+.4%}  implied_move={implied_move:.4%}"
        )

        # Entry condition: positive gap that exceeds the options-implied move
        if gap <= 0:
            logger.info(f"[PEAD] {symbol}: gap is not positive ({gap:+.4%}). No entry.")
            return

        if gap <= implied_move:
            logger.info(
                f"[PEAD] {symbol}: gap {gap:+.4%} does not exceed "
                f"implied move {implied_move:.4%}. No entry."
            )
            return

        # Size position at 10% of current buying power
        buying_power = self.portfolio.buying_power()
        qty = math.floor((buying_power * 0.10) / price)
        if qty <= 0:
            logger.warning(
                f"{yellow}[PEAD] ENTRY signal for {symbol} but qty=0 "
                f"(buying_power={buying_power:.2f}, price={price:.2f}). "
                f"Skipping.{reset}"
            )
            return

        self.post_market_order(symbol, quantity=qty)
        self._entry_times[symbol] = now_est

        logger.info(
            f"{hl_green}[PEAD] ENTRY: {symbol}  "
            f"gap={gap:+.4%} > implied={implied_move:.4%}  "
            f"qty={qty}  price~{price:.2f}  "
            f"(10% of ${buying_power:,.2f} buying power){reset}"
        )
        self._record_trade(
            side="BUY",
            symbol=symbol,
            qty=qty,
            price=price,
            gap=gap,
            implied_move=implied_move,
        )

    def _check_exit(self, symbol: str, price: float, now_est: datetime) -> None:
        """
        Exit the position in symbol if 2 trading days have elapsed since entry.
        Uses _pending_exits to ensure only one exit order is sent per position.
        """
        if symbol not in self._entry_times:
            return

        # Already sent an exit order — wait for the fill callback
        if symbol in self._pending_exits:
            return

        # Position may have been closed externally; clean up if so
        if not self.portfolio.is_invested_in(symbol):
            logger.warning(
                f"{yellow}[PEAD] {symbol} no longer in portfolio but still "
                f"tracked in entry_times. Removing stale state.{reset}"
            )
            self._entry_times.pop(symbol, None)
            return

        entry_date     = self._entry_times[symbol].date()
        current_date   = now_est.date()
        trading_days   = self._trading_days_elapsed(entry_date, current_date)

        if trading_days < 2:
            return

        # 2 trading days have passed — exit the full position
        try:
            pos = self.portfolio.position(symbol)
        except ValueError:
            # Portfolio says we're not in the position (race condition)
            self._entry_times.pop(symbol, None)
            return

        qty_to_sell = abs(pos.qty)
        if qty_to_sell <= 0:
            self._entry_times.pop(symbol, None)
            return

        self.post_market_order(symbol, quantity=-qty_to_sell)
        self._pending_exits.add(symbol)

        logger.info(
            f"{hl_blue}[PEAD] EXIT: {symbol}  "
            f"{trading_days} trading days since entry ({entry_date})  "
            f"selling {qty_to_sell} shares @ ~{price:.2f}{reset}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prev_trading_day(d: date) -> date:
        """Return the most recent weekday before d (does not account for holidays)."""
        prev = d - timedelta(days=1)
        while prev.weekday() >= 5:  # 5=Saturday, 6=Sunday
            prev -= timedelta(days=1)
        return prev

    @staticmethod
    def _trading_days_elapsed(entry_date: date, current_date: date) -> int:
        """
        Count trading (business) days from entry_date up to but not including
        current_date. Returns 0 if current_date <= entry_date.

        Examples:
          Monday → Wednesday  = 2  (exit Wednesday)
          Thursday → Monday   = 2  (Friday + Monday, exit Monday)
        """
        if current_date <= entry_date:
            return 0
        return int(np.busday_count(entry_date, current_date))

    def _record_trade(
        self,
        side: str,
        symbol: str,
        qty: float,
        price: float,
        **extra,
    ) -> None:
        """Append a structured trade record to trading_results.json."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "strategy": "PEAD",
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "price": price,
            **extra,
        }
        with open("trading_results.json", "a") as f:
            f.write(json.dumps(record) + "\n")


def main():
    setup_logging()
    logger.info("Starting Systrade PEAD Trading Application...")

    if not os.getenv("ALPACA_API_KEY"):
        logger.error(f"{hl_red}ALPACA_API_KEY not set. Exiting.{reset}")
        return
    if not os.getenv("ALPACA_API_SECRET"):
        logger.error(f"{hl_red}ALPACA_API_SECRET not set. Exiting.{reset}")
        return

    feed     = AlpacaLiveStockFeed()
    broker   = AlpacaBroker()
    strategy = PEADStrategy()

    # NOTE: starting_cash is used for local portfolio accounting only.
    # The live portfolio queries buying power directly from the Alpaca API,
    # so this value does not affect order sizing.
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
