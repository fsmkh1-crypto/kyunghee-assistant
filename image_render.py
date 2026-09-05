from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps


DEFAULT_ALPHA_THRESHOLD = 112


def _target_contain_size(size: tuple[int, int], max_size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    max_width, max_height = max_size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    scale = min(max_width / width, max_height / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def resize_rgba_alpha_safe(
    image: Image.Image,
    max_size: tuple[int, int],
    *,
    crop: bool = False,
    centering: tuple[float, float] = (0.5, 0.5),
) -> Image.Image:
    """Resize RGBA using Pillow's premultiplied RGBa mode to avoid dark edge fringes."""
    rgba = image.convert("RGBA")
    premul = rgba.convert("RGBa")
    if crop:
        resized = ImageOps.fit(
            premul,
            max_size,
            method=Image.Resampling.LANCZOS,
            centering=centering,
        )
    else:
        target = _target_contain_size(rgba.size, max_size)
        if target == rgba.size:
            resized = premul.copy()
        else:
            resized = premul.resize(target, Image.Resampling.LANCZOS)
    return resized.convert("RGBA")


def threshold_alpha(
    image: Image.Image,
    threshold: int = DEFAULT_ALPHA_THRESHOLD,
    *,
    smooth_radius: float = 0.0,
) -> Image.Image:
    """Convert alpha to binary transparency for Tk color-key windows after resizing.

    ``smooth_radius`` gently regularizes the resized alpha mask before the binary
    color-key cut.  A zero radius preserves the historical behavior exactly.
    """
    if not 0 <= threshold <= 255:
        raise ValueError("alpha threshold must be between 0 and 255")
    if smooth_radius < 0:
        raise ValueError("alpha smooth radius must be non-negative")
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if smooth_radius:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=float(smooth_radius)))
    rgba.putalpha(alpha.point(lambda value: 0 if value < threshold else 255))
    return rgba
