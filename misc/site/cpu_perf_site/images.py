"""The Open Graph image, cut from the README's banner (AVIF, which link
unfurlers ignore) to the 1200x630 JPEG they expect."""

from __future__ import annotations

from pathlib import Path


def write_all(site, dist: Path) -> None:
    banner = site.build_dir / "assets" / "banner.avif" if getattr(site, "build_dir", None) else None
    if banner is None or not banner.is_file():
        return
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a site dependency
        return
    with Image.open(banner) as im:
        im = im.convert("RGB")
        w, h = im.size
        target = 1200 / 630
        crop_w = min(w, int(h * target))
        left = (w - crop_w) // 2
        og = im.crop((left, 0, left + crop_w, h)).resize((1200, 630), Image.LANCZOS)
        og.save(dist / "og.jpg", "JPEG", quality=82, optimize=True, progressive=True)
