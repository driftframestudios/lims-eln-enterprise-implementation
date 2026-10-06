"""Command-line entry point for the Golden Specimen Workbench."""

from __future__ import annotations

import argparse
import os

import uvicorn

from .runtime import ADAPTERS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Golden Specimen Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--adapter",
        choices=ADAPTERS,
        default=os.environ.get("LIMS_WORKBENCH_ADAPTER", "process_local"),
        help="Select process-local state or the prepared PostgreSQL reference profile",
    )
    arguments = parser.parse_args()
    if arguments.adapter not in ADAPTERS:
        parser.error("LIMS_WORKBENCH_ADAPTER requires process_local or postgresql")
    if not 1 <= arguments.port <= 65535:
        parser.error("--port requires an integer from 1 to 65535")
    os.environ["LIMS_WORKBENCH_ADAPTER"] = arguments.adapter
    uvicorn.run(
        "lims_eln_implementation.workbench.runtime:create_configured_app",
        factory=True,
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
    )


if __name__ == "__main__":
    main()
