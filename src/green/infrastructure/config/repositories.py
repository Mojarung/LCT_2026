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
from green.application.symbols import SymbolCatalog, SymbolEntry
from green.domain.norms import (
    Act,
    Citation,
    DistanceRule,
    InvasiveGroupRule,
    InvasiveSpecies,
    Reference,
    RuleBook,
    SpeciesRestriction,
)
from green.domain.planting import LifeForm, Species
from green.infrastructure.config.schemas import (
    ActsFile,
    CitationModel,
    LayerMapFile,
    ProfileModel,
    RulesFile,
    SpeciesFile,
    SpeciesModel,
    SymbolsFile,
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


def _species(model: SpeciesModel) -> Species:
    """Запись каталога в доменный объект: списки становятся frozenset, life_form - перечислением."""
    return Species(
        code=model.code,
        name_ru=model.name_ru,
        name_lat=model.name_lat,
        crown_diameter_m=model.crown_diameter_m,
        genus=model.genus,
        family=model.family,
        life_form=LifeForm(model.life_form),
        height_m=model.height_m,
        crown_mature_m=model.crown_mature_m,
        evergreen=model.evergreen,
        root_type=model.root_type,
        growth=model.growth,
        lifespan_years=model.lifespan_years,
        hardiness_zone=model.hardiness_zone,
        light=model.light,
        moisture=model.moisture,
        salt_tolerance=model.salt_tolerance,
        gas_tolerance=model.gas_tolerance,
        compaction_tolerance=model.compaction_tolerance,
        allergen=model.allergen,
        toxic=model.toxic,
        thorny=model.thorny,
        fluff=model.fluff,
        planting_sex=model.planting_sex,
        fruit_litter=model.fruit_litter,
        invasive_group=model.invasive_group,
        decor_months=frozenset(model.decor_months),
        uses=frozenset(model.uses),
        care_level=model.care_level,
        pilot_streets=model.pilot_streets,
        pilot_count=model.pilot_count,
        categories={str(key): str(value) for key, value in model.categories.items()},
        status=model.status,
        sources=dict(model.sources),
    )


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
                min_crown_m=r.min_crown_m,
                traits=frozenset(r.traits),
            )
            for r in rules_file.distance_rules
        )
        rulebook = RuleBook(
            acts=acts,
            distance_rules=distance,
            fingerprint=hashlib.sha256((acts_digest + rules_digest).encode()).hexdigest(),
            invasive_species=tuple(
                InvasiveSpecies(
                    rule_id=i.rule_id,
                    species_lat=i.species_lat,
                    group=i.group,
                    citation=_citation(i.citation),
                )
                for i in rules_file.invasive_species
            ),
            invasive_groups=tuple(
                InvasiveGroupRule(
                    rule_id=g.rule_id,
                    group=g.group,
                    conditional_on=frozenset(g.conditional_on),
                    condition=g.condition,
                    citation=_citation(g.citation),
                )
                for g in rules_file.invasive_groups
            ),
            species_restrictions=tuple(
                SpeciesRestriction(rule_id=r.rule_id, kind=r.kind, citation=_citation(r.citation))
                for r in rules_file.species_restrictions
            ),
        )
        ids = [rule.rule_id for rule in rulebook.all_rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ConfigurationError(f"Повторяются rule_id: {', '.join(duplicates)}")
        cited = {act_id for r in rulebook.all_rules for act_id in r.citation.act_ids}
        unknown_acts = sorted(cited - acts.keys())
        if unknown_acts:
            raise ConfigurationError(
                f"Правила ссылаются на неизвестные акты: {', '.join(unknown_acts)}"
            )
        return rulebook


class YamlLayerMapSource:
    """Карта слоёв и словарь условных знаков рядом с ней (symbols.yaml, если он есть)."""

    def __init__(self, path: Path, symbols: Path | None = None) -> None:
        self._path = path
        self._symbols = symbols if symbols is not None else path.with_name("symbols.yaml")

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
                priority=rule.priority,
            )
            for rule in parsed.rules
        )
        catalog = SymbolCatalog()
        if self._symbols.exists():
            symbol_data, symbol_digest = _read(self._symbols)
            parsed_symbols = _validate(SymbolsFile, symbol_data, self._symbols)
            catalog = SymbolCatalog(
                entries={
                    code: SymbolEntry(model.object_class, model.role, model.confirmed, model.note)
                    for code, model in parsed_symbols.symbols.items()
                },
                fingerprint=symbol_digest,
            )
            # Отпечаток семантики прогона учитывает и слои, и знаки.
            digest = hashlib.sha256(f"{digest}:{symbol_digest}".encode()).hexdigest()
        return LayerMap(rules=rules, fingerprint=digest, symbols=catalog)


class YamlSpeciesCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: tuple[Species, ...] | None = None

    def all(self) -> tuple[Species, ...]:
        if self._cache is None:
            data, _ = _read(self._path)
            parsed = _validate(SpeciesFile, data, self._path)
            codes = [s.code for s in parsed.species]
            duplicates = sorted({c for c in codes if codes.count(c) > 1})
            if duplicates:
                raise ConfigurationError(f"Повторяются коды видов: {', '.join(duplicates)}")
            self._cache = tuple(_species(s) for s in parsed.species)
        return self._cache

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
