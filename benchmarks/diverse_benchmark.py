#!/usr/bin/env python3
from __future__ import annotations

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

from wikispeedrun import WikiClient, solve


CHOSEN_CATEGORY_RACES = [
    ("Taylor Swift", "Quantum mechanics"),
    ("Python (programming language)", "Artificial intelligence"),
    ("LeBron James", "Machine learning"),
    ("Minecraft", "World War II"),
    ("Sourdough", "Semiconductor"),
    ("William Shakespeare", "Bitcoin"),
    ("New York City", "Photosynthesis"),
    ("The Beatles", "Space exploration"),
    ("Chess", "Climate change"),
    ("Barack Obama", "Large language model"),
    ("Mona Lisa", "Blockchain"),
    ("Mount Everest", "DNA"),
    ("Coffee", "Nuclear fusion"),
    ("Soccer", "Mars"),
    ("Nintendo", "Philosophy"),
]


class QuietConsole:
    def print(self, *args, **kwargs) -> None:
        return None


def summarize(rows: list[dict], console: Console) -> None:
    successes = [row for row in rows if row["success"]]
    click_values = [row["clicks"] for row in successes]
    elapsed_values = [row["elapsed"] for row in successes]
    fetch_values = [row["fetches"] for row in rows]

    summary = Table(title="30 Different Wikipedia Speedruns")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Runs", str(len(rows)))
    summary.add_row("Successes", f"{len(successes)}/{len(rows)}")
    summary.add_row("Success rate", f"{len(successes) / len(rows):.1%}")
    summary.add_row("Avg clicks", f"{statistics.mean(click_values):.2f}" if click_values else "n/a")
    summary.add_row("Median clicks", f"{statistics.median(click_values):.2f}" if click_values else "n/a")
    all_elapsed = [row["elapsed"] for row in rows]
    summary.add_row("Avg elapsed (all runs)", f"{statistics.mean(all_elapsed):.2f}s")
    summary.add_row("Avg elapsed (successes)", f"{statistics.mean(elapsed_values):.2f}s" if elapsed_values else "n/a")
    summary.add_row("Median elapsed (successes)", f"{statistics.median(elapsed_values):.2f}s" if elapsed_values else "n/a")
    summary.add_row("Avg network fetches", f"{statistics.mean(fetch_values):.2f}")
    summary.add_row("Total network fetches", str(sum(fetch_values)))
    console.print(summary)

    table = Table(title="Per-Run Results")
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
            f"{row['elapsed']:.2f}s" if row["success"] else "n/a",
            row["path"] if row["success"] else "No path within budget",
        )
    console.print(table)
    results_dir = ROOT / "benchmarks/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "diverse_benchmark_results.json", "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    with open(results_dir / "diverse_benchmark_results.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    console.print("[dim]Wrote benchmarks/results/diverse_benchmark_results.json and .csv[/dim]")


def run_one(
    client: WikiClient,
    quiet: QuietConsole,
    run_number: int,
    run_type: str,
    start: str,
    target: str,
) -> dict:
    before_fetches = client.network_fetches
    display_start = start
    display_target = target
    if "Special:Random" in start:
        page = client.fetch(start)
        start = page.url
        display_start = page.title
    if "Special:Random" in target:
        page = client.fetch(target)
        target = page.url
        display_target = page.title
    started = time.perf_counter()
    client.clear_session()
    result = solve(
        client,
        start,
        target,
        beam=42,
        max_pages=16,
        max_depth=6,
        time_limit=4.0,
        console=quiet,
    )
    fetches = client.network_fetches - before_fetches
    if result is None:
        return {
            "run": run_number,
            "type": run_type,
            "start": display_start,
            "target": display_target,
            "success": False,
            "clicks": None,
            "fetches": fetches,
            "elapsed": min(time.perf_counter() - started, 4.0),
            "path": "",
        }
    return {
        "run": run_number,
        "type": run_type,
        "start": result.path[0],
        "target": result.path[-1],
        "success": True,
        "clicks": len(result.path) - 1,
        "fetches": fetches,
        "elapsed": result.elapsed,
        "path": " -> ".join(result.path),
    }


def main() -> int:
    console = Console()
    quiet = QuietConsole()
    client = WikiClient(min_interval=0.12)
    rows: list[dict] = []

    for idx, (start, target) in enumerate(CHOSEN_CATEGORY_RACES, start=1):
        console.print(f"[dim]chosen {idx:02d}/15: {start} -> {target}[/dim]")
        rows.append(run_one(client, quiet, idx, "chosen", start, target))
        time.sleep(0.35)

    for offset in range(15):
        run_number = 16 + offset
        console.print(f"[dim]random {offset + 1:02d}/15: Special:Random -> Special:Random[/dim]")
        rows.append(
            run_one(
                client,
                quiet,
                run_number,
                "random",
                "https://en.wikipedia.org/wiki/Special:Random",
                "https://en.wikipedia.org/wiki/Special:Random",
            )
        )
        time.sleep(0.35)

    summarize(rows, console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
