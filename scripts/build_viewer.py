"""Build once before creating wheels; installed users do not need Node.js."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--built", action="store_true", help="Copy an already built frontend/dist")
args = parser.parse_args()
if not args.built:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("Install Node.js 22.12+ or 24 and npm for a source build.")
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=root / "frontend", check=True)
    subprocess.run([npm, "run", "build"], cwd=root / "frontend", check=True)
source = root / "frontend" / "dist"
if not (source / "index.html").is_file():
    raise SystemExit("frontend/dist/index.html is missing")
target = root / "src" / "seqatelier" / "web_assets"
# This exact generated-assets directory is owned by this build script.
if target.exists():
    if target.is_symlink() or root not in target.resolve().parents:
        raise SystemExit("Generated assets path resolves outside this source checkout")
    shutil.rmtree(target)
shutil.copytree(source, target)
print(f"Packaged viewer assets: {target}")
