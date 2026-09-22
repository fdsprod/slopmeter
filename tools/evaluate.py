"""Evaluate pinned public Python source without executing target code."""

import argparse
import math
import sys
from pathlib import Path

from evaluation_manifest import Manifest, read_json
from evaluation_runtime import execute, save


def _positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a positive finite number of seconds.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fetch", action="store_true", help="Fetch missing pinned GitHub source blobs."
    )
    parser.add_argument(
        "--timeout", type=_positive, default=180.0, help="Wall-clock seconds per worker."
    )
    options = parser.parse_args(argv)
    try:
        manifest_bytes = options.manifest.read_bytes()
        manifest = Manifest.model_validate(read_json(manifest_bytes))
        output, cache = options.output.resolve(), options.cache.resolve()
        if output.exists():
            raise ValueError(
                "Output directory must be new; existing results are never overwritten."
            )
        if output.is_relative_to(cache) or cache.is_relative_to(output):
            raise ValueError("Output and cache directories must not overlap.")
        output.mkdir(parents=True)
        save(output / "manifest.json", manifest.model_dump(mode="json"))
        result, status = execute(manifest, manifest_bytes, options)
        save(output / "result.json", result)
    except (OSError, ValueError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 2
    print(f"Evaluation {result['state']}: {output / 'result.json'}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
