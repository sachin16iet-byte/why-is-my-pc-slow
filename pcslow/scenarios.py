from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import ProcessSample, ResourceSnapshot


def scenario(name: str) -> list[ResourceSnapshot]:
    scenarios = {
        "normal": normal_pc,
        "memory": memory_pressure,
        "cpu": cpu_saturation,
        "disk": disk_saturation,
        "background": background_process,
        "low-disk": low_disk_space,
        "gpu": gpu_heavy,
        "network": network_latency,
        "multiple": multiple_bottlenecks,
        "insufficient": insufficient_evidence,
    }
    try:
        return scenarios[name]()
    except KeyError as exc:
        valid = ", ".join(sorted(scenarios))
        raise ValueError(f"Unknown scenario '{name}'. Valid scenarios: {valid}") from exc


def base_time() -> datetime:
    return datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def snap(index: int, **kwargs) -> ResourceSnapshot:
    defaults = {
        "cpu_percent": 25.0,
        "memory_used_percent": 55.0,
        "memory_available_mb": 6500.0,
        "pagefile_activity_bps": 200_000.0,
        "disk_util_percent": 15.0,
        "disk_read_bps": 1_000_000.0,
        "disk_write_bps": 500_000.0,
        "disk_latency_ms": 8.0,
        "disk_free_percent": 40.0,
        "gpu_percent": 10.0,
        "gpu_memory_used_percent": 20.0,
        "network_latency_ms": 25.0,
        "packet_loss_percent": 0.0,
        "processes": (
            ProcessSample(100, "explorer.exe", cpu_percent=2, memory_mb=250),
            ProcessSample(200, "browser.exe", cpu_percent=8, memory_mb=900),
        ),
        "source": "simulated",
    }
    defaults.update(kwargs)
    return ResourceSnapshot(base_time() + timedelta(seconds=index * 10), **defaults)


def normal_pc() -> list[ResourceSnapshot]:
    return [snap(i, cpu_percent=20 + i, memory_used_percent=55 + i, disk_util_percent=12 + i) for i in range(6)]


def memory_pressure() -> list[ResourceSnapshot]:
    return [
        snap(0),
        snap(1, memory_used_percent=82, memory_available_mb=2200, pagefile_activity_bps=300_000),
        snap(2, memory_used_percent=91, memory_available_mb=900, pagefile_activity_bps=900_000),
        snap(3, memory_used_percent=96, memory_available_mb=450, pagefile_activity_bps=3_000_000, disk_util_percent=78),
        snap(4, memory_used_percent=97, memory_available_mb=300, pagefile_activity_bps=5_000_000, disk_util_percent=92),
    ]


def cpu_saturation() -> list[ResourceSnapshot]:
    worker = ProcessSample(300, "video-export.exe", cpu_percent=72, memory_mb=700)
    return [snap(i, cpu_percent=88 + i, processes=(worker,)) for i in range(5)]


def disk_saturation() -> list[ResourceSnapshot]:
    backup = ProcessSample(400, "backup.exe", cpu_percent=8, memory_mb=300, disk_read_bps=6_000_000, disk_write_bps=11_000_000)
    return [
        snap(i, disk_util_percent=90 + i, disk_latency_ms=65 + i * 5, disk_write_bps=15_000_000, processes=(backup,))
        for i in range(5)
    ]


def background_process() -> list[ResourceSnapshot]:
    quiet = ProcessSample(500, "indexer.exe", cpu_percent=2, memory_mb=300, disk_write_bps=100_000)
    loud = ProcessSample(500, "indexer.exe", cpu_percent=44, memory_mb=1500, disk_write_bps=12_000_000)
    return [snap(0, processes=(quiet,)), snap(1, processes=(quiet,)), snap(2, processes=(loud,)), snap(3, processes=(loud,))]


def low_disk_space() -> list[ResourceSnapshot]:
    return [snap(i, disk_free_percent=4.0, disk_util_percent=50) for i in range(4)]


def gpu_heavy() -> list[ResourceSnapshot]:
    return [snap(i, gpu_percent=94, gpu_memory_used_percent=91, processes=(ProcessSample(600, "game.exe", cpu_percent=18, memory_mb=900),)) for i in range(4)]


def network_latency() -> list[ResourceSnapshot]:
    return [snap(i, network_latency_ms=230, packet_loss_percent=3.5) for i in range(4)]


def multiple_bottlenecks() -> list[ResourceSnapshot]:
    samples = memory_pressure()
    return [
        ResourceSnapshot(
            **{
                **sample.__dict__,
                "cpu_percent": 92,
                "processes": (ProcessSample(700, "compiler.exe", cpu_percent=55, memory_mb=2300),),
            }
        )
        for sample in samples
    ]


def insufficient_evidence() -> list[ResourceSnapshot]:
    return [snap(0)]
