"""Generate 1024x1024 TikTok/App PNG and multi-size Windows ICO from MuseCat logo."""

from pathlib import Path
from PIL import Image, ImageOps

ASSETS_DIR = Path(__file__).resolve().parent
SRC = ASSETS_DIR / "musecat_source.webp"
OUT_PNG = ASSETS_DIR / "musecat_icon_1024.png"
OUT_ICO = ASSETS_DIR / "musecat_icon.ico"


def build() -> None:
    if not SRC.is_file():
        raise FileNotFoundError(f"Kaynak logo bulunamadı: {SRC}")

    with Image.open(SRC) as im:
        rgba = im.convert("RGBA")
        # Ensure exact 1024x1024 square using high-quality Lanczos resampling
        icon_1024 = ImageOps.fit(rgba, (1024, 1024), method=Image.Resampling.LANCZOS)
        # TikTok accepts PNG/JPEG up to 5MB (RGB PNG keeps file size crisp and small)
        icon_1024.convert("RGB").save(OUT_PNG, format="PNG", optimize=True)

        # Multi-size Windows ICO for taskbar & window titlebar
        icon_1024.save(
            OUT_ICO,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )

    print(f"OK: {OUT_PNG} ({OUT_PNG.stat().st_size // 1024} KB)")
    print(f"OK: {OUT_ICO} ({OUT_ICO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
