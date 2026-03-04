"""Tests for backtest and market-status API endpoints."""

from unittest.mock import MagicMock, patch

import pytest

from src.api.endpoints import get_market_status, run_backtest_endpoint


class TestBacktestEndpoint:
    """Tests for POST /backtest."""

    @pytest.mark.asyncio
    @patch("kdbx.backtest.run_backtest")
    async def test_backtest_returns_correct_shape(self, mock_run_backtest):
        """Verify POST /backtest returns all expected fields."""
        mock_run_backtest.return_value = {
            "sharpe": 1.2,
            "max_drawdown": -0.05,
            "total_return": 0.15,
            "win_rate": 0.55,
            "n_trades": 30,
        }

        result = await run_backtest_endpoint(
            model_id="test-model",
            universe=None,
            cost_bps=5.0,
        )

        assert result["model_id"] == "test-model"
        assert result["cost_bps"] == 5.0
        assert result["sharpe"] == 1.2
        assert result["max_drawdown"] == -0.05
        assert result["total_return"] == 0.15
        assert result["win_rate"] == 0.55
        assert result["n_trades"] == 30
        assert result["universe"] is None

    @pytest.mark.asyncio
    @patch("kdbx.backtest.run_backtest")
    async def test_backtest_with_universe(self, mock_run_backtest):
        """Verify POST /backtest passes universe to run_backtest."""
        mock_run_backtest.return_value = {
            "sharpe": 0.8,
            "max_drawdown": -0.1,
            "total_return": 0.05,
            "win_rate": 0.5,
            "n_trades": 10,
        }

        result = await run_backtest_endpoint(
            model_id="test-model",
            universe=["AAPL", "MSFT"],
            cost_bps=3.0,
        )

        mock_run_backtest.assert_called_once_with(
            model_id="test-model",
            universe=["AAPL", "MSFT"],
            cost_bps=3.0,
        )
        assert result["universe"] == ["AAPL", "MSFT"]

    @pytest.mark.asyncio
    @patch("kdbx.backtest.run_backtest")
    async def test_backtest_uses_default_cost(self, mock_run_backtest):
        """Verify POST /backtest uses config default when cost_bps not provided."""
        mock_run_backtest.return_value = {
            "sharpe": 1.0,
            "max_drawdown": -0.02,
            "total_return": 0.1,
            "win_rate": 0.6,
            "n_trades": 20,
        }

        result = await run_backtest_endpoint(
            model_id="test-model",
            cost_bps=None,
        )

        # Should use settings.backtest_config.cost_bps as default
        assert result["cost_bps"] is not None


class TestMarketStatusEndpoint:
    """Tests for GET /market-status."""

    @pytest.mark.asyncio
    @patch("kdbx.connection.pykx_connection")
    async def test_market_status_returns_table_counts(self, mock_pykx_conn):
        """Verify GET /market-status returns counts for all tables."""
        mock_q = MagicMock()

        def count_side_effect(query, *args):
            # Parameterized query: q("{[t] count value t}", kx.SymbolAtom(table))
            # Extract table name from the SymbolAtom arg
            if args:
                table_name = str(args[0])
            else:
                table_name = ""
            counts = {
                "market_ticks": 1000,
                "order_book": 500,
                "signals": 200,
                "backtest_results": 50,
            }
            return MagicMock(py=MagicMock(return_value=counts.get(table_name, 0)))

        mock_q.side_effect = count_side_effect
        mock_pykx_conn.return_value.__enter__ = MagicMock(return_value=mock_q)
        mock_pykx_conn.return_value.__exit__ = MagicMock(return_value=False)

        result = await get_market_status()

        assert "market_ticks" in result
        assert "order_book" in result
        assert "signals" in result
        assert "backtest_results" in result
        assert result["market_ticks"]["row_count"] == 1000
        assert result["order_book"]["row_count"] == 500
        assert result["signals"]["row_count"] == 200
        assert result["backtest_results"]["row_count"] == 50

    @pytest.mark.asyncio
    @patch("kdbx.connection.pykx_connection")
    async def test_market_status_handles_missing_tables(self, mock_pykx_conn):
        """Verify GET /market-status handles missing tables gracefully."""
        mock_q = MagicMock()
        mock_q.side_effect = Exception("table not found")
        mock_pykx_conn.return_value.__enter__ = MagicMock(return_value=mock_q)
        mock_pykx_conn.return_value.__exit__ = MagicMock(return_value=False)

        result = await get_market_status()

        for table in ["market_ticks", "order_book", "signals", "backtest_results"]:
            assert result[table]["row_count"] == 0
            assert "error" in result[table]
