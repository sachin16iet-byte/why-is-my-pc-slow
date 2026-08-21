from __future__ import annotations

import argparse
import time
from pathlib import Path

from .collectors import WindowsSnapshotCollector
from .diagnosis import DiagnosisEngine
from .formatting import format_diagnoses
from .scenarios import scenario
from .storage import MetricStore


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pcslow",
        description="Local-first performance evidence collector and diagnosis prototype.",
    )
    parser.add_argument("--db", default="data/pcslow.db", help="SQLite database path.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    simulate = subcommands.add_parser("simulate", help="Analyze a built-in simulated slowdown scenario.")
    simulate.add_argument(
        "scenario",
        choices=["normal", "memory", "cpu", "disk", "background", "low-disk", "gpu", "network", "multiple", "insufficient"],
    )
    simulate.add_argument("--store", action="store_true", help="Store simulated snapshots and diagnoses in SQLite.")

    collect = subcommands.add_parser("collect", help="Collect real Windows snapshots into SQLite.")
    collect.add_argument("--samples", type=int, default=6, help="Number of samples to collect.")
    collect.add_argument("--interval", type=float, default=5.0, help="Seconds between samples.")

    subcommands.add_parser("diagnose", help="Diagnose recent snapshots from SQLite.")
    subcommands.add_parser("status", help="Show local database status.")

    args = parser.parse_args()
    store = MetricStore(args.db)

    if args.command == "simulate":
        snapshots = scenario(args.scenario)
        diagnoses = DiagnosisEngine().analyze(snapshots)
        if args.store:
            for snapshot in snapshots:
                store.add_snapshot(snapshot)
            for diagnosis in diagnoses:
                store.add_diagnosis(diagnosis)
        print(format_diagnoses(diagnoses))
        return 0

    if args.command == "collect":
        collector = WindowsSnapshotCollector()
        for index in range(args.samples):
            snapshot = collector.collect()
            store.add_snapshot(snapshot)
            print(
                f"Collected sample {index + 1}/{args.samples}: "
                f"CPU={display(snapshot.cpu_percent, '%')} "
                f"RAM={display(snapshot.memory_used_percent, '%')} "
                f"Disk={display(snapshot.disk_util_percent, '%')}"
            )
            if index < args.samples - 1:
                time.sleep(args.interval)
        diagnoses = DiagnosisEngine().analyze(store.recent_snapshots(limit=max(args.samples, 6)))
        for diagnosis in diagnoses:
            store.add_diagnosis(diagnosis)
        print()
        print(format_diagnoses(diagnoses))
        return 0

    if args.command == "diagnose":
        snapshots = store.recent_snapshots(limit=30)
        diagnoses = DiagnosisEngine().analyze(snapshots)
        for diagnosis in diagnoses:
            store.add_diagnosis(diagnosis)
        print(format_diagnoses(diagnoses))
        return 0

    if args.command == "status":
        db_path = Path(args.db)
        print(f"Database: {db_path.resolve()}")
        print(f"Snapshots stored: {store.count_snapshots()}")
        return 0

    return 1


def display(value: float | None, unit: str) -> str:
    return "unknown" if value is None else f"{round(value, 1)}{unit}"


if __name__ == "__main__":
    raise SystemExit(main())
