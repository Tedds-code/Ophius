# Made in cooperation with ChatGPT
# File: src/astro_health/medical_assessment.py

from dataclasses import dataclass

from astro_health.models import Reading


@dataclass(frozen=True)
class MedicalAssessmentResult:
    """Result of medical assessment."""

    reading: Reading
    assessed: bool
    reason: str | None = None


def assess_medical_validity(reading: Reading) -> MedicalAssessmentResult:
    """
    Assess a reading against medical reference data.

    Medical reference data and assessment rules have not
    been implemented yet. This file acts as a placeholder
    until actual data is introduced, and must be changed before
    the program is finalized.
    
    """

    if reading.quality == "invalid":
        return MedicalAssessmentResult(
            reading=reading,
            assessed=False,
            reason="Reading failed structural validation.",
        )

    return MedicalAssessmentResult(
        reading=reading,
        assessed=False,
        reason="Medical reference data is not yet implemented.",
    )