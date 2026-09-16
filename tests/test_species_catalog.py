"""База видов: полнота записей, согласованность с нормами и отказ от неполных файлов."""

from __future__ import annotations

from pathlib import Path

import pytest

from green.application.errors import ConfigurationError
from green.domain.norms import genus_of
from green.domain.planting import LifeForm
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
CATALOG = YamlSpeciesCatalog(CONFIG / "species.yaml")


def test_catalog_entries_are_complete_and_consistent() -> None:
    species = CATALOG.all()
    assert len(species) >= 40
    codes = [s.code for s in species]
    assert len(codes) == len(set(codes))
    for s in species:
        assert s.genus == genus_of(s.name_lat), s.code
        assert s.family, s.code
        assert s.height_m > 0, s.code
        assert s.crown_mature_m > 0, s.code
        assert 1 <= s.hardiness_zone <= 9, s.code
        assert s.decor_months <= set(range(1, 13)), s.code
        assert s.status in {"verified", "reference", "pilot", "draft"}, s.code
        assert set(s.sources) >= {"hardiness_zone", "salt_tolerance"}, s.code


def test_invasive_species_carry_group_and_are_banned() -> None:
    """Каталог и rules.yaml не расходятся: инвазивная пометка без правила запрета бесполезна."""
    negundo = CATALOG.get("acer_negundo")
    assert negundo.invasive_group is not None
    rulebook = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
    assert rulebook.ban_for(negundo.name_lat) is not None
    for s in CATALOG.all():
        banned = rulebook.ban_for(s.name_lat) is not None
        assert banned == (s.invasive_group is not None), s.code


def test_conifers_detected_by_family() -> None:
    assert CATALOG.get("picea_abies").is_conifer
    assert not CATALOG.get("tilia_cordata").is_conifer
    assert CATALOG.get("picea_abies").life_form is LifeForm.TREE_LARGE


def test_life_forms_match_height() -> None:
    for s in CATALOG.all():
        if s.life_form is LifeForm.TREE_LARGE:
            assert s.height_m >= 20, s.code
        elif s.life_form is LifeForm.TREE_MEDIUM:
            assert 10 <= s.height_m < 20, s.code
        elif s.life_form is LifeForm.TREE_SMALL:
            assert s.height_m < 10, s.code
        elif s.life_form is LifeForm.SHRUB_TALL:
            assert s.height_m > 2, s.code
        elif s.life_form is LifeForm.SHRUB_MEDIUM:
            assert 1 <= s.height_m <= 2, s.code
        elif s.life_form is LifeForm.SHRUB_LOW:
            assert s.height_m < 1, s.code


def test_missing_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "species.yaml").write_text(
        "version: 2\nspecies:\n  - {code: x, name_ru: X, name_lat: Xus x, crown_diameter_m: 3}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlSpeciesCatalog(tmp_path / "species.yaml").all()


def test_catalog_is_read_once(tmp_path: Path) -> None:
    path = tmp_path / "species.yaml"
    path.write_text((CONFIG / "species.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    catalog = YamlSpeciesCatalog(path)
    first = catalog.all()
    path.unlink()
    assert catalog.all() == first
