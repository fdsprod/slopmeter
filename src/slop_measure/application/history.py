"""Follow source-line introductions through a bounded sequence of pinned snapshots."""

from dataclasses import dataclass

from slop_measure.application.comparison import assemble_comparison
from slop_measure.application.service import AnalysisService, _Snapshot
from slop_measure.domain.changes import AddedFile, DeletedFile, FileChange, MeasuredLineDelta
from slop_measure.domain.history import (
    HistoryCohort,
    HistoryReport,
    HistoryRequest,
    HistoryStep,
    KnownRework,
    ReworkAssessment,
    UnresolvedRework,
)
from slop_measure.domain.reports import AnalysisReport, ComparisonCohortReport
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import (
    Cohort,
    GitSourceIdentity,
    GitSourceReference,
    ProjectPath,
    SourceDocument,
)
from slop_measure.metrics.loc_delta import aligned_line_pairs
from slop_measure.sources.git import rename_pairs
from slop_measure.sources.history import HistoryCommit, read_history_range


@dataclass(frozen=True)
class _Origin:
    commit: str
    path: ProjectPath
    line: int
    timestamp: int


_LineKey = tuple[str, Cohort, str, int]


class _LineHistory:
    def __init__(self, window_days: int) -> None:
        self.window_seconds = window_days * 86400
        self.origins: dict[_LineKey, _Origin] = {}

    def _assessment(
        self, key: _LineKey, timestamp: int, deleted_path: ProjectPath
    ) -> ReworkAssessment:
        origin = self.origins.get(key)
        if origin is None:
            return UnresolvedRework(
                deleted_path=deleted_path, deleted_line=key[3], reason="unknown-introduction"
            )
        age = timestamp - origin.timestamp
        if age < 0:
            return UnresolvedRework(
                deleted_path=deleted_path, deleted_line=key[3], reason="timestamp-order"
            )
        return KnownRework(
            state="recent" if age <= self.window_seconds else "outside-window",
            deleted_path=deleted_path,
            deleted_line=key[3],
            introduced_commit=origin.commit,
            introduced_path=origin.path,
            introduced_line=origin.line,
            age_seconds=age,
        )

    def _file(
        self,
        change: FileChange,
        cohort: ComparisonCohortReport,
        commit: HistoryCommit,
        documents: tuple[dict[str, SourceDocument], dict[str, SourceDocument]],
        following: dict[_LineKey, _Origin],
    ) -> tuple[ReworkAssessment, ...]:
        if not isinstance(change.lines, MeasuredLineDelta):
            return ()
        old_path = None if isinstance(change.pair, AddedFile) else change.pair.baseline_path
        new_path = None if isinstance(change.pair, DeletedFile) else change.pair.current_path
        prefix = (cohort.language, cohort.cohort)
        assessments = tuple(
            self._assessment((*prefix, old_path.root, line), commit.timestamp, old_path)
            for line in change.lines.deleted_lines
            if old_path is not None
        )
        if new_path is None:
            return assessments
        for line in change.lines.added_lines:
            following[*prefix, new_path.root, line] = _Origin(
                commit.revision, new_path, line, commit.timestamp
            )
        if old_path is not None:
            self._carry(change.lines, prefix, (old_path, new_path), documents, following)
        return assessments

    def _carry(
        self,
        lines: MeasuredLineDelta,
        prefix: tuple[str, Cohort],
        paths: tuple[ProjectPath, ProjectPath],
        documents: tuple[dict[str, SourceDocument], dict[str, SourceDocument]],
        following: dict[_LineKey, _Origin],
    ) -> None:
        old_path, new_path = paths
        deleted, added = set(lines.deleted_lines), set(lines.added_lines)
        for old_line, new_line in aligned_line_pairs(
            documents[0].get(old_path.root), documents[1].get(new_path.root)
        ):
            origin = self.origins.get((*prefix, old_path.root, old_line))
            if origin is not None and old_line not in deleted and new_line not in added:
                following[*prefix, new_path.root, new_line] = origin

    def step(
        self, commit: HistoryCommit, comparison: AnalysisReport, before: _Snapshot, after: _Snapshot
    ) -> HistoryStep:
        following: dict[_LineKey, _Origin] = {}
        documents = (
            {doc.path.root: doc for doc in before.inventory.documents},
            {doc.path.root: doc for doc in after.inventory.documents},
        )
        cohorts = []
        for cohort in comparison.cohorts:
            if not isinstance(cohort, ComparisonCohortReport):
                raise ValueError("history requires comparison cohorts")
            assessments = tuple(
                assessment
                for change in cohort.changes
                for assessment in self._file(change, cohort, commit, documents, following)
            )
            cohorts.append(
                HistoryCohort(
                    language=cohort.language,
                    cohort=cohort.cohort,
                    changes=cohort.changes,
                    rework=assessments,
                )
            )
        self.origins = following
        return HistoryStep(
            commit=commit.revision,
            parent=commit.parents[0],
            timestamp=commit.timestamp,
            cohorts=tuple(cohorts),
            coverage=comparison.coverage,
            diagnostics=comparison.diagnostics,
        )


def analyze_history(request: HistoryRequest) -> HistoryReport:
    """Measure observed integration churn and recent rework without executing target code."""
    history = read_history_range(request)
    service = AnalysisService()
    anchor = history.commits[0].parents[0] if history.commits else history.end.revision
    before = service._scan(
        SnapshotRequest(
            target=GitSourceReference(root=history.start.root, revision=anchor),
            config=request.config,
        )
    )
    line_history = _LineHistory(request.window_days)
    steps = []
    provenance = before.report.provenance
    for commit in history.commits:
        after = service._scan(
            SnapshotRequest(
                target=GitSourceReference(root=history.start.root, revision=commit.revision),
                config=request.config,
            )
        )
        comparison = assemble_comparison(
            before.report,
            after.report,
            before.inventory,
            after.inventory,
            renames=rename_pairs(
                GitSourceIdentity(root=history.start.root, revision=commit.parents[0]),
                GitSourceIdentity(root=history.start.root, revision=commit.revision),
            ),
        )
        steps.append(line_history.step(commit, comparison, before, after))
        provenance = comparison.provenance
        before = after
    return HistoryReport(
        start=history.start,
        end=history.end,
        window_days=request.window_days,
        max_commits=request.max_commits,
        traversal=history.traversal,
        provenance=provenance,
        steps=tuple(steps),
    )
