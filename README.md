# Event Neutral toolkit

Agent skills that find Kalshi and Polymarket prediction markets matching a business risk, read what each one actually settles on, check how much can be bought near the price, and size a hedge.

They read public market data only. Nothing needs an account or API key, and nothing places trades. The one script needs Python 3.9 or later and no packages.

## Install

For any agent that reads [Agent Skills](https://agentskills.io) (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot and others):

```
npx skills add jmfinnegan12/event-neutral-toolkit
```

For Claude Code, as a plugin:

```
/plugin marketplace add jmfinnegan12/event-neutral-toolkit
/plugin install event-neutral@event-neutral-toolkit
```

Or copy the folders in `skills/` into your agent's skills folder.

## Skills

- `find-markets` pins down the event, the date and the dollars at stake, then searches both exchanges.
- `read-market` reads one market's rules, settlement source, dates, prices and history, and the implied odds across its event.
- `check-liquidity` works out what buying a given number of contracts costs and how far it moves the price.
- `size-hedge` gives the contracts to buy, the cost, and the result whether or not the event happens.

Each skill calls the same script, which also runs on its own. Add `--json` to any command for the full result.

```
$ python src/eventneutral.py search "fed funds" --limit 2
451 open markets found; showing 2, best match and most traded first.
kalshi:KXFED-26DEC-T4.50  Fed funds rate: Will the upper bound of the federal funds rate be above 4.50% following the Fed's Dec 9, 2026 meeting?  | closes 2026-12-09 | yes 0.01/0.02 | volume 295,877
kalshi:KXFED-26DEC-T4.00  Fed funds rate: Will the upper bound of the federal funds rate be above 4.00% following the Fed's Dec 9, 2026 meeting?  | closes 2026-12-09 | yes 0.82/0.83 | volume 98,009

$ python src/eventneutral.py book kalshi:KXFED-26DEC-T4.25 --size 10000
Best yes ask 0.03. 32,060 contracts on offer within 5 cents of it; 1,046,350 in the whole book.
Buying 10,000 averages 0.03 and reaches 0.03, 0.0 cents above the best ask. Cost $300.00 plus $20.37 in fees.

$ python src/eventneutral.py hedge kalshi:KXFED-26DEC-T4.25 --loss 10000 --side yes
To cover a $10,000.00 loss: buy 10,000 yes contracts, each paying $1 if the market settles yes (Above 4.25%).
Cost $300.00 at an average 0.03, plus $20.37 in fees: $320.37 in all.
If it settles yes: the business loses $10,000.00, the contracts pay $10,000.00, net -$320.37.
If it settles no: the contracts expire worthless, net -$320.37.
```

The other two commands are `market <id> [--event]` and `history <id> [--days N]`.

## How the numbers work

Each contract pays $1 if its side wins, so covering a loss of $L$ dollars takes $L$ contracts. The cost is the walk up the order book for that many contracts, $\sum_i p_i s_i$ over the price levels taken. With full cover the business ends down by that cost whichever way the event goes.

Fees are estimates from each exchange's published table:

- Kalshi: $0.07 \times m \times C \times p(1-p)$, rounded up to the cent, where $m$ is the series fee multiplier ([fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)).
- Polymarket: $r \times C \times p(1-p)$, with the rate $r$ set by market category ([fees](https://docs.polymarket.com/trading/fees.md)).

## Limits

- Kalshi has no text search. The script matches words against Kalshi's list of series, cached for a day in `~/.cache/eventneutral`, and uses Polymarket's own search.
- Order books are snapshots, and thin markets change quickly.
- polymarket.com is view-only in the United States.
- Only open markets are searched, and Kalshi history covers only its live data.

## Development

`src/eventneutral.py` is the only source. `python tools/sync.py` copies it into each skill, because skill installers copy only a skill's own folder. `python -m unittest discover tests` runs the tests, which also fail if a copy is out of date.

Built with Claude Code. MIT license.
