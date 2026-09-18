"""Measure a complete source scan in a fresh process without executing the source."""

import argparse
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from slop_measure import __version__
from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan

_ASSIGNMENTS = 8
_LINES_PER_FUNCTION = 10


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Counts must be positive integers.")
    return number


def _generate(work: Path, files: int, functions: int) -> tuple[Path, str]:
    work.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="project-", dir=work)).resolve()
    digest = hashlib.sha256()
    for module in range(files):
        lines: list[str] = []
        for function in range(functions):
            lines.append(f"def function_{module}_{function}(value):")
            for assignment in range(_ASSIGNMENTS):
                operand = "value" if assignment == 0 else f"local_{assignment - 1}"
                literal = (module * functions + function) * _ASSIGNMENTS + assignment
                lines.append(f"    local_{assignment} = {operand} + {literal}")
            lines.append(f"    return local_{_ASSIGNMENTS - 1}")
        name = f"module_{module:06d}.py"
        content = ("\n".join(lines) + "\n").encode("utf-8")
        (root / name).write_bytes(content)
        for part in (name.encode("utf-8"), content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return root, digest.hexdigest()


class _MemoryCounters(ctypes.Structure):
    # Match PROCESS_MEMORY_COUNTERS from psapi.h; SIZE_T follows pointer width.
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_rss() -> int:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_MemoryCounters),
            ctypes.c_uint32,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = _MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    import resource  # noqa: PLC0415 - the resource module is unavailable on Windows

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak * (1 if sys.platform == "darwin" else 1024))


def _measure(root: Path) -> dict[str, object]:
    config = AnalysisConfig()
    start = time.perf_counter()
    report = scan(SnapshotRequest(target=DirectorySourceReference(root=root), config=config))
    elapsed = time.perf_counter() - start
    peak = _peak_rss()
    files = tuple(file for cohort in report.cohorts for file in cohort.current.files)
    if report.diagnostics or any(file.evidence.parse_state.value != "parsed" for file in files):
        raise ValueError("Benchmark analysis produced diagnostics or incomplete file evidence.")
    return {
        "schema_version": "1.0",
        "tool_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "files": len(files),
        "sloc": sum(file.evidence.sloc for file in files),
        "elapsed_seconds": elapsed,
        "peak_rss_bytes": peak,
        "config": config.model_dump(mode="json"),
        "diagnostics_count": len(report.diagnostics),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--files", type=_positive, default=100)
    parser.add_argument("--functions-per-file", type=_positive, default=100)
    parser.add_argument("--work-dir", type=Path, default=Path(".tmp/benchmark"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        print(json.dumps(_measure(args.worker), sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required")
    root, source_hash = _generate(args.work_dir, args.files, args.functions_per_file)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
    }
    # The fixture owns its inventory, independent of an enclosing checkout's ignores.
    environment["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    result = subprocess.run(  # noqa: S603 - fixed interpreter and owned benchmark worker
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(root)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        print(f"Benchmark worker failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    payload = json.loads(result.stdout)
    expected_sloc = args.files * args.functions_per_file * _LINES_PER_FUNCTION
    if payload["files"] != args.files or payload["sloc"] != expected_sloc:
        print("Benchmark analysis did not account for all generated source.", file=sys.stderr)
        return 1
    payload.update(source_sha256=source_hash, source_root=str(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
