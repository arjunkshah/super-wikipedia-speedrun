#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
import time

from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.diverse_benchmark import QuietConsole
from wikispeedrun import WikiClient, solve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay the saved 30-race dataset.")
    parser.add_argument("--dataset", default=str(ROOT / "benchmarks/data/frozen_30_races.json"))
    parser.add_argument("--out-json", default=str(ROOT / "benchmarks/results/replay_benchmark_results.json"))
    parser.add_argument("--out-csv", default=str(ROOT / "benchmarks/results/replay_benchmark_results.csv"))
    parser.add_argument("--beam", type=int, default=42)
    parser.add_argument("--max-pages", type=int, default=16)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--time-limit", type=float, default=3.6)
    parser.add_argument("--min-interval", type=float, default=0.18)
    parser.add_argument("--race-interval", type=float, default=0.4, help="Pause between races")
    return parser.parse_args()


def load_pairs(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    return [{"run": row["run"], "type": row["type"], "start": row["start"], "target": row["target"]} for row in rows]


def summarize(rows: list[dict], console: Console, out_json: str, out_csv: str) -> None:
    successes = [row for row in rows if row["success"]]
    all_elapsed = [row["elapsed"] for row in rows if row["elapsed"] is not None]
    elapsed_values = [row["elapsed"] for row in successes if row["elapsed"] is not None]
    click_values = [row["clicks"] for row in successes]
    fetch_values = [row["fetches"] for row in rows]

    summary = Table(title="Replay Benchmark: Same 30 Pairs")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Runs", str(len(rows)))
    summary.add_row("Successes", f"{len(successes)}/{len(rows)}")
    summary.add_row("Success rate", f"{len(successes) / len(rows):.1%}")
    summary.add_row("Avg clicks", f"{statistics.mean(click_values):.2f}" if click_values else "n/a")
    summary.add_row("Median clicks", f"{statistics.median(click_values):.2f}" if click_values else "n/a")
    summary.add_row("Avg elapsed (all runs)", f"{statistics.mean(all_elapsed):.2f}s" if all_elapsed else "n/a")
    summary.add_row("Avg elapsed (successes)", f"{statistics.mean(elapsed_values):.2f}s" if elapsed_values else "n/a")
    summary.add_row("Median elapsed (successes)", f"{statistics.median(elapsed_values):.2f}s" if elapsed_values else "n/a")
    summary.add_row("Avg network fetches", f"{statistics.mean(fetch_values):.2f}")
    summary.add_row("Total network fetches", str(sum(fetch_values)))
    console.print(summary)

    table = Table(title="Replay Results")
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Start")
    table.add_column("Target")
    table.add_column("Clicks", justify="right")
    table.add_column("Fetches", justify="right")
    table.add_column("Elapsed", justify="right")
    table.add_column("Path")
    for row in rows:
        table.add_row(
            str(row["run"]),
            row["type"],
            row["start"],
            row["target"],
            str(row["clicks"]) if row["success"] else "FAIL",
            str(row["fetches"]),
            f"{row['elapsed']:.2f}s" if row.get("elapsed") is not None else "n/a",
            row["path"] if row["success"] else "No path within budget",
        )
    console.print(table)

    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    console = Console()
    quiet = QuietConsole()
    client = WikiClient(min_interval=args.min_interval)
    rows = []

    for pair in load_pairs(args.dataset):
        console.print(
            f"[dim]replay {pair['run']:02d}/30: {pair['start']} -> {pair['target']}[/dim]"
        )
        race_started = time.perf_counter()
        before_fetches = client.network_fetches
        client.clear_session()
        result = solve(
            client,
            pair["start"],
            pair["target"],
            beam=args.beam,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            time_limit=args.time_limit,
            console=quiet,
        )
        fetches = client.network_fetches - before_fetches
        race_elapsed = time.perf_counter() - race_started
        if result is None:
            rows.append(
                {
                    **pair,
                    "success": False,
                    "clicks": None,
                    "fetches": fetches,
                    "elapsed": race_elapsed,
                    "path": "",
                }
            )
        else:
            rows.append(
                {
                    **pair,
                    "success": True,
                    "clicks": len(result.path) - 1,
                    "fetches": fetches,
                    "elapsed": result.elapsed,
                    "path": " -> ".join(result.path),
                }
            )

        if args.race_interval > 0:
            time.sleep(args.race_interval)

    summarize(rows, console, args.out_json, args.out_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
