#!/usr/bin/env python3
"""Split a fixed-order 5x2 Kyunghee character sheet into 10 reviewed PNG assets.

This is a developer utility, not runtime application code.

Workflow:
  1) Preview: python tools/import_asset_sheet.py path/to/sheet.png
  2) Inspect the generated contact sheet.
  3) Install: python tools/import_asset_sheet.py path/to/sheet.png --install --approved
  4) Optional local commit: add --commit

The role order is fixed left-to-right, top-to-bottom:
  default, cheer, rest, away, warning,
  leave, stats, settings, alert, profile
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

try:
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy.ndimage import (
        binary_erosion,
        binary_fill_holes,
        distance_transform_edt,
        label as ndi_label,
    )
    from skimage.feature import peak_local_max
    from skimage.segmentation import watershed
except ImportError as exc:  # pragma: no cover - environment-dependent
    missing = getattr(exc, "name", "a required package")
    raise SystemExit(
        f"Missing asset-import dependency: {missing}. "
        "Install with: python -m pip install -r tools/requirements-asset-import.txt"
    ) from exc

ROLES = (
    "default",
    "cheer",
    "rest",
    "away",
    "warning",
    "leave",
    "stats",
    "settings",
    "alert",
    "profile",
)

ALGORITHM_VERSION = "kyunghee-5x2-watershed-v2-softalpha"
INDEX_SCHEMA_VERSION = 1
INDEX_PATH_NAME = "asset_index.json"
PREVIEW_SENTINEL = ".kyunghee_asset_preview"
DEFAULT_BG_THRESHOLD = 4
DEFAULT_MARGIN_FRACTION = 0.05
DEFAULT_PEAKS_PER_CELL = 1
DEFAULT_CELL_INSET = 0.05
DEFAULT_MIN_COMPONENT_AREA = 100
DEFAULT_EDGE_LOW = 2
DEFAULT_EDGE_HIGH = 28
DEFAULT_CENTROID_TOLERANCE = 0.80
SIL_MAX_DIFF_RATIO = 0.02
LUMA_MAX_DIFF = 6
APPEARANCE_MAX_MAE = 8.0

CONTACT_TILE_WIDTH = 300
CONTACT_TILE_HEIGHT = 410
CONTACT_IMAGE_HEIGHT = 360
CONTACT_LABEL_Y = 366
CONTACT_NOTE_Y = 384


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def discover_next_set(repo_root: Path) -> int:
    highest = 0
    for role in ROLES:
        folder = repo_root / "assets" / role
        if not folder.is_dir():
            continue
        pattern = re.compile(rf"^{re.escape(role)}_(\d{{2}})\.png$")
        for path in folder.iterdir():
            match = pattern.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def parse_set_number(raw: str | None, repo_root: Path) -> int:
    if raw is None or raw.lower() == "auto":
        value = discover_next_set(repo_root)
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SystemExit(f"Invalid --set value: {raw!r}; use auto or an integer 1-99") from exc
    if not 1 <= value <= 99:
        raise SystemExit("Set number must be between 1 and 99")
    return value


def parse_manual_seeds(values: Iterable[str]) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {role: [] for role in ROLES}
    for raw in values:
        try:
            role, xy = raw.split(":", 1)
            x_text, y_text = xy.split(",", 1)
            x, y = int(x_text), int(y_text)
        except ValueError as exc:
            raise SystemExit(
                f"Invalid --seed {raw!r}; expected ROLE:X,Y, e.g. away:985,424. "
                "Coordinates are X first, then Y."
            ) from exc
        if role not in result:
            raise SystemExit(f"Unknown seed role {role!r}; expected one of: {', '.join(ROLES)}")
        result[role].append((x, y))
    return result


def validate_sheet(rgb: np.ndarray, bg_threshold: int) -> None:
    height, width = rgb.shape[:2]
    if width < 500 or height < 500:
        raise SystemExit(f"Source sheet is too small ({width}x{height}); expected a 5x2 character sheet")

    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    border_brightness = np.max(border, axis=1)
    dark_ratio = float(np.mean(border_brightness <= max(12, bg_threshold + 8)))
    if dark_ratio < 0.80:
        raise SystemExit(
            "Standard importer expects a black/near-black outer background. "
            f"Only {dark_ratio:.1%} of border pixels look dark. Stop for manual review instead of guessing."
        )

    foreground = np.max(rgb, axis=2) > bg_threshold
    for row in range(2):
        for col in range(5):
            x0, x1 = int(col * width / 5), int((col + 1) * width / 5)
            y0, y1 = int(row * height / 2), int((row + 1) * height / 2)
            occupancy = int(np.count_nonzero(foreground[y0:y1, x0:x1]))
            if occupancy < 1_000:
                role = ROLES[row * 5 + col]
                raise SystemExit(
                    f"Cell {row + 1},{col + 1} ({role}) has too little foreground ({occupancy} px). "
                    "The sheet may not follow the standard 5x2 layout."
                )


def find_row_split(foreground: np.ndarray) -> int:
    """Find the low-density horizontal valley separating the two logical rows."""
    height = foreground.shape[0]
    low = int(height * 0.42)
    high = int(height * 0.68)
    counts = foreground.sum(axis=1).astype(np.float32)
    smooth = np.convolve(counts, np.ones(9, dtype=np.float32) / 9.0, mode="same")
    return low + int(np.argmin(smooth[low:high]))


def row_overlap_diagnostics(labels: np.ndarray, row_split: int) -> dict[str, object]:
    report: dict[str, object] = {}
    for role_index, role in enumerate(ROLES, start=1):
        ys, _ = np.where(labels == role_index)
        total = len(ys)
        if not total:
            continue
        if role_index <= 5:
            overlap = int(np.count_nonzero(ys >= row_split))
            direction = "below_split"
        else:
            overlap = int(np.count_nonzero(ys < row_split))
            direction = "above_split"
        fraction = overlap / total
        report[role] = {
            direction + "_pixels": overlap,
            direction + "_fraction": round(fraction, 4),
            "review_recommended": bool(overlap >= 100),
        }
    return report


def build_markers(
    distance: np.ndarray,
    manual_seeds: dict[str, list[tuple[int, int]]],
    *,
    row_split: int,
    peaks_per_cell: int,
    cell_inset: float,
) -> np.ndarray:
    height, width = distance.shape
    markers = np.zeros((height, width), dtype=np.int32)

    for role_index, role in enumerate(ROLES, start=1):
        row = (role_index - 1) // 5
        col = (role_index - 1) % 5
        x0, x1 = int(col * width / 5), int((col + 1) * width / 5)
        y0, y1 = ((0, row_split) if row == 0 else (row_split, height))
        dx = int((x1 - x0) * cell_inset)
        dy = int((y1 - y0) * cell_inset)
        ix0, ix1 = x0 + dx, x1 - dx
        iy0, iy1 = y0 + dy, y1 - dy
        sub = distance[iy0:iy1, ix0:ix1]

        min_peak_distance = max(10, int(min(y1 - y0, x1 - x0) * 0.08))
        coords = peak_local_max(
            sub,
            min_distance=min_peak_distance,
            threshold_abs=4,
            num_peaks=peaks_per_cell,
            exclude_border=False,
        )
        if not len(coords):
            y_rel, x_rel = np.unravel_index(np.argmax(sub), sub.shape)
            coords = np.array([(int(y_rel), int(x_rel))])

        for y_rel, x_rel in coords:
            markers[iy0 + int(y_rel), ix0 + int(x_rel)] = role_index

        for x, y in manual_seeds[role]:
            if not (0 <= x < width and 0 <= y < height):
                raise SystemExit(f"Manual seed for {role} is outside the image: {x},{y}")
            if distance[y, x] <= 0:
                raise SystemExit(
                    f"Manual seed for {role} at {x},{y} lands on background. "
                    "Choose a visible subject/prop pixel."
                )
            markers[y, x] = role_index

    return markers


def assign_unseeded_components(
    labels: np.ndarray,
    foreground: np.ndarray,
    *,
    min_component_area: int,
    row_split: int,
) -> tuple[np.ndarray, dict[str, int]]:
    """Attach detached props by nominal 5x2 cell instead of nearest pose seed."""
    height, width = foreground.shape
    components, count = ndi_label(foreground & (labels == 0), np.ones((3, 3), dtype=int))
    result = labels.copy()
    assigned = skipped = skipped_pixels = 0
    for component_id in range(1, count + 1):
        ys, xs = np.where(components == component_id)
        area = len(xs)
        if area < min_component_area:
            skipped += 1
            skipped_pixels += area
            continue
        center_x = float(xs.mean())
        center_y = float(ys.mean())
        row = 0 if center_y < row_split else 1
        col = min(4, int(center_x / (width / 5)))
        role_index = row * 5 + col + 1
        result[components == component_id] = role_index
        assigned += 1
    return result, {
        "unseeded_components_assigned": assigned,
        "unseeded_small_components_skipped": skipped,
        "unseeded_small_pixels_skipped": skipped_pixels,
    }


def remove_tiny_role_fragments(
    labels: np.ndarray,
    min_component_area: int,
) -> tuple[np.ndarray, dict[str, int]]:
    result = labels.copy()
    structure = np.ones((3, 3), dtype=int)
    removed = removed_pixels = 0
    for role_index in range(1, len(ROLES) + 1):
        components, count = ndi_label(labels == role_index, structure)
        for component_id in range(1, count + 1):
            component = components == component_id
            area = int(np.count_nonzero(component))
            if area < min_component_area:
                result[component] = 0
                removed += 1
                removed_pixels += area
    return result, {
        "tiny_role_fragments_removed": removed,
        "tiny_role_pixels_removed": removed_pixels,
    }


def validate_role_centroids(
    labels: np.ndarray,
    *,
    tolerance: float,
    row_split: int,
) -> dict[str, dict[str, float]]:
    height, width = labels.shape
    cell_w = width / 5.0
    report: dict[str, dict[str, float]] = {}
    for role_index, role in enumerate(ROLES, start=1):
        ys, xs = np.where(labels == role_index)
        if not len(xs):
            raise SystemExit(f"Automatic split failed centroid gate for {role}: no labeled pixels")
        actual_x = float(xs.mean()) / cell_w
        row = (role_index - 1) // 5
        if row == 0:
            actual_y = float(ys.mean()) / max(1.0, float(row_split))
        else:
            actual_y = (float(ys.mean()) - row_split) / max(1.0, float(height - row_split))
        expected_x = ((role_index - 1) % 5) + 0.5
        dx = abs(actual_x - expected_x)
        dy = abs(actual_y - 0.5)
        report[role] = {"dx_cells": round(dx, 4), "dy_cells": round(dy, 4)}
        if dx > tolerance or dy > tolerance:
            raise SystemExit(
                f"Automatic split failed role-position gate for {role}: centroid is "
                f"{dx:.2f} cells horizontally / {dy:.2f} vertically from its expected cell. "
                "Stop for manual seed correction instead of guessing."
            )
    return report


def refine_alpha(
    rgb: np.ndarray,
    mask: np.ndarray,
    *,
    edge_low: int,
    edge_high: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recover straight RGB and soft alpha from a black-matted source edge."""
    luma = np.max(rgb, axis=2).astype(np.float32)
    structure = np.ones((3, 3), dtype=bool)

    # Brightness identifies confident foreground; morphology restores dark
    # interior regions while guaranteeing the outermost silhouette is never core.
    core_luma = binary_fill_holes(mask & (luma > edge_high))
    core_geom = binary_erosion(mask, structure=structure, iterations=2, border_value=0)
    core = core_luma | binary_fill_holes(core_geom)
    core &= binary_erosion(mask, structure=structure, iterations=1, border_value=0)

    if not np.any(core):
        core = binary_erosion(mask, structure=structure, iterations=1, border_value=0)

    span = max(1, edge_high - edge_low)
    band = np.clip((luma - edge_low) / span, 0.0, 1.0)
    alpha = np.where(core, 1.0, band)
    alpha = np.where(mask, alpha, 0.0).astype(np.float32)

    safe_alpha = np.maximum(alpha, 1.0 / 255.0)[:, :, None]
    straight = np.clip(rgb.astype(np.float32) / safe_alpha, 0, 255).astype(np.uint8)
    soft_alpha = np.rint(alpha * 255.0).astype(np.uint8)
    return straight, soft_alpha, core


def bleed_transparent_rgb(
    rgb: np.ndarray,
    alpha: np.ndarray,
    core: np.ndarray,
) -> np.ndarray:
    """Fill transparent RGB from nearest trusted core pixels for clean resizing."""
    seeds = core
    if not np.any(seeds):
        seeds = alpha >= 128
    if not np.any(seeds):
        return rgb
    _, (iy, ix) = distance_transform_edt(~seeds, return_indices=True)
    result = rgb.copy()
    transparent = alpha == 0
    result[transparent] = rgb[iy[transparent], ix[transparent]]
    return result


def _bbox_for_alpha(alpha: np.ndarray, threshold: int = 24) -> tuple[int, int, int, int]:
    ys, xs = np.where(alpha > threshold)
    if not len(xs):
        return 0, 0, alpha.shape[1], alpha.shape[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _bits_to_hex(bits: np.ndarray) -> str:
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bool(bit))
    width = (bits.size + 3) // 4
    return f"{value:0{width}x}"


def signatures(rgb: np.ndarray, alpha: np.ndarray) -> dict[str, object]:
    """Return pose and appearance signatures normalized to the visible alpha bbox."""
    box = _bbox_for_alpha(alpha)
    rgb_image = Image.fromarray(rgb, "RGB").crop(box)
    alpha_image = Image.fromarray(alpha, "L").crop(box)

    sil = alpha_image.resize((32, 32), Image.Resampling.BILINEAR)
    silhouette = _bits_to_hex(np.asarray(sil) > 127)

    small_rgb = np.asarray(rgb_image.resize((9, 8), Image.Resampling.BILINEAR), dtype=np.float32)
    small_alpha = np.asarray(alpha_image.resize((9, 8), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    composited = small_rgb * small_alpha[:, :, None] + 128.0 * (1.0 - small_alpha[:, :, None])
    luma = composited.mean(axis=2)
    luminance = _bits_to_hex(luma[:, 1:] > luma[:, :-1])

    app_rgb = np.asarray(rgb_image.resize((8, 8), Image.Resampling.BILINEAR), dtype=np.float32)
    app_alpha = np.asarray(alpha_image.resize((8, 8), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    appearance = np.clip(
        app_rgb * app_alpha[:, :, None] + 128.0 * (1.0 - app_alpha[:, :, None]),
        0,
        255,
    ).astype(np.uint8)

    visible = alpha > 24
    if np.any(visible):
        mean_rgb = [int(round(float(rgb[:, :, channel][visible].mean()))) for channel in range(3)]
    else:
        mean_rgb = [0, 0, 0]
    return {
        "silhouette": silhouette,
        "luminance": luminance,
        "appearance": appearance.tobytes().hex(),
        "mean_rgb": mean_rgb,
    }


def hamming_hex(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def appearance_mae(a: str, b: str) -> float:
    left = np.frombuffer(bytes.fromhex(a), dtype=np.uint8).astype(np.int16)
    right = np.frombuffer(bytes.fromhex(b), dtype=np.uint8).astype(np.int16)
    if left.size != right.size or left.size == 0:
        return 255.0
    return float(np.abs(left - right).mean())


def load_index(repo_root: Path) -> dict[str, object]:
    path = repo_root / "assets" / INDEX_PATH_NAME
    if not path.is_file():
        return {"schema_version": INDEX_SCHEMA_VERSION, "sources": {}, "assets": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SystemExit(f"Asset index is unreadable: {path}")
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict) or not isinstance(raw.get("assets"), dict):
        raise SystemExit(f"Asset index has an invalid structure: {path}")
    return raw


def annotate_duplicates(index: dict[str, object], records: list[dict[str, object]]) -> list[dict[str, object]]:
    indexed_assets = index.get("assets", {})
    assert isinstance(indexed_assets, dict)
    warnings: list[dict[str, object]] = []

    existing_by_sha: dict[str, str] = {}
    for name, raw in indexed_assets.items():
        if isinstance(raw, dict) and isinstance(raw.get("sha256"), str):
            existing_by_sha[str(raw["sha256"])] = str(name)

    current_sha: dict[str, str] = {}
    for record in records:
        filename = str(record["file"])
        sha = str(record["sha256"])
        duplicate = existing_by_sha.get(sha) or current_sha.get(sha)
        if duplicate:
            record["duplicate_kind"] = "exact"
            record["duplicate_of"] = duplicate
            warnings.append({"file": filename, "kind": "exact", "of": duplicate})
            continue
        current_sha[sha] = filename

        role = str(record["role"])
        sig = record.get("signature", {})
        if not isinstance(sig, dict):
            continue
        best: tuple[str, int, int, float] | None = None
        for name, raw in indexed_assets.items():
            if not isinstance(raw, dict) or raw.get("role") != role:
                continue
            try:
                sil_d = hamming_hex(str(sig["silhouette"]), str(raw["silhouette"]))
                lum_d = hamming_hex(str(sig["luminance"]), str(raw["luminance"]))
                app_d = appearance_mae(str(sig["appearance"]), str(raw["appearance"]))
            except (KeyError, TypeError, ValueError):
                continue
            if sil_d / 1024.0 <= SIL_MAX_DIFF_RATIO and lum_d <= LUMA_MAX_DIFF and app_d <= APPEARANCE_MAX_MAE:
                candidate = (str(name), sil_d, lum_d, app_d)
                if best is None or (sil_d, lum_d, app_d) < (best[1], best[2], best[3]):
                    best = candidate
        if best:
            name, sil_d, lum_d, app_d = best
            record["duplicate_kind"] = "near"
            record["duplicate_of"] = name
            record["duplicate_metrics"] = {
                "silhouette_bits": sil_d,
                "luminance_bits": lum_d,
                "appearance_mae": round(app_d, 3),
            }
            warnings.append(
                {
                    "file": filename,
                    "kind": "near",
                    "of": name,
                    "silhouette_bits": sil_d,
                    "luminance_bits": lum_d,
                    "appearance_mae": round(app_d, 3),
                }
            )
    return warnings


def closest_distances(index: dict[str, object], records: list[dict[str, object]]) -> list[str]:
    indexed_assets = index.get("assets", {})
    assert isinstance(indexed_assets, dict)
    lines: list[str] = []
    for record in records:
        role = str(record["role"])
        sig = record.get("signature", {})
        if not isinstance(sig, dict):
            continue
        best: tuple[str, int, int, float] | None = None
        for name, raw in indexed_assets.items():
            if not isinstance(raw, dict) or raw.get("role") != role:
                continue
            try:
                item = (
                    str(name),
                    hamming_hex(str(sig["silhouette"]), str(raw["silhouette"])),
                    hamming_hex(str(sig["luminance"]), str(raw["luminance"])),
                    appearance_mae(str(sig["appearance"]), str(raw["appearance"])),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if best is None or (item[1], item[2], item[3]) < (best[1], best[2], best[3]):
                best = item
        if best:
            lines.append(
                f"{record['file']}: closest {best[0]} | silhouette {best[1]}/1024, "
                f"luminance {best[2]}/64, appearance MAE {best[3]:.2f}"
            )
    return lines


def split_sheet(
    source: Path,
    output_dir: Path,
    set_number: int,
    manual_seeds: dict[str, list[tuple[int, int]]],
    *,
    bg_threshold: int,
    margin_fraction: float,
    peaks_per_cell: int,
    cell_inset: float,
    min_component_area: int,
    edge_low: int,
    edge_high: int,
    centroid_tolerance: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    image = Image.open(source).convert("RGBA")
    rgba = np.array(image)
    rgb = rgba[:, :, :3]
    height, width = rgb.shape[:2]
    validate_sheet(rgb, bg_threshold)

    foreground = np.max(rgb, axis=2) > bg_threshold
    row_split = find_row_split(foreground)
    distance = distance_transform_edt(foreground)
    markers = build_markers(
        distance,
        manual_seeds,
        row_split=row_split,
        peaks_per_cell=peaks_per_cell,
        cell_inset=cell_inset,
    )
    labels = watershed(-distance, markers=markers, mask=foreground)
    labels, unseeded_diag = assign_unseeded_components(
        labels,
        foreground,
        min_component_area=min_component_area,
        row_split=row_split,
    )
    labels, tiny_diag = remove_tiny_role_fragments(labels, min_component_area)
    centroid_report = validate_role_centroids(labels, tolerance=centroid_tolerance, row_split=row_split)
    overlap_report = row_overlap_diagnostics(labels, row_split)

    diagnostics: dict[str, object] = {
        **unseeded_diag,
        **tiny_diag,
        "row_split": int(row_split),
        "centroids": centroid_report,
        "row_overlap": overlap_report,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    for role_index, role in enumerate(ROLES, start=1):
        mask = labels == role_index
        ys, xs = np.where(mask)
        foreground_pixels = len(xs)
        if foreground_pixels < 1_000:
            raise SystemExit(
                f"Automatic split failed quality gate for {role}: only {foreground_pixels} foreground pixels."
            )

        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        margin_x = max(8, round((x1 - x0) * margin_fraction))
        margin_y = max(8, round((y1 - y0) * margin_fraction))
        x0, x1 = max(0, x0 - margin_x), min(width, x1 + margin_x)
        y0, y1 = max(0, y0 - margin_y), min(height, y1 + margin_y)

        crop_rgb = rgba[y0:y1, x0:x1, :3].copy()
        crop_mask = mask[y0:y1, x0:x1]
        straight_rgb, soft_alpha, core = refine_alpha(
            crop_rgb,
            crop_mask,
            edge_low=edge_low,
            edge_high=edge_high,
        )
        straight_rgb = bleed_transparent_rgb(straight_rgb, soft_alpha, core)
        crop = np.dstack([straight_rgb, soft_alpha]).astype(np.uint8)

        edge = (soft_alpha > 8) & (soft_alpha < 248)
        edge_pixels = int(np.count_nonzero(edge))
        edge_before = float(crop_rgb[edge].mean()) if edge_pixels else 0.0
        edge_after = float(straight_rgb[edge].mean()) if edge_pixels else 0.0

        filename = f"{role}_{set_number:02d}.png"
        output_path = output_dir / filename
        Image.fromarray(crop, "RGBA").save(output_path, "PNG", optimize=True)
        records.append(
            {
                "role": role,
                "file": filename,
                "path": str(output_path),
                "width": int(crop.shape[1]),
                "height": int(crop.shape[0]),
                "foreground_pixels": int(foreground_pixels),
                "soft_edge_pixels": edge_pixels,
                "edge_mean_before": round(edge_before, 3),
                "edge_mean_after": round(edge_after, 3),
                "sha256": sha256_file(output_path),
                "signature": signatures(straight_rgb, soft_alpha),
            }
        )

    return records, diagnostics


def create_contact_sheet(records: list[dict[str, object]], output_path: Path) -> None:
    sheet = Image.new(
        "RGBA",
        (CONTACT_TILE_WIDTH * 5, CONTACT_TILE_HEIGHT * 2),
        (255, 255, 255, 255),
    )
    checker = 20

    for index, record in enumerate(records):
        image = Image.open(str(record["path"])).convert("RGBA")
        tile = Image.new("RGBA", (CONTACT_TILE_WIDTH, CONTACT_TILE_HEIGHT), (245, 245, 245, 255))
        draw = ImageDraw.Draw(tile)
        for y in range(0, CONTACT_IMAGE_HEIGHT, checker):
            for x in range(0, CONTACT_TILE_WIDTH, checker):
                if (x // checker + y // checker) % 2:
                    draw.rectangle((x, y, x + checker - 1, y + checker - 1), fill=(220, 220, 220, 255))
        thumb = image.copy()
        thumb.thumbnail((280, CONTACT_IMAGE_HEIGHT - 15), Image.Resampling.LANCZOS)
        tile.alpha_composite(
            thumb,
            ((CONTACT_TILE_WIDTH - thumb.width) // 2, (CONTACT_IMAGE_HEIGHT - thumb.height) // 2),
        )
        draw.text((8, CONTACT_LABEL_Y), str(record["file"]), fill=(0, 0, 0, 255))
        duplicate_of = record.get("duplicate_of")
        if duplicate_of:
            draw.rectangle(
                (1, 1, CONTACT_TILE_WIDTH - 2, CONTACT_TILE_HEIGHT - 2),
                outline=(220, 40, 40, 255),
                width=4,
            )
            draw.text(
                (8, CONTACT_NOTE_Y),
                f"{record.get('duplicate_kind', 'dup')} ~ {Path(str(duplicate_of)).name}",
                fill=(190, 0, 0, 255),
            )
        sheet.alpha_composite(tile, ((index % 5) * CONTACT_TILE_WIDTH, (index // 5) * CONTACT_TILE_HEIGHT))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "PNG", optimize=True)


def write_manifest(
    source: Path,
    set_number: int,
    records: list[dict[str, object]],
    contact_path: Path,
    output_path: Path,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
) -> None:
    manifest = {
        "algorithm": ALGORITHM_VERSION,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "set": f"{set_number:02d}",
        "roles": list(ROLES),
        "contact_sheet": str(contact_path),
        "parameters": parameters,
        "diagnostics": diagnostics,
        "files": records,
        "approval_required_before_install": True,
    }
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _index_path(repo_root: Path) -> Path:
    return repo_root / "assets" / INDEX_PATH_NAME


def save_index(repo_root: Path, index: dict[str, object]) -> Path:
    path = _index_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def update_index_after_install(
    repo_root: Path,
    index: dict[str, object],
    source: Path,
    set_number: int,
    records: list[dict[str, object]],
    targets: list[Path],
) -> Path:
    sources = index.setdefault("sources", {})
    assets = index.setdefault("assets", {})
    if not isinstance(sources, dict) or not isinstance(assets, dict):
        raise SystemExit("Asset index structure changed during import")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_hash = sha256_file(source)
    sources[source_hash] = {
        "set": f"{set_number:02d}",
        "source_name": source.name,
        "imported_at": now,
    }
    for record, target in zip(records, targets, strict=True):
        relative = target.relative_to(repo_root).as_posix()
        assets[relative] = {
            "role": str(record["role"]),
            "set": f"{set_number:02d}",
            "sha256": str(record["sha256"]),
            **dict(record["signature"]),
        }
    index["schema_version"] = INDEX_SCHEMA_VERSION
    index["updated_at"] = now
    return save_index(repo_root, index)


def install_assets(
    repo_root: Path,
    records: list[dict[str, object]],
    *,
    approved: bool,
) -> list[Path]:
    if not approved:
        raise SystemExit("Refusing to install without --approved. Inspect the contact sheet first.")

    targets: list[Path] = []
    for record in records:
        role = str(record["role"])
        target = repo_root / "assets" / role / str(record["file"])
        if target.exists():
            raise SystemExit(f"Refusing to overwrite existing variant: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        targets.append(target)

    created: list[Path] = []
    try:
        for record, target in zip(records, targets, strict=True):
            shutil.copy2(Path(str(record["path"])), target)
            created.append(target)
            if sha256_file(target) != str(record["sha256"]):
                raise SystemExit(f"SHA-256 mismatch after install: {target}")
    except BaseException:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    return targets


def git_commit_exact(repo_root: Path, targets: list[Path], index_path: Path, set_number: int) -> str:
    """Commit one normal import: exactly ten PNGs plus the synchronized index."""
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
        return proc.stdout.strip()

    existing_staged = [line for line in run("diff", "--cached", "--name-only").splitlines() if line]
    if existing_staged:
        raise SystemExit(
            "Refusing --commit because unrelated staged changes already exist:\n- " + "\n- ".join(existing_staged)
        )

    relative_targets = [str(path.relative_to(repo_root)).replace("\\", "/") for path in targets]
    relative_index = str(index_path.relative_to(repo_root)).replace("\\", "/")
    expected = relative_targets + [relative_index]
    run("add", "--", *expected)
    staged = [line for line in run("diff", "--cached", "--name-only").splitlines() if line]
    if sorted(staged) != sorted(expected):
        raise SystemExit(
            "Git safety gate failed: staged file set is not exactly 10 PNGs plus asset_index.json.\n"
            f"Expected: {expected}\nActual: {staged}"
        )
    pngs = [name for name in staged if name.lower().endswith(".png")]
    if len(pngs) != 10 or len(staged) != 11 or relative_index not in staged:
        raise SystemExit(
            f"Git safety gate failed: expected 10 PNGs + 1 index, found {len(pngs)} PNGs / {len(staged)} files"
        )

    run("commit", "-m", f"Add character asset variant set {set_number:02d}")
    return run("rev-parse", "HEAD")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def prepare_preview_dir(repo_root: Path, preview_dir: Path) -> None:
    preview_dir = preview_dir.resolve()
    safe_root = (repo_root / ".asset_import_preview").resolve()
    dangerous = {repo_root.resolve(), Path.home().resolve()}
    if preview_dir.anchor:
        dangerous.add(Path(preview_dir.anchor).resolve())
    if preview_dir in dangerous:
        raise SystemExit(f"Refusing dangerous preview directory: {preview_dir}")
    if preview_dir.exists():
        safe_managed = _is_within(preview_dir, safe_root) or (preview_dir / PREVIEW_SENTINEL).is_file()
        if not safe_managed:
            raise SystemExit(
                f"Refusing to delete existing --preview-dir without importer sentinel: {preview_dir}. "
                "Use a new/empty path or a prior importer-created preview directory."
            )
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / PREVIEW_SENTINEL).write_text(ALGORITHM_VERSION + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automatically split a standard 5x2 Kyunghee asset sheet into 10 transparent PNG variants."
    )
    parser.add_argument("source", type=Path, help="Source 5x2 PNG/JPG sheet with black or near-black background")
    parser.add_argument("--set", dest="set_number", default="auto", help="Variant number 01-99; default: auto")
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=None,
        help="Preview directory; default: <repo>/.asset_import_preview/set_NN",
    )
    parser.add_argument(
        "--seed",
        action="append",
        default=[],
        help="Optional corrective seed ROLE:X,Y (X first, then Y); repeatable",
    )
    parser.add_argument("--install", action="store_true", help="Copy reviewed outputs into assets/<role>/")
    parser.add_argument("--approved", action="store_true", help="Confirm that the generated contact sheet was visually reviewed")
    parser.add_argument("--commit", action="store_true", help="After install, commit exactly 10 PNGs plus asset_index.json")
    parser.add_argument("--allow-duplicate-source", action="store_true", help="Allow re-importing a source file with an indexed SHA-256")
    parser.add_argument("--allow-duplicate", action="store_true", help="Allow exact output duplicates after manual review")
    parser.add_argument("--allow-near-duplicate", action="store_true", help="Allow near-identical appearance/pose duplicates after manual review")
    parser.add_argument("--report-distances", action="store_true", help="Print closest indexed same-role signature distances")
    parser.add_argument("--bg-threshold", type=int, default=DEFAULT_BG_THRESHOLD)
    parser.add_argument("--edge-low", type=int, default=DEFAULT_EDGE_LOW)
    parser.add_argument("--edge-high", type=int, default=DEFAULT_EDGE_HIGH)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_FRACTION)
    parser.add_argument("--peaks-per-cell", type=int, default=DEFAULT_PEAKS_PER_CELL)
    parser.add_argument("--cell-inset", type=float, default=DEFAULT_CELL_INSET)
    parser.add_argument("--min-component-area", type=int, default=DEFAULT_MIN_COMPONENT_AREA)
    parser.add_argument("--centroid-tolerance", type=float, default=DEFAULT_CENTROID_TOLERANCE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = repo_root_from_script()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Source file not found: {source}")
    if args.commit and not args.install:
        raise SystemExit("--commit requires --install")
    if args.install and not args.approved:
        raise SystemExit("--install requires --approved after contact-sheet review")
    if not (0 <= args.bg_threshold <= 32):
        raise SystemExit("--bg-threshold must be between 0 and 32")
    if not (0 <= args.edge_low < args.edge_high <= 96):
        raise SystemExit("Require 0 <= --edge-low < --edge-high <= 96")
    if not (0.01 <= args.margin <= 0.20):
        raise SystemExit("--margin must be between 0.01 and 0.20")
    if not (1 <= args.peaks_per_cell <= 8):
        raise SystemExit("--peaks-per-cell must be between 1 and 8")
    if not (0.0 <= args.cell_inset < 0.25):
        raise SystemExit("--cell-inset must be between 0.0 and 0.25")
    if args.min_component_area < 1:
        raise SystemExit("--min-component-area must be positive")
    if not (0.5 <= args.centroid_tolerance <= 1.5):
        raise SystemExit("--centroid-tolerance must be between 0.5 and 1.5 cells")

    index = load_index(repo_root)
    source_hash = sha256_file(source)
    sources = index.get("sources", {})
    if isinstance(sources, dict) and source_hash in sources and not args.allow_duplicate_source:
        previous = sources[source_hash]
        raise SystemExit(
            f"This source sheet is already indexed: {previous}. "
            "If intentional, rerun with --allow-duplicate-source after review."
        )

    set_number = parse_set_number(args.set_number, repo_root)
    preview_dir = (
        args.preview_dir.expanduser().resolve()
        if args.preview_dir
        else repo_root / ".asset_import_preview" / f"set_{set_number:02d}"
    )
    prepare_preview_dir(repo_root, preview_dir)

    manual_seeds = parse_manual_seeds(args.seed)
    parameters = {
        "bg_threshold": args.bg_threshold,
        "edge_low": args.edge_low,
        "edge_high": args.edge_high,
        "margin": args.margin,
        "peaks_per_cell": args.peaks_per_cell,
        "cell_inset": args.cell_inset,
        "min_component_area": args.min_component_area,
        "centroid_tolerance": args.centroid_tolerance,
        "manual_seeds": {role: manual_seeds[role] for role in ROLES if manual_seeds[role]},
    }
    records, diagnostics = split_sheet(
        source,
        preview_dir,
        set_number,
        manual_seeds,
        bg_threshold=args.bg_threshold,
        margin_fraction=args.margin,
        peaks_per_cell=args.peaks_per_cell,
        cell_inset=args.cell_inset,
        min_component_area=args.min_component_area,
        edge_low=args.edge_low,
        edge_high=args.edge_high,
        centroid_tolerance=args.centroid_tolerance,
    )

    duplicate_warnings = annotate_duplicates(index, records)
    diagnostics["duplicate_warnings"] = duplicate_warnings
    contact_path = preview_dir / f"contact_set_{set_number:02d}.png"
    create_contact_sheet(records, contact_path)
    manifest_path = preview_dir / f"manifest_set_{set_number:02d}.json"
    write_manifest(source, set_number, records, contact_path, manifest_path, parameters, diagnostics)

    print(f"Prepared set {set_number:02d}: 10 PNGs")
    print(f"Contact sheet: {contact_path}")
    print(f"Manifest: {manifest_path}")
    print("Review gate: do not install if any body part/prop is missing or assigned to a neighboring role.")
    skipped = int(diagnostics.get("unseeded_small_components_skipped", 0))
    removed = int(diagnostics.get("tiny_role_fragments_removed", 0))
    if skipped or removed:
        print(
            "Small-part diagnostic: "
            f"{skipped} unseeded components skipped / {removed} labeled fragments removed. "
            "Inspect props and sparkles in the contact sheet."
        )
    overlap_report = diagnostics.get("row_overlap", {})
    if isinstance(overlap_report, dict):
        suspicious = [role for role, raw in overlap_report.items() if isinstance(raw, dict) and raw.get("review_recommended")]
        if suspicious:
            print(
                "Row-overlap diagnostic: review these tiles carefully for neighboring feet/heads/props: "
                + ", ".join(suspicious)
            )
    edge_pixels = sum(int(rec.get("soft_edge_pixels", 0)) for rec in records)
    if edge_pixels:
        before = sum(float(rec["edge_mean_before"]) * int(rec["soft_edge_pixels"]) for rec in records) / edge_pixels
        after = sum(float(rec["edge_mean_after"]) * int(rec["soft_edge_pixels"]) for rec in records) / edge_pixels
        print(f"Edge brightness diagnostic: {before:.1f} -> {after:.1f} after unpremultiply (higher means less black matte).")

    if args.report_distances:
        for line in closest_distances(index, records):
            print("  " + line)

    exact = [item for item in duplicate_warnings if item.get("kind") == "exact"]
    near = [item for item in duplicate_warnings if item.get("kind") == "near"]
    if duplicate_warnings:
        print("Duplicate review:")
        for item in duplicate_warnings:
            if item.get("kind") == "near":
                print(
                    f"  {item['file']} ~ {item['of']} "
                    f"(sil {item['silhouette_bits']}/1024, lum {item['luminance_bits']}/64, "
                    f"appearance MAE {item['appearance_mae']})"
                )
            else:
                print(f"  {item['file']} == {item['of']} (exact bytes)")
        if exact and not args.allow_duplicate:
            raise SystemExit(
                "Exact duplicate output detected. Contact sheet was generated; review it and use --allow-duplicate only if intentional."
            )
        if near and not args.allow_near_duplicate:
            raise SystemExit(
                "Near-identical same-role output detected. Different clothing/color is excluded by the appearance gate; "
                "review the contact sheet and use --allow-near-duplicate only if intentional."
            )

    if not args.install:
        print(
            "After visual approval, rerun with: "
            f'python tools/import_asset_sheet.py "{source}" --set {set_number:02d} --install --approved'
        )
        return 0

    targets = install_assets(repo_root, records, approved=args.approved)
    index_path = update_index_after_install(repo_root, index, source, set_number, records, targets)
    print("Installed exactly 10 assets and updated the asset index:")
    for target in targets:
        print(f"  {target.relative_to(repo_root)}")
    print(f"  {index_path.relative_to(repo_root)}")

    if args.commit:
        commit_sha = git_commit_exact(repo_root, targets, index_path, set_number)
        print(f"Created commit: {commit_sha}")
    else:
        print("No git commit created. Review `git diff --stat` before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
