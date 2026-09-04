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
    from scipy.ndimage import distance_transform_edt, label as ndi_label
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

ALGORITHM_VERSION = "kyunghee-5x2-watershed-v1"
DEFAULT_BG_THRESHOLD = 4
DEFAULT_MARGIN_FRACTION = 0.05
DEFAULT_PEAKS_PER_CELL = 3
DEFAULT_CELL_INSET = 0.05
DEFAULT_MIN_COMPONENT_AREA = 100


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
                f"Invalid --seed {raw!r}; expected ROLE:X,Y, e.g. away:985,424"
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


def build_markers(
    distance: np.ndarray,
    manual_seeds: dict[str, list[tuple[int, int]]],
    *,
    peaks_per_cell: int,
    cell_inset: float,
) -> np.ndarray:
    height, width = distance.shape
    markers = np.zeros((height, width), dtype=np.int32)

    for role_index, role in enumerate(ROLES, start=1):
        row = (role_index - 1) // 5
        col = (role_index - 1) % 5
        x0, x1 = int(col * width / 5), int((col + 1) * width / 5)
        y0, y1 = int(row * height / 2), int((row + 1) * height / 2)
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
        coords = sorted(coords, key=lambda yx: float(sub[tuple(yx)]), reverse=True)
        if not coords:
            y_rel, x_rel = np.unravel_index(np.argmax(sub), sub.shape)
            coords = [(int(y_rel), int(x_rel))]

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
) -> np.ndarray:
    """Attach detached props by nominal 5x2 cell instead of nearest pose seed."""
    height, width = foreground.shape
    components, count = ndi_label(foreground & (labels == 0), np.ones((3, 3), dtype=int))
    result = labels.copy()
    for component_id in range(1, count + 1):
        ys, xs = np.where(components == component_id)
        area = len(xs)
        if area < min_component_area:
            continue
        center_x = float(xs.mean())
        center_y = float(ys.mean())
        row = min(1, int(center_y / (height / 2)))
        col = min(4, int(center_x / (width / 5)))
        role_index = row * 5 + col + 1
        result[components == component_id] = role_index
    return result


def remove_tiny_role_fragments(labels: np.ndarray, min_component_area: int) -> np.ndarray:
    result = labels.copy()
    structure = np.ones((3, 3), dtype=int)
    for role_index in range(1, len(ROLES) + 1):
        components, count = ndi_label(labels == role_index, structure)
        for component_id in range(1, count + 1):
            component = components == component_id
            if int(np.count_nonzero(component)) < min_component_area:
                result[component] = 0
    return result


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
) -> list[dict[str, object]]:
    image = Image.open(source).convert("RGBA")
    rgba = np.array(image)
    rgb = rgba[:, :, :3]
    height, width = rgb.shape[:2]
    validate_sheet(rgb, bg_threshold)

    foreground = np.max(rgb, axis=2) > bg_threshold
    distance = distance_transform_edt(foreground)
    markers = build_markers(
        distance,
        manual_seeds,
        peaks_per_cell=peaks_per_cell,
        cell_inset=cell_inset,
    )
    labels = watershed(-distance, markers=markers, mask=foreground)
    labels = assign_unseeded_components(
        labels,
        foreground,
        min_component_area=min_component_area,
    )
    labels = remove_tiny_role_fragments(labels, min_component_area)

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

        crop = rgba[y0:y1, x0:x1].copy()
        crop_mask = mask[y0:y1, x0:x1]
        crop[:, :, 3] = np.where(crop_mask, rgba[y0:y1, x0:x1, 3], 0).astype(np.uint8)
        crop[crop[:, :, 3] == 0, :3] = 0

        filename = f"{role}_{set_number:02d}.png"
        output_path = output_dir / filename
        Image.fromarray(crop).save(output_path, "PNG", optimize=True)
        records.append(
            {
                "role": role,
                "file": filename,
                "path": str(output_path),
                "width": int(crop.shape[1]),
                "height": int(crop.shape[0]),
                "foreground_pixels": int(foreground_pixels),
                "sha256": sha256_file(output_path),
            }
        )

    return records


def create_contact_sheet(records: list[dict[str, object]], output_path: Path) -> None:
    tile_width, tile_height = 300, 390
    sheet = Image.new("RGBA", (tile_width * 5, tile_height * 2), (255, 255, 255, 255))
    checker = 20

    for index, record in enumerate(records):
        image = Image.open(str(record["path"])).convert("RGBA")
        tile = Image.new("RGBA", (tile_width, tile_height), (245, 245, 245, 255))
        draw = ImageDraw.Draw(tile)
        for y in range(0, 360, checker):
            for x in range(0, tile_width, checker):
                if (x // checker + y // checker) % 2:
                    draw.rectangle((x, y, x + checker - 1, y + checker - 1), fill=(220, 220, 220, 255))
        thumb = image.copy()
        thumb.thumbnail((280, 345), Image.Resampling.LANCZOS)
        tile.alpha_composite(thumb, ((tile_width - thumb.width) // 2, (350 - thumb.height) // 2))
        draw.text((8, 365), str(record["file"]), fill=(0, 0, 0, 255))
        sheet.alpha_composite(tile, ((index % 5) * tile_width, (index // 5) * tile_height))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "PNG", optimize=True)


def write_manifest(
    source: Path,
    set_number: int,
    records: list[dict[str, object]],
    contact_path: Path,
    output_path: Path,
    parameters: dict[str, object],
) -> None:
    manifest = {
        "algorithm": ALGORITHM_VERSION,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "set": f"{set_number:02d}",
        "roles": list(ROLES),
        "contact_sheet": str(contact_path),
        "parameters": parameters,
        "files": records,
        "approval_required_before_install": True,
    }
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def install_assets(repo_root: Path, records: list[dict[str, object]], *, approved: bool) -> list[Path]:
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

    for record, target in zip(records, targets, strict=True):
        shutil.copy2(Path(str(record["path"])), target)
        if sha256_file(target) != str(record["sha256"]):
            raise SystemExit(f"SHA-256 mismatch after install: {target}")
    return targets


def git_commit_exact(repo_root: Path, targets: list[Path], set_number: int) -> str:
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
    run("add", "--", *relative_targets)
    staged = [line for line in run("diff", "--cached", "--name-only").splitlines() if line]
    if sorted(staged) != sorted(relative_targets):
        raise SystemExit(
            "Git safety gate failed: staged file set is not exactly the 10 expected PNGs.\n"
            f"Expected: {relative_targets}\nActual: {staged}"
        )
    if len(staged) != 10:
        raise SystemExit(f"Git safety gate failed: expected 10 staged files, found {len(staged)}")

    run("commit", "-m", f"Add character asset variant set {set_number:02d}")
    return run("rev-parse", "HEAD")


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
    parser.add_argument("--seed", action="append", default=[], help="Optional corrective seed ROLE:X,Y; repeatable")
    parser.add_argument("--install", action="store_true", help="Copy reviewed outputs into assets/<role>/")
    parser.add_argument("--approved", action="store_true", help="Confirm that the generated contact sheet was visually reviewed")
    parser.add_argument("--commit", action="store_true", help="After install, create one local git commit containing exactly the 10 PNGs")
    parser.add_argument("--bg-threshold", type=int, default=DEFAULT_BG_THRESHOLD)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_FRACTION)
    parser.add_argument("--peaks-per-cell", type=int, default=DEFAULT_PEAKS_PER_CELL)
    parser.add_argument("--cell-inset", type=float, default=DEFAULT_CELL_INSET)
    parser.add_argument("--min-component-area", type=int, default=DEFAULT_MIN_COMPONENT_AREA)
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
    if not (0.01 <= args.margin <= 0.20):
        raise SystemExit("--margin must be between 0.01 and 0.20")
    if not (1 <= args.peaks_per_cell <= 8):
        raise SystemExit("--peaks-per-cell must be between 1 and 8")
    if not (0.0 <= args.cell_inset < 0.25):
        raise SystemExit("--cell-inset must be between 0.0 and 0.25")
    if args.min_component_area < 1:
        raise SystemExit("--min-component-area must be positive")

    set_number = parse_set_number(args.set_number, repo_root)
    preview_dir = (
        args.preview_dir.expanduser().resolve()
        if args.preview_dir
        else repo_root / ".asset_import_preview" / f"set_{set_number:02d}"
    )
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)

    manual_seeds = parse_manual_seeds(args.seed)
    parameters = {
        "bg_threshold": args.bg_threshold,
        "margin": args.margin,
        "peaks_per_cell": args.peaks_per_cell,
        "cell_inset": args.cell_inset,
        "min_component_area": args.min_component_area,
        "manual_seeds": {role: manual_seeds[role] for role in ROLES if manual_seeds[role]},
    }
    records = split_sheet(
        source,
        preview_dir,
        set_number,
        manual_seeds,
        bg_threshold=args.bg_threshold,
        margin_fraction=args.margin,
        peaks_per_cell=args.peaks_per_cell,
        cell_inset=args.cell_inset,
        min_component_area=args.min_component_area,
    )
    contact_path = preview_dir / f"contact_set_{set_number:02d}.png"
    create_contact_sheet(records, contact_path)
    manifest_path = preview_dir / f"manifest_set_{set_number:02d}.json"
    write_manifest(source, set_number, records, contact_path, manifest_path, parameters)

    print(f"Prepared set {set_number:02d}: 10 PNGs")
    print(f"Contact sheet: {contact_path}")
    print(f"Manifest: {manifest_path}")
    print("Review gate: do not install if any body part/prop is missing or assigned to a neighboring role.")

    if not args.install:
        print(
            "After visual approval, rerun with: "
            f'python tools/import_asset_sheet.py "{source}" --set {set_number:02d} --install --approved'
        )
        return 0

    targets = install_assets(repo_root, records, approved=args.approved)
    print("Installed exactly 10 assets:")
    for target in targets:
        print(f"  {target.relative_to(repo_root)}")

    if args.commit:
        commit_sha = git_commit_exact(repo_root, targets, set_number)
        print(f"Created commit: {commit_sha}")
    else:
        print("No git commit created. Review `git diff --stat` before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
