"""Small, JSON-first command line interface; optional dependencies are lazy loaded."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

from seqatelier import __version__
from seqatelier.core.types import SeqAtelierError
from seqatelier.workspace import Workspace, WorkspaceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seqatelier", description="Portable sequence workspaces and design tools"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--workspace", help="Override the registered data directory (or SEQATELIER_WORKSPACE)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a workspace without overwriting existing records")
    init.add_argument("--demo", action="store_true", help="Add synthetic demo-vector and demo-insert")
    sub.add_parser("doctor", help="Report environment and workspace readiness as JSON")
    location = sub.add_parser("workspace", help="Show or register this computer's workspace location")
    locations = location.add_subparsers(dest="workspace_action", required=True)
    use = locations.add_parser("use", help="Remember an existing workspace folder on this computer")
    use.add_argument("path", type=Path)
    locations.add_parser("show", help="Show the current folder and stable workspace ID")
    listing = sub.add_parser("list", help="List/search records")
    listing.add_argument("query", nargs="?", default="")
    inspect = sub.add_parser("show", help="Read a record")
    inspect.add_argument("id")
    inspect.add_argument("--sequence", action="store_true")
    imp = sub.add_parser("import", help="Copy a single GenBank record into the workspace")
    imp.add_argument("file", type=Path)
    imp.add_argument("--id")
    imp.add_argument("--name")
    imp.add_argument("--kind", choices=["plasmid", "fragment", "primer"], default="plasmid")
    export = sub.add_parser("export", help="Export a record as GenBank; refuses to overwrite")
    export.add_argument("id")
    export.add_argument("output", type=Path)
    history = sub.add_parser("history")
    history.add_argument("id")
    restore = sub.add_parser("restore", help="Restore a revision as a new saved revision")
    restore.add_argument("id")
    restore.add_argument("revision")
    restore.add_argument("--expected-revision", required=True)
    backup = sub.add_parser("backup", help="Create a consistent portable ZIP backup")
    backup.add_argument("output", type=Path)
    design = sub.add_parser("design", help="Preview a design from a JSON request file")
    design.add_argument("request", type=Path)
    design.add_argument(
        "--save", action="store_true", help="Save only when expected_revisions matches the preview"
    )
    sub.add_parser("designs", help="List saved designs")
    order = sub.add_parser("order", help="Export a saved design's primer order CSV")
    order.add_argument("id")
    order.add_argument("output", type=Path)
    serve = sub.add_parser("serve", help="Start the Web viewer (install the viewer extra)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    host = sub.add_parser("host", help="Start Web + MCP with OAuth (install the cloud extra)")
    host.add_argument("--host", default="0.0.0.0")
    host.add_argument("--port", type=int, default=10000)
    host.add_argument("--allow-writes", action="store_true", help="Expose explicit MCP import/save tools")
    mcp = sub.add_parser("mcp", help="Start the MCP server (install the mcp extra)")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8766)
    mcp.add_argument("--allow-writes", action="store_true", help="Expose explicit import/save tools")
    args = parser.parse_args(argv)
    try:
        if args.command == "workspace" and args.workspace_action == "use":
            result = Workspace(args.path).use()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        ws = Workspace(args.workspace)
        if args.command == "workspace":
            result = ws.info()
        elif args.command == "init":
            ws.initialize()
            if args.demo:
                from seqatelier.demo import initialize_demo

                initialize_demo(ws)
            result = ws.info()
        elif args.command == "doctor":
            result = {
                "version": __version__,
                "python": sys.version.split()[0],
                "workspace": str(ws.path),
                "initialized": ws.database.is_file(),
                "viewer_installed": importlib.util.find_spec("fastapi") is not None,
                "mcp_installed": importlib.util.find_spec("mcp") is not None,
                "viewer_assets": (Path(__file__).parent / "web_assets" / "index.html").is_file(),
            }
            if ws.database.is_file():
                result.update(ws.info())
            elif ws.selection.workspace_id:
                raise WorkspaceError("Registered workspace is missing. Check its path and synchronization.")
        elif args.command == "list":
            result = ws.list_records(args.query)
        elif args.command == "show":
            result = ws.get_record(args.id, include_sequence=args.sequence)
        elif args.command == "import":
            result = ws.import_record(
                args.file.read_text(encoding="utf-8"), record_id=args.id, name=args.name, kind=args.kind
            )
            result.pop("sequence", None)
        elif args.command == "export":
            text = ws.export_genbank(args.id)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(text)
            result = {"exported": str(args.output.resolve())}
        elif args.command == "history":
            result = ws.history(args.id)
        elif args.command == "restore":
            result = ws.restore(args.id, args.revision, args.expected_revision)
        elif args.command == "backup":
            result = {"backup": str(ws.backup(args.output))}
        elif args.command == "design":
            from seqatelier.service import preview_design, save_design

            request = json.loads(args.request.read_text(encoding="utf-8"))
            if args.save:
                result = save_design(
                    ws,
                    request["method"],
                    request["parameters"],
                    request.get("expected_revisions", {}),
                    request.get("name", "design"),
                )
            else:
                result = preview_design(
                    ws, request["method"], request["parameters"], request.get("name", "design")
                )
        elif args.command == "designs":
            result = ws.list_designs()
        elif args.command == "order":
            from seqatelier.service import order_csv

            text = order_csv(ws.get_design(args.id))
            with args.output.open("x", encoding="utf-8", newline="") as handle:
                handle.write(text)
            result = {"exported": str(args.output.resolve())}
        elif args.command == "host":
            import uvicorn

            from seqatelier.mcp_server import create_http_app
            from seqatelier.oauth import OAuthSettings
            from seqatelier.web import create_app

            oauth = OAuthSettings.from_env()
            if oauth is None:
                raise WorkspaceError(
                    "Hosting requires SEQATELIER_AUTH_ISSUER, SEQATELIER_AUTH_CLIENT_ID and SEQATELIER_AUTH_SUBJECTS."
                )
            ws.initialize()
            mcp_app = create_http_app(
                ws, oauth=oauth, allow_writes=args.allow_writes, host=args.host, raw=True
            )
            uvicorn.run(create_app(ws, oauth=oauth, mcp_app=mcp_app), host=args.host, port=args.port)
            return 0
        elif args.command in {"serve", "mcp"}:
            ws.info()
            if (
                (args.command == "serve" or args.transport == "streamable-http")
                and args.host not in {"127.0.0.1", "localhost", "::1"}
                and not os.environ.get("SEQATELIER_TOKEN")
            ):
                raise WorkspaceError("Set SEQATELIER_TOKEN before binding to a non-loopback interface.")
            if args.command == "serve":
                import uvicorn

                from seqatelier.web import create_app

                uvicorn.run(create_app(ws), host=args.host, port=args.port)
            else:
                from seqatelier.mcp_server import run_server

                run_server(
                    ws,
                    transport=args.transport,
                    host=args.host,
                    port=args.port,
                    allow_writes=args.allow_writes,
                )
            return 0
        else:
            raise WorkspaceError("Unknown command")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ImportError as exc:
        print(
            json.dumps({"error": f"Optional dependency missing: {exc}. Install seqatelier[viewer,mcp]."}),
            file=sys.stderr,
        )
        return 2
    except (SeqAtelierError, OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
