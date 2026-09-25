"""Resolve XREFs from an explicit package; never discover files from a DXF path."""

from __future__ import annotations

import hashlib
import posixpath
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ezdxf import xref
from ezdxf.entities import Insert
from ezdxf.lldxf import const

from green.application.assembly import PackageAssembly, PackageInput, ReferenceBinding
from green.application.errors import InputError
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import require_exportable_document

if TYPE_CHECKING:
    from collections.abc import Sequence
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

    @classmethod
    def load(cls, sources: Sequence[Path], names: Sequence[str] = ()) -> DrawingPackage:
        labels = tuple(names) if names else tuple(str(path) for path in sources)
        if len(labels) != len(sources):
            raise InputError("Комплект: число исходных имён не совпадает с числом файлов")
        if len({path.resolve() for path in sources}) != len(sources):
            raise InputError("Комплект содержит один и тот же файл несколько раз")
        documents, notes = [], []
        for path in sources:
            doc, warnings = load_document(path)
            require_exportable_document(doc, path.name)
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
        referenced = {link.target for group in links for link in group if link.target is not None}
        if 0 in referenced:
            raise InputError(
                "Комплект: основа сама указана во внешней ссылке; проверьте цикл/выбор основы"
            )
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
        return cls(sources, labels, tuple(documents), roots, links, notes)

    def resolve(self) -> None:
        for index in self.roots:
            self._resolve(index, chain=())

    def _resolve(self, index: int, *, chain: tuple[int, ...]) -> None:
        if index in chain or len(chain) >= MAX_REFERENCE_DEPTH:
            raise InputError(f"XREF: цикл или слишком глубокая вложенность: {self.names[index]}")
        if index in self.resolved:
            return
        doc = self.documents[index]
        for link in self.links[index]:
            block = link.block
            if chain and link.overlay:
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
                continue
            if link.target is None:
                raise InputError(
                    f"XREF {block.name}: файл {link.reference!r} не предоставлен в комплекте "
                    f"для {self.names[index]}. Автоматический поиск вне комплекта запрещён."
                )
            if len(block):
                raise InputError(f"XREF {block.name}: непустой кэш нельзя незаметно заменить")
            self._resolve(link.target, chain=(*chain, index))
            source = self.documents[link.target]
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
                missing = expected - actual
                added = actual - expected
                details = "; ".join(
                    f"{label}: "
                    + ", ".join(f"{kind}×{count}" for kind, count in sorted(changes.items())[:5])
                    for label, changes in (("недостаёт", missing), ("добавлено", added))
                    if changes
                )
                raise InputError(
                    f"XREF {block.name}: при внедрении потеряны/заменены сущности ({details})"
                )
            self.bindings.append(
                ReferenceBinding(
                    self.names[index],
                    block.name,
                    link.reference,
                    self.names[link.target],
                    "embedded",
                    len(source.modelspace()),
                )
            )
        self.resolved.add(index)

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
    return _unambiguous(matches, reference) if matches else None


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
