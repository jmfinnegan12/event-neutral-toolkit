---
name: find-markets
description: Finds open Kalshi and Polymarket prediction markets that match a business risk, need or question. Use when someone describes an event that could hurt or help a business (weather, a game, a rate decision, an election, a price) and wants to know whether a market exists to hedge it or to learn what traders expect.
---

# Find markets

First pin down three things, asking only for what's missing:
- the event, as something that either happens or doesn't ("Stowe gets 65 inches of snow or less by December 24");
- the date it's decided;
- the dollars at stake if it goes the wrong way.

Then search, passing several words and synonyms in one call. A market matches when any of them starts a word in its title.

    python scripts/eventneutral.py search snowfall snow Stowe

The script is `scripts/eventneutral.py` in this skill's folder. Commands run from the user's project folder, so give its full path. Use `python3` if `python` isn't found. It needs Python 3.9 or later and nothing else.

Each row gives an id, the title, the close date, the Yes bid and ask, and volume, best matches first. Pick the few closest to the user's event and read each with the read-market skill before calling it a match: titles hide differences in place, dates, thresholds and data sources.

## Gotchas

- Kalshi has no text search. The tool matches words against Kalshi's series titles, categories and tags, so search for the kind of event ("snowfall", "fed funds", "gas price"), not the kind of business.
- Kalshi often splits one event into a ladder of markets (above 45, 55, 65 inches). Choose the rung nearest the user's threshold.
- Polymarket prices in search rows come from Polymarket's cache and can lag. `market` and `book` read the live order book.
- polymarket.com is view-only in the United States, so a US business may only be able to trade the Kalshi markets.
- Ids look like `kalshi:TICKER` or `polymarket:slug`. The other commands take them as given.
