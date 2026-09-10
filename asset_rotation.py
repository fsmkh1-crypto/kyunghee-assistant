from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import re
from typing import Iterable

SUPPORTED_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
ROLE_FOLDERS = ('default', 'cheer', 'rest', 'away', 'warning', 'leave', 'stats', 'settings', 'alert', 'profile')
_VARIANT_PATTERN = re.compile(r'^(?P<role>[a-z_]+)_(?P<set>\d{2})\.png$')


def raw_complete_sets(asset_dir: Path) -> tuple[int, ...]:
    root = Path(asset_dir)
    per_role: list[set[int]] = []
    for role in ROLE_FOLDERS:
        folder = root / role
        numbers: set[int] = set()
        if folder.is_dir():
            for path in folder.glob(f'{role}_[0-9][0-9].png'):
                match = _VARIANT_PATTERN.match(path.name)
                if match and match.group('role') == role and path.is_file():
                    numbers.add(int(match.group('set')))
        per_role.append(numbers)
    if not per_role:
        return ()
    return tuple(sorted(set.intersection(*per_role)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def complete_set_signature(asset_dir: Path, set_number: int) -> tuple[str, ...] | None:
    root = Path(asset_dir)
    values: list[str] = []
    for role in ROLE_FOLDERS:
        path = root / role / f'{role}_{int(set_number):02d}.png'
        if not path.is_file():
            return None
        values.append(_sha256(path))
    return tuple(values)


def unique_complete_sets(asset_dir: Path) -> tuple[int, ...]:
    """Return complete sets with byte-identical whole-set duplicates collapsed.

    Set 10 is preferred over set 09 only when the two whole sets are byte-for-byte
    identical.  This keeps the explicitly restored set-10 identity in automatic
    rotation without deleting either set from the asset catalog/manual picker.
    Other duplicate groups keep their lowest numbered representative.
    """
    groups: dict[tuple[str, ...], list[int]] = {}
    for number in raw_complete_sets(asset_dir):
        signature = complete_set_signature(asset_dir, number)
        if signature is None:
            continue
        groups.setdefault(signature, []).append(number)

    selected: list[int] = []
    for numbers in groups.values():
        numbers = sorted(numbers)
        if 9 in numbers and 10 in numbers:
            selected.append(10)
        else:
            selected.append(numbers[0])
    return tuple(sorted(selected))


def _read_state(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _new_cycle(values: list, last, rng) -> list:
    result = list(values)
    rng.shuffle(result)
    if len(result) > 1 and last is not None and result[0] == last:
        result[0], result[1] = result[1], result[0]
    return result


def next_nonrepeating_set(asset_dir: Path, state_path: Path, rng: random.Random | None = None) -> int | None:
    """Persistently consume each unique complete set once before reshuffling."""
    catalog = list(unique_complete_sets(asset_dir))
    if not catalog:
        return None
    chooser = rng or random.SystemRandom()
    state = _read_state(Path(state_path))
    old_catalog = state.get('catalog')
    remaining = state.get('remaining')
    last = state.get('last')

    valid = (
        isinstance(old_catalog, list)
        and [int(v) for v in old_catalog if isinstance(v, int)] == catalog
        and isinstance(remaining, list)
        and all(isinstance(v, int) and v in catalog for v in remaining)
    )
    if not valid:
        remaining = []
        last = last if isinstance(last, int) and last in catalog else None

    if not remaining:
        remaining = _new_cycle(catalog, last, chooser)

    selected = int(remaining.pop(0))
    _write_state(Path(state_path), {
        'catalog': catalog,
        'remaining': remaining,
        'last': selected,
    })
    return selected


def next_nonrepeating_ref(refs: Iterable[str], state_path: Path, rng: random.Random | None = None) -> str | None:
    """Persistently consume every catalog reference once before reshuffling."""
    catalog = sorted({str(ref) for ref in refs if str(ref)})
    if not catalog:
        return None
    chooser = rng or random.SystemRandom()
    state = _read_state(Path(state_path))
    remaining = state.get('remaining')
    last = state.get('last')
    valid = (
        state.get('catalog') == catalog
        and isinstance(remaining, list)
        and all(isinstance(v, str) and v in catalog for v in remaining)
    )
    if not valid:
        remaining = []
        last = last if isinstance(last, str) and last in catalog else None
    if not remaining:
        remaining = _new_cycle(catalog, last, chooser)
    selected = str(remaining.pop(0))
    _write_state(Path(state_path), {
        'catalog': catalog,
        'remaining': remaining,
        'last': selected,
    })
    return selected
