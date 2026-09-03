"""WebUI server — starts the Jarvis Control Plane API.

Usage:
    jarvis-webui                    # start on port 8090
    jarvis-webui --port 3000        # custom port
    jarvis-webui --host 0.0.0.0     # bind all interfaces
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis-webui",
        description="Jarvis Control Plane WebUI",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8090, help="Port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print(
            "FastAPI/uvicorn not installed.\n"
            "Install with: pip install 'jarvis[daemon]'\n"
            "Or use Nix: nix develop (includes daemon deps)",
            file=sys.stderr,
        )
        return 1

    print(f"🤖 Jarvis WebUI starting on http://{args.host}:{args.port}")
    print(f"   API docs: http://{args.host}:{args.port}/docs")
    print(f"   SSE stream: http://{args.host}:{args.port}/api/events/stream")
    print()

    uvicorn.run(
        "jarvis.webui.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
