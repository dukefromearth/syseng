"""Local preview composition; graph remains authored through the normal indexing tool."""

import argparse
import os
import sys
from pathlib import Path

from typed_graph.adapters.workspace import open_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--strictPort", action="store_true")
    parser.add_argument("--profile", type=Path, default=os.environ.get("TYPED_GRAPH_PROFILE"))
    args = parser.parse_args()
    workspace = Path(os.environ.get("TYPED_GRAPH_WORKSPACE", "/tmp/typed-graph-reader-preview"))
    model = workspace / "model"
    if not model.exists():
        model.mkdir(parents=True)
        example = Path(__file__).resolve().parents[1] / "examples" / "model.json"
        (model / "example.json").write_text(example.read_text())
        service = open_service(workspace)
        service.dispatch("index_model", {})
    profile_args = ["--profile", str(args.profile)] if args.profile else []
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "typed_graph.adapters.spec_server",
            str(workspace),
            "--port",
            str(args.port),
            *profile_args,
        ],
    )


if __name__ == "__main__":
    main()
