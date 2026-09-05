"""Genereaza icon.icns pentru pachetul .app, pornind de la iconita desenata in gui.py."""
import subprocess
import shutil
from pathlib import Path
from tkinter import Tk

from gui import _build_app_icon

BASE_SIZES = [16, 32, 128, 256, 512]   # standard iconset @1x slots; @2x = dublu

def main():
    root = Tk()
    root.withdraw()

    out_dir = Path(__file__).parent
    iconset = out_dir / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()

    for size in BASE_SIZES:
        img = _build_app_icon(size)
        img.write(str(iconset / f"icon_{size}x{size}.png"), format="png")
        img2x = _build_app_icon(size * 2)
        img2x.write(str(iconset / f"icon_{size}x{size}@2x.png"), format="png")

    icns_path = out_dir / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)], check=True)
    shutil.rmtree(iconset)
    print(f"Creat: {icns_path}")

    root.destroy()


if __name__ == "__main__":
    main()
