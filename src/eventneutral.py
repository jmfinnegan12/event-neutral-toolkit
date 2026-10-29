"""Find Kalshi and Polymarket markets that match a business risk, read them, and size a hedge.

Reads public market data only: no account, no key, no trading. Standard library only.

    python eventneutral.py search snowfall "ski resort"
    python eventneutral.py market kalshi:KXNORTHSTARSNOW-26DEC24-T90 --event
    python eventneutral.py history polymarket:first-snow-2026-buffalo-ny-by-october-31
    python eventneutral.py book kalshi:KXNORTHSTARSNOW-26DEC24-T90 --size 500
    python eventneutral.py hedge kalshi:KXNORTHSTARSNOW-26DEC24-T90 --loss 20000 --side no

Every command prints short text; add --json for the full result.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KALSHI = os.environ.get("KALSHI_API", "https://external-api.kalshi.com/trade-api/v2")
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
USER_AGENT = "eventneutral/0.1 (+https://github.com/jmfinnegan12/event-neutral-toolkit)"
CACHE = Path(os.environ.get("EVENTNEUTRAL_CACHE", Path.home() / ".cache" / "eventneutral"))

# About two requests a second keeps well under both exchanges' public limits.
PACE_SECONDS = 0.5
# Kalshi adds a few series a day, so a day-old series list misses little.
SERIES_MAX_AGE = 24 * 3600
# How many of the best-matching Kalshi series to fetch open markets for.
SERIES_TO_FETCH = 12
# A bid-ask gap above 10 cents makes the midpoint a poor estimate of the probability.
WIDE_SPREAD = 0.10

# Kalshi's general fee table: taker fee = 0.07 x multiplier x C x P x (1 - P), rounded up to the cent.
# From https://kalshi.com/docs/kalshi-fee-schedule.pdf, which often answers HTTP 429 to scripts.
KALSHI_TAKER_RATE = 0.07
# Polymarket's taker fee = C x rate x p x (1 - p), with the rate set by category.
# From https://docs.polymarket.com/trading/fees.md (geopolitics is fee-free and reports fees disabled).
POLYMARKET_RATES = {
    "crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04, "economics": 0.05,
    "culture": 0.05, "weather": 0.05, "mentions": 0.04, "tech": 0.04, "geopolitics": 0.0,
}
POLYMARKET_DEFAULT_RATE = 0.05  # the "Other / General" row

# Rule wording that changes what a market pays, adapted from a checklist used on sports futures.
RULE_FLAGS = {
    "tie": r"\b(tie|ties|tied|dead heat|co-champions?|co-winners?)\b",
    "void or delay": r"\b(cancel\w*|void\w*|postpon\w*|suspend\w*|abandon\w*|delay\w*|not (?:be )?played)\b",
    "50-50 payout": r"\b50[-/]50\b",
    "revised data": r"\b(revis\w*|preliminary|initial release|first release)\b",
}


class Fail(Exception):
    """An error the user can act on; main() prints it without a traceback."""


# ---------------------------------------------------------------- fetching

_last_request = 0.0


def get(url, params=None):
    global _last_request
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    for attempt in range(4):
        wait = PACE_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Fail(f"not found: {url}. Run search to get a current id.")
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise Fail(f"HTTP {e.code} from {url}. Wait a minute and try again.")
        except urllib.error.URLError as e:
            raise Fail(f"could not reach {url} ({e.reason}). Check the internet connection.")


def num(value):
    """Exchanges send prices and sizes as strings, numbers, or empty. Returns a float or None."""
    if value is None or value == "":
        return None
    return float(value)


def quote(value, empty):
    """Kalshi reports a side with no orders as a bid of 0 or an ask of 1."""
    value = num(value)
    return None if value is None or value == empty else value


def day(timestamp):
    return timestamp[:10] if timestamp else None


def parse_id(market_id):
    venue, _, key = market_id.partition(":")
    if venue not in ("kalshi", "polymarket") or not key:
        raise Fail(f"{market_id!r} is not an id from search. Ids look like kalshi:TICKER or polymarket:slug.")
    return venue, key


# ---------------------------------------------------------------- Kalshi

def kalshi_series_list():
    """Every Kalshi series, cached for a day. Kalshi has no text search, so search runs on this."""
    path = CACHE / "kalshi_series.json"
    if path.exists() and time.time() - path.stat().st_mtime < SERIES_MAX_AGE:
        return json.loads(path.read_text(encoding="utf-8"))
    series = [
        {
            "ticker": s["ticker"],
            "title": s.get("title") or "",
            "category": s.get("category") or "",
            "tags": s.get("tags") or [],
            "settlement_sources": [src.get("url") or src.get("name") for src in s.get("settlement_sources") or []],
            "contract_terms_url": s.get("contract_terms_url"),
            "fee_type": s.get("fee_type"),
            "fee_multiplier": s.get("fee_multiplier"),
        }
        for s in get(f"{KALSHI}/series").get("series") or []
    ]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(series), encoding="utf-8")
    return series


def kalshi_series(ticker):
    for s in kalshi_series_list():
        if s["ticker"] == ticker:
            return s
    return get(f"{KALSHI}/series/{ticker}")["series"]


def kalshi_series_ticker(event_ticker):
    # Event tickers start with their series ticker; the event lookup covers the exceptions.
    prefix = event_ticker.split("-")[0]
    if any(s["ticker"] == prefix for s in kalshi_series_list()):
        return prefix
    return get(f"{KALSHI}/events/{event_ticker}")["event"]["series_ticker"]


def kalshi_open_markets(**filters):
    markets, cursor = [], None
    for _ in range(10):
        page = get(f"{KALSHI}/markets", {"status": "open", "limit": 1000, "mve_filter": "exclude", "cursor": cursor, **filters})
        markets += page.get("markets") or []
        cursor = page.get("cursor")
        if not cursor:
            return markets
    raise Fail(f"more than 10,000 open markets for {filters}; narrow the search.")


def kalshi_row(m):
    title = m.get("title") or ""
    sub = m.get("yes_sub_title") or ""
    if sub and sub.lower() not in title.lower():
        title = f"{title}: {sub}"
    return {
        "id": f"kalshi:{m['ticker']}",
        "title": title,
        "close": day(m.get("close_time")),
        "bid": quote(m.get("yes_bid_dollars"), 0),
        "ask": quote(m.get("yes_ask_dollars"), 1),
        "last": num(m.get("last_price_dollars")),
        "volume": num(m.get("volume_fp")) or 0.0,
        "volume_24h": num(m.get("volume_24h_fp")) or 0.0,
        "open_interest": num(m.get("open_interest_fp")),
    }


def matches(terms, text):
    """How many search terms appear in the text, each matched from the start of a word."""
    return sum(1 for t in terms if re.search(r"\b" + re.escape(t), text, re.I))


def kalshi_search(terms):
    scored = []
    for s in kalshi_series_list():
        score = matches(terms, " ".join([s["title"], s["category"], *s["tags"]]))
        if score:
            scored.append((score, s))
    scored.sort(key=lambda pair: -pair[0])
    rows = []
    for score, s in scored[:SERIES_TO_FETCH]:
        for m in kalshi_open_markets(series_ticker=s["ticker"]):
            row = kalshi_row(m) | {"match": score}
            # Ladder markets are titled only by their rung ("Above 100 inches").
            if s["title"].lower() not in row["title"].lower():
                row["title"] = f"{s['title']}: {row['title']}"
            rows.append(row)
    return rows


def kalshi_fee_rate(series):
    return KALSHI_TAKER_RATE * (series.get("fee_multiplier") or 0)


def kalshi_market(ticker):
    m = get(f"{KALSHI}/markets/{ticker}")["market"]
    series = kalshi_series(kalshi_series_ticker(m["event_ticker"]))
    out = kalshi_row(m)
    if series["title"].lower() not in out["title"].lower():
        out["title"] = f"{series['title']}: {out['title']}"
    yes = m.get("yes_sub_title") or "Yes"
    no = m.get("no_sub_title")
    out.update({
        "venue": "kalshi",
        "status": m.get("status"),
        "yes_means": yes,
        # Ladder markets repeat the Yes wording as the No subtitle.
        "no_means": no if no and no != yes else f"Not: {yes}",
        "expires": day(m.get("expected_expiration_time") or m.get("expiration_time")),
        "rules": "\n".join(r for r in (m.get("rules_primary"), m.get("rules_secondary")) if r),
        "early_close": m.get("early_close_condition") if m.get("can_close_early") else None,
        "settlement_sources": series.get("settlement_sources") or [],
        "contract_terms": series.get("contract_terms_url"),
        "fee_rate": kalshi_fee_rate(series),
        "event": m["event_ticker"],
        "series": series["ticker"],
        "strike_type": m.get("strike_type"),
        "floor_strike": m.get("floor_strike"),
        "cap_strike": m.get("cap_strike"),
    })
    return out


def kalshi_book(ticker):
    """Asks to buy each side. Kalshi lists bids only: a No bid at p is a Yes ask at 1 - p."""
    book = get(f"{KALSHI}/markets/{ticker}/orderbook")["orderbook_fp"]
    yes_bids = [(num(p), num(s)) for p, s in book.get("yes_dollars") or [] if num(s) > 0]
    no_bids = [(num(p), num(s)) for p, s in book.get("no_dollars") or [] if num(s) > 0]
    return {
        "yes": sorted((round(1 - p, 4), s) for p, s in no_bids),
        "no": sorted((round(1 - p, 4), s) for p, s in yes_bids),
    }


def kalshi_history(ticker, series, days):
    end = int(time.time())
    data = get(f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks",
               {"start_ts": end - days * 86400, "end_ts": end, "period_interval": 1440})
    points = []
    for c in data.get("candlesticks") or []:
        close = num((c.get("price") or {}).get("close_dollars"))
        if close is None:  # no trade that day: use the quote midpoint
            bid = num((c.get("yes_bid") or {}).get("close_dollars"))
            ask = num((c.get("yes_ask") or {}).get("close_dollars"))
            close = (bid + ask) / 2 if bid is not None and ask is not None else None
        stamp = datetime.fromtimestamp(c["end_period_ts"], timezone.utc).strftime("%Y-%m-%d")
        points.append({"date": stamp, "price": close, "volume": num(c.get("volume_fp"))})
    return points


def kalshi_event_markets(event_ticker):
    return [kalshi_row(m) | {"strike_type": m.get("strike_type"), "floor_strike": m.get("floor_strike"),
                             "cap_strike": m.get("cap_strike")}
            for m in kalshi_open_markets(event_ticker=event_ticker)]


# ---------------------------------------------------------------- Polymarket

def pm_row(m):
    return {
        "id": f"polymarket:{m['slug']}",
        "title": m.get("question") or "",
        "close": day(m.get("endDate")),
        # Gamma's quotes are cached and can lag; market and book read the live order book.
        "bid": num(m.get("bestBid")),
        "ask": num(m.get("bestAsk")),
        "last": num(m.get("lastTradePrice")),
        "volume": num(m.get("volumeNum")) or num(m.get("volume")) or 0.0,
        "volume_24h": num(m.get("volume24hr")) or 0.0,
        "open_interest": None,
    }


def pm_search(terms):
    # Polymarket's search is loose ("snowfall" can return acquisition markets), so keep only
    # markets whose own or event title contains a term.
    rows = {}
    for term in terms:
        found = get(f"{GAMMA}/public-search", {"q": term, "limit_per_type": 10, "events_status": "active"})
        for event in found.get("events") or []:
            for m in event.get("markets") or []:
                score = matches(terms, f"{event.get('title') or ''} {m.get('question') or ''}")
                if m.get("slug") and not m.get("closed") and score:
                    rows[m["slug"]] = pm_row(m) | {"match": score}
    return list(rows.values())


def pm_gamma_market(slug):
    found = get(f"{GAMMA}/markets", {"slug": slug})
    if not found:
        raise Fail(f"no Polymarket market {slug!r}. Run search to get a current id.")
    return found[0]


def pm_tokens(m):
    """The order-book token for each side. Yes is the first listed outcome, No the second."""
    if not m.get("clobTokenIds"):
        raise Fail(f"Polymarket market {m.get('slug')!r} has no order book.")
    tokens = json.loads(m["clobTokenIds"])
    outcomes = json.loads(m.get("outcomes") or '["Yes", "No"]')
    return {"yes": tokens[0], "no": tokens[1]}, outcomes


def pm_fee_rate(m):
    if not m.get("feesEnabled") or m.get("feeType") == "zero_fees":
        return 0.0
    tags = get(f"{CLOB}/markets/{m['conditionId']}").get("tags") or []
    for tag in tags:
        if tag.lower() in POLYMARKET_RATES:
            return POLYMARKET_RATES[tag.lower()]
    return POLYMARKET_DEFAULT_RATE


def pm_market(slug):
    m = pm_gamma_market(slug)
    tokens, outcomes = pm_tokens(m)
    book = pm_book(tokens["yes"])
    out = pm_row(m)
    out.update({
        "venue": "polymarket",
        "status": "closed" if m.get("closed") else "open",
        "bid": book["bids"][0][0] if book["bids"] else None,
        "ask": book["asks"][0][0] if book["asks"] else None,
        "yes_means": outcomes[0],
        "no_means": outcomes[1],
        "expires": day(m.get("endDate")),
        # resolutionSource is often empty; the full rules are in the description.
        "rules": m.get("description") or "",
        "early_close": None,
        "settlement_sources": [m["resolutionSource"]] if m.get("resolutionSource") else [],
        "contract_terms": None,
        "fee_rate": pm_fee_rate(m),
        "event": (m.get("events") or [{}])[0].get("slug"),
        "neg_risk": bool(m.get("negRisk")),
    })
    return out


def pm_book(token):
    """Bids and asks for one outcome token, best first. Polymarket lists both with the best price last."""
    book = get(f"{CLOB}/book", {"token_id": token})
    asks = sorted((num(a["price"]), num(a["size"])) for a in book.get("asks") or [] if num(a["size"]) > 0)
    bids = sorted(((num(b["price"]), num(b["size"])) for b in book.get("bids") or [] if num(b["size"]) > 0),
                  reverse=True)
    return {"asks": asks, "bids": bids}


def pm_history(token, days):
    # Polymarket refuses long start/end windows, so fetch daily points for all time and trim.
    data = get(f"{CLOB}/prices-history", {"market": token, "interval": "max", "fidelity": 1440})
    cutoff = time.time() - days * 86400
    return [{"date": datetime.fromtimestamp(p["t"], timezone.utc).strftime("%Y-%m-%d"), "price": p["p"], "volume": None}
            for p in data.get("history") or [] if p["t"] >= cutoff]


def pm_event_markets(event_slug):
    found = get(f"{GAMMA}/events", {"slug": event_slug})
    markets = found[0].get("markets") or [] if found else []
    return [pm_row(m) for m in markets if not m.get("closed")]


# ---------------------------------------------------------------- math

def walk(asks, contracts):
    """Buy `contracts` up the asks (price, size), best first. Returns the fills taken."""
    fills, left = [], contracts
    for price, size in asks:
        if left <= 0:
            break
        take = min(size, left)
        fills.append((price, take))
        left -= take
    return fills


def fill_summary(asks, contracts, fee_rate, venue):
    fills = walk(asks, contracts)
    filled = sum(s for _, s in fills)
    cost = sum(p * s for p, s in fills)
    fee = sum(fee_rate * s * p * (1 - p) for p, s in fills)
    if venue == "kalshi":
        fee = math.ceil(round(fee * 100, 6)) / 100  # Kalshi rounds fees up to the cent
    return {
        "wanted": contracts,
        "filled": filled,
        "best_ask": asks[0][0] if asks else None,
        "average_price": cost / filled if filled else None,
        "last_price": fills[-1][0] if fills else None,
        "cost": cost,
        "fee": fee,
        "on_offer": sum(s for _, s in asks),
    }


def hedge(loss, cover, side_asks, fee_rate, venue, price=None):
    """Contracts pay $1 each when the loss happens, so covering $L takes L contracts.

    Whatever happens, the business ends down by the hedge's cost: if the event happens the
    contracts pay back the covered loss, and if it doesn't they expire worthless.
    """
    contracts = math.ceil(loss * cover)
    if price is not None:
        side_asks = [(price, float(contracts))]
    fill = fill_summary(side_asks, contracts, fee_rate, venue)
    total = fill["cost"] + fill["fee"]
    paid_out = fill["filled"]
    return fill | {
        "loss": loss,
        "covered": paid_out,
        "total_cost": total,
        "if_event": -loss + paid_out - total,
        "if_not": -total,
    }


def tight(m):
    """A two-sided quote no wider than WIDE_SPREAD, so its midpoint means something."""
    return m["bid"] is not None and m["ask"] is not None and 0 <= m["ask"] - m["bid"] <= WIDE_SPREAD


def ranges(markets):
    """Implied probability of each outcome range in a laddered or multi-outcome event.

    Uses only markets with tight quotes. "Above X" ladders are differenced into ranges, then
    all ranges are scaled to sum to 1. Adapted from the de-vig step used on Kalshi's Fed and
    CPI ladders.
    """
    priced = [m for m in markets if tight(m)]
    if len(priced) < 2:
        return []

    def mid(m):
        return (m["bid"] + m["ask"]) / 2

    if all(m.get("strike_type") == "greater" and m.get("floor_strike") is not None for m in priced):
        ladder = sorted(priced, key=lambda m: m["floor_strike"])
        above = [mid(m) for m in ladder]
        edges = [m["floor_strike"] for m in ladder]
        raw = [(f"{edges[0]:g} or less", 1 - above[0])]
        raw += [(f"{edges[i]:g} to {edges[i + 1]:g}", above[i] - above[i + 1]) for i in range(len(edges) - 1)]
        raw.append((f"above {edges[-1]:g}", above[-1]))
    else:
        raw = [(m["title"], mid(m)) for m in priced]
    raw = [(label, max(p, 0.0)) for label, p in raw]  # bid/ask noise can push a difference below 0
    total = sum(p for _, p in raw)
    return [{"outcome": label, "probability": p / total} for label, p in raw] if total else []


def rule_flags(text):
    flags = []
    for name, pattern in RULE_FLAGS.items():
        m = re.search(pattern, text or "", re.I)
        if m:
            snippet = " ".join(text[max(0, m.start() - 90): m.end() + 90].split())
            flags.append({"flag": name, "text": snippet})
    return flags


# ---------------------------------------------------------------- commands

def market(market_id):
    venue, key = parse_id(market_id)
    return kalshi_market(key) if venue == "kalshi" else pm_market(key)


def side_book(market_id, side):
    """The asks for one side, plus the fee rate, venue and what that side pays out on."""
    venue, key = parse_id(market_id)
    if venue == "kalshi":
        m = get(f"{KALSHI}/markets/{key}")["market"]
        series = kalshi_series(kalshi_series_ticker(m["event_ticker"]))
        yes = m.get("yes_sub_title") or "Yes"
        pays_if = yes if side == "yes" else f"Not: {yes}"
        return kalshi_book(key)[side], kalshi_fee_rate(series), venue, pays_if
    m = pm_gamma_market(key)
    tokens, outcomes = pm_tokens(m)
    return pm_book(tokens[side])["asks"], pm_fee_rate(m), venue, outcomes[0 if side == "yes" else 1]


def cmd_search(args):
    rows = kalshi_search(args.terms) + pm_search(args.terms)
    rows.sort(key=lambda r: (r["match"], r["volume"]), reverse=True)
    return {"found": len(rows), "markets": rows[: args.limit]}


def cmd_market(args):
    m = market(args.id)
    m["flags"] = rule_flags(m["rules"])
    if args.event and m.get("event"):
        siblings = kalshi_event_markets(m["event"]) if m["venue"] == "kalshi" else pm_event_markets(m["event"])
        m["event_markets"] = siblings
        m["ranges"] = ranges(siblings)
        m["ranges_from"] = sum(1 for s in siblings if tight(s))
    return m


def cmd_history(args):
    venue, key = parse_id(args.id)
    if venue == "kalshi":
        m = get(f"{KALSHI}/markets/{key}")["market"]
        points = kalshi_history(key, kalshi_series_ticker(m["event_ticker"]), args.days)
    else:
        tokens, _ = pm_tokens(pm_gamma_market(key))
        points = pm_history(tokens["yes"], args.days)
    return {"id": args.id, "days": args.days, "history": points}


def cmd_book(args):
    asks, fee_rate, venue, _ = side_book(args.id, args.side)
    out = fill_summary(asks, args.size, fee_rate, venue)
    best = out["best_ask"]
    out["within"] = sum(s for p, s in asks if best is not None and p <= best + args.within)
    out.update({"id": args.id, "side": args.side, "window": args.within, "levels": asks[:20]})
    return out


def cmd_hedge(args):
    asks, fee_rate, venue, pays_if = side_book(args.id, args.side)
    out = hedge(args.loss, args.cover, asks, fee_rate, venue, args.price)
    out.update({"id": args.id, "side": args.side, "fee_rate": fee_rate, "pays_if": pays_if})
    return out


# ---------------------------------------------------------------- text output

def money(x):
    if x is None:
        return "n/a"
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def price(x):
    if x is None:
        return "--"
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def show_search(r):
    lines = [f"{r['found']} open markets found; showing {len(r['markets'])}, best match and most traded first."]
    for m in r["markets"]:
        lines.append(f"{m['id']}  {m['title']}  | closes {m['close']} | yes {price(m['bid'])}/{price(m['ask'])}"
                     f" | volume {m['volume']:,.0f}")
    return lines


def show_market(m):
    lines = [m["id"], m["title"],
             f"Yes means: {m['yes_means']}. No means: {m['no_means']}.",
             f"Status {m['status']}, trading closes {m['close']}, expected to settle {m['expires']}.",
             f"Yes bid {price(m['bid'])}, ask {price(m['ask'])}, last {price(m['last'])}. "
             f"Volume {m['volume']:,.0f}, last 24h {m['volume_24h']:,.0f}"
             + (f", open interest {m['open_interest']:,.0f}." if m["open_interest"] is not None else ".")]
    if m["settlement_sources"]:
        lines.append("Settlement source: " + ", ".join(m["settlement_sources"]))
    if m["contract_terms"]:
        lines.append(f"Contract terms: {m['contract_terms']}")
    lines.append(f"Taker fee rate: {m['fee_rate']:g} (fee = rate x contracts x price x (1 - price)).")
    lines.append("Rules: " + m["rules"])
    if m["early_close"]:
        lines.append("Can close early: " + m["early_close"])
    for f in m["flags"]:
        lines.append(f"Check the {f['flag']} wording: \"{f['text']}\"")
    if "event_markets" in m:
        lines.append(f"The event has {len(m['event_markets'])} open markets.")
        if m["ranges"]:
            lines.append(f"Implied probability, from the {m['ranges_from']} with quotes "
                         f"within {WIDE_SPREAD * 100:.0f} cents:")
            lines += [f"  {r['outcome']}: {r['probability']:.0%}" for r in m["ranges"]]
        else:
            lines.append("Too few of them have tight quotes to estimate a probability for each outcome.")
    return lines


def show_history(r):
    if not r["history"]:
        return [f"No price history for {r['id']} in the last {r['days']} days."]
    return [f"{p['date']}  {price(p['price'])}" + (f"  volume {p['volume']:,.0f}" if p["volume"] else "")
            for p in r["history"]]


def show_book(r):
    if not r["filled"]:
        return [f"Nothing is on offer on the {r['side']} side of {r['id']}."]
    lines = [f"Best {r['side']} ask {price(r['best_ask'])}. {r['within']:,.0f} contracts on offer within "
             f"{r['window']:g} of it; {r['on_offer']:,.0f} in the whole book."]
    if r["filled"] < r["wanted"]:
        lines.append(f"Only {r['filled']:,.0f} of the {r['wanted']:,.0f} wanted are on offer.")
    lines.append(f"Buying {r['filled']:,.0f} averages {price(r['average_price'])} and reaches {price(r['last_price'])}, "
                 f"{(r['last_price'] - r['best_ask']) * 100:.1f} cents above the best ask. "
                 f"Cost {money(r['cost'])} plus {money(r['fee'])} in fees.")
    return lines


def show_hedge(r):
    if not r["filled"]:
        return [f"Nothing is on offer on the {r['side']} side of {r['id']}, so there is nothing to hedge with."]
    share = "" if r["wanted"] >= r["loss"] else f"{r['wanted'] / r['loss']:.0%} of "
    meaning = "" if r["pays_if"].lower() == r["side"] else f" ({r['pays_if']})"
    lines = [f"To cover {share}a {money(r['loss'])} loss: buy {r['wanted']:,} {r['side']} contracts, "
             f"each paying $1 if the market settles {r['side']}{meaning}."]
    if r["filled"] < r["wanted"]:
        lines.append(f"Only {r['filled']:,.0f} are on offer, so this covers {money(r['covered'])}.")
    lines.append(f"Cost {money(r['cost'])} at an average {price(r['average_price'])}, plus {money(r['fee'])} in fees: "
                 f"{money(r['total_cost'])} in all.")
    lines.append(f"If {r['pays_if']}: the business loses {money(r['loss'])}, the contracts pay {money(r['covered'])}, "
                 f"net {money(r['if_event'])}.")
    lines.append(f"Otherwise: the contracts expire worthless, net {money(r['if_not'])}.")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="open markets on both exchanges matching any of the words")
    p.add_argument("terms", nargs="+", help="words or quoted phrases; several synonyms find more")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(run=cmd_search, show=show_search)

    p = sub.add_parser("market", help="one market's rules, settlement source, prices and fees")
    p.add_argument("id")
    p.add_argument("--event", action="store_true", help="also list the event's other markets and implied ranges")
    p.set_defaults(run=cmd_market, show=show_market)

    p = sub.add_parser("history", help="daily prices")
    p.add_argument("id")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(run=cmd_history, show=show_history)

    p = sub.add_parser("book", help="what buying a given size costs and how far it moves the price")
    p.add_argument("id")
    p.add_argument("--size", type=int, required=True, help="contracts to buy")
    p.add_argument("--side", choices=["yes", "no"], default="yes")
    p.add_argument("--within", type=float, default=0.05, help="price window above the best ask (default 0.05)")
    p.set_defaults(run=cmd_book, show=show_book)

    p = sub.add_parser("hedge", help="contracts, cost and payoff to cover a dollar loss")
    p.add_argument("id")
    p.add_argument("--loss", type=float, required=True, help="dollars lost if the bad outcome happens")
    p.add_argument("--side", choices=["yes", "no"], required=True, help="the side that pays when the loss happens")
    p.add_argument("--cover", type=float, default=1.0, help="share of the loss to cover (default 1)")
    p.add_argument("--price", type=float, help="assume this price instead of reading the order book")
    p.set_defaults(run=cmd_hedge, show=show_hedge)

    args = parser.parse_args(argv)
    try:
        result = args.run(args)
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print("\n".join(args.show(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
