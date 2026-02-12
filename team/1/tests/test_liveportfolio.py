import pytest
from unittest.mock import MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

from systrade.portfolio import LivePortfolioView
from systrade.broker import AlpacaBroker
from systrade.data import Bar, BarData

@pytest.fixture
def mock_broker():
    """Creates a mock AlpacaBroker that looks like the real thing."""
    broker = MagicMock(spec=AlpacaBroker)
    # Mock the TradingClient attribute which is often accessed directly
    broker.trading_client = MagicMock()
    return broker

@pytest.fixture
def live_pf(mock_broker):
    """Initializes LivePortfolioView with a mocked broker."""
    return LivePortfolioView(broker=mock_broker)

def test_live_cash_uses_broker_details(live_pf, mock_broker):
    """Verify cash() pulls from broker.get_account_details() dot notation."""
    # Setup mock return object
    mock_acct = MagicMock()
    mock_acct.cash = "1500.50"
    mock_broker.get_account_details.return_value = mock_acct

    assert live_pf.cash() == 1500.50
    mock_broker.get_account_details.assert_called_once()

def test_live_buying_power(live_pf, mock_broker):
    """Verify buying_power() pulls from broker.get_account_details()."""
    mock_acct = MagicMock()
    mock_acct.buying_power = "4000.00"
    mock_broker.get_account_details.return_value = mock_acct

    assert live_pf.buying_power() == 4000.00

def test_live_value_is_equity(live_pf, mock_broker):
    """In Alpaca, total portfolio value is the 'equity' field."""
    mock_acct = MagicMock()
    mock_acct.equity = "10000.00"
    mock_broker.get_account_details.return_value = mock_acct

    assert live_pf.value() == 10000.00

def test_is_invested_calls_alpaca_positions(live_pf, mock_broker):
    """Verify is_invested() checks the live trading client."""
    # Scenario 1: No positions
    mock_broker.trading_client.get_all_positions.return_value = []
    assert not live_pf.is_invested()

    # Scenario 2: Has positions
    mock_broker.trading_client.get_all_positions.return_value = [MagicMock(symbol="SPY")]
    assert live_pf.is_invested()

def test_is_invested_in_specific_symbol(live_pf, mock_broker):
    """Tests the try-except logic for get_position."""
    # Mock success (invested)
    mock_broker.trading_client.get_position.return_value = MagicMock(symbol="SPY")
    assert live_pf.is_invested_in("SPY")

    # Mock failure (not invested) - Alpaca raises 404 error usually
    mock_broker.trading_client.get_position.side_effect = Exception("Not found")
    assert not live_pf.is_invested_in("AAPL")

def test_on_data_updates_internal_price_cache(live_pf):
    """Verify BarData correctly updates the _last_prices dict."""
    as_of = datetime(2026, 2, 12, 16, 0, tzinfo=ZoneInfo("UTC"))
    data = BarData(as_of=as_of)
    data["SPY"] = Bar(close=690.00)
    
    live_pf.on_data(data)
    
    # Internal cache check
    assert live_pf._last_prices["SPY"] == 690.00
    assert live_pf.as_of() == as_of

def test_asset_value_of_uses_live_position_data(live_pf, mock_broker):
    """Tests math for a specific symbol using live market value."""
    mock_pos = MagicMock()
    mock_pos.market_value = "2100.00"
    mock_broker.trading_client.get_position.return_value = mock_pos
    
    # asset_value_of in LivePortfolioView usually hits the API 
    # for the most accurate current value
    assert live_pf.asset_value_of("SPY") == 2100.00

def test_on_fill_does_not_crash(live_pf):
    """Ensure the dummy on_fill we added doesn't break the engine loop."""
    # This should do nothing and return None
    try:
        live_pf.on_fill("SPY", 690.00, 10)
    except AttributeError:
        pytest.fail("LivePortfolioView is missing on_fill method!")
