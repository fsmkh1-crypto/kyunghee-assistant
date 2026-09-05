#!/usr/bin/env python3
"""Compare true per-pixel alpha with the compact app's current color-key cut.

Developer diagnostic only. It never modifies source PNGs or runtime settings.
The goal is to decide whether visible jaggedness is primarily in the PNG edge
itself or introduced when the compact Tk window converts soft alpha to binary.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asset_display_lab as lab
from image_render import DEFAULT_ALPHA_THRESHOLD


def _composite_on_checker(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    tile = lab.checkerboard(size, cell=14)
    preview = lab._fit_for_tile(image, (size[0] - 14, size[1] - 14))
    tile.alpha_composite(preview, ((size[0] - preview.width) // 2, (size[1] - preview.height) // 2))
    return tile


def _soft_edge_metrics(rendered: Image.Image) -> dict[str, float | int]:
    rgba = np.asarray(rendered.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    visible = alpha > 0
    soft = (alpha > 0) & (alpha < 255)
    binary = alpha >= DEFAULT_ALPHA_THRESHOLD

    visible_count = int(np.count_nonzero(visible))
    soft_count = int(np.count_nonzero(soft))
    soft_ratio = float(soft_count / max(1, visible_count))
    alpha_mae = float(np.mean(np.abs(alpha.astype(np.float32) / 255.0 - binary.astype(np.float32))))

    if soft_count:
        src = rgba[:, :, :3].astype(np.float32)
        a = (alpha.astype(np.float32) / 255.0)[:, :, None]
        ab = binary.astype(np.float32)[:, :, None]
        errors = []
        for background in (32.0, 224.0):
            true_rgb = src * a + background * (1.0 - a)
            binary_rgb = src * ab + background * (1.0 - ab)
            errors.append(float(np.mean(np.abs(true_rgb[soft] - binary_rgb[soft]))))
        edge_rgb_mae = float(sum(errors) / len(errors))
    else:
        edge_rgb_mae = 0.0

    return {
        "visible_pixels": visible_count,
        "soft_edge_pixels": soft_count,
        "soft_edge_ratio": soft_ratio,
        "alpha_binary_mae": alpha_mae,
        "soft_edge_rgb_mae": edge_rgb_mae,
    }


def diagnose(assets_dir: Path, output_dir: Path, *, scale: int = 100, top_n: int = 12) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = lab.discover_assets(assets_dir)
    baseline = lab.Variant(DEFAULT_ALPHA_THRESHOLD, 0.0)

    ranked: list[tuple[float, str, Path, Image.Image, dict[str, float | int]]] = []
    all_metrics: list[dict[str, object]] = []
    for set_number, role, path in assets:
        name = f"{role}_{set_number:02d}"
        rendered = lab.rendered_rgba(path, scale)
        mask = lab.colorkey_mask(rendered, baseline)
        roughness = lab._roughness_score(lab.measure_mask(mask))
        metrics = _soft_edge_metrics(rendered)
        row = {"asset": name, "roughness_score": roughness, **metrics}
        all_metrics.append(row)
        ranked.append((roughness, name, path, rendered, metrics))

    ranked.sort(reverse=True, key=lambda item: item[0])
    selected = ranked[: min(top_n, len(ranked))]

    tile_w, tile_h = 360, 420
    sheet = Image.new("RGB", (tile_w * 2, tile_h * len(selected)), (34, 34, 34))
    draw = ImageDraw.Draw(sheet)
    for row_index, (_roughness, name, _path, rendered, metrics) in enumerate(selected):
        current_mask = lab.colorkey_mask(rendered, baseline)
        binary = lab.apply_mask(rendered, current_mask)
        for col, (label, image) in enumerate((("true alpha", rendered), ("current color-key", binary))):
            tile = _composite_on_checker(image, (tile_w, tile_h - 42))
            x, y = col * tile_w, row_index * tile_h
            sheet.paste(tile.convert("RGB"), (x, y))
            draw.text((x + 6, y + tile_h - 36), f"{name} · {label}", fill="white")
            draw.text(
                (x + 6, y + tile_h - 20),
                f"soft {float(metrics['soft_edge_ratio']):.2%} · edge MAE {float(metrics['soft_edge_rgb_mae']):.1f}",
                fill=(210, 210, 210),
            )
    comparison_path = output_dir / "alpha_vs_colorkey.png"
    sheet.save(comparison_path, optimize=True)

    mean_soft = float(np.mean([float(row["soft_edge_ratio"]) for row in all_metrics]))
    mean_edge_mae = float(np.mean([float(row["soft_edge_rgb_mae"]) for row in all_metrics]))
    selected_names = [name for _score, name, _path, _rendered, _metrics in selected]
    report = {
        "asset_count": len(all_metrics),
        "scale": scale,
        "threshold": DEFAULT_ALPHA_THRESHOLD,
        "mean_soft_edge_ratio": mean_soft,
        "mean_soft_edge_rgb_mae": mean_edge_mae,
        "review_priority": selected_names,
        "assets": all_metrics,
        "interpretation": {
            "soft_edge_ratio": "How much antialiased/translucent edge data exists in the resized PNG before the color-key cut.",
            "soft_edge_rgb_mae": "Average visible RGB error on soft-edge pixels when true alpha is replaced by the current binary cut, averaged over dark/light backgrounds.",
            "rule": "If true-alpha previews are visibly smoother and these values are material, renderer/color-key conversion is the primary bottleneck; if both sides are rough, source PNG cleanup remains necessary.",
        },
    }
    (output_dir / "alpha_diagnosis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("asset_count", "scale", "threshold", "mean_soft_edge_ratio", "mean_soft_edge_rgb_mae", "review_priority")}, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    diagnose(REPO_ROOT / "assets", REPO_ROOT / ".asset_display_lab")
