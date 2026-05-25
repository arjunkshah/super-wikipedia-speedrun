# Contributing

Thanks for working on Super Wikipedia Speedrun.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Development Checks

```bash
python -m py_compile web_app.py wiki_speedrun.py replay_benchmark.py diverse_benchmark.py src/wikispeedrun/solver.py
python wiki_speedrun.py "Python (programming language)" "Artificial intelligence"
python replay_benchmark.py
```

## Solver Guidelines

- Do not add article-specific hardcoded paths.
- Do not rely on persistent caches for benchmark claims.
- Keep Wikipedia request rates reasonable.
- Prefer general heuristics that work on unseen articles.
- Record benchmark settings when reporting performance.

## Pull Requests

Include:

- What changed
- Why it improves speed, success rate, reliability, or UX
- Benchmark command and result
- Any known tradeoffs
