# Super Wikipedia Speedrun

A fast, no-persistent-cache solver for the Wikipedia speedrun game.

Given a start article and a target article, the solver clicks only real
Wikipedia article links and tries to find a path under a tight wall-clock
budget. It ships with a CLI, a local web UI, and reproducible benchmark scripts.

Repository: <https://github.com/arjunkshah/super-wikipedia-speedrun>

## Features

- Live Wikipedia solving with no SQLite or cross-run page cache
- Article titles or full Wikipedia URLs as input
- BeautifulSoup + `lxml` link extraction
- Wikipedia REST summary API for compact target understanding
- MediaWiki search API for target-adjacent bridge hints
- Greedy priority search with soft, general heuristics
- Local browser UI for trying arbitrary article pairs
- Frozen 30-race benchmark dataset

## Quickstart

```bash
git clone https://github.com/arjunkshah/super-wikipedia-speedrun.git
cd super-wikipedia-speedrun
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## CLI

```bash
python wiki_speedrun.py "Python (programming language)" "Artificial intelligence"
```

Or, after `pip install -e .`:

```bash
wiki-speedrun "Taylor Swift" "Quantum mechanics" --time-limit 3.6
```

Useful knobs:

```bash
python wiki_speedrun.py \
  "https://en.wikipedia.org/wiki/Minecraft" \
  "https://en.wikipedia.org/wiki/World_War_II" \
  --beam 42 \
  --max-pages 16 \
  --max-depth 6 \
  --time-limit 3.6
```

## Web UI

```bash
python web_app.py
```

Open:

```text
http://127.0.0.1:8787
```

Paste two article titles or Wikipedia URLs, tune the search budget, and run the
solver from the browser.

## How It Works

The solver is designed for speed, not shortest-path proof.

For each race it:

1. Fetches the start article links with a lite HTML parse.
2. Fetches the target article summary through Wikipedia REST.
3. Uses MediaWiki search to discover target-adjacent bridge pages.
4. Scores outgoing links using token overlap, hashed cosine similarity, hub-page
   shape, domain patterns, bridge hits, and trap penalties.
5. Expands the best links first with a priority queue.
6. Stops at the deadline instead of crawling forever.

Benchmarks clear in-memory session state between races. There is no persistent
page cache in the active solver.

## Benchmarks

Replay the frozen 30-race dataset:

```bash
python replay_benchmark.py
```

Dataset:

```text
benchmarks/data/frozen_30_races.json
```

Latest no-persistent-cache replay from this workspace:

```text
Runs: 30
Successes: 7/30
Average elapsed, all runs: 3.40s
Average elapsed, successful runs: 2.40s
Total network fetches: 242
```

More details: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Project Layout

```text
src/wikispeedrun/solver.py      core solver and CLI entrypoint
web_app.py                      local HTTP server and JSON API
web/                            static browser UI
benchmarks/                     frozen dataset, benchmark runners, results
docs/ARCHITECTURE.md            solver architecture
docs/BENCHMARKS.md              benchmark rules and results
```

## Development

```bash
python -m py_compile web_app.py wiki_speedrun.py replay_benchmark.py diverse_benchmark.py src/wikispeedrun/solver.py
python wiki_speedrun.py "Python (programming language)" "Artificial intelligence"
python replay_benchmark.py
```

## Notes

Random obscure article pairs are hard under a 3.6 second no-cache budget. The
solver is meant to be fast and general, not guaranteed complete.

## License

MIT. See [LICENSE](LICENSE).
