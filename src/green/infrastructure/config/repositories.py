"""Загрузка YAML в доменные объекты. Отпечаток файла попадает в манифест каждого прогона."""

from __future__ import annotations

import hashlib
import re
from dataclasses import fields
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from green.application.classification import LayerMap, LayerRule
from green.application.errors import ConfigurationError, InputError
from green.application.params import PlanParams
from green.domain.norms import Act, Citation, DistanceRule, Reference, RuleBook, SpeciesBan
from green.domain.planting import Species
from green.infrastructure.config.schemas import (
    ActsFile,
    CitationModel,
    LayerMapFile,
    ProfileModel,
    RulesFile,
    SpeciesFile,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from pydantic import BaseModel

_PROFILE_NAME = re.compile(r"^[a-z0-9_-]{1,64}$")
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _read(path: Path) -> tuple[Any, str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Нет файла конфигурации {path}: {error}") from error
    return yaml.load(raw, Loader=_LOADER), hashlib.sha256(raw).hexdigest()  # noqa: S506 - SafeLoader


def _validate[T: BaseModel](model: type[T], data: object, path: Path) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ConfigurationError(f"{path.name}: {error}") from error


def _citation(model: CitationModel) -> Citation:
    return Citation(
        act_id=model.act_id,
        clause=model.clause,
        quote=model.quote,
        status=model.status,
        related=tuple(Reference(act_id=r.act_id, clause=r.clause) for r in model.related),
    )


class YamlRuleBookSource:
    def __init__(self, acts_path: Path, rules_path: Path) -> None:
        self._acts_path = acts_path
        self._rules_path = rules_path

    def load(self) -> RuleBook:
        acts_data, acts_digest = _read(self._acts_path)
        rules_data, rules_digest = _read(self._rules_path)
        acts_file = _validate(ActsFile, acts_data, self._acts_path)
        rules_file = _validate(RulesFile, rules_data, self._rules_path)
        acts = {
            a.act_id: Act(
                act_id=a.act_id,
                title=a.title,
                edition=a.edition,
                url=a.url,
                checked_at=a.checked_at,
                short=a.short,
            )
            for a in acts_file.acts
        }
        distance = tuple(
            DistanceRule(
                rule_id=r.rule_id,
                object_class=r.object_class,
                planting_type=r.planting_type,
                min_distance_m=r.min_distance_m,
                measure_to=r.measure_to,
                severity=r.severity,
                citation=_citation(r.citation),
                genera=frozenset(g.casefold() for g in r.genera),
            )
            for r in rules_file.distance_rules
        )
        bans = tuple(
            SpeciesBan(rule_id=b.rule_id, species_lat=b.species_lat, citation=_citation(b.citation))
            for b in rules_file.species_bans
        )
        ids = [rule.rule_id for rule in (*distance, *bans)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ConfigurationError(f"Повторяются rule_id: {', '.join(duplicates)}")
        cited = {act_id for r in (*distance, *bans) for act_id in r.citation.act_ids}
        unknown_acts = sorted(cited - acts.keys())
        if unknown_acts:
            raise ConfigurationError(
                f"Правила ссылаются на неизвестные акты: {', '.join(unknown_acts)}"
            )
        fingerprint = hashlib.sha256((acts_digest + rules_digest).encode()).hexdigest()
        return RuleBook(
            acts=acts, distance_rules=distance, species_bans=bans, fingerprint=fingerprint
        )


class YamlLayerMapSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> LayerMap:
        data, digest = _read(self._path)
        parsed = _validate(LayerMapFile, data, self._path)
        rules = tuple(
            LayerRule(
                pattern=re.compile(rule.pattern, re.IGNORECASE),
                target=rule.target,
                object_class=rule.object_class,
                confirmed=rule.confirmed,
                geometry=rule.geometry,
            )
            for rule in parsed.rules
        )
        return LayerMap(rules=rules, fingerprint=digest)


class YamlSpeciesCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def all(self) -> tuple[Species, ...]:
        data, _ = _read(self._path)
        parsed = _validate(SpeciesFile, data, self._path)
        return tuple(
            Species(
                code=s.code,
                name_ru=s.name_ru,
                name_lat=s.name_lat,
                crown_diameter_m=s.crown_diameter_m,
            )
            for s in parsed.species
        )

    def get(self, code: str) -> Species:
        for species in self.all():
            if species.code == code:
                return species
        raise InputError(f"Вид '{code}' отсутствует в ассортименте config/species.yaml")


class YamlProfileSource:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(p.stem for p in self._directory.glob("*.yaml")))

    def load(self, name: str, overrides: Mapping[str, object] | None = None) -> PlanParams:
        if not _PROFILE_NAME.fullmatch(name) or name not in self.names():
            raise InputError(f"Неизвестный профиль '{name}'. Доступны: {', '.join(self.names())}")
        path = self._directory / f"{name}.yaml"
        data, _ = _read(path)
        try:
            profile = ProfileModel.model_validate({**(data or {}), **(overrides or {})})
        except ValidationError as error:
            raise InputError(f"Параметры профиля '{name}' некорректны: {error}") from error
        values = profile.model_dump()
        return PlanParams(**{f.name: values[f.name] for f in fields(PlanParams)})
