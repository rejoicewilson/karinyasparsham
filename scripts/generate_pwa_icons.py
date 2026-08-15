from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
MASTER = PUBLIC / "logo.png"


def render_icon(size: int, logo_fraction: float, background: tuple[int, int, int, int]) -> Image.Image:
    source = Image.open(MASTER).convert("RGBA")
    alpha_bounds = source.getchannel("A").getbbox()
    if alpha_bounds is None:
        raise ValueError("The master logo has no visible pixels")

    source = source.crop(alpha_bounds)
    target = round(size * logo_fraction)
    source.thumbnail((target, target), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), background)
    offset = ((size - source.width) // 2, (size - source.height) // 2)
    canvas.alpha_composite(source, offset)
    return canvas


def main() -> None:
    render_icon(192, 0.9, (0, 0, 0, 0)).save(
        PUBLIC / "pwa-192x192.png", optimize=True
    )
    render_icon(512, 0.9, (0, 0, 0, 0)).save(
        PUBLIC / "pwa-512x512.png", optimize=True
    )
    render_icon(512, 0.68, (245, 248, 246, 255)).save(
        PUBLIC / "maskable-icon-512x512.png", optimize=True
    )


if __name__ == "__main__":
    main()
