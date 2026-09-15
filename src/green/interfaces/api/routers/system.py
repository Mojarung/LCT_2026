"""Состояние сервиса и справочники для клиента."""

from __future__ import annotations

from fastapi import APIRouter

from green import __version__
from green.infrastructure.cad.writer import LAYER_COLORS, REJECT_BLOCK
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.schemas import ConverterOut, HealthOut, MetaOut, RulesOut, SpeciesOut

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> HealthOut:
    return HealthOut(version=__version__)


@router.get("/meta")
def meta(container: ContainerDep) -> MetaOut:
    rulebook = container.rules.load()
    rules = (*rulebook.distance_rules, *rulebook.species_bans)
    return MetaOut(
        version=__version__,
        default_profile=container.settings.default_profile,
        profiles=list(container.profiles.names()),
        result_layers=[*LAYER_COLORS, REJECT_BLOCK],
        rules=RulesOut(
            total=len(rules),
            verified=sum(r.citation.is_verified for r in rules),
            fingerprint=rulebook.fingerprint,
        ),
        species=[
            SpeciesOut(
                code=s.code,
                name_ru=s.name_ru,
                name_lat=s.name_lat,
                crown_diameter_m=s.crown_diameter_m,
            )
            for s in container.species.all()
        ],
        converters=[
            ConverterOut(name=c.name, available=c.available()) for c in container.converters
        ],
    )
