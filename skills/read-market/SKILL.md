---
name: read-market
description: Reads one Kalshi or Polymarket market in full, covering exactly what makes it pay, its settlement source and dates, wording on ties, voids and revised data, prices, volume, price history, and the implied odds across its event. Use before relying on a market to hedge or inform a decision, or when someone asks what a market really settles on or what it implies.
---

# Read a market

    python scripts/eventneutral.py market kalshi:KXSTOWESNOW-24DEC26-GT65 --event
    python scripts/eventneutral.py history kalshi:KXSTOWESNOW-24DEC26-GT65 --days 30

The script is `scripts/eventneutral.py` in this skill's folder. Commands run from the user's project folder, so give its full path. Use `python3` if `python` isn't found.

`market` prints what Yes and No mean, the status and dates, prices, volume, the settlement source, the fee rate, the full rules, and any wording worth checking. `--event` adds the event's other markets and, when enough have quotes within 10 cents, the implied probability of each outcome. `history` prints daily prices.

Compare the rules with the user's actual exposure:
- what is measured, where, and by whom;
- when the measurement window ends, when trading closes, and when it settles;
- the exact threshold, and whether "above" excludes the threshold itself;
- what happens on a tie, a cancellation, a delay or a data revision.

List every difference and say whether it could leave the user unpaid while they still take the loss. Don't call a market a match while a difference is unresolved.

## Gotchas

- A price is only a fair read of the odds when the bid and ask are close. With a wide gap, say the market has no clear view.
- Kalshi's Yes condition is the market subtitle ("Above 65 inches"); No is everything else.
- Polymarket's settlement-source field is often empty. The full rules are in the description, which `market` prints.
- Trading can close before the event is decided, and Kalshi markets can close early once the outcome is certain.
