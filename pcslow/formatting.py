from __future__ import annotations

from .models import DiagnosisResult, DiagnosisType


def format_diagnoses(diagnoses: list[DiagnosisResult]) -> str:
    lines: list[str] = []
    for diagnosis in diagnoses:
        if diagnosis.diagnosis_type == DiagnosisType.INSUFFICIENT_EVIDENCE:
            lines.append("Insufficient evidence to determine the cause.")
            lines.append(f"Reason: {diagnosis.summary}")
            continue

        lines.append(f"Likely cause: {diagnosis.label}")
        lines.append(f"Confidence: {round(diagnosis.confidence * 100)}%")
        lines.append(f"Severity: {diagnosis.severity.value}")
        lines.append(f"Why: {diagnosis.summary}")
        lines.append("Evidence:")
        for item in diagnosis.evidence:
            value = "" if item.value is None else f" ({item.value}{item.unit})"
            lines.append(f"- {item.observation}{value}")
        if diagnosis.alternatives:
            alternatives = ", ".join(item.value.replace("_", " ") for item in diagnosis.alternatives)
            lines.append(f"Possible alternative causes: {alternatives}")
        if diagnosis.data_gaps:
            lines.append("Data gaps:")
            for gap in diagnosis.data_gaps:
                lines.append(f"- {gap}")
        lines.append("")
    return "\n".join(lines).strip()
