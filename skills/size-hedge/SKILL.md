---
name: size-hedge
description: Works out a prediction-market hedge for a dollar loss, giving how many contracts to buy, the cost at current order-book prices including fees, and the result for the business whether or not the event happens. Use when someone wants to offset a specific financial exposure with a Kalshi or Polymarket market.
---

# Size a hedge

    python scripts/eventneutral.py hedge kalshi:KXSTOWESNOW-24DEC26-GT65 --loss 20000 --side no

The script is `scripts/eventneutral.py` in this skill's folder. Commands run from the user's project folder, so give its full path. Use `python3` if `python` isn't found.

- `--loss`: the dollars the business loses if the bad outcome happens.
- `--side`: the side that pays when it happens. A ski area that loses money if snowfall stays at 65 inches or less buys No on "Above 65 inches".
- `--cover`: the share of the loss to cover, 1 by default. Covering half halves both the cost and the protection.
- `--price`: assume a price instead of reading the book, for what-if questions.

Each contract pays $1, so covering a loss of L dollars takes L contracts. The cost is what those contracts cost up the order book, plus fees. With full cover the business ends down by about that cost whatever happens: the contracts repay the loss if it happens and expire worthless if it doesn't.

Show the contracts, the cost and both outcomes. Then say what the hedge leaves uncovered: any gap between the market's rules and the real exposure (from read-market), a book too thin for the size (from check-liquidity), and price moves between now and buying.

## Gotchas

- When the book is too thin for the full size, the tool covers only what's on offer and says so.
- A hedge priced near 1 costs almost what it pays out, which means the market expects the loss.
