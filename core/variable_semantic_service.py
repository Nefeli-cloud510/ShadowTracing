"""Variable semantic layer for the Shadow Tracing closed loop.

The system stores two parallel namespaces on purpose:
- ``raw_name``: the exact column header used by DataFrames, protocol
  parameters and the execution layer. Never translated back into prompt text.
- ``display_name``: the human-readable physical variable names shown in
  hypothesis statements, uncertainty text, candidate experiments and the UI.
- ``physical_name``: the canonical physical variable identifier kept for
  traceability when display aliases are refined later.

Business output always goes through :meth:`VariableSemanticService.to_display`
or :meth:`VariableSemanticService.display_text`; feature selection and protocol
features continue to use raw names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from core.unified_schema import DataDictionary, DataDictionarySummary

_IDENTIFIER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_\u4e00-\u9fff])"
    r"[A-Za-z]{1,8}_"
    r"[A-Za-z0-9_\-（）()\u4e00-\u9fff]{1,120}"
    r"(?![A-Za-z0-9_\u4e00-\u9fff])"
)


@dataclass(frozen=True)
class VariableSemanticEntry:
    raw_name: str
    physical_name: str
    display_name: str


@dataclass
class VariableSemanticService:
    entries: list[VariableSemanticEntry] = field(default_factory=list)

    @classmethod
    def from_data_dictionary(cls, dictionary: DataDictionary) -> "VariableSemanticService":
        entries: list[VariableSemanticEntry] = []
        for field_descriptor in dictionary.fields:
            raw = field_descriptor.field_name
            physical = (
                field_descriptor.physical_name
                or field_descriptor.physical_meaning
                or dictionary.user_supplementary.get(raw)
                or raw
            )
            display = (
                field_descriptor.display_name
                or dictionary.user_supplementary.get(raw)
                or field_descriptor.physical_meaning
                or raw
            )
            entries.append(
                VariableSemanticEntry(
                    raw_name=raw,
                    physical_name=physical,
                    display_name=display,
                )
            )
        for raw, display in dictionary.user_supplementary.items():
            if raw in {entry.raw_name for entry in entries}:
                continue
            entries.append(
                VariableSemanticEntry(
                    raw_name=raw,
                    physical_name=display,
                    display_name=display,
                )
            )
        return cls(entries=entries)

    @classmethod
    def from_summary(
        cls,
        summary: DataDictionarySummary | None,
    ) -> "VariableSemanticService":
        if summary is None:
            return cls(entries=[])
        entries: list[VariableSemanticEntry] = []
        seen_raw: set[str] = set()
        raw_names = _unique([
            summary.time_column,
            *summary.target_candidates,
            *summary.feature_candidates,
        ])
        for raw in raw_names:
            if raw in seen_raw:
                continue
            seen_raw.add(raw)
            display = summary.raw_display_map.get(raw) or _find_display(
                summary=summary,
                raw=raw,
            )
            entries.append(
                VariableSemanticEntry(
                    raw_name=raw,
                    physical_name=display,
                    display_name=display,
                )
            )
        for raw, display in summary.raw_display_map.items():
            if raw in seen_raw:
                continue
            seen_raw.add(raw)
            entries.append(
                VariableSemanticEntry(
                    raw_name=raw,
                    physical_name=display,
                    display_name=display,
                )
            )
        for display, raw in summary.display_raw_map.items():
            if raw in seen_raw:
                continue
            seen_raw.add(raw)
            display_name = next(
                (
                    entry.display_name
                    for entry in entries
                    if entry.raw_name == raw
                ),
                display,
            )
            entries.append(
                VariableSemanticEntry(
                    raw_name=raw,
                    physical_name=display_name,
                    display_name=display_name,
                )
            )
        return cls(entries=entries)

    def to_display(self, raw_name: str) -> str:
        entry = self._find_raw(raw_name)
        return entry.display_name if entry else raw_name

    def to_physical(self, raw_name: str) -> str:
        entry = self._find_raw(raw_name)
        return entry.physical_name if entry else raw_name

    def to_raw(self, name: str) -> str:
        entry = self._find_display(name)
        if entry is not None:
            return entry.raw_name
        return name

    def display_list(self, raw_names: Iterable[str]) -> list[str]:
        return _unique(self.to_display(raw_name) for raw_name in raw_names)

    def raw_list(self, display_names: Iterable[str]) -> list[str]:
        return _unique(self.to_raw(name) for name in display_names)

    def display_text(self, text: str) -> str:
        """Replace raw column headers with display names in user-facing text."""
        if not text:
            return text
        replaced, identifier_tokens = _protect_identifier_tokens(text)
        replaced, display_tokens = _protect_display_fragments(
            replaced,
            self._protectable_fragments(),
        )
        # Longest raw names first so nested/prefix headers are replaced correctly.
        for raw in sorted(self.raw_names(), key=len, reverse=True):
            if not raw or not replaced:
                continue
            display = self.to_display(raw)
            if display == raw:
                continue
            pattern = re.compile(re.escape(raw))
            replaced = pattern.sub(display, replaced)
        # Also collapse display aliases that are already a superset of a mapped
        # raw name (e.g. "p2_y中心值" contains raw "p2_y").
        display_aliases = {
            alias: display
            for alias, display in self._alias_replacements().items()
        }
        for alias in sorted(display_aliases, key=len, reverse=True):
            if not alias or alias == display_aliases[alias]:
                continue
            pattern = re.compile(re.escape(alias))
            replaced = pattern.sub(display_aliases[alias], replaced)
        for placeholder, original in display_tokens.items():
            replaced = replaced.replace(placeholder, original)
        for placeholder, original in identifier_tokens.items():
            replaced = replaced.replace(placeholder, original)
        return replaced

    def _protectable_fragments(self) -> set[str]:
        """Display/physical names that must never be re-translated again."""
        fragments: set[str] = set()
        for entry in self.entries:
            if entry.display_name and entry.display_name != entry.raw_name:
                fragments.add(entry.display_name)
            if entry.physical_name and entry.physical_name != entry.raw_name:
                fragments.add(entry.physical_name)
        fragments.update(self._alias_replacements())
        return {fragment for fragment in fragments if fragment}

    def _alias_replacements(self) -> dict[str, str]:
        """Map physical/display aliases that are supersets of a raw header."""
        replacements: dict[str, str] = {}
        raw_names = set(self.raw_names())
        for entry in self.entries:
            for name in (entry.display_name, entry.physical_name):
                if not name or name == entry.raw_name:
                    continue
                for raw in raw_names:
                    if raw != entry.raw_name and name and name != raw and raw in name:
                        replacements[name] = entry.display_name
                        break
        return replacements

    def matches_text(self, raw_name: str, text: str) -> bool:
        lowered = str(text or "").lower()
        if raw_name and raw_name.lower() in lowered:
            return True
        display = self.to_display(raw_name)
        return bool(display and display.lower() in lowered)

    def raw_names(self) -> list[str]:
        return _unique(entry.raw_name for entry in self.entries if entry.raw_name)

    def display_names(self) -> list[str]:
        return _unique(entry.display_name for entry in self.entries if entry.display_name)

    def build_display_summary(
        self,
        summary: DataDictionarySummary,
    ) -> DataDictionarySummary:
        raw_to_display = {
            raw: self.to_display(raw)
            for raw in [summary.time_column, *summary.target_candidates, *summary.feature_candidates]
            if raw and self.to_display(raw) != raw
        }
        display_to_raw = {
            display: raw
            for raw, display in raw_to_display.items()
        }
        return summary.model_copy(
            update={
                "display_time_column": self.to_display(summary.time_column),
                "display_target_candidates": self.display_list(summary.target_candidates),
                "display_feature_candidates": self.display_list(summary.feature_candidates),
                "raw_display_map": raw_to_display,
                "display_raw_map": display_to_raw,
            }
        )

    def build_display_block(
        self,
        target_names: Iterable[str] | None = None,
    ) -> str:
        raw_to_display = {
            entry.raw_name: entry.display_name
            for entry in self.entries
            if entry.raw_name and entry.display_name != entry.raw_name
        }
        display_targets = self.display_list(target_names or [])
        return (
            "{"
            f'"display_target_candidates": {display_targets}, '
            f'"display_feature_candidates": {self.display_names()}, '
            f'"raw_display_map": {raw_to_display}'
            "}"
        )

    def _find_raw(self, raw_name: str) -> VariableSemanticEntry | None:
        return next(
            (entry for entry in self.entries if entry.raw_name == raw_name),
            None,
        )

    def _find_display(self, name: str) -> VariableSemanticEntry | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry.display_name == name or entry.physical_name == name
            ),
            None,
        )


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.add(item)
            result.append(str(item))
    return result


def _protect_identifier_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Keep stable IDs such as ``H_p2_y..._branch`` from alias replacement."""
    placeholders: dict[str, str] = {}

    def keep_identifier(match: re.Match[str]) -> str:
        token = match.group(0)
        placeholder = f"\u0000ID{len(placeholders)}\u0000"
        placeholders[placeholder] = token
        return placeholder

    return _IDENTIFIER_TOKEN_RE.sub(keep_identifier, str(text)), placeholders


def _protect_display_fragments(
    text: str,
    fragments: set[str],
) -> tuple[str, dict[str, str]]:
    """Hold already-rendered display names so nested raw headers stay intact."""
    placeholders: dict[str, str] = {}
    result = text
    for fragment in sorted(fragments, key=len, reverse=True):
        if not fragment or fragment not in result:
            continue
        placeholder = f"\u0000D{len(placeholders)}\u0000"
        placeholders[placeholder] = fragment
        result = result.replace(fragment, placeholder)
    return result, placeholders


def _find_display(*, summary: DataDictionarySummary, raw: str) -> str:
    display = summary.display_raw_map.get(raw)
    if display:
        return display
    return next(
        (
            display_name
            for display_name, raw_name in summary.display_raw_map.items()
            if raw_name == raw
        ),
        raw,
    )
