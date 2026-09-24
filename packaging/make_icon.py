"""Generate the Aurora Windows icon from the player waveform mark."""
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 1000, 1000), radius=224, fill="#151515", outline="#424242", width=16)
    bars = ((220, 405, 620), (338, 300, 735), (456, 220, 815),
            (574, 305, 735), (692, 390, 625), (810, 450, 570))
    for left, top, bottom in bars:
        draw.rounded_rectangle((left, top, left + 57, bottom), radius=28, fill="#f5f5f5")
    output = Path(__file__).resolve().parents[1] / "assets"
    output.mkdir(exist_ok=True)
    image.save(output / "aurora.ico", format="ICO", sizes=[
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
    ])


if __name__ == "__main__":
    main()
