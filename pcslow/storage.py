from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import DiagnosisResult, EvidenceItem, ProcessSample, ResourceSnapshot, TimelineEvent


SCHEMA = """
create table if not exists snapshots (
    id integer primary key autoincrement,
    timestamp_utc text not null,
    source text not null,
    cpu_percent real,
    cpu_frequency_mhz real,
    memory_used_percent real,
    memory_available_mb real,
    committed_percent real,
    pagefile_used_percent real,
    pagefile_activity_bps real,
    disk_util_percent real,
    disk_read_bps real,
    disk_write_bps real,
    disk_latency_ms real,
    disk_free_percent real,
    gpu_percent real,
    gpu_memory_used_percent real,
    network_latency_ms real,
    packet_loss_percent real
);

create index if not exists ix_snapshots_timestamp on snapshots(timestamp_utc);

create table if not exists process_samples (
    id integer primary key autoincrement,
    snapshot_id integer not null references snapshots(id) on delete cascade,
    pid integer not null,
    name text not null,
    cpu_percent real not null,
    memory_mb real not null,
    disk_read_bps real not null,
    disk_write_bps real not null,
    network_rx_bps real not null,
    network_tx_bps real not null,
    start_time_utc text
);

create table if not exists diagnoses (
    id integer primary key autoincrement,
    created_utc text not null default current_timestamp,
    diagnosis_type text not null,
    confidence real not null,
    severity text not null,
    summary text not null,
    observed_measurements_json text not null,
    data_gaps_json text not null
);

create table if not exists diagnosis_evidence (
    id integer primary key autoincrement,
    diagnosis_id integer not null references diagnoses(id) on delete cascade,
    signal text not null,
    observation text not null,
    value_text text,
    unit text not null,
    timestamp_utc text,
    weight real not null,
    supports integer not null
);

create table if not exists timeline_events (
    id integer primary key autoincrement,
    diagnosis_id integer not null references diagnoses(id) on delete cascade,
    timestamp_utc text not null,
    event_type text not null,
    description text not null,
    related_metric text not null
);
"""


class MetricStore:
    def __init__(self, path: str | Path = "pcslow.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        return connection

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript(SCHEMA)

    def add_snapshot(self, snapshot: ResourceSnapshot) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """
                insert into snapshots (
                    timestamp_utc, source, cpu_percent, cpu_frequency_mhz, memory_used_percent,
                    memory_available_mb, committed_percent, pagefile_used_percent, pagefile_activity_bps,
                    disk_util_percent, disk_read_bps, disk_write_bps, disk_latency_ms, disk_free_percent,
                    gpu_percent, gpu_memory_used_percent, network_latency_ms, packet_loss_percent
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.timestamp_utc.isoformat(),
                    snapshot.source,
                    snapshot.cpu_percent,
                    snapshot.cpu_frequency_mhz,
                    snapshot.memory_used_percent,
                    snapshot.memory_available_mb,
                    snapshot.committed_percent,
                    snapshot.pagefile_used_percent,
                    snapshot.pagefile_activity_bps,
                    snapshot.disk_util_percent,
                    snapshot.disk_read_bps,
                    snapshot.disk_write_bps,
                    snapshot.disk_latency_ms,
                    snapshot.disk_free_percent,
                    snapshot.gpu_percent,
                    snapshot.gpu_memory_used_percent,
                    snapshot.network_latency_ms,
                    snapshot.packet_loss_percent,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            db.executemany(
                """
                insert into process_samples (
                    snapshot_id, pid, name, cpu_percent, memory_mb, disk_read_bps, disk_write_bps,
                    network_rx_bps, network_tx_bps, start_time_utc
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        process.pid,
                        process.name,
                        process.cpu_percent,
                        process.memory_mb,
                        process.disk_read_bps,
                        process.disk_write_bps,
                        process.network_rx_bps,
                        process.network_tx_bps,
                        process.start_time_utc.isoformat() if process.start_time_utc else None,
                    )
                    for process in snapshot.processes
                ],
            )
            return snapshot_id

    def recent_snapshots(self, limit: int = 20) -> list[ResourceSnapshot]:
        with self._connect() as db:
            rows = list(
                db.execute(
                    "select * from snapshots order by timestamp_utc desc limit ?",
                    (limit,),
                )
            )
            snapshots = []
            for row in reversed(rows):
                process_rows = list(db.execute("select * from process_samples where snapshot_id = ?", (row["id"],)))
                snapshots.append(row_to_snapshot(row, process_rows))
            return snapshots

    def add_diagnosis(self, diagnosis: DiagnosisResult) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """
                insert into diagnoses (
                    diagnosis_type, confidence, severity, summary,
                    observed_measurements_json, data_gaps_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnosis.diagnosis_type.value,
                    diagnosis.confidence,
                    diagnosis.severity.value,
                    diagnosis.summary,
                    json.dumps(diagnosis.observed_measurements),
                    json.dumps(list(diagnosis.data_gaps)),
                ),
            )
            diagnosis_id = int(cursor.lastrowid)
            db.executemany(
                """
                insert into diagnosis_evidence (
                    diagnosis_id, signal, observation, value_text, unit, timestamp_utc, weight, supports
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [evidence_values(diagnosis_id, item) for item in diagnosis.evidence],
            )
            db.executemany(
                """
                insert into timeline_events (
                    diagnosis_id, timestamp_utc, event_type, description, related_metric
                ) values (?, ?, ?, ?, ?)
                """,
                [timeline_values(diagnosis_id, item) for item in diagnosis.timeline],
            )
            return diagnosis_id

    def count_snapshots(self) -> int:
        with self._connect() as db:
            return int(db.execute("select count(*) from snapshots").fetchone()[0])


def evidence_values(diagnosis_id: int, item: EvidenceItem) -> tuple:
    return (
        diagnosis_id,
        item.signal,
        item.observation,
        None if item.value is None else str(item.value),
        item.unit,
        item.timestamp_utc.isoformat() if item.timestamp_utc else None,
        item.weight,
        1 if item.supports else 0,
    )


def timeline_values(diagnosis_id: int, item: TimelineEvent) -> tuple:
    return (
        diagnosis_id,
        item.timestamp_utc.isoformat(),
        item.event_type,
        item.description,
        item.related_metric,
    )


def row_to_snapshot(row: sqlite3.Row, process_rows: list[sqlite3.Row]) -> ResourceSnapshot:
    from datetime import datetime

    processes = tuple(
        ProcessSample(
            pid=process["pid"],
            name=process["name"],
            cpu_percent=process["cpu_percent"],
            memory_mb=process["memory_mb"],
            disk_read_bps=process["disk_read_bps"],
            disk_write_bps=process["disk_write_bps"],
            network_rx_bps=process["network_rx_bps"],
            network_tx_bps=process["network_tx_bps"],
            start_time_utc=datetime.fromisoformat(process["start_time_utc"]) if process["start_time_utc"] else None,
        )
        for process in process_rows
    )
    return ResourceSnapshot(
        timestamp_utc=datetime.fromisoformat(row["timestamp_utc"]),
        source=row["source"],
        cpu_percent=row["cpu_percent"],
        cpu_frequency_mhz=row["cpu_frequency_mhz"],
        memory_used_percent=row["memory_used_percent"],
        memory_available_mb=row["memory_available_mb"],
        committed_percent=row["committed_percent"],
        pagefile_used_percent=row["pagefile_used_percent"],
        pagefile_activity_bps=row["pagefile_activity_bps"],
        disk_util_percent=row["disk_util_percent"],
        disk_read_bps=row["disk_read_bps"],
        disk_write_bps=row["disk_write_bps"],
        disk_latency_ms=row["disk_latency_ms"],
        disk_free_percent=row["disk_free_percent"],
        gpu_percent=row["gpu_percent"],
        gpu_memory_used_percent=row["gpu_memory_used_percent"],
        network_latency_ms=row["network_latency_ms"],
        packet_loss_percent=row["packet_loss_percent"],
        processes=processes,
    )
