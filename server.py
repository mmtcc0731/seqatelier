"""Compatibility entry point. Prefer seqatelier --workspace PATH serve."""
from seqatelier.web import create_app

app = create_app()

if __name__ == "__main__":
    from seqatelier.cli import main
    raise SystemExit(main(["serve"]))
