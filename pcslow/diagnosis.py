from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import (
    DiagnosisResult,
    DiagnosisType,
    EvidenceItem,
    ResourceSnapshot,
    Severity,
    TimelineEvent,
)


@dataclass(frozen=True)
class DiagnosisThresholds:
    memory_high_percent: float = 90.0
    memory_critical_percent: float = 95.0
    memory_low_available_mb: float = 1024.0
    cpu_high_percent: float = 85.0
    disk_high_percent: float = 85.0
    disk_high_latency_ms: float = 50.0
    low_disk_free_percent: float = 10.0
    critical_disk_free_percent: float = 5.0
    gpu_high_percent: float = 90.0
    process_cpu_spike_percent: float = 35.0
    process_memory_high_mb: float = 1024.0
    network_latency_high_ms: float = 150.0
    packet_loss_high_percent: float = 2.0


class DiagnosisEngine:
    def __init__(self, thresholds: DiagnosisThresholds | None = None) -> None:
        self.thresholds = thresholds or DiagnosisThresholds()

    def analyze(self, snapshots: Iterable[ResourceSnapshot]) -> list[DiagnosisResult]:
        ordered = sorted(snapshots, key=lambda sample: sample.timestamp_utc)
        if len(ordered) < 3:
            return [self._insufficient("Need at least three samples to analyze trends and timing.")]

        candidates = [
            self._memory_pressure(ordered),
            self._cpu_bottleneck(ordered),
            self._disk_bottleneck(ordered),
            self._low_disk_space(ordered),
            self._gpu_bottleneck(ordered),
            self._background_process(ordered),
            self._network_related(ordered),
        ]
        diagnoses = [candidate for candidate in candidates if candidate is not None]
        diagnoses.sort(key=lambda item: (item.severity.value, item.confidence), reverse=True)
        diagnoses.sort(key=lambda item: item.confidence, reverse=True)

        if not diagnoses:
            return [self._insufficient("No sustained abnormal resource pattern was detected.")]

        primary_types = {diagnosis.diagnosis_type for diagnosis in diagnoses}
        with_alternatives: list[DiagnosisResult] = []
        for diagnosis in diagnoses:
            alternatives = tuple(kind for kind in primary_types if kind != diagnosis.diagnosis_type)
            with_alternatives.append(
                DiagnosisResult(
                    diagnosis_type=diagnosis.diagnosis_type,
                    confidence=diagnosis.confidence,
                    severity=diagnosis.severity,
                    summary=diagnosis.summary,
                    evidence=diagnosis.evidence,
                    timeline=diagnosis.timeline,
                    alternatives=alternatives,
                    observed_measurements=diagnosis.observed_measurements,
                    data_gaps=diagnosis.data_gaps,
                )
            )
        return with_alternatives

    def _memory_pressure(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        evidence: list[EvidenceItem] = []
        gaps: list[str] = []

        high_memory = [s for s in samples if value_gte(s.memory_used_percent, t.memory_high_percent)]
        critical_memory = [s for s in samples if value_gte(s.memory_used_percent, t.memory_critical_percent)]
        low_available = [s for s in samples if value_lte(s.memory_available_mb, t.memory_low_available_mb)]
        pagefile_rise = rose(samples, "pagefile_activity_bps", minimum_factor=1.5)
        disk_rise_after_memory = event_order(
            first_samples=high_memory or low_available,
            second_samples=[s for s in samples if value_gte(s.disk_util_percent, t.disk_high_percent) or rose_until(samples, s, "disk_total_bps")],
        )

        if high_memory:
            evidence.append(ev("memory_used_percent", "RAM usage was sustained at a high level.", latest.memory_used_percent, "%", latest, 0.24))
        if critical_memory:
            evidence.append(ev("memory_used_percent", "RAM usage reached a critical level.", latest.memory_used_percent, "%", latest, 0.18))
        if low_available:
            evidence.append(ev("memory_available_mb", "Available memory fell below a practical safety margin.", latest.memory_available_mb, "MB", latest, 0.2))
        if pagefile_rise:
            evidence.append(ev("pagefile_activity_bps", "Pagefile activity increased during the slowdown window.", latest.pagefile_activity_bps, "B/s", latest, 0.18))
        elif latest.pagefile_activity_bps is None:
            gaps.append("Pagefile activity was not available, lowering memory-pressure confidence.")
        if disk_rise_after_memory:
            evidence.append(ev("disk_after_memory", "Disk activity increased after memory pressure appeared.", latest.disk_util_percent, "%", latest, 0.17))

        confidence = clamp(sum(item.weight for item in evidence))
        if confidence < 0.45:
            return None
        return DiagnosisResult(
            diagnosis_type=DiagnosisType.MEMORY_PRESSURE,
            confidence=confidence,
            severity=Severity.HIGH if confidence >= 0.7 else Severity.MEDIUM,
            summary="Memory pressure is likely slowing the PC by forcing more paging and related disk activity.",
            evidence=tuple(evidence),
            timeline=timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
            data_gaps=tuple(gaps),
        )

    def _cpu_bottleneck(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        high_cpu = [s for s in samples if value_gte(s.cpu_percent, t.cpu_high_percent)]
        top_cpu = top_process(latest, "cpu_percent")
        evidence: list[EvidenceItem] = []

        if len(high_cpu) >= max(2, len(samples) // 2):
            evidence.append(ev("cpu_percent", "CPU usage was high for a sustained part of the window.", latest.cpu_percent, "%", latest, 0.45))
        if top_cpu and top_cpu.cpu_percent >= t.process_cpu_spike_percent:
            evidence.append(ev("process_cpu_percent", f"{top_cpu.name} was a major CPU consumer.", top_cpu.cpu_percent, "%", latest, 0.25))
        if not value_gte(latest.memory_used_percent, t.memory_high_percent) and not value_gte(latest.disk_util_percent, t.disk_high_percent):
            evidence.append(ev("resource_isolation", "Memory and disk did not show stronger simultaneous bottlenecks.", "cpu-dominant", "", latest, 0.1))

        confidence = clamp(sum(item.weight for item in evidence))
        if confidence < 0.45:
            return None
        return DiagnosisResult(
            DiagnosisType.CPU_BOTTLENECK,
            confidence,
            Severity.HIGH if confidence >= 0.7 else Severity.MEDIUM,
            "The processor appears saturated long enough to make applications wait for CPU time.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
        )

    def _disk_bottleneck(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        high_disk = [s for s in samples if value_gte(s.disk_util_percent, t.disk_high_percent)]
        high_latency = [s for s in samples if value_gte(s.disk_latency_ms, t.disk_high_latency_ms)]
        top_disk = max(latest.processes, key=lambda p: p.disk_total_bps, default=None)
        evidence: list[EvidenceItem] = []
        gaps: list[str] = []

        if len(high_disk) >= max(2, len(samples) // 2):
            evidence.append(ev("disk_util_percent", "Disk utilization was high for a sustained part of the window.", latest.disk_util_percent, "%", latest, 0.35))
        if high_latency:
            evidence.append(ev("disk_latency_ms", "Disk latency was high, which can make the whole PC feel unresponsive.", latest.disk_latency_ms, "ms", latest, 0.25))
        elif latest.disk_latency_ms is None:
            gaps.append("Disk latency was not available.")
        if top_disk and top_disk.disk_total_bps > 5_000_000:
            evidence.append(ev("process_disk_bps", f"{top_disk.name} was a significant disk I/O source.", round(top_disk.disk_total_bps), "B/s", latest, 0.18))

        confidence = clamp(sum(item.weight for item in evidence))
        if confidence < 0.45:
            return None
        return DiagnosisResult(
            DiagnosisType.DISK_BOTTLENECK,
            confidence,
            Severity.HIGH if confidence >= 0.7 else Severity.MEDIUM,
            "Disk activity or latency appears high enough to delay application work.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
            data_gaps=tuple(gaps),
        )

    def _low_disk_space(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        if latest.disk_free_percent is None or latest.disk_free_percent > t.low_disk_free_percent:
            return None
        critical = latest.disk_free_percent <= t.critical_disk_free_percent
        evidence = [
            ev(
                "disk_free_percent",
                "Free disk space is critically low." if critical else "Free disk space is low.",
                latest.disk_free_percent,
                "%",
                latest,
                0.55 if critical else 0.45,
            )
        ]
        if value_gte(latest.disk_util_percent, t.disk_high_percent):
            evidence.append(ev("disk_util_percent", "Disk was also busy while space was low.", latest.disk_util_percent, "%", latest, 0.15))
        return DiagnosisResult(
            DiagnosisType.LOW_DISK_SPACE,
            clamp(sum(item.weight for item in evidence)),
            Severity.HIGH if critical else Severity.MEDIUM,
            "Low free space may be contributing to degraded performance and update/cache problems.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
        )

    def _gpu_bottleneck(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        high_gpu = [s for s in samples if value_gte(s.gpu_percent, t.gpu_high_percent)]
        high_gpu_memory = [s for s in samples if value_gte(s.gpu_memory_used_percent, t.gpu_high_percent)]
        evidence: list[EvidenceItem] = []
        if high_gpu:
            evidence.append(ev("gpu_percent", "GPU utilization was high.", latest.gpu_percent, "%", latest, 0.35))
        if high_gpu_memory:
            evidence.append(ev("gpu_memory_used_percent", "GPU memory usage was high.", latest.gpu_memory_used_percent, "%", latest, 0.25))
        confidence = clamp(sum(item.weight for item in evidence))
        if confidence < 0.45:
            return None
        return DiagnosisResult(
            DiagnosisType.GPU_BOTTLENECK,
            confidence,
            Severity.MEDIUM,
            "Graphics resources appear saturated, which can affect games, video, and GPU-accelerated apps.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
        )

    def _background_process(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        latest = samples[-1]
        first = samples[0]
        evidence: list[EvidenceItem] = []
        first_by_pid = {p.pid: p for p in first.processes}
        for proc in latest.processes:
            earlier = first_by_pid.get(proc.pid)
            new_or_changed = earlier is None or proc.cpu_percent - earlier.cpu_percent >= 25 or proc.disk_total_bps - earlier.disk_total_bps >= 5_000_000
            heavy_now = proc.cpu_percent >= 35 or proc.memory_mb >= 1024 or proc.disk_total_bps >= 10_000_000
            if new_or_changed and heavy_now:
                evidence.append(ev("background_process", f"{proc.name} became a heavy resource consumer during the window.", proc.pid, "pid", latest, 0.48))
                break
        if not evidence:
            return None
        return DiagnosisResult(
            DiagnosisType.BACKGROUND_PROCESS,
            clamp(sum(item.weight for item in evidence)),
            Severity.MEDIUM,
            "A process changed behavior during the slowdown window and may be the visible trigger.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
        )

    def _network_related(self, samples: list[ResourceSnapshot]) -> DiagnosisResult | None:
        t = self.thresholds
        latest = samples[-1]
        evidence: list[EvidenceItem] = []
        if value_gte(latest.network_latency_ms, t.network_latency_high_ms):
            evidence.append(ev("network_latency_ms", "Network latency was high.", latest.network_latency_ms, "ms", latest, 0.28))
        if value_gte(latest.packet_loss_percent, t.packet_loss_high_percent):
            evidence.append(ev("packet_loss_percent", "Packet loss was detected.", latest.packet_loss_percent, "%", latest, 0.32))
        if not evidence:
            return None
        return DiagnosisResult(
            DiagnosisType.NETWORK_RELATED,
            clamp(sum(item.weight for item in evidence)),
            Severity.LOW,
            "The evidence points to network slowness, not necessarily general PC slowness.",
            tuple(evidence),
            timeline_from_evidence(evidence),
            observed_measurements=observed(latest),
        )

    def _insufficient(self, reason: str) -> DiagnosisResult:
        return DiagnosisResult(
            DiagnosisType.INSUFFICIENT_EVIDENCE,
            0.0,
            Severity.INFO,
            reason,
            evidence=(),
        )


def ev(signal: str, observation: str, value: float | str | None, unit: str, sample: ResourceSnapshot, weight: float) -> EvidenceItem:
    return EvidenceItem(signal, observation, value, unit, sample.timestamp_utc, weight)


def value_gte(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def value_lte(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def clamp(value: float) -> float:
    return max(0.0, min(round(value, 2), 0.95))


def get_metric(sample: ResourceSnapshot, name: str) -> float | None:
    value = getattr(sample, name)
    return value() if callable(value) else value


def rose(samples: list[ResourceSnapshot], metric: str, minimum_factor: float) -> bool:
    first = get_metric(samples[0], metric)
    last = get_metric(samples[-1], metric)
    if first is None or last is None:
        return False
    baseline = max(first, 1.0)
    return last >= baseline * minimum_factor and last - first > 1.0


def rose_until(samples: list[ResourceSnapshot], current: ResourceSnapshot, metric: str) -> bool:
    first = get_metric(samples[0], metric)
    current_value = get_metric(current, metric)
    if first is None or current_value is None:
        return False
    return current_value >= max(first, 1.0) * 1.5


def event_order(first_samples: list[ResourceSnapshot], second_samples: list[ResourceSnapshot]) -> bool:
    if not first_samples or not second_samples:
        return False
    return min(s.timestamp_utc for s in first_samples) <= max(s.timestamp_utc for s in second_samples)


def top_process(sample: ResourceSnapshot, metric: str):
    if not sample.processes:
        return None
    return max(sample.processes, key=lambda process: getattr(process, metric, 0.0))


def timeline_from_evidence(evidence: list[EvidenceItem]) -> tuple[TimelineEvent, ...]:
    return tuple(
        TimelineEvent(
            timestamp_utc=item.timestamp_utc,
            event_type=item.signal,
            description=item.observation,
            related_metric=item.signal,
        )
        for item in evidence
        if item.timestamp_utc is not None
    )


def observed(sample: ResourceSnapshot) -> dict[str, float | None]:
    return {
        "cpu_percent": sample.cpu_percent,
        "memory_used_percent": sample.memory_used_percent,
        "memory_available_mb": sample.memory_available_mb,
        "pagefile_activity_bps": sample.pagefile_activity_bps,
        "disk_util_percent": sample.disk_util_percent,
        "disk_latency_ms": sample.disk_latency_ms,
        "disk_free_percent": sample.disk_free_percent,
        "gpu_percent": sample.gpu_percent,
        "network_latency_ms": sample.network_latency_ms,
        "packet_loss_percent": sample.packet_loss_percent,
    }
