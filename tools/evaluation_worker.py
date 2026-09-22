"""Owned subprocess tasks. Target Python files are only parsed by Slopmeter."""

import json
import sys
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913, PLR0917 - stdlib override
        raise ValueError("Source download redirects are not allowed.")


def _fetch(job: dict[str, object]) -> None:
    url = str(job["url"])
    if not url.startswith("https://raw.githubusercontent.com/"):
        raise ValueError("Source downloads require the pinned GitHub raw host.")
    request = Request(url, headers={"User-Agent": "slopmeter-public-evaluation"})  # noqa: S310
    with build_opener(_NoRedirect()).open(request, timeout=30) as response:
        Path(str(job["destination"])).write_bytes(response.read())


def _analyze(job: dict[str, object]) -> None:
    import slop_measure  # noqa: PLC0415 - verify the isolated worker loads the pinned analyzer
    from slop_measure.api import (  # noqa: PLC0415 - only the analysis worker loads analyzers
        AnalysisConfig,
        ComparisonRequest,
        DirectorySourceReference,
        SnapshotRequest,
        review_change,
    )
    from slop_measure.application.derived import inspect_derived  # noqa: PLC0415
    from slop_measure.application.error_review import inspect_errors  # noqa: PLC0415

    if Path(slop_measure.__file__).resolve().parent != Path(str(job["analyzer_path"])):
        raise ValueError("Worker and coordinator loaded different analyzer packages.")
    config = AnalysisConfig(
        calibration_profile="__raw__",
        languages=frozenset({"python"}),
        generated_markers=(),
        exclusions=(),
    )
    if job["kind"] == "changes":
        report = review_change(
            ComparisonRequest(
                baseline=DirectorySourceReference(root=Path(str(job["before"]))),
                current=DirectorySourceReference(root=Path(str(job["after"]))),
                config=config,
            )
        )
    else:
        request = SnapshotRequest(
            target=DirectorySourceReference(root=Path(str(job["source"]))), config=config
        )
        if job["command"] == "errors":
            report = inspect_errors(request)
        elif job["command"] == "derived":
            report = inspect_derived(request)
        else:
            raise ValueError("Unknown evaluation command.")
    Path(str(job["report"])).write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if job["kind"] == "fetch":
        _fetch(job)
    elif job["kind"] in {"snapshot", "changes"}:
        _analyze(job)
    else:
        raise ValueError("Unknown worker task.")


if __name__ == "__main__":
    main()
