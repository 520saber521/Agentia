"""Development server entry point with Windows subprocess-compatible loop."""

from __future__ import annotations

import argparse

import uvicorn

from main import windows_proactor_loop_factory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop=windows_proactor_loop_factory,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
