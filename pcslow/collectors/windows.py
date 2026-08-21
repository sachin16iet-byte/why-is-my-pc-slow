from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timezone

from ..models import ProcessSample, ResourceSnapshot, utc_now


class WindowsSnapshotCollector:
    """Best-effort Windows collector using built-in PowerShell/CIM commands.

    This is intentionally conservative: it collects performance counters and
    process resource totals, but avoids command lines, windows, documents,
    screenshots, registry changes, or process control.
    """

    def collect(self) -> ResourceSnapshot:
        if not shutil.which("powershell"):
            return ResourceSnapshot(timestamp_utc=utc_now(), source="windows-unavailable")

        data = self._run_powershell()
        memory = data.get("memory") or {}
        cpu = data.get("cpu") or {}
        disk = data.get("disk") or {}
        logical = data.get("logicalDisk") or {}
        processes = tuple(parse_process(item) for item in data.get("processes") or [])

        total_kb = as_float(memory.get("TotalVisibleMemorySize"))
        free_kb = as_float(memory.get("FreePhysicalMemory"))
        memory_available_mb = free_kb / 1024 if free_kb is not None else None
        memory_used_percent = None
        if total_kb and free_kb is not None:
            memory_used_percent = round(((total_kb - free_kb) / total_kb) * 100, 2)

        disk_free_percent = None
        free_space = as_float(logical.get("FreeSpace"))
        size = as_float(logical.get("Size"))
        if size and free_space is not None:
            disk_free_percent = round((free_space / size) * 100, 2)

        return ResourceSnapshot(
            timestamp_utc=utc_now(),
            source="windows-powershell",
            cpu_percent=as_float(cpu.get("PercentProcessorTime")),
            memory_used_percent=memory_used_percent,
            memory_available_mb=memory_available_mb,
            committed_percent=as_float(memory.get("PercentCommittedBytesInUse")),
            pagefile_used_percent=as_float(memory.get("PercentUsage")),
            disk_util_percent=as_float(disk.get("PercentDiskTime")),
            disk_read_bps=as_float(disk.get("DiskReadBytesPersec")),
            disk_write_bps=as_float(disk.get("DiskWriteBytesPersec")),
            disk_latency_ms=seconds_to_ms(as_float(disk.get("AvgDisksecPerTransfer"))),
            disk_free_percent=disk_free_percent,
            processes=processes,
        )

    def _run_powershell(self) -> dict:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'" |
  Select-Object -Property PercentProcessorTime
$memory = Get-CimInstance Win32_OperatingSystem |
  Select-Object -Property TotalVisibleMemorySize,FreePhysicalMemory
$memPerf = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory |
  Select-Object -Property PercentCommittedBytesInUse
$page = Get-CimInstance Win32_PerfFormattedData_PerfOS_PagingFile -Filter "Name='_Total'" |
  Select-Object -Property PercentUsage
$disk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'" |
  Select-Object -Property PercentDiskTime,DiskReadBytesPersec,DiskWriteBytesPersec,AvgDisksecPerTransfer
$logical = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" |
  Select-Object -Property FreeSpace,Size
$processes = Get-CimInstance Win32_PerfFormattedData_PerfProc_Process |
  Where-Object { $_.Name -ne '_Total' -and $_.Name -ne 'Idle' } |
  Sort-Object -Property PercentProcessorTime -Descending |
  Select-Object -First 12 -Property IDProcess,Name,PercentProcessorTime,WorkingSet,IOReadBytesPersec,IOWriteBytesPersec
[pscustomobject]@{
  cpu = $cpu
  memory = [pscustomobject]@{
    TotalVisibleMemorySize = $memory.TotalVisibleMemorySize
    FreePhysicalMemory = $memory.FreePhysicalMemory
    PercentCommittedBytesInUse = $memPerf.PercentCommittedBytesInUse
    PercentUsage = $page.PercentUsage
  }
  disk = $disk
  logicalDisk = $logical
  processes = $processes
} | ConvertTo-Json -Depth 5
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        return json.loads(completed.stdout)


def parse_process(item: dict) -> ProcessSample:
    return ProcessSample(
        pid=int(as_float(item.get("IDProcess")) or 0),
        name=str(item.get("Name") or "unknown"),
        cpu_percent=as_float(item.get("PercentProcessorTime")) or 0.0,
        memory_mb=(as_float(item.get("WorkingSet")) or 0.0) / (1024 * 1024),
        disk_read_bps=as_float(item.get("IOReadBytesPersec")) or 0.0,
        disk_write_bps=as_float(item.get("IOWriteBytesPersec")) or 0.0,
    )


def as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def seconds_to_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 1000, 2)
