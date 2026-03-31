from pathlib import Path
import shutil

src = Path("station.db")
dst_dir = Path("/data")
dst = dst_dir / "station.db"

if not dst_dir.exists():
    print("/data not found, nothing to copy")
    raise SystemExit(0)

if not src.exists():
    print("local station.db not found, nothing to copy")
    raise SystemExit(0)

if dst.exists():
    print("/data/station.db already exists, not overwriting")
    raise SystemExit(0)

shutil.copy2(src, dst)
print(f"copied {src} -> {dst}")
