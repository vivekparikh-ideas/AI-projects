"""Live data: SEC EDGAR (filings, XBRL facts, Form 4, filing text) and yfinance (prices, valuation, holders).

Everything is cached per day (`nexus.data.cache`). SEC requests carry the required User-Agent and stay
under 10 requests/second. Text taken from filings is untrusted data; callers delimit it in prompts (D-014).
"""

from __future__ import annotations

import os
import re
import time
import warnings
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any

import httpx

from nexus import tracing
from nexus.data.cache import cached
from nexus.tools import indicators as ind

warnings.filterwarnings("ignore", message=r".*inplace.*")  # pandas deprecation noise raised inside yfinance

REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
_QUARTER = re.compile(r"^CY(\d{4})Q([1-4])$")
_YEAR = re.compile(r"^CY(\d{4})$")
_INSTANT = re.compile(r"^CY(\d{4})Q([1-4])I$")
# (section heading, the heading that ends it). Headings must start a line, which skips cross-references.
SECTION_HEADINGS = {
    "risk_factors": (r"(?:^|\n)\s*item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors", r"\n\s*item\s*(?:1b|2|3)\b"),
    "mda": (r"(?:^|\n)\s*item\s*[27]\.?\s*[\-–—:]?\s*management[’']s\s+discussion", r"\n\s*item\s*(?:3|7a|8)\b"),
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text))


class LiveProvider:
    name = "live"

    def __init__(self) -> None:
        ua = os.environ.get("NEXUS_SEC_USER_AGENT")
        if not ua:
            raise RuntimeError("Set NEXUS_SEC_USER_AGENT (e.g. 'Nexus Research you@example.com') for SEC EDGAR access")
        self._http = httpx.Client(headers={"User-Agent": ua}, timeout=30.0, follow_redirects=True)
        self._last_sec = 0.0

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _sec(self, url: str, as_json: bool = True) -> Any:
        def fetch():
            for attempt in range(4):
                wait = 0.15 - (time.monotonic() - self._last_sec)
                if wait > 0:
                    time.sleep(wait)
                self._last_sec = time.monotonic()
                try:
                    r = self._http.get(url)
                except httpx.TransportError:  # timeouts and dropped connections: back off and retry
                    if attempt == 3:
                        raise
                    time.sleep(2**attempt)
                    continue
                if r.status_code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(2**attempt)
                    continue
                tracing.annotate(attempts=attempt + 1, status=r.status_code)
                r.raise_for_status()
                return r.json() if as_json else r.text
            raise RuntimeError(f"SEC request failed: {url}")

        return cached("sec", url, fetch)

    def _cik(self, ticker: str) -> int:
        table = self._sec("https://www.sec.gov/files/company_tickers.json")
        for row in table.values():
            if row["ticker"] == ticker.upper():
                return int(row["cik_str"])
        raise KeyError(f"{ticker} is not in SEC's ticker list")

    def _facts(self, ticker: str) -> dict[str, Any]:
        return self._sec(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self._cik(ticker):010d}.json")["facts"].get("us-gaap", {})

    def _submissions(self, ticker: str) -> list[dict[str, str]]:
        r = self._sec(f"https://data.sec.gov/submissions/CIK{self._cik(ticker):010d}.json")["filings"]["recent"]
        return [dict(form=f, date=d, accession=a, doc=p) for f, d, a, p in zip(r["form"], r["filingDate"], r["accessionNumber"], r["primaryDocument"])]

    def _series(self, tags: tuple[str, ...], pattern: re.Pattern) -> dict[str, float]:
        """Values by calendar frame for the first tag that has the most recent frame."""
        best: dict[str, float] = {}
        for tag in tags:
            node = self._facts_cache.get(tag)
            if not node:
                continue
            series = {v["frame"]: float(v["val"]) for unit in node["units"].values() for v in unit if pattern.match(v.get("frame", ""))}
            if series and (not best or max(series) > max(best)):
                best = series
        return dict(sorted(best.items()))

    def _load_facts(self, ticker: str) -> None:
        self._facts_cache = self._facts(ticker)

    def _yf(self, ticker: str):
        import yfinance as yf

        if os.environ.get("NEXUS_CACHE_DIR"):  # serverless: only /tmp is writable
            yf.set_tz_cache_location(os.path.join(os.environ["NEXUS_CACHE_DIR"], "yfinance"))
        return yf.Ticker(ticker)

    def _history(self, ticker: str) -> dict[str, list[float]]:
        def fetch():
            h = self._yf(ticker).history(period="1y", interval="1d")
            if h.empty:
                raise KeyError(f"No price history for {ticker}")
            return {"close": h["Close"].tolist(), "high": h["High"].tolist(), "low": h["Low"].tolist(), "volume": h["Volume"].tolist(), "last_date": str(h.index[-1].date())}

        return cached("yf-history", ticker, fetch)

    def _info(self, ticker: str) -> dict[str, Any]:
        def fetch():
            info = self._yf(ticker).info or {}
            keep = ("longName", "forwardPE", "enterpriseToEbitda", "freeCashflow", "marketCap", "bid", "ask", "currentPrice", "regularMarketPrice")
            return {k: info.get(k) for k in keep}

        return cached("yf-info", ticker, fetch)

    # ── provider interface ───────────────────────────────────────────────────

    def as_of(self) -> str:
        return date.today().isoformat()

    def company(self, ticker: str) -> str:
        return self._info(ticker).get("longName") or ticker

    def filings(self, ticker: str) -> list[dict[str, str]]:
        out, seen = [], set()
        for f in self._submissions(ticker):
            if f["form"] in ("10-K", "10-Q", "8-K") and f["form"] not in seen:
                out.append({"form": f["form"], "date": f["date"]})
                seen.add(f["form"])
        return out

    def financials(self, ticker: str, quarters: int = 1) -> dict[str, Any]:
        self._load_facts(ticker)
        rev_q = self._series(REVENUE_TAGS, _QUARTER)
        gp_q = self._series(("GrossProfit",), _QUARTER)
        cost_q = self._series(("CostOfRevenue", "CostOfGoodsAndServicesSold"), _QUARTER)
        shares_q = self._series(("WeightedAverageNumberOfDilutedSharesOutstanding",), _QUARTER)
        rev_a = self._series(REVENUE_TAGS, _YEAR)
        sbc_a = self._series(("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"), _YEAR)
        ocf_a = self._series(("NetCashProvidedByUsedInOperatingActivities",), _YEAR)
        ni_a = self._series(("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"), _YEAR)
        ar_i = self._series(("AccountsReceivableNetCurrent",), _INSTANT)
        if not rev_q:
            raise KeyError(f"No quarterly revenue in SEC XBRL facts for {ticker}")
        latest = max(rev_q)
        y, q = _QUARTER.match(latest).groups()
        year_ago = f"CY{int(y) - 1}Q{q}"

        def margin(frame: str) -> float | None:
            gp = gp_q.get(frame)
            if gp is None and frame in cost_q:
                gp = rev_q[frame] - cost_q[frame]
            return round(gp / rev_q[frame] * 100, 1) if gp is not None and rev_q.get(frame) else None

        growth = round((rev_q[latest] / rev_q[year_ago] - 1) * 100, 1) if year_ago in rev_q else None
        last_year = max(rev_a) if rev_a else None
        sbc = round(sbc_a[last_year] / rev_a[last_year] * 100, 1) if last_year and last_year in sbc_a else None
        net_shares = round((shares_q[latest] / shares_q[year_ago] - 1) * 100, 1) if latest in shares_q and year_ago in shares_q else None
        cash_year = max(ocf_a) if ocf_a else None
        ar_latest = max(ar_i) if ar_i else None
        ar_year_ago = f"CY{int(ar_latest[2:6]) - 1}{ar_latest[6:]}" if ar_latest else None
        out = {
            "period": latest,
            "revenue_q_usd_b": round(rev_q[latest] / 1e9, 2),
            "revenue_growth_pct": growth,
            "gross_margin_pct": margin(latest),
            "sbc_pct_rev": sbc,
            "net_share_change_pct": net_shares,
            "cash_flow_year": cash_year,
            "operating_cash_flow_usd_b": round(ocf_a[cash_year] / 1e9, 2) if cash_year else None,
            "net_income_usd_b": round(ni_a[cash_year] / 1e9, 2) if cash_year and cash_year in ni_a else None,
            "receivables_growth_pct": round((ar_i[ar_latest] / ar_i[ar_year_ago] - 1) * 100, 1) if ar_year_ago in ar_i else None,
        }
        if quarters > 1:
            out["gross_margin_4q"] = [m for m in (margin(f) for f in list(rev_q)[-quarters:]) if m is not None]
        return out

    def dilution(self, ticker: str) -> dict[str, Any]:
        fin = self.financials(ticker)
        shares_q = self._series(("WeightedAverageNumberOfDilutedSharesOutstanding",), _QUARTER)
        buyback_a = self._series(("PaymentsForRepurchaseOfCommonStock",), _YEAR)
        return {
            "diluted_shares_b": round(shares_q[max(shares_q)] / 1e9, 2) if shares_q else None,
            "sbc_pct_rev": fin["sbc_pct_rev"],
            "buyback_usd_b": round(buyback_a[max(buyback_a)] / 1e9, 1) if buyback_a else 0.0,
            "net_share_change_pct": fin["net_share_change_pct"],
        }

    def section(self, ticker: str, form: str, section: str) -> str:
        filing = next((f for f in self._submissions(ticker) if f["form"] == form), None)
        if filing is None:
            return f"No {form} on file."
        url = f"https://www.sec.gov/Archives/edgar/data/{self._cik(ticker)}/{filing['accession'].replace('-', '')}/{filing['doc']}"
        text = _html_to_text(self._sec(url, as_json=False))
        heading, ender = SECTION_HEADINGS[section]
        hits = [m.end() for m in re.finditer(heading, text, flags=re.I)]
        if not hits:
            return f"Section {section} not found in the {form} filed {filing['date']}."

        def length(i: int) -> int:
            nxt = re.search(ender, text[i:], flags=re.I)
            return nxt.start() if nxt else len(text) - i

        start = max(hits, key=length)  # table-of-contents entries are short; the real section is longest
        if section == "mda":  # skip the forward-looking-statements boilerplate when the results discussion follows
            results = re.search(r"\n\s*results\s+of\s+operations", text[start:start + length(start)], flags=re.I)
            start += results.start() if results else 0
        body = re.sub(r"\s+", " ", text[start:start + 6000]).strip()
        return f"[{form} filed {filing['date']}] " + body[:2500]

    def insider(self, ticker: str, days: int) -> dict[str, Any]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        cik = self._cik(ticker)
        recent = [f for f in self._submissions(ticker) if f["form"] == "4" and f["date"] >= cutoff][:20]
        sales = planned = buys = 0
        for f in recent:
            doc = f["doc"].split("/")[-1]
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accession'].replace('-', '')}/{doc}"
            try:
                root = ET.fromstring(self._sec(url, as_json=False))
            except ET.ParseError:
                continue
            codes = {e.text for e in root.iter("transactionCode")}
            plan = (root.findtext("aff10b5One") or "").strip().lower() in ("1", "true")
            if "S" in codes:
                sales += 1
                planned += plan
            if "P" in codes:
                buys += 1
        summary = f"{sales} Form 4 filings with sales ({planned} under 10b5-1 plans) | {buys} open-market buys in {days} days"
        return {"filings_checked": len(recent), "sales": sales, "planned_sales": planned, "open_market_buys": buys, "summary": summary}

    def institutional(self, ticker: str) -> dict[str, Any]:
        def fetch():
            df = self._yf(ticker).institutional_holders
            if df is None or df.empty:
                return {"qoq_change_pct": None, "summary": "No institutional holder data"}
            rows = df.head(10).to_dict("records")
            total = sum(r.get("Shares") or 0 for r in rows)
            change = sum((r.get("pctChange") or 0) * (r.get("Shares") or 0) for r in rows) / total * 100 if total else 0.0
            top = rows[0]
            return {
                "qoq_change_pct": round(change, 1),
                "top_holder": top.get("Holder"),
                "summary": f"Top 10 holders net {change:+.1f}% QoQ | largest: {top.get('Holder')} {float(top.get('pctHeld') or 0) * 100:.1f}%",
            }

        return cached("yf-holders", ticker, fetch)

    def valuation(self, ticker: str) -> dict[str, Any]:
        info = self._info(ticker)
        fcf, cap = info.get("freeCashflow"), info.get("marketCap")
        return {
            "fwd_pe": round(info["forwardPE"], 1) if info.get("forwardPE") else None,
            "ev_ebitda": round(info["enterpriseToEbitda"], 1) if info.get("enterpriseToEbitda") else None,
            "fcf_yield_pct": round(fcf / cap * 100, 1) if fcf and cap else None,
        }

    def price_history(self, ticker: str) -> dict[str, Any]:
        h = self._history(ticker)
        return {"bars": len(h["close"]), "last_close": round(h["close"][-1], 2), "last_date": h["last_date"]}

    def technicals(self, ticker: str) -> dict[str, float]:
        h = self._history(ticker)
        c = h["close"]
        return {
            "spot": round(c[-1], 2),
            "dma50": round(ind.sma(c, 50), 2),
            "dma200": round(ind.sma(c, 200), 2),
            "rsi14": round(ind.rsi_wilder(c, 14), 1),
            "vwap": round(ind.vwap(h["high"], h["low"], c, h["volume"], 20), 2),
        }

    def market(self, ticker: str, holdings: dict[str, float]) -> dict[str, Any]:
        r = ind.returns(self._history(ticker)["close"])
        spy = ind.returns(self._history("SPY")["close"])
        corrs = {t: ind.correlation(r, ind.returns(self._history(t)["close"])) for t in holdings if t != ticker}
        best = max(corrs, key=corrs.get) if corrs else None
        portfolio = 0.0
        if holdings:
            series = {t: ind.returns(self._history(t)["close"]) for t in holdings}
            n = min(len(s) for s in series.values())
            total = sum(holdings.values()) or 1.0
            mix = [sum(series[t][-n:][i] * w / total for t, w in holdings.items()) for i in range(n)]
            portfolio = ind.correlation(r, mix)
        return {
            "realized_vol": round(ind.annualized_vol(r), 3),
            "beta": round(ind.beta(r, spy), 2),
            "max_corr_holding": best,
            "max_corr": round(corrs[best], 2) if best else 0.0,
            "corr_to_portfolio": round(portfolio, 2),
        }

    def quote(self, ticker: str) -> dict[str, float]:
        info = self._info(ticker)
        bid, ask = info.get("bid") or 0, info.get("ask") or 0
        if not bid or not ask or ask <= bid or (ask - bid) / bid > 0.005:
            # Off-hours quotes are often empty or stale-wide: fall back to last price ± 1 cent.
            last = self.close(ticker)
            bid, ask = round(last - 0.01, 2), round(last + 0.01, 2)
        return {"bid": float(bid), "ask": float(ask)}

    def _filing_url(self, ticker: str, f: dict[str, str], index: bool = False) -> str:
        base = f"https://www.sec.gov/Archives/edgar/data/{self._cik(ticker)}/{f['accession'].replace('-', '')}/"
        return base if index else base + f["doc"]

    def source(self, kind: str, ticker: str, form: str | None = None) -> tuple[str, str | None]:
        """Where each kind of data comes from, as a label and a link the user can open (D-040)."""
        t = ticker.upper()
        if kind in ("financials", "dilution", "section"):
            forms = (form,) if form else ("10-Q", "10-K")
            f = next((x for x in self._submissions(t) if x["form"] in forms), None)
            if f:
                return f"{f['form']} filed {f['date']}", self._filing_url(t, f, index=kind != "section")
        if kind == "insider":
            return "SEC Form 4 filings", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={self._cik(t)}&type=4&owner=include&count=40"
        if kind == "filings":
            return "SEC EDGAR filings", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={self._cik(t)}&owner=include&count=40"
        if kind == "institutional":
            return "Yahoo Finance holders", f"https://finance.yahoo.com/quote/{t}/holders"
        return "Yahoo Finance", f"https://finance.yahoo.com/quote/{t}"

    def close(self, ticker: str) -> float:
        info = self._info(ticker)
        return float(info.get("currentPrice") or info.get("regularMarketPrice") or self._history(ticker)["close"][-1])
