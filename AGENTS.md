The tool's only source is `src/eventneutral.py`. Each `skills/*/scripts/eventneutral.py` is a copy made by `python tools/sync.py`; never edit a copy.

Run the tests with `python -m unittest discover tests` before committing. They fail if a copy differs from the source.
