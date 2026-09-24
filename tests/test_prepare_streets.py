"""Комплект улицы собирается по внешним ссылкам основного чертежа, как его видит AutoCAD.

Основные чертежи пилота - сборки: сети по планшетам, борта, заливки, границы работ лежат
отдельными файлами и подключены внешними ссылками (перепись 25.09.2026: 253 ссылки, 137 из
них вели в файлы архива, не попавшие в комплект). Без них на плане нет части объектов.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import ezdxf
from ezdxf import xref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import prepare_streets as ps  # noqa: E402

STREET = "Пилотный проект 20 улиц/1. Улица"
HOST = f"{STREET}/Исходные данные/ГП.dwg"


def _members(*entries: tuple[str, int, int]) -> dict[str, zipfile.ZipInfo]:
    """Оглавление архива: путь, размер и CRC каждого файла."""
    members = {}
    for name, size, crc in entries:
        info = zipfile.ZipInfo(name)
        info.file_size, info.CRC = size, crc
        members[name] = info
    return members


def test_reference_is_found_by_its_relative_path_first() -> None:
    borders = f"{STREET}/Исходные данные/ссылки/Борта.dwg"
    elsewhere = f"{STREET}/Архив/Борта.dwg"
    members = _members((HOST, 10, 1), (borders, 5, 2), (elsewhere, 7, 3))

    assert ps.resolve_reference(HOST, ".\\ссылки\\Борта.dwg", members) == (borders, "по пути")


def test_path_ignores_case_unicode_form_and_dwg_dxf_extension() -> None:
    nets = f"{STREET}/СЕТИ/Сети.dwg"
    members = _members((HOST, 10, 1), (nets, 5, 2))

    assert ps.resolve_reference(HOST, "..\\сети\\СЕТИ.DXF", members) == (nets, "по пути")


def test_absolute_path_of_the_designer_falls_back_to_the_file_name() -> None:
    topo = f"{STREET}/Исходные данные/00.1_1_Топография.dwg"
    members = _members((HOST, 10, 1), (topo, 5, 2))

    found = ps.resolve_reference(HOST, "C:\\Users\\gip\\Desktop\\00.1_1_Топография.dwg", members)

    assert found == (topo, "по имени")


def test_of_differing_copies_the_one_nearest_to_the_host_wins() -> None:
    near = f"{STREET}/Исходные данные/tp/output[1]_tp.dwg"
    far = f"{STREET}/Старое/output[1]_tp.dwg"
    members = _members((HOST, 10, 1), (near, 5, 2), (far, 6, 3))

    assert ps.resolve_reference(HOST, "D:\\output[1]_tp.dwg", members) == (near, "по имени")


def test_equally_near_differing_copies_are_not_guessed() -> None:
    first = f"{STREET}/Исходные данные/a/Заливки.dwg"
    second = f"{STREET}/Исходные данные/b/Заливки.dwg"
    members = _members((HOST, 10, 1), (first, 5, 2), (second, 6, 3))

    assert ps.resolve_reference(HOST, "Заливки.dwg", members) == (None, "неоднозначно")


def test_identical_copies_are_one_and_the_same_reference() -> None:
    first = f"{STREET}/Исходные данные/a/Заливки.dwg"
    second = f"{STREET}/Исходные данные/b/Заливки.dwg"
    members = _members((HOST, 10, 1), (first, 5, 2), (second, 5, 2))

    assert ps.resolve_reference(HOST, "Заливки.dwg", members) == (first, "по имени")


def test_reference_absent_from_the_archive_is_reported_not_invented() -> None:
    members = _members((HOST, 10, 1))

    assert ps.resolve_reference(HOST, ".\\НО наташинский пр.dwg", members) == (
        None,
        "нет в архиве",
    )


def test_xrefs_lists_references_and_overlays_of_a_dxf(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    xref.attach(doc, block_name="Борта", filename=".\\ссылки\\Борта.dwg", insert=(0, 0))
    xref.attach(doc, block_name="Сетка", filename="Сетка.dwg", insert=(0, 0), overlay=True)
    path = tmp_path / "host.dxf"
    doc.saveas(path)

    assert sorted(ps.xrefs(path)) == [
        ("Борта", ".\\ссылки\\Борта.dwg", False),
        ("Сетка", "Сетка.dwg", True),
    ]


def test_kit_keeps_one_copy_of_equal_content_and_unique_catalog_names() -> None:
    same_a = f"{STREET}/a/Сети.dwg"
    same_b = f"{STREET}/b/Сети.dwg"
    other = f"{STREET}/c/Сети.dwg"
    members = _members((HOST, 10, 1), (same_a, 5, 2), (same_b, 5, 2), (other, 6, 3))
    kit = ps.Kit(ps.Street(number=1, title="1. Улица", slug="1-ulitsa"), members)

    for member in (HOST, same_a, same_b, other):
        kit.add(member, "ссылка")

    assert kit.files == {HOST: "gp.dxf", same_a: "seti.dxf", other: "seti-2.dxf"}
