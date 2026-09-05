#!/usr/bin/env python3
"""Developer-only visual/metric lab for built-in Kyunghee PNG assets.

The lab intentionally does not modify assets or runtime settings. It reproduces
compact-runtime resizing and colour-key alpha thresholding, then compares small
parameter variations so edge tuning can be decided before touching source PNGs.

Typical use:
  python tools/asset_display_lab.py
  python tools/asset_display_lab.py --assets-dir path/to/assets --output-dir out

Requires the asset-import developer dependencies (numpy/scipy/Pillow).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import label as ndi_label

# Make repository modules importable when the script is launched from tools/.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from image_render import DEFAULT_ALPHA_THRESHOLD, resize_rgba_alpha_safe, threshold_alpha  # noqa: E402

ROLES = (
    "default", "cheer", "rest", "away", "warning",
    "leave", "stats", "settings", "alert", "profile",
)
DEFAULT_SCALES = (80, 100, 140, 200)
DEFAULT_THRESHOLDS = (96, 112, 128)
DEFAULT_SMOOTH_RADII = (0.0, 0.35)
CHARACTER_MAX = (346, 384)


@dataclass(frozen=True)
class Variant:
    threshold: int
    smooth_radius: float

    @property
    def key(self) -> str:
        return f"t{self.threshold}_s{self.smooth_radius:g}"


@dataclass
class MaskMetrics:
    area: int
    transitions: int
    corners: int
    small_components: int
    large_components: int


@dataclass
class Comparison:
    asset: str
    scale: int
    threshold: int
    smooth_radius: float
    symmetric_diff_ratio: float
    area_change_ratio: float
    transitions_change_ratio: float
    corners_change_ratio: float
    topology_changed: bool


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("list must not be empty")
    return values


def _parse_float_list(raw: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("list must not be empty")
    if any(value < 0 for value in values):
        raise argparse.ArgumentTypeError("smooth radii must be non-negative")
    return values


def discover_assets(assets_dir: Path) -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for set_number in range(1, 100):
        set_paths: list[tuple[int, str, Path]] = []
        for role in ROLES:
            path = assets_dir / role / f"{role}_{set_number:02d}.png"
            if path.is_file():
                set_paths.append((set_number, role, path))
        if not set_paths:
            continue
        if len(set_paths) != len(ROLES):
            missing = [role for role in ROLES if not (assets_dir / role / f"{role}_{set_number:02d}.png").is_file()]
            raise SystemExit(f"Set {set_number:02d} is incomplete; missing: {', '.join(missing)}")
        found.extend(set_paths)
    if not found:
        raise SystemExit(f"No numbered built-in PNG assets found under {assets_dir}")
    return found


def rendered_rgba(path: Path, scale: int) -> Image.Image:
    target = (
        max(1, round(CHARACTER_MAX[0] * scale / 100)),
        max(1, round(CHARACTER_MAX[1] * scale / 100)),
    )
    with Image.open(path) as source:
        return resize_rgba_alpha_safe(source, target)


def colorkey_mask(image: Image.Image, variant: Variant) -> np.ndarray:
    # Use runtime helper for the baseline path. The optional smoothing path is
    # equivalent except that only alpha is gently regularized before threshold.
    if variant.smooth_radius == 0:
        binary = threshold_alpha(image, variant.threshold)
        return np.asarray(binary.getchannel("A"), dtype=np.uint8) == 255
    alpha = image.getchannel("A").filter(ImageFilter.GaussianBlur(radius=variant.smooth_radius))
    arr = np.asarray(alpha, dtype=np.uint8)
    return arr >= variant.threshold


def apply_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    result = image.convert("RGBA").copy()
    result.putalpha(Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L"))
    return result


def measure_mask(mask: np.ndarray) -> MaskMetrics:
    area = int(np.count_nonzero(mask))
    if area == 0:
        return MaskMetrics(0, 0, 0, 0, 0)
    horizontal = int(np.count_nonzero(mask[:, 1:] != mask[:, :-1]))
    vertical = int(np.count_nonzero(mask[1:, :] != mask[:-1, :]))
    transitions = horizontal + vertical
    block_sum = (
        mask[:-1, :-1].astype(np.uint8)
        + mask[1:, :-1].astype(np.uint8)
        + mask[:-1, 1:].astype(np.uint8)
        + mask[1:, 1:].astype(np.uint8)
    )
    corners = int(np.count_nonzero((block_sum == 1) | (block_sum == 3)))
    labels, count = ndi_label(mask, np.ones((3, 3), dtype=np.uint8))
    if count:
        sizes = np.bincount(labels.ravel())[1:]
        small = int(np.count_nonzero(sizes < 8))
        large = int(np.count_nonzero(sizes >= 20))
    else:
        small = large = 0
    return MaskMetrics(area, transitions, corners, small, large)


def compare_mask(base: np.ndarray, candidate: np.ndarray, base_m: MaskMetrics, cand_m: MaskMetrics) -> tuple[float, float, float, float, bool]:
    denom_area = max(1, base_m.area)
    sym = float(np.count_nonzero(base != candidate) / denom_area)
    area_delta = float((cand_m.area - base_m.area) / denom_area)
    transitions_delta = float((cand_m.transitions - base_m.transitions) / max(1, base_m.transitions))
    corners_delta = float((cand_m.corners - base_m.corners) / max(1, base_m.corners))
    topology_changed = cand_m.large_components != base_m.large_components
    return sym, area_delta, transitions_delta, corners_delta, topology_changed


def checkerboard(size: tuple[int, int], cell: int = 12) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (72, 72, 72, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(width - 1, x + cell - 1), min(height - 1, y + cell - 1)), fill=(112, 112, 112, 255))
    return image


def _fit_for_tile(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(max_size, Image.Resampling.LANCZOS)
    return copy


def build_overview(
    assets: list[tuple[int, str, Path]],
    output: Path,
    *,
    scale: int,
    variant: Variant,
) -> None:
    tile_w, tile_h = 220, 270
    set_numbers = sorted({set_number for set_number, _role, _path in assets})
    sheet = Image.new("RGB", (tile_w * len(ROLES), tile_h * len(set_numbers)), (38, 38, 38))
    draw = ImageDraw.Draw(sheet)
    by_key = {(set_number, role): path for set_number, role, path in assets}
    for row, set_number in enumerate(set_numbers):
        for col, role in enumerate(ROLES):
            rendered = rendered_rgba(by_key[(set_number, role)], scale)
            mask = colorkey_mask(rendered, variant)
            rendered = apply_mask(rendered, mask)
            tile = checkerboard((tile_w, tile_h - 22))
            preview = _fit_for_tile(rendered, (tile_w - 12, tile_h - 34))
            tile.alpha_composite(preview, ((tile_w - preview.width) // 2, max(2, (tile_h - 22 - preview.height) // 2)))
            x, y = col * tile_w, row * tile_h
            sheet.paste(tile.convert("RGB"), (x, y))
            draw.text((x + 5, y + tile_h - 18), f"{role}_{set_number:02d}", fill="white")
    sheet.save(output, optimize=True)


def _roughness_score(metric: MaskMetrics) -> float:
    if metric.area <= 0:
        return 0.0
    scale = math.sqrt(metric.area)
    return (metric.transitions + 0.75 * metric.corners) / max(1.0, scale) + metric.small_components * 0.25


def build_priority_comparison(
    assets: list[tuple[int, str, Path]],
    output: Path,
    *,
    scale: int,
    baseline: Variant,
    candidate: Variant,
    top_n: int,
) -> list[str]:
    rows: list[tuple[float, str, Path]] = []
    for set_number, role, path in assets:
        rendered = rendered_rgba(path, scale)
        base_mask = colorkey_mask(rendered, baseline)
        metric = measure_mask(base_mask)
        rows.append((_roughness_score(metric), f"{role}_{set_number:02d}", path))
    rows.sort(reverse=True, key=lambda item: item[0])
    selected = rows[: min(top_n, len(rows))]

    tile_w, tile_h = 340, 410
    sheet = Image.new("RGB", (tile_w * 2, tile_h * len(selected)), (34, 34, 34))
    draw = ImageDraw.Draw(sheet)
    labels = (f"baseline {baseline.key}", f"candidate {candidate.key}")
    for row, (_score, name, path) in enumerate(selected):
        rendered = rendered_rgba(path, scale)
        for col, variant in enumerate((baseline, candidate)):
            mask = colorkey_mask(rendered, variant)
            visible = apply_mask(rendered, mask)
            tile = checkerboard((tile_w, tile_h - 30), cell=14)
            preview = _fit_for_tile(visible, (tile_w - 14, tile_h - 44))
            tile.alpha_composite(preview, ((tile_w - preview.width) // 2, max(2, (tile_h - 30 - preview.height) // 2)))
            x, y = col * tile_w, row * tile_h
            sheet.paste(tile.convert("RGB"), (x, y))
            draw.text((x + 6, y + tile_h - 24), f"{name} · {labels[col]}", fill="white")
    sheet.save(output, optimize=True)
    return [name for _score, name, _path in selected]


def run(args: argparse.Namespace) -> dict[str, object]:
    assets_dir = args.assets_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    assets = discover_assets(assets_dir)
    baseline = Variant(DEFAULT_ALPHA_THRESHOLD, 0.0)
    variants = [Variant(threshold, radius) for threshold in args.thresholds for radius in args.smooth_radii]
    if baseline not in variants:
        variants.append(baseline)

    comparisons: list[Comparison] = []
    aggregate: dict[str, dict[str, float | int]] = {}
    for variant in variants:
        aggregate[variant.key] = {
            "samples": 0,
            "mean_symmetric_diff_ratio": 0.0,
            "mean_area_change_ratio": 0.0,
            "mean_transitions_change_ratio": 0.0,
            "mean_corners_change_ratio": 0.0,
            "topology_change_count": 0,
        }

    for set_number, role, path in assets:
        asset_name = f"{role}_{set_number:02d}"
        for scale in args.scales:
            rendered = rendered_rgba(path, scale)
            base_mask = colorkey_mask(rendered, baseline)
            base_m = measure_mask(base_mask)
            for variant in variants:
                mask = colorkey_mask(rendered, variant)
                metric = measure_mask(mask)
                sym, area_delta, trans_delta, corner_delta, topo = compare_mask(base_mask, mask, base_m, metric)
                comparisons.append(Comparison(asset_name, scale, variant.threshold, variant.smooth_radius, sym, area_delta, trans_delta, corner_delta, topo))
                bucket = aggregate[variant.key]
                n = int(bucket["samples"])
                bucket["samples"] = n + 1
                for key, value in (
                    ("mean_symmetric_diff_ratio", sym),
                    ("mean_area_change_ratio", area_delta),
                    ("mean_transitions_change_ratio", trans_delta),
                    ("mean_corners_change_ratio", corner_delta),
                ):
                    old = float(bucket[key])
                    bucket[key] = old + (value - old) / (n + 1)
                if topo:
                    bucket["topology_change_count"] = int(bucket["topology_change_count"]) + 1

    csv_path = output_dir / "comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(comparisons[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(item) for item in comparisons)

    # Candidate recommendation: no topology changes first, then lowest mean edge
    # transitions, while keeping average silhouette pixel change very small.
    candidates = []
    for variant in variants:
        item = aggregate[variant.key]
        candidates.append((
            int(item["topology_change_count"]),
            abs(float(item["mean_area_change_ratio"])),
            float(item["mean_symmetric_diff_ratio"]),
            float(item["mean_transitions_change_ratio"]),
            variant,
        ))
    safe = [row for row in candidates if row[0] == 0 and row[2] <= args.max_mean_diff]
    if safe:
        # Prefer the largest edge-transition reduction among safe, minimally
        # different masks. The last tie-break prefers lower pixel change.
        safe.sort(key=lambda row: (row[3], row[2], row[1]))
        recommended = safe[0][4]
    else:
        recommended = baseline

    build_overview(assets, output_dir / "baseline_scale100.png", scale=100, variant=baseline)
    build_overview(assets, output_dir / "candidate_scale100.png", scale=100, variant=recommended)
    priorities = build_priority_comparison(
        assets,
        output_dir / "priority_comparison.png",
        scale=100,
        baseline=baseline,
        candidate=recommended,
        top_n=args.top,
    )

    report = {
        "assets_dir": str(assets_dir),
        "asset_count": len(assets),
        "scales": list(args.scales),
        "baseline": asdict(baseline),
        "recommended": asdict(recommended),
        "aggregate": aggregate,
        "review_priority": priorities,
        "notes": [
            "Metrics are review aids, not an automatic quality verdict.",
            "No source PNG is modified by this tool.",
            "Colour-key transparency remains binary; smoothing can regularize the silhouette but cannot provide true per-pixel alpha.",
        ],
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=REPO_ROOT / "assets")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / ".asset_display_lab")
    parser.add_argument("--scales", type=_parse_int_list, default=DEFAULT_SCALES)
    parser.add_argument("--thresholds", type=_parse_int_list, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--smooth-radii", type=_parse_float_list, default=DEFAULT_SMOOTH_RADII)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--max-mean-diff", type=float, default=0.0015, help="Maximum mean silhouette diff ratio for auto-recommendation")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
