import pandas as pd
import numpy as np
import yfinance as yf
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def build_estimates_and_scores():
    logging.info("Starting Event Score generation...")

    # 1. Load the required existing datasets
    if not os.path.exists("earnings_calendar.csv") or not os.path.exists("options_data.csv"):
        logging.error("Missing required datasets. Run build_datasets.py first.")
        return

    calendar_df = pd.read_csv("earnings_calendar.csv")
    options_df = pd.read_csv("options_data.csv")
    
    symbols = calendar_df['symbol'].unique().tolist()
    logging.info(f"Processing {len(symbols)} symbols from the calendar...")

    # Fetch SPY for market relative strength comparison
    spy_data = yf.download("SPY", period="2mo", progress=False)
    if isinstance(spy_data.columns, pd.MultiIndex):
        spy_data = spy_data.xs('SPY', level=1, axis=1) # Flatten if multi-index
    spy_20d_return = (spy_data['Close'].iloc[-1] / spy_data['Close'].iloc[-20]) - 1

    feature_records = []

    for symbol in symbols:
        try:
            logging.info(f"Calculating features for {symbol}...")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2mo")
            
            if len(hist) < 21:
                logging.warning(f"Not enough historical data for {symbol}. Skipping.")
                continue

            # --- Component 1 & 2: Fundamental Revision Proxies (55% Weight) ---
            # Proxy: We use the 3-month price momentum and current P/E expansion 
            # as a proxy for Wall Street revising estimates upward.
            # For the script, we will calculate a normalized fundamental momentum score.
            fund_momentum = (hist['Close'].iloc[-1] / hist['Close'].iloc[-40]) - 1 if len(hist) >= 40 else 0
            
            # --- Component 3: 20-Day Relative Strength vs Sector/Market (20% Weight) ---
            sym_20d_return = (hist['Close'].iloc[-1] / hist['Close'].iloc[-20]) - 1
            relative_strength = sym_20d_return - spy_20d_return

            # --- Component 4: Abnormal Accumulation (15% Weight) ---
            # Count days in the last 20 where the stock closed higher than it opened AND volume was > 20-day average
            hist['20d_Avg_Vol'] = hist['Volume'].rolling(window=20).mean()
            accumulation_days = len(hist.tail(20)[
                (hist['Close'].tail(20) > hist['Open'].tail(20)) & 
                (hist['Volume'].tail(20) > hist['20d_Avg_Vol'].tail(20))
            ])

            # --- Component 5: Implied Move Attractiveness (10% Weight) ---
            # We want moderate implied moves. Extreme moves (>10%) are penalized as too crowded/risky.
            try:
                implied_move = options_df[options_df['symbol'] == symbol]['implied_move_pct'].values[0]
            except IndexError:
                implied_move = 0.05 # Default if missing
            
            # Attractiveness score: Peaks around 4-5% implied move, drops off if it's 15%
            iv_attractiveness = 1.0 - abs(implied_move - 0.045) 

            feature_records.append({
                "symbol": symbol,
                "fund_momentum_proxy": fund_momentum,
                "relative_strength": relative_strength,
                "accumulation_days": accumulation_days,
                "iv_attractiveness": iv_attractiveness
            })

        except Exception as e:
            logging.error(f"Failed to calculate features for {symbol}: {e}")

    # 2. Build the DataFrame and Calculate Cross-Sectional Percentiles
    df = pd.DataFrame(feature_records)

    # Rank each component as a percentile (0.0 to 1.0) within our specific universe
    df['eps_rev_rank'] = df['fund_momentum_proxy'].rank(pct=True) # 35%
    df['rev_rev_rank'] = df['fund_momentum_proxy'].rank(pct=True) # 20% (Using same proxy for simplicity)
    df['rs_rank']      = df['relative_strength'].rank(pct=True)   # 20%
    df['accum_rank']   = df['accumulation_days'].rank(pct=True)   # 15%
    df['iv_rank']      = df['iv_attractiveness'].rank(pct=True)   # 10%

    # 3. Calculate the Final Weighted Event Score
    df['event_score_percentile'] = (
        (df['eps_rev_rank'] * 0.35) +
        (df['rev_rev_rank'] * 0.20) +
        (df['rs_rank'] * 0.20) +
        (df['accum_rank'] * 0.15) +
        (df['iv_rank'] * 0.10)
    )

    # Clean up the output to only include what the trading bot needs
    final_output = df[['symbol', 'event_score_percentile']].copy()
    
    # Sort from highest conviction to lowest
    final_output = final_output.sort_values(by='event_score_percentile', ascending=False)
    final_output.to_csv("estimates.csv", index=False)

    logging.info("==================================================")
    logging.info(f"SUCCESS: Generated estimates.csv with Event Scores for {len(final_output)} symbols.")
    logging.info(f"Top Pick: {final_output.iloc[0]['symbol']} (Score: {final_output.iloc[0]['event_score_percentile']:.4f})")
    logging.info("==================================================")

if __name__ == "__main__":
    build_estimates_and_scores()