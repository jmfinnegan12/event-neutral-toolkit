---
name: check-liquidity
description: Checks how many contracts a Kalshi or Polymarket market has on offer near its price, what buying a given number would cost on average, and how far it would move the price. Use after choosing a market to hedge with and before sizing the hedge, or when someone asks whether a market is deep enough for a given size.
---

# Check liquidity

    python scripts/eventneutral.py book kalshi:KXFED-26DEC-T4.50 --side yes --size 3000

The script is `scripts/eventneutral.py` in this skill's folder. Commands run from the user's project folder, so give its full path. Use `python3` if `python` isn't found.

`--side` is the side the user would buy: the one that pays when their loss happens. `--size` counts contracts, and each pays $1, so a $20,000 exposure is 20,000 contracts. The output gives the best ask, the contracts on offer within 5 cents of it (change with `--within`), the average and last price for the size, and the cost and fees.

Tell the user whether the market can take their size. If it can't, say how much it can take before the price moves further than they'd accept.

## Gotchas

- The book is a snapshot. Depth comes and goes, especially in thin markets, so check again just before acting.
- Kalshi lists only bids. The tool turns them into asks for each side (a No bid at 0.75 is a Yes ask at 0.25).
- Fees are estimates: Kalshi's from its general fee table, Polymarket's from its table by category. Some markets charge none.
