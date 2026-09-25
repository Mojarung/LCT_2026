"""Resolve XREFs from an explicit package; never discover files from a DXF path."""

from __future__ import annotations

import hashlib
import posixpath
import struct
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ezdxf import xref
from ezdxf.entities import Insert
from ezdxf.lldxf import const
from ezdxf.math import Vec3

from green.application.assembly import PackageAssembly, PackageInput, ReferenceBinding
from green.application.errors import InputError
from green.application.semantic_names import slug_key
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import require_exportable_document

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import Block
    from ezdxf.layouts import BaseLayout, BlockLayout

MAX_REFERENCE_DEPTH = 8


@dataclass(frozen=True, slots=True)
class _Link:
    block: BlockLayout
    reference: str
    target: int | None
    overlay: bool


@dataclass(slots=True)
class DrawingPackage:
    sources: Sequence[Path]
    names: tuple[str, ...]
    documents: tuple[Drawing, ...]
    roots: tuple[int, ...]
    links: tuple[tuple[_Link, ...], ...]
    notes: list[str]
    bindings: list[ReferenceBinding] = field(default_factory=list)
    resolved: set[int] = field(default_factory=set)
    absent: frozenset[tuple[str, str]] = frozenset()

    @classmethod
    def load(
        cls,
        sources: Sequence[Path],
        names: Sequence[str] = (),
        absent: Collection[tuple[str, str]] = (),
    ) -> DrawingPackage:
        """absent - пары (файл комплекта, путь ссылки), которых нет в исходных данных заказчика.

        Их составляет каталог улиц, проверив весь архив. Такая ссылка не останавливает сборку,
        а становится названным пробелом входных данных; любая другая ненайденная - ошибка.
        """
        labels = tuple(names) if names else tuple(str(path) for path in sources)
        if len(labels) != len(sources):
            raise InputError("Комплект: число исходных имён не совпадает с числом файлов")
        if len({path.resolve() for path in sources}) != len(sources):
            raise InputError("Комплект содержит один и тот же файл несколько раз")
        documents, notes = [], []
        for path in sources:
            doc, warnings = load_document(path)
            require_exportable_document(doc, path.name)
            replaced = _explode_proxies(doc)
            if replaced:
                notes.append(
                    f"Комплект: в {path.name} {replaced} прокси-объектов (ACAD_PROXY_ENTITY) "
                    "заменены своим рисунком: ezdxf не переносит их между файлами"
                )
            documents.append(doc)
            notes.extend(warnings)
        links = tuple(
            tuple(
                _Link(
                    block,
                    _definition(block).dxf.get("xref_path", ""),
                    _match(labels, index, _definition(block).dxf.get("xref_path", "")),
                    _definition(block).is_xref_overlay,
                )
                for block in _references(doc.modelspace())
            )
            for index, doc in enumerate(documents)
        )
        # Ссылка на основу не делает её «ссылаемой»: основа уже во входе (_provide_base).
        referenced = {link.target for group in links for link in group if link.target}
        roots = (0, *(index for index in range(1, len(sources)) if index not in referenced))
        # A closed component of extra files must not silently disappear from a package.
        reached = set(roots)
        pending = list(roots)
        while pending:
            for link in links[pending.pop()]:
                if link.target is not None and link.target not in reached:
                    reached.add(link.target)
                    pending.append(link.target)
        if len(reached) != len(sources):
            raise InputError("Комплект: замкнутый цикл внешних ссылок среди дополнительных файлов")
        declared = frozenset((_nfc(host), _nfc(reference)) for host, reference in absent)
        return cls(sources, labels, tuple(documents), roots, links, notes, absent=declared)

    def resolve(self) -> None:
        for index in self.roots:
            self._resolve(index, chain=())

    def _resolve(self, index: int, *, chain: tuple[int, ...]) -> None:
        if index in chain or len(chain) >= MAX_REFERENCE_DEPTH:
            raise InputError(f"XREF: цикл или слишком глубокая вложенность: {self.names[index]}")
        if index in self.resolved:
            return
        for link in self.links[index]:
            if chain and link.overlay:
                self._exclude_nested_overlay(index, link)
                continue
            if (
                link.target is None
                and (_nfc(self.names[index]), _nfc(link.reference)) in self.absent
            ):
                self._skip_absent(index, link)
                continue
            target = self._supplied_target(index, link)
            if target == 0:
                self._provide_base(index, link, nested=bool(chain))
            else:
                self._resolve(target, chain=(*chain, index))
                self._embed(index, link, target)
        self.resolved.add(index)

    def _exclude_nested_overlay(self, index: int, link: _Link) -> None:
        block = link.block
        if len(block):
            raise InputError(f"XREF {block.name}: вложенный overlay содержит кэш геометрии")
        _clear_xref_flags(block)
        self.bindings.append(
            ReferenceBinding(
                self.names[index],
                block.name,
                link.reference,
                self.names[link.target] if link.target is not None else None,
                "excluded_nested_overlay",
                0,
            )
        )

    def _skip_absent(self, index: int, link: _Link) -> None:
        """Файла ссылки нет в исходных данных: объектов из него на плане нет, и это видно."""
        block = link.block
        if len(block):
            raise InputError(f"XREF {block.name}: непустой кэш нельзя незаметно заменить")
        _clear_xref_flags(block)
        self.notes.append(
            f"XREF {block.name}: файла {link.reference!r} нет в исходных данных заказчика, "
            f"его объектов на плане нет ({self.names[index]})"
        )
        self.bindings.append(
            ReferenceBinding(
                self.names[index], block.name, link.reference, None, "absent_in_source", 0
            )
        )

    def _supplied_target(self, index: int, link: _Link) -> int:
        block = link.block
        if link.target is None:
            raise InputError(
                f"XREF {block.name}: файл {link.reference!r} не предоставлен в комплекте "
                f"для {self.names[index]}. Автоматический поиск вне комплекта запрещён."
            )
        if len(block):
            raise InputError(f"XREF {block.name}: непустой кэш нельзя незаметно заменить")
        return link.target

    def _embed(self, index: int, link: _Link, target: int) -> None:
        block, doc, source = link.block, self.documents[index], self.documents[target]
        if source.dxfversion > doc.dxfversion:
            raise InputError(
                f"XREF {block.name}: версия DXF новее основы; приведите версии к общей"
            )
        expected = expanded_entity_counts(source.modelspace())
        loader = xref.Loader(source, doc, conflict_policy=xref.ConflictPolicy.XREF_PREFIX)
        loader.load_modelspace(block)
        loader.execute(xref_prefix=block.name)
        _clear_xref_flags(block)
        _definition(block).dxf.base_point = source.header.get("$INSBASE", (0, 0, 0))
        actual = expanded_entity_counts(block)
        if actual != expected:
            raise InputError(
                f"XREF {block.name}: при внедрении потеряны/заменены сущности: "
                f"{count_difference(expected, actual)}"
            )
        self.bindings.append(
            ReferenceBinding(
                self.names[index],
                block.name,
                link.reference,
                self.names[target],
                "embedded",
                len(source.modelspace()),
            )
        )

    def _provide_base(self, index: int, link: _Link, *, nested: bool) -> None:
        """Ссылка на основу комплекта: основа уже во входе, второй раз её не внедряем.

        Так устроены комплекты каталога: файл границ работ ссылается на топографию, которая
        сама загружена основой. Это верно, только если ссылка ставит основу туда, где она
        и лежит: вставка в пространстве модели в (0, 0, 0), масштаб 1, без поворота, точка
        вставки основы (0, 0, 0). Иначе ссылка означает второе положение основы - ошибка.
        """
        block = link.block
        if nested:
            raise InputError(
                f"XREF {block.name}: цикл ссылок через основу {self.names[0]}: "
                f"{self.names[index]} вложен в комплект и снова ссылается на основу"
            )
        inserts = _inserts_of(self.documents[index], block.name)
        placed_as_is = Vec3(self.documents[0].header.get("$INSBASE", (0, 0, 0))).is_null and all(
            owner == "*model_space" and _identity(insert) for owner, insert in inserts
        )
        if not placed_as_is:
            raise InputError(
                f"XREF {block.name}: ссылка на основу {self.names[0]} ставит её не на своё "
                f"место (сдвиг, поворот, масштаб или вставка внутри блока) в {self.names[index]}"
            )
        _clear_xref_flags(block)
        self.bindings.append(
            ReferenceBinding(
                self.names[index], block.name, link.reference, self.names[0], "provided_as_input", 0
            )
        )

    def report(self) -> PackageAssembly:
        inputs = []
        for index, path in enumerate(self.sources):
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            role = "base" if index == 0 else "overlay" if index in self.roots else "xref_asset"
            inputs.append(PackageInput(self.names[index], digest, role))
        return PackageAssembly(tuple(inputs), tuple(self.bindings))


def _clear_xref_flags(block: BlockLayout) -> None:
    _definition(block).set_flag_state(
        const.BLK_XREF | const.BLK_XREF_OVERLAY | const.BLK_EXTERNAL, state=False
    )


def _definition(block: BlockLayout) -> Block:
    entity = block.block
    if entity is None:
        raise InputError(f"Нет определения блока {block.name}")
    return entity


def _path_key(name: str) -> str:
    name = posixpath.normpath(unicodedata.normalize("NFC", name.replace("\\", "/"))).casefold()
    stem, suffix = posixpath.splitext(name)
    return stem + ".dxf" if suffix in {".dwg", ".dxf"} else name


def _match(names: tuple[str, ...], host: int, reference: str) -> int | None:
    if not reference:
        return None
    keys = [_path_key(name) for name in names]
    relative = _path_key(
        posixpath.join(
            posixpath.dirname(names[host].replace("\\", "/")), reference.replace("\\", "/")
        )
    )
    for target in (relative, _path_key(reference)):
        exact = [index for index, key in enumerate(keys) if key == target]
        if exact:
            return _unambiguous(exact, reference)
    base = posixpath.basename(_path_key(reference))
    matches = [index for index, key in enumerate(keys) if posixpath.basename(key) == base]
    if matches:
        return _unambiguous(matches, reference)
    # Каталог улиц хранит файлы транслитом («00-1-10004141-topografiya.dxf»), а ссылка помнит
    # исходное имя («00.1_10004141_Топография.dwg»): последняя попытка - ключ имени.
    stem = _stem_key(reference)
    slugged = [index for index, name in enumerate(names) if _stem_key(name) == stem]
    return _unambiguous(slugged, reference) if stem and slugged else None


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _stem_key(name: str) -> str:
    return slug_key(posixpath.splitext(posixpath.basename(name.replace("\\", "/")))[0])


def _inserts_of(doc: Drawing, name: str) -> list[tuple[str, Insert]]:
    """Все вставки блока в документе с именем владельца (пространство модели или блок)."""
    key = name.casefold()
    found = []
    for layout in doc.blocks:
        owner = layout.name.casefold()
        if owner.startswith("*paper_space"):
            continue
        found.extend(
            (owner, entity)
            for entity in layout.query("INSERT")
            if isinstance(entity, Insert) and entity.dxf.name.casefold() == key
        )
    return found


def _identity(insert: Insert) -> bool:
    dxf = insert.dxf
    scales = (dxf.get("xscale", 1), dxf.get("yscale", 1), dxf.get("zscale", 1))
    return (
        Vec3(dxf.insert).is_null
        and all(abs(scale - 1) < 1e-9 for scale in scales)  # noqa: PLR2004 - точность double
        and abs(dxf.get("rotation", 0) % 360) < 1e-9  # noqa: PLR2004
        and Vec3(dxf.get("extrusion", (0, 0, 1))).isclose((0, 0, 1))
        and insert.mcount == 1
    )


def _unambiguous(matches: list[int], reference: str) -> int:
    if len(matches) != 1:
        raise InputError(
            f"XREF {reference!r}: несколько одноимённых файлов, нужен точный путь в комплекте"
        )
    return matches[0]


def _references(layout: BaseLayout) -> tuple[BlockLayout, ...]:
    found, seen = [], set()
    pending = [layout]
    while pending:
        for entity in pending.pop().query("INSERT"):
            if not isinstance(entity, Insert):
                raise InputError("Некорректная сущность INSERT в комплекте")
            block = entity.block()
            if block is None:
                raise InputError(f"INSERT {entity.dxf.name}: нет определения блока")
            if block.name.casefold() in seen:
                continue
            seen.add(block.name.casefold())
            if _definition(block).is_xref or _definition(block).is_xref_overlay:
                found.append(block)
            else:
                pending.append(block)
    return tuple(found)


def _explode_proxies(doc: Drawing) -> int:
    """Прокси-объект с рисунком - примитивами рисунка на своём слое, в загруженной копии
    комплекта (файл на диске не меняется). Без рисунка или с нечитаемым рисунком объект
    остаётся, и проверка внедрения назовёт его потерю."""
    replaced = 0
    for layout in (doc.modelspace(), *doc.blocks):
        for proxy in list(layout.query("ACAD_PROXY_ENTITY")):
            if not proxy.proxy_graphic:
                continue
            layer = proxy.dxf.get("layer", "0")
            try:
                parts = proxy.explode()  # ty: ignore[unresolved-attribute]
            except ValueError, TypeError, ArithmeticError, IndexError, struct.error:
                continue
            for part in parts:
                if part.dxf.get("layer", "0") == "0":
                    part.dxf.layer = layer
            replaced += 1
    return replaced


def count_difference(expected: Counter[str], actual: Counter[str]) -> str:
    """Какие типы разошлись: «ACAD_PROXY_ENTITY 4 -> 0, LINE 120 -> 118»."""
    kinds = sorted(set(expected) | set(actual), key=lambda k: -abs(expected[k] - actual[k]))
    changed = [f"{k} {expected[k]} -> {actual[k]}" for k in kinds if expected[k] != actual[k]]
    more = f" и ещё {len(changed) - 8}" if len(changed) > 8 else ""  # noqa: PLR2004
    return ", ".join(changed[:8]) + more


def expanded_entity_counts(layout: BaseLayout) -> Counter[str]:
    """Check every referenced block too; top-level INSERT counts can hide losses."""
    cache: dict[str, Counter[str]] = {}

    def visit(space: BaseLayout, chain: tuple[str, ...]) -> Counter[str]:
        if len(chain) > MAX_REFERENCE_DEPTH:
            raise InputError("Склейка: слишком глубокая вложенность блоков")
        result: Counter[str] = Counter()
        for entity in space:
            kind = entity.dxftype()
            result[kind] += 1
            if kind != "INSERT":
                continue
            if not isinstance(entity, Insert):
                raise InputError("Некорректная сущность INSERT в комплекте")
            block = entity.block()
            if block is None or block.name in chain:
                raise InputError("Склейка: отсутствующий блок или цикл в структуре сущностей")
            if block.name not in cache:
                cache[block.name] = visit(block, (*chain, block.name))
            result.update(
                {kind: count * entity.mcount for kind, count in cache[block.name].items()}
            )
            result["ATTRIB"] += len(entity.attribs) * entity.mcount
        return +result

    return visit(layout, ())
