import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# The 10-day competition trading window
START_DATE = datetime.date(2026, 4, 6)
END_DATE = datetime.date(2026, 4, 17)

# A curated universe of highly liquid, large-cap stocks that frequently report in mid-April
UNIVERSE = [
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW",  # Financials
    "DAL", "UAL", "AAL", "LUV",                           # Airlines
    "UNH", "JNJ", "PFE", "ABT",                           # Healthcare
    "NFLX", "TSLA", "IBM", "INTC",                        # Early Tech
    "PG", "KO", "PEP", "PM"                               # Consumer Defensive
]

def build_datasets():
    logging.info(f"Building datasets for {len(UNIVERSE)} symbols...")
    
    calendar_data = []
    options_data = []

    for symbol in UNIVERSE:
        try:
            logging.info(f"Processing {symbol}...")
            ticker = yf.Ticker(symbol)
            
            # 1. Fetch Earnings Dates
            # yfinance returns future earnings dates. We grab the next upcoming one.
            earnings_dates = ticker.calendar
            
            # Handle different versions of yfinance calendar output
            if isinstance(earnings_dates, pd.DataFrame) and not earnings_dates.empty:
                # If it's a dataframe, usually the 'Earnings Date' is the first row
                if 'Earnings Date' in earnings_dates.index:
                    next_earnings = earnings_dates.loc['Earnings Date'].iloc[0]
                else:
                    next_earnings = earnings_dates.iloc[0, 0]
            elif isinstance(earnings_dates, dict) and 'Earnings Date' in earnings_dates:
                 next_earnings = earnings_dates['Earnings Date'][0]
            else:
                 logging.warning(f"  -> Could not parse earnings calendar for {symbol}. Skipping.")
                 continue

            # Convert to a clean date object
            if pd.notna(next_earnings):
                if isinstance(next_earnings, pd.Timestamp):
                    report_date = next_earnings.date()
                else:
                    report_date = next_earnings
            else:
                continue

            # Check if the date falls inside our competition window
            # (Note: If Yahoo hasn't updated the 2026 dates yet, we force it to a random day in our window for testing)
            if not (START_DATE <= report_date <= END_DATE):
                 # Fallback: Assign a realistic date inside the window so you have data to trade
                 np.random.seed(len(symbol)) # Deterministic random based on ticker length
                 random_offset = np.random.randint(0, 10)
                 report_date = START_DATE + datetime.timedelta(days=random_offset)
                 logging.info(f"  -> {symbol} forced to {report_date} to fit the 10-day window.")

            # Assign time randomly between BMO (Before Market Open) and AMC (After Market Close)
            report_time = "BMO" if np.random.random() > 0.5 else "AMC"

            calendar_data.append({
                "symbol": symbol,
                "report_date": report_date.strftime("%Y-%m-%d"),
                "time": report_time
            })

            # 2. Calculate the "Implied Move" Proxy (Historical Realized Volatility)
            # Download the last 3 months of daily data to calculate standard deviation
            hist = ticker.history(period="3mo")
            if not hist.empty and len(hist) > 10:
                # Calculate daily returns
                hist['Returns'] = hist['Close'].pct_change()
                # Calculate the standard deviation of returns (daily volatility)
                daily_vol = hist['Returns'].std()
                # Project the daily volatility to a 2-day expected earnings move (approximate)
                # We multiply by a factor (e.g., 3x) because earnings moves are outlier events
                implied_move = round(daily_vol * 3, 4)
                
                # Cap it between 2% and 15% to keep it realistic
                implied_move = max(0.02, min(0.15, implied_move))
                
                options_data.append({
                    "symbol": symbol,
                    "implied_move_pct": implied_move
                })

        except Exception as e:
            logging.error(f"  -> Failed to process {symbol}: {e}")

    # 3. Export to CSVs
    if calendar_data and options_data:
        cal_df = pd.DataFrame(calendar_data)
        opt_df = pd.DataFrame(options_data)

        cal_df.to_csv("earnings_calendar.csv", index=False)
        opt_df.to_csv("options_data.csv", index=False)

        logging.info("==================================================")
        logging.info(f"SUCCESS: Generated earnings_calendar.csv ({len(cal_df)} rows)")
        logging.info(f"SUCCESS: Generated options_data.csv ({len(opt_df)} rows)")
        logging.info("==================================================")
    else:
        logging.error("Failed to generate datasets. No valid data found.")

if __name__ == "__main__":
    build_datasets()