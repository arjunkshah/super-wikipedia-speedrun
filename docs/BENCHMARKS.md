# Benchmarks

Benchmarks use the frozen 30-race dataset in:

```text
benchmarks/data/frozen_30_races.json
```

The dataset contains:

- 15 chosen cross-domain article pairs
- 15 random article pairs sampled from `Special:Random`

## Run

```bash
python replay_benchmark.py
```

Equivalent direct command:

```bash
python benchmarks/replay_benchmark.py
```

## Current Result

Latest root-level no-persistent-cache replay:

```text
Runs: 30
Successes: 7/30
Average elapsed, all runs: 3.40s
Average elapsed, successful runs: 2.40s
Total network fetches: 242
```

Output artifacts:

```text
benchmarks/results/root_no_cache_replay_results.json
benchmarks/results/root_no_cache_replay_results.csv
```

## Rules

- No article-specific hardcoding.
- No persistent cache for benchmark claims.
- Session state must be cleared between benchmark races.
- Failures count toward all-run average using actual wall time.
