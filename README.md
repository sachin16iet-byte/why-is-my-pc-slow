# Why Is My PC Slow?

Local-first backend prototype for a Windows performance diagnosis app.

This first version does not build a desktop UI yet. It provides:

- Deterministic diagnosis engine
- Evidence and confidence model
- Simulated slowdown datasets
- SQLite local history
- Best-effort Windows snapshot collector
- Automated tests

It does not terminate processes, edit the registry, delete files, inspect documents, capture screenshots, record keystrokes, or send data to cloud services.

## Requirements

- Python 3.10+
- Windows PowerShell for real local collection

No third-party Python packages are required.

## Run Simulated Diagnoses

```powershell
python -m pcslow.cli simulate memory
python -m pcslow.cli simulate cpu
python -m pcslow.cli simulate disk
python -m pcslow.cli simulate background
python -m pcslow.cli simulate normal
```

Store simulated data in SQLite:

```powershell
python -m pcslow.cli simulate memory --store
```

## Collect Real Local Samples

This collects a small number of local Windows performance snapshots and stores them in `data/pcslow.db`.

```powershell
python -m pcslow.cli collect --samples 6 --interval 5
```

Then diagnose recent stored samples:

```powershell
python -m pcslow.cli diagnose
```

Show database status:

```powershell
python -m pcslow.cli status
```

Use another database path:

```powershell
python -m pcslow.cli --db data/test.db simulate disk --store
python -m pcslow.cli --db data/test.db diagnose
```

## Run Tests

```powershell
python -m unittest discover -s tests
```

## Current Architecture

```text
Collectors
  -> ResourceSnapshot / ProcessSample
  -> SQLite Storage
  -> Historical Window
  -> Diagnosis Engine
  -> Evidence / Timeline / Confidence
  -> CLI now, Desktop UI later
```

## Next Development Steps

1. Add delta-based process CPU and I/O sampling for more accurate real process attribution.
2. Add retention/downsampling jobs for long-running history.
3. Improve Windows collection with PDH or ETW for lower overhead and better reliability.
4. Add a local application API layer for the future desktop UI.
5. Build the WinUI/WPF desktop app around explanations, not raw dashboards.
