# Architecture

Super Wikipedia Speedrun solves the Wikipedia game:

1. Start from one article.
2. Click only linked article words.
3. Reach a target article as fast as possible.

The solver is optimized for latency, not guaranteed shortest paths.

## Components

- `src/wikispeedrun/solver.py`  
  Core Wikipedia client, scraper, scoring heuristics, and priority search.

- `wiki_speedrun.py`  
  Thin CLI wrapper for local script usage.

- `web_app.py`  
  Small stdlib HTTP server. Serves `web/` assets and exposes `POST /api/solve`.

- `web/`  
  Static browser UI.

- `benchmarks/`  
  Frozen dataset, benchmark scripts, and recorded result artifacts.

## Request Model

The solver does not use a persistent SQLite cache. Each benchmark race clears
session state before solving.

For a race, the solver uses:

- Lite HTML fetch for the start/current page links
- Wikipedia REST summary for compact target text
- MediaWiki search API for target-adjacent bridge hints
- In-memory page dedup during the current race only

## Search Model

The search is a greedy priority search with a beam. Links are scored using:

- token overlap with the target
- hashed cosine similarity against target text
- bridge hits from Wikipedia search
- broad hub-page shape
- media, region, science, and history patterns
- penalties for narrow traps like songs, games, and parenthetical pages

The default deadline is `3.6s`. Races that do not find a path inside the budget
fail quickly instead of crawling the graph indefinitely.

## Tradeoff

This project optimizes for speed and demo usefulness. It does not prove the
shortest possible path, and obscure random pairs can miss within the default
deadline.
