"""Comparison of complete, independently checked alternatives under one quality policy."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VariantResult:
    name: str
    solver: str
    lawn_phase: tuple[float, float]
    lawn_rotation_deg: float
    valid: bool
    quality_index: float | None
    trees: int
    shrubs: int
    needs_approval: int
    error: str = ""


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    chosen: str
    variants: tuple[VariantResult, ...]
    objective: str = (
        "Only independently valid plans; maximize the configured final quality index, "
        "then prefer fewer approvals, then the earlier variant (baseline first)."
    )
    scope: str = (
        "Best among the listed completed variants, including species and shrubs. "
        "Quality weights are project choices, not a universal aesthetic optimum. "
        "Generation history only: manual edits require a new comparison."
    )
