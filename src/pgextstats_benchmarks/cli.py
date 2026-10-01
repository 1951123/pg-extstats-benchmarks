"""Read-only CLI skeleton."""
import argparse
from pathlib import Path
import sys
import yaml
from .paths import benchmark_data_root
from .registry import load_registry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pgextbench")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("list")
    verify = commands.add_parser("verify")
    verify.add_argument("benchmark")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(f"Data root: {benchmark_data_root()}")
        else:
            registry = load_registry(args.repo)
            if args.command == "list":
                for benchmark in registry.values():
                    print(f"{benchmark.id}\t{benchmark.status}")
            else:
                if args.benchmark not in registry:
                    raise ValueError(f"Unknown benchmark: {args.benchmark}")
                path = registry[args.benchmark].path / "benchmark.yaml"
                if not path.is_file():
                    raise ValueError(f"Missing benchmark manifest: {path}")
                print(f"Manifest exists: {args.benchmark} (existence check only)")
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"pgextbench: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
