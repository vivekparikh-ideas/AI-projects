"""M1 fixtures (D-010). Every tool reads from here until M2 swaps in EDGAR / yfinance / Alpaca.

Narrative numbers (bull/bear text) must be grounded in tool outputs, so they are written
from the same figures the tools return.
"""

from __future__ import annotations

from typing import Any

AS_OF = "2026-10-21"
NAV = 2_450_000.00

PORTFOLIO: dict[str, Any] = {
    "as_of": AS_OF,
    "nav": NAV,
    "settled_cash": 612_000.00,
    "beta": 1.08,
    "current_var_pct": 1.9,
    # (ticker, weight %, last price)
    "positions": [
        ("MSFT", 4.8, 418.00),
        ("AAPL", 2.5, 228.50),
        ("JPM", 3.5, 224.00),
        ("AMD", 3.2, 158.20),
        ("XOM", 2.9, 118.40),
    ],
    "realized_losses": [
        {"ticker": "AAPL", "date": "2026-10-09", "amount_usd": -4_210.00},
    ],
}

MANDATE: dict[str, float] = {
    "max_single_name_pct": 5.0,
    "max_var_pct": 2.5,
    "target_vol": 0.45,
    "corr_threshold": 0.60,
    "resize_buffer_pct": 0.5,
    "min_conviction": 5.0,  # sizing ramp starts here
    "min_buy_conviction": 6.0,  # below this a BUY becomes HOLD (D-034)
    "wash_sale_window_days": 30,
}

FILINGS: dict[str, list[dict[str, str]]] = {
    "NVDA": [{"form": "10-Q", "date": "2026-08-27"}, {"form": "10-K", "date": "2026-02-26"}, {"form": "8-K", "date": "2026-08-27"}],
    "AMD": [{"form": "10-Q", "date": "2026-08-05"}, {"form": "10-K", "date": "2026-02-04"}, {"form": "8-K", "date": "2026-08-05"}],
    "AAPL": [{"form": "10-Q", "date": "2026-08-01"}, {"form": "10-K", "date": "2025-10-31"}, {"form": "8-K", "date": "2026-07-31"}],
}

TICKERS: dict[str, dict[str, Any]] = {
    "NVDA": {
        "company": "NVIDIA Corp",
        "financials": {
            "revenue_q_usd_b": 35.1, "revenue_growth_pct": 94.0, "gross_margin_pct": 75.0,
            "sbc_pct_rev": 1.1, "net_share_change_pct": -0.4,
            "gross_margin_4q": [78.4, 76.1, 75.5, 75.0],
        },
        "valuation": {"fwd_pe": 32.4, "ev_ebitda": 41.2, "fcf_yield_pct": 2.1},
        "dilution": {"diluted_shares_b": 24.5, "sbc_pct_rev": 1.1, "buyback_usd_b": 50.0, "net_share_change_pct": -0.4},
        "technicals": {"spot": 141.80, "dma50": 132.40, "dma200": 118.90, "rsi14": 61.3, "vwap": 140.95},
        "insider": {"sales": 3, "planned_sales": 3, "open_market_buys": 0, "summary": "3 Form 4 sales, all 10b5-1 planned | 0 open-market buys"},
        "institutional": {"qoq_change_pct": 1.8, "summary": "Institutional ownership +1.8% QoQ"},
        "sections": {"risk_factors": "Top 4 customers ≈ 40% of revenue; export controls limit China sales"},
        "market": {"realized_vol": 0.48, "corr_to_portfolio": 0.67, "max_corr_holding": "AMD", "max_corr": 0.71, "beta": 1.70},
        "quote": {"bid": 141.94, "ask": 141.98},
        "close": 142.05,
        "research_script": {
            1: [
                {"tool": "sec_get_insider_trades", "args": {"days": 90}, "reason": "Scorecard ignores insider activity; check recent Form 4 filings"},
                {"tool": "get_cap_table", "args": {}, "reason": "Stock comp is 1.1% of revenue; confirm buybacks offset dilution"},
                {"tool": "sec_get_filing_section", "args": {"form": "10-Q", "section": "risk_factors"}, "reason": "Customer concentration and China exposure need the Risk Factors text"},
            ],
            2: [
                {"tool": "sec_get_financials", "args": {"quarters": 4}, "reason": "PM asked for the gross-margin trend over the last 4 quarters"},
            ],
        },
        "synthesis": {
            "bull_case": "Revenue +94% YoY at a 75.0% gross margin; $50B of buybacks shrink the share count 0.4% a year.",
            "bear_case": "Top 4 customers are about 40% of revenue, export controls cap China sales, and the stock trades at 32.4x forward earnings.",
            "llm_adjustment": 0.5,
            "adjustment_reason": "Insider sales are all pre-planned 10b5-1 trades and buybacks offset stock comp.",
            "round_2_note": "Gross margin eased from 78.4% to 75.0% over 4 quarters but remains high.",
        },
        "pm_script": {
            "default": [{"action": "BUY", "limit_price": 142.10, "stop_loss_price": 128.00}],
            "needs_more": [
                {"action": "NEED_MORE_RESEARCH", "question": "What is the gross-margin trend over the last 4 quarters?"},
                {"action": "BUY", "limit_price": 142.10, "stop_loss_price": 128.00},
            ],
            "loop_forever": [
                {"action": "NEED_MORE_RESEARCH", "question": "What is the gross-margin trend over the last 4 quarters?"},
                {"action": "NEED_MORE_RESEARCH", "question": "What did management say about next-quarter supply?"},
            ],
        },
    },
    "AMD": {
        "company": "Advanced Micro Devices",
        "financials": {
            "revenue_q_usd_b": 7.7, "revenue_growth_pct": 18.0, "gross_margin_pct": 53.0,
            "sbc_pct_rev": 7.0, "net_share_change_pct": -0.3,
            "gross_margin_4q": [52.1, 52.6, 52.8, 53.0],
        },
        "valuation": {"fwd_pe": 28.0, "ev_ebitda": 31.5, "fcf_yield_pct": 1.9},
        "dilution": {"diluted_shares_b": 1.63, "sbc_pct_rev": 7.0, "buyback_usd_b": 6.0, "net_share_change_pct": -0.3},
        "technicals": {"spot": 158.20, "dma50": 150.10, "dma200": 141.30, "rsi14": 57.8, "vwap": 157.60},
        "insider": {"sales": 2, "planned_sales": 2, "open_market_buys": 0, "summary": "2 Form 4 sales, both 10b5-1 planned | 0 open-market buys"},
        "institutional": {"qoq_change_pct": 0.9, "summary": "Institutional ownership +0.9% QoQ"},
        "sections": {"risk_factors": "Competes with NVIDIA in data-center GPUs; relies on TSMC for leading-edge supply"},
        "market": {"realized_vol": 0.50, "corr_to_portfolio": 0.70, "max_corr_holding": "MSFT", "max_corr": 0.52, "beta": 1.65},
        "quote": {"bid": 158.48, "ask": 158.54},
        "close": 158.70,
        "research_script": {
            1: [
                {"tool": "sec_get_insider_trades", "args": {"days": 90}, "reason": "Scorecard ignores insider activity; check recent Form 4 filings"},
                {"tool": "sec_get_filing_section", "args": {"form": "10-Q", "section": "risk_factors"}, "reason": "Competitive position against NVIDIA needs the Risk Factors text"},
            ],
        },
        "synthesis": {
            "bull_case": "Revenue +18% YoY as data-center GPUs ramp; price is above both the 50-DMA and 200-DMA.",
            "bear_case": "Stock comp is 7.0% of revenue and the stock trades at 28.0x forward earnings.",
            "llm_adjustment": 1.4,
            "adjustment_reason": "Data-center GPU demand is ramping faster than trailing revenue growth shows.",
        },
        "pm_script": {"default": [{"action": "BUY", "limit_price": 158.55, "stop_loss_price": 142.70}]},
    },
    "AAPL": {
        "company": "Apple Inc",
        "financials": {
            "revenue_q_usd_b": 94.9, "revenue_growth_pct": 6.0, "gross_margin_pct": 46.2,
            "sbc_pct_rev": 3.0, "net_share_change_pct": -3.0,
            "gross_margin_4q": [45.9, 46.6, 47.1, 46.2],
        },
        "valuation": {"fwd_pe": 30.0, "ev_ebitda": 23.4, "fcf_yield_pct": 3.3},
        "dilution": {"diluted_shares_b": 15.2, "sbc_pct_rev": 3.0, "buyback_usd_b": 110.0, "net_share_change_pct": -3.0},
        "technicals": {"spot": 228.50, "dma50": 231.20, "dma200": 214.80, "rsi14": 47.5, "vwap": 229.10},
        "insider": {"sales": 4, "planned_sales": 4, "open_market_buys": 0, "summary": "4 Form 4 sales, all 10b5-1 planned | 0 open-market buys"},
        "institutional": {"qoq_change_pct": -0.2, "summary": "Institutional ownership -0.2% QoQ"},
        "sections": {"risk_factors": "Greater China is a large share of sales; App Store fees face regulatory pressure"},
        "market": {"realized_vol": 0.26, "corr_to_portfolio": 0.62, "max_corr_holding": "MSFT", "max_corr": 0.66, "beta": 1.10},
        "quote": {"bid": 228.46, "ask": 228.52},
        "close": 228.70,
        "research_script": {
            1: [
                {"tool": "get_cap_table", "args": {}, "reason": "Buyback program is large; confirm the net share reduction"},
            ],
        },
        "synthesis": {
            "bull_case": "Buybacks ($110B) cut the share count 3.0% a year; price holds above the 200-DMA.",
            "bear_case": "Revenue grew only 6% and the stock trades at 30.0x forward earnings.",
            "llm_adjustment": 1.0,
            "adjustment_reason": "Buybacks of $110B a year steadily raise each share's claim on earnings.",
        },
        "pm_script": {"default": [{"action": "BUY", "limit_price": 228.95, "stop_loss_price": 206.00}]},
    },
}


def ticker_data(ticker: str) -> dict[str, Any]:
    try:
        return TICKERS[ticker]
    except KeyError:
        raise KeyError(f"No M1 fixture for {ticker!r}; available: {', '.join(sorted(TICKERS))}") from None
