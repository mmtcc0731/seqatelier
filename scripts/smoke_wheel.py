"""Install the built wheel into a fresh venv and exercise it outside the checkout."""

import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path

root = Path(__file__).resolve().parents[1]
wheels = list((root / "dist").glob("*.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected exactly one wheel in dist/")
with tempfile.TemporaryDirectory(prefix="sequence-wheel-") as folder:
    scratch = Path(folder)
    venv.EnvBuilder(with_pip=True).create(scratch / "env")
    python = scratch / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheels[0]) + "[viewer,mcp]"],
        check=True,
        cwd=scratch,
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "SEQATELIER_WORKSPACE", "SEQATELIER_TOKEN"}
    }
    env["SEQATELIER_CONFIG"] = str(scratch / "settings.json")
    env["SEQATELIER_CACHE_HOME"] = str(scratch / "cache")
    command = [str(python), "-m", "seqatelier", "--workspace", str(scratch / "data")]
    subprocess.run([*command, "init", "--demo"], cwd=scratch, env=env, check=True, capture_output=True)
    result = subprocess.run(
        [*command, "doctor"], cwd=scratch, env=env, check=True, capture_output=True, text=True
    )
    doctor = json.loads(result.stdout)
    assert doctor["records"] == 2 and doctor["viewer_assets"] and doctor["mcp_installed"], doctor
    subprocess.run(
        [str(python), "-m", "seqatelier", "workspace", "use", str(scratch / "data")],
        cwd=scratch,
        env=env,
        check=True,
        capture_output=True,
    )
    selected = subprocess.run(
        [str(python), "-m", "seqatelier", "workspace", "show"],
        cwd=scratch,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(selected.stdout)["workspace_id"] == doctor["workspace_id"]
    # Import through the installed wheel, not the editable checkout.
    subprocess.run(
        [
            str(python),
            "-c",
            "from seqatelier.web import create_app; from seqatelier.mcp_server import create_server",
        ],
        cwd=scratch,
        env=env,
        check=True,
    )
    print(
        json.dumps(
            {
                "wheel": wheels[0].name,
                "version": doctor["version"],
                "clean_install": "passed",
                "viewer_assets": doctor["viewer_assets"],
            }
        )
    )
