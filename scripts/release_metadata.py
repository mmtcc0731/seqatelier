"""Check artifact names and emit checksums and an Actions release tag."""

import hashlib
import os
import re
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit("Expected a numeric three-part release version")
dist = root / "dist"
names = [f"seqatelier-{version}-py3-none-any.whl", f"seqatelier-{version}.tar.gz"]
packages = sorted(p.name for p in dist.iterdir() if p.name not in {"SHA256SUMS.txt", ".gitignore"})
if packages != sorted(names):
    raise SystemExit(f"Unexpected distribution contents: {packages}")
checksums = [f"{hashlib.sha256((dist / name).read_bytes()).hexdigest()}  {name}" for name in names]
(dist / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
if os.environ.get("GITHUB_OUTPUT"):
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"tag=v{version}\n")
print(f"Prepared v{version}: {', '.join(names)}")
