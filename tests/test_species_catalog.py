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


RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()


def test_catalog_groups_match_the_369_pp_list() -> None:
    """Группа в каталоге равна группе перечня 369-ПП, и ни один вид перечня не пропущен."""
    for s in CATALOG.all():
        listed = RULEBOOK.invasive_for(s.name_lat)
        group = listed.group if listed is not None else None
        assert group == s.invasive_group, s.code


@pytest.mark.parametrize(
    ("code", "group"),
    [
        ("acer_negundo", 2),  # приложение 1, п. 2.1
        ("sorbaria_sorbifolia", 3),  # п. 3.12
        ("amelanchier_spicata", 3),  # п. 3.5
        ("cornus_alba", 3),  # п. 3.3
        ("physocarpus_opulifolius", 3),  # п. 3.9
        ("prunus_virginiana", 3),  # п. 3.13
    ],
)
def test_groups_follow_the_text_of_the_list(code: str, group: int) -> None:
    assert CATALOG.get(code).invasive_group == group


def test_every_invasive_group_has_a_verified_procedure() -> None:
    for listed in RULEBOOK.invasive_species:
        assert listed.citation.is_verified, listed.rule_id
        procedure = RULEBOOK.invasive_group(listed.group)
        assert procedure is not None, listed.rule_id
        assert procedure.citation.is_verified


def test_restricting_flags_require_a_source(tmp_path: Path) -> None:
    """Запрет по 743-ПП п. 3.6.18 без источника отнесения вида не загружается."""
    entry = (
        "  - {code: betula_x, name_ru: Берёза, name_lat: Betula x, genus: betula,"
        " family: Betulaceae, life_form: tree_large, height_m: 25, crown_diameter_m: 3,"
        " crown_mature_m: 10, hardiness_zone: 2, salt_tolerance: 0, allergen: 2,"
        " sources: {hardiness_zone: a, salt_tolerance: b}}\n"
    )
    (tmp_path / "species.yaml").write_text("version: 2\nspecies:\n" + entry, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        YamlSpeciesCatalog(tmp_path / "species.yaml").all()


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
