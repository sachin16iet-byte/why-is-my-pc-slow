from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DiagnosisType(str, Enum):
    MEMORY_PRESSURE = "memory_pressure"
    CPU_BOTTLENECK = "cpu_bottleneck"
    DISK_BOTTLENECK = "disk_bottleneck"
    GPU_BOTTLENECK = "gpu_bottleneck"
    BACKGROUND_PROCESS = "background_process"
    LOW_DISK_SPACE = "low_disk_space"
    NETWORK_RELATED = "network_related"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    name: str
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    network_rx_bps: float = 0.0
    network_tx_bps: float = 0.0
    start_time_utc: datetime | None = None

    @property
    def disk_total_bps(self) -> float:
        return self.disk_read_bps + self.disk_write_bps


@dataclass(frozen=True)
class ResourceSnapshot:
    timestamp_utc: datetime
    cpu_percent: float | None = None
    cpu_frequency_mhz: float | None = None
    memory_used_percent: float | None = None
    memory_available_mb: float | None = None
    committed_percent: float | None = None
    pagefile_used_percent: float | None = None
    pagefile_activity_bps: float | None = None
    disk_util_percent: float | None = None
    disk_read_bps: float | None = None
    disk_write_bps: float | None = None
    disk_latency_ms: float | None = None
    disk_free_percent: float | None = None
    gpu_percent: float | None = None
    gpu_memory_used_percent: float | None = None
    network_latency_ms: float | None = None
    packet_loss_percent: float | None = None
    processes: tuple[ProcessSample, ...] = field(default_factory=tuple)
    source: str = "unknown"

    @property
    def disk_total_bps(self) -> float | None:
        if self.disk_read_bps is None and self.disk_write_bps is None:
            return None
        return (self.disk_read_bps or 0.0) + (self.disk_write_bps or 0.0)


@dataclass(frozen=True)
class EvidenceItem:
    signal: str
    observation: str
    value: float | str | None
    unit: str
    timestamp_utc: datetime | None
    weight: float
    supports: bool = True


@dataclass(frozen=True)
class TimelineEvent:
    timestamp_utc: datetime
    event_type: str
    description: str
    related_metric: str


@dataclass(frozen=True)
class DiagnosisResult:
    diagnosis_type: DiagnosisType
    confidence: float
    severity: Severity
    summary: str
    evidence: tuple[EvidenceItem, ...]
    timeline: tuple[TimelineEvent, ...] = field(default_factory=tuple)
    alternatives: tuple[DiagnosisType, ...] = field(default_factory=tuple)
    observed_measurements: dict[str, Any] = field(default_factory=dict)
    data_gaps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return self.diagnosis_type.value.replace("_", " ").title()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
