# Self-review of every reported hotspot

Date: 2026-09-21. Baseline: `408a5fd`. This is an agent-assisted source review,
not independently adjudicated defect ground truth or calibration evidence.

## Result

Reviewed all 69 baseline complexity hotspots, both pattern findings, and the
deliberate parse-error fixture. The two fixes introduced one more complexity
hotspot, which was also reviewed. Across these 73 records, 64 need no change,
six have deferred maintenance concerns, and three led to two general evaluator
fixes. No score-driven refactoring or project-specific evaluator tuning occurred.

Every hotspot's reported complexity matched direct Radon analysis. Every measured
file's M4 numerator, denominator, and value reconciled independently. A valid CC
measurement does not establish that the function needs refactoring. The two
confirmed defects came from inspecting source, not from the numerical score
detecting those defects automatically.

## General defects fixed

1. **Class-local Boolean annotation shadowing (`5084ac1`).** A dataclass body
   assigning `bool = int` could cause the model experiment to label an integer
   field as Boolean and emit unsupported coupled-state evidence. The detector now
   leaves this binding unresolved. The paired unshadowed model still produces its
   expected evidence. This applies to any class with such shadowing; it is not a
   special case for this repository. Regression: `bec66ba`.
2. **Historical complexity selection (`0cfc86a`).** The findings query always
   selected test callables with the current assertion-excluded basis. That could
   omit a hotspot in a valid M4 v1/v2 report carrying assertion evidence, while
   its version-aware explanation used full CC. Selection now shares that existing
   version policy: v1/v2 full CC, v3 cohort-aware CC, unknown/missing version
   unassessed. Current v3 arithmetic and scores are unchanged. Regressions:
   `3651727`, `0458733`; supported fixture provenance corrected in `76b0f66`.

The first fix adds a necessary guard and raises `_fields` to CC11. We retained it.
Removing or disguising that check to lower the score would weaken correctness.

## Source and evaluator decisions

The table records baseline dispositions. `Fixed evaluator` means a reproduced
general defect was corrected; it does not mean the displayed CC was wrong.
`Defer` means a maintenance concern without a demonstrated correctness defect.
The [complete record](self-review-2026-09-21.json) retains individual evidence,
reason, remaining risk, next step, original/final measurements, hashes, and fix IDs.

| ID | Source / callable | Effective CC / SLOC | Decision | Rationale |
|---|---|---:|---|---|
| 1 | `src/slop_measure/application/_review_targets.py:87`<br>`_analysis` | 12 / 33 | no-change | Dispatch selects distinct version identities for patterns, clones, and complexity. Missing analyzer or metric identity yields an unavailable anchor. |
| 2 | `src/slop_measure/application/_review_targets.py:122`<br>`_snapshot_targets` | 12 / 53 | no-change | Current-side groups, patterns, and callables keep their owned source paths and hashes. Clone anchors use only effective member assignments; baseline evidence is skipped. |
| 3 | `src/slop_measure/application/comparison.py:102`<br>`_changes` | 16 / 38 | no-change | File pairing retains unreadable evidence and computes deltas from the two owned document maps. Added, deleted, and renamed paths stay explicit. |
| 4 | `src/slop_measure/application/comparison.py:219`<br>`assemble_comparison` | 13 / 50 | no-change | Assembly checks snapshot/provenance compatibility, remaps side-specific IDs and diagnostics, and preserves both source populations. Most decisions are comprehensions over the two sides. |
| 5 | `src/slop_measure/application/derived.py:36`<br>`inspect_derived` | 13 / 33 | no-change | Directory inventory, isolated per-file analysis, failed-read outcomes, and strict-mode errors are separate visible phases. The CC counts filters and diagnostic accumulation. |
| 6 | `src/slop_measure/application/models.py:32`<br>`inspect_models` | 13 / 33 | no-change | The model experiment uses the same explicit inventory/failure/strict/report sequence. It does not import source or turn failed files into empty findings. |
| 7 | `src/slop_measure/application/reviews.py:43`<br>`_resolve` | 15 / 33 | no-change | Legacy resolution requires exact anchor equality for current; candidates with changed or missing identity are stale and absent candidates are missing. |
| 8 | `src/slop_measure/application/service.py:64`<br>`_validate_evidence` | 13 / 19 | no-change | Short adapter contract checklist verifies complete path/language/cohort accounting, declared capabilities, and error evidence for failed files. |
| 9 | `src/slop_measure/application/service.py:129`<br>`AnalysisService._scan` | 15 / 60 | defer | The scan loop performs config validation, source discovery, adapter isolation, provenance assembly, aggregation and strict-mode enforcement. The full source-review path did not establish a correctness defect. |
| 10 | `src/slop_measure/application/variants.py:36`<br>`inspect_variants` | 13 / 33 | no-change | The variant experiment preserves directory source coverage and failures, then applies strict mode to error diagnostics. The complexity reflects the same explicit application pipeline. |
| 11 | `src/slop_measure/domain/comparison_validation.py:64`<br>`validate_deltas` | 11 / 22 | no-change | Delta validation distinguishes missing, unavailable, and incompatible inputs and verifies current-minus-baseline arithmetic with a small tolerance. |
| 12 | `src/slop_measure/domain/comparison_validation.py:110`<br>`_validate_totals` | 16 / 41 | no-change | Line totals reconcile every source file and measured change. M1 availability and raw values must agree with owned totals. |
| 13 | `src/slop_measure/domain/evidence.py:489`<br>`LanguageEvidence.validate_clone_analyses` | 11 / 16 | no-change | Capability guard and exact parsed-file coverage checks protect clone evidence. Candidate spans are validated against their own file. |
| 14 | `src/slop_measure/domain/evidence.py:557`<br>`LanguageEvidence.validate_pattern_analyses` | 11 / 16 | no-change | Pattern capability and one-outcome-per-parsed-file checks prevent partial output from looking complete. Finding spans are checked against source lines. |
| 15 | `src/slop_measure/domain/reports.py:341`<br>`AnalysisReport.clone_review_anchor` | 13 / 37 | no-change | Legacy anchors require owned current groups, hashes for each member, and the clone metric version before storing the exact policy/definition context. |
| 16 | `src/slop_measure/domain/reports.py:419`<br>`AnalysisReport.validate_reviews` | 15 / 19 | no-change | Imported current reviews must match their actual anchors; stale candidate IDs and supplied explanations must agree with current groups. |
| 17 | `src/slop_measure/domain/reports.py:440`<br>`AnalysisReport.validate_clones` | 13 / 29 | no-change | Clone context is recomputed from declarations; each member must belong to a source file with matching language/cohort and valid spans. |
| 18 | `src/slop_measure/domain/reports.py:516`<br>`AnalysisReport.validate_metadata` | 13 / 27 | no-change | Snapshot metadata cannot claim a baseline. Coverage, diagnostic IDs, exclusions, and metric diagnostic links are checked for unique source ownership. |
| 19 | `src/slop_measure/domain/scoring.py:298`<br>`CalibrationProfile.validate_models` | 11 / 18 | no-change | Profile validation checks unique models/eligibility/versions, required metric definitions, distribution inputs, and non-overlapping population ranges. |
| 20 | `src/slop_measure/languages/python/clones.py:148`<br>`extract_clone_candidates` | 13 / 33 | no-change | Complete sibling runs are thresholded by both statement count and exact owned SLOC, then deduplicated by observable identity. Nested suites and token projection account for the branches. |
| 21 | `src/slop_measure/languages/python/derived_review.py:138`<br>`_mutation_kind` | 15 / 22 | no-change | The explicit append/insert/extend alternatives establish guaranteed length increases. Integer-position and literal-argument guards are evidence preconditions, not redundant defenses. |
| 22 | `src/slop_measure/languages/python/model_review.py:73`<br>`_field_kind` | 13 / 14 | Fixed evaluator | CC is valid, but builtin-bool proof is not: class-local bool = int before active: bool still yields kind boolean and a coupled-state finding. This is a general detector binding bug. |
| 23 | `src/slop_measure/languages/python/model_review.py:120`<br>`_predicate` | 20 / 30 | no-change | The recursive predicate recognizer accepts only declared Boolean attributes, nullable identity comparisons, and explicit Boolean operators. Receiver normalization preserves operand order and structure. |
| 24 | `src/slop_measure/languages/python/model_review.py:263`<br>`_findings` | 11 / 27 | no-change | The finding join requires a rejecting validator, mixed Boolean/nullable fields, and two distinct typed consumers; branches enforce the experiment evidence threshold. |
| 25 | `src/slop_measure/languages/python/model_review.py:292`<br>`_model_reason` | 22 / 23 | Fixed evaluator | Module-level and decorator identity guards are valid but omit class-local bool resolution. Its caller therefore accepts an unsupported field type. |
| 26 | `src/slop_measure/languages/python/model_review.py:317`<br>`_construction_reason` | 13 / 17 | no-change | Constructor and post-init replacement checks reject cases where dataclass-generated construction cannot be established; init must be literal True when specified. |
| 27 | `src/slop_measure/languages/python/rules/_shared.py:58`<br>`bound_names` | 12 / 23 | no-change | Binding alternatives cover Python name stores, parameters, imports, exception captures, match captures and type parameters. Each alternative is a distinct binding form. |
| 28 | `src/slop_measure/languages/python/rules/_shared.py:121`<br>`ScopeIndex.stable_local` | 17 / 21 | no-change | A stable local requires lexical ownership, a real binding, no relevant global/nonlocal, dynamic introspection or nested capture. Flat rejection checks protect rule soundness. |
| 29 | `src/slop_measure/languages/python/rules/_shared.py:183`<br>`header` | 13 / 28 | no-change | Token-based header spans track indentation and bracket depth so punctuation inside expressions is not the block boundary. The if caller handles lambda-colon ambiguity. |
| 30 | `src/slop_measure/languages/python/rules/abstraction.py:72`<br>`_plain_forwarder` | 22 / 30 | no-change | Twenty-two paths largely represent explicit exclusions for API boundaries and forwarding shape. Defaults, annotations, decorators, variadics and keyword calls each invalidate the narrow proof. |
| 31 | `src/slop_measure/languages/python/rules/abstraction.py:104`<br>`_trivial_wrapper` | 13 / 21 | no-change | The wrapper rule combines private nested ownership, a plain forwarding body, one use and an immediately following direct call. It avoids project-wide reachability claims. |
| 32 | `src/slop_measure/languages/python/rules/abstraction.py:127`<br>`_return_binding` | 14 / 22 | no-change | A single binding immediately returned qualifies only when local and unique, with no await/yield or type-comment boundary. Its branches prevent cross-scope and typed-binding false positives. |
| 33 | `src/slop_measure/languages/python/rules/defensive.py:23`<br>`_reraise` | 13 / 25 | no-change | Only one bare except containing a bare raise qualifies; typed handlers, aliases, else and finally are preserved. Exact header-to-raise ownership is explicit. |
| 34 | `src/slop_measure/languages/python/rules/defensive.py:92`<br>`_literal_guard` | 12 / 21 | no-change | Immediate non-None literal assignment plus stable local identity proves the None branch unreachable within the supported shape. Calls and uncertain bindings are kept. |
| 35 | `src/slop_measure/languages/python/rules/redundancy.py:36`<br>`_identity_comprehension` | 12 / 15 | no-change | An identity list comprehension is recognized only over list/tuple literal ASTs with a simple matching target, no filter, async iteration or starred elements. |
| 36 | `src/slop_measure/languages/python/sloc.py:50`<br>`classify_sloc` | 11 / 19 | no-change | Token and physical-line checks distinguish code, true docstrings and multiline literal content while reusing the supplied AST. Multiple branches implement documented SLOC semantics. |
| 37 | `src/slop_measure/languages/python/variant_review.py:173`<br>`_enum_members` | 12 / 29 | no-change | Each enum member must be a single unique ordinary assignment; mixed auto/literal modes and aliases are rejected. The finite vocabulary is not inferred from dynamic values. |
| 38 | `src/slop_measure/languages/python/variant_review.py:204`<br>`_enum_value` | 13 / 24 | no-change | Enum values are restricted to proven direct auto calls or supported literals with IntEnum/StrEnum type restrictions. Local auto shadowing is excluded. |
| 39 | `src/slop_measure/languages/python/variant_review.py:247`<br>`_alias_parts` | 11 / 20 | no-change | Plain assignment, imported TypeAlias annotation and non-generic type-alias syntax are separate supported forms; other assignment shapes return no declaration. |
| 40 | `src/slop_measure/languages/python/variant_review.py:269`<br>`_literal_declaration` | 11 / 26 | no-change | A Literal declaration requires a known import, supported constant values and a unique finite set; per-element locations are retained. |
| 41 | `src/slop_measure/languages/python/variant_review.py:349`<br>`_handler_type` | 21 / 19 | no-change | The handler must be a top-level undecorated function whose first effective statement matches a fixed typed argument. Binding, rebinding and variadic checks protect subject identity. |
| 42 | `src/slop_measure/languages/python/variant_review.py:370`<br>`_pattern_cases` | 15 / 19 | no-change | OR patterns recurse only through recognized case values; enum qualifiers and literal values must belong to the exact finite declaration. Unsupported structural patterns return unresolved. |
| 43 | `src/slop_measure/languages/registry.py:20`<br>`_normalized_extensions` | 13 / 24 | no-change | Extension validation rejects malformed suffixes and case-normalized duplicates before registration changes state. Branches implement independent registry invariants. |
| 44 | `src/slop_measure/languages/registry.py:84`<br>`LanguageRegistry.resolve_languages` | 12 / 20 | no-change | Language selection resolves installed IDs then aliases, rejects unknown or ambiguous requests, and returns canonical deduplicated identities. No unavailable adapter is simulated. |
| 45 | `src/slop_measure/metrics/aggregate.py:132`<br>`_PatternContext.measure` | 14 / 24 | no-change | The method isolates pattern failures from function/clone outcomes, preserves parse or analyzer failure precedence, and measures a union of owned source lines. Its branches correspond to real analyzed, unsupported, and failed states; merging those states to reduce CC would weaken the contract. |
| 46 | `src/slop_measure/metrics/aggregate.py:350`<br>`_project_errors` | 13 / 21 | no-change | Project-level errors include unassigned source discovery failures and language-owned pathless analyzer errors. Failed-file diagnostics remain file-scoped. This deliberately prevents an unenumerated directory from producing a false complete cohort result. |
| 47 | `src/slop_measure/metrics/aggregate.py:373`<br>`_snapshot_metrics` | 21 / 44 | defer | The three capability-specific projections repeat filtering, but None means unsupported while an empty tuple means supported with no outcomes. Current code preserves that distinction and keeps M2, M3, and M4 failures independent. The CC count is accurate; repetition is a maintainability concern rather than a demonstrated bad metric. |
| 48 | `src/slop_measure/metrics/aggregate.py:449`<br>`aggregate_snapshot` | 31 / 110 | defer | The 110-SLOC coordinator owns diagnostic collection, file/source hash ownership, population formation, coverage, provenance, findings, and clone annotations. Direct Radon confirms CC31. Existing outcomes and sorted report construction are consistent; the long function is a credible review priority but no source correctness defect was reproduced. |
| 49 | `src/slop_measure/metrics/clones.py:28`<br>`_contained` | 11 / 30 | no-change | Containment uses an injective matching between inner and outer instances, not a simple any-parent test. This is necessary when repeated spans in one file overlap: two inner instances cannot collapse into one enclosing instance. The recursive augmenting-path helper has a real algorithmic purpose. |
| 50 | `src/slop_measure/metrics/clones.py:72`<br>`group_clones` | 12 / 46 | no-change | Grouping checks owning files and exact SLOC, rejects duplicate identities, and partitions by language, cohort, normalization version, and complete token sequences. Fingerprint equality alone never creates a group. Stable sorting and maximal containment preserve deterministic native evidence. |
| 51 | `src/slop_measure/metrics/deltas.py:54`<br>`metric_deltas` | 16 / 24 | no-change | The method compares current minus baseline while preserving missing, unavailable, and incompatible states. It rejects file/project and language/cohort mixing and compares scores only under the same profile/model IDs. The guards prevent plausible but fabricated zero deltas. |
| 52 | `src/slop_measure/reporting/callables.py:19`<br>`render_callable_basis` | 11 / 40 | no-change | Callable presentation correctly distinguishes M4v1 above-threshold mass, M4v2 excess mass, and M4v3 assertion-excluded test CC. Unknown versions report an unavailable basis. Production assertions are retained and the self-check hint does not reclassify source. |
| 53 | `src/slop_measure/reporting/derived.py:6`<br>`render_derived` | 11 / 42 | defer | The renderer exposes derivation, mutation, and read locations and distinguishes unresolved functions from failed files. It calls results review candidates and retains interpretation text about intentional snapshots. Its nested loops reflect the report hierarchy rather than hidden analysis. |
| 54 | `src/slop_measure/reporting/evidence.py:55`<br>`render_findings` | 18 / 82 | defer | Evidence rendering keeps native pattern, clone, and callable records separate and retains all members of any displayed clone group. Top limits whole records and reports omitted counts. Family ordering is deterministic, not an invented mixed-unit priority score. |
| 55 | `src/slop_measure/reporting/models.py:6`<br>`render_models` | 12 / 48 | defer | The renderer shows coupled fields, the rejecting validator, and each distinct repeated consumer, while keeping unresolved models and failed files visible. It says review candidate and includes the trust-boundary limitation; there is no unsupported proof-of-defect claim. |
| 56 | `src/slop_measure/reporting/queries.py:153`<br>`query_findings` | 23 / 59 | Fixed evaluator | The measured CC23 is accurate, but query_findings delegates eroded selection to _eroded, which always calls complexity_for(cohort). That applies M4v3 assertion exclusion even when the report declares M4v1/v2. The existing version-aware renderer then disagrees: a test callable with fullCC12 and adjustedCC1 should be selected under v1/v2 but is omitted. A bounded probe and the existing historical-rendering fixture reproduce the mismatch. |
| 57 | `src/slop_measure/reporting/terminal.py:380`<br>`_score_row` | 11 / 31 | no-change | The score row keeps unavailable scores distinct from measured zero, reports profile/model/reference support, and explains nonzero raw evidence at percentile-zero or rounded-zero points. Contributions show their own raw value, percentile, weight, and severity transform. Stored contributions have one-decimal precision, matching display precision. |
| 58 | `src/slop_measure/reporting/terminal.py:765`<br>`_explain_change` | 11 / 36 | no-change | The whole-file change block shows both paths, measured added/deleted/net lines and growth, and marks unavailable inputs explicitly. Raw ratio deltas use percentage points; score deltas use points. Better/worse applies to lower-is-better metrics, while M1 line growth is left without a quality judgment. |
| 59 | `src/slop_measure/scoring/calibration.py:43`<br>`_signature` | 13 / 26 | no-change | Calibration signature requires snapshots, exactly one language, rule/clone identity, all metric versions and matching metric settings. |
| 60 | `src/slop_measure/scoring/calibration.py:128`<br>`_collect` | 13 / 21 | no-change | Samples remain separated by file/project, production/test, scoring model, and SLOC band. Empty or incomplete metric observations are skipped. |
| 61 | `src/slop_measure/scoring/calibration.py:151`<br>`build_profile` | 13 / 65 | no-change | Profile construction rejects duplicate identities and incompatible signatures before collecting enough complete samples. Fixed models/weights are explicit. |
| 62 | `src/slop_measure/scoring/engine.py:191`<br>`score_snapshot` | 13 / 34 | no-change | Scoring validates scope/metric uniqueness, selects a compatible model/population, and sums rounded contributions into the configured band. |
| 63 | `src/slop_measure/scoring/engine.py:228`<br>`_score_result` | 17 / 51 | no-change | Score availability rules preserve raw facts and attach individual metric percentiles from the selected population. The project result is computed from aggregate inputs. |
| 64 | `src/slop_measure/sources/filesystem.py:171`<br>`FilesystemSourceProvider._git_paths` | 13 / 27 | no-change | Git inventory collapses ignored-directory coverage, keeps independent ignored leaves, and checks candidate paths for safe traversal before reading. |
| 65 | `src/slop_measure/sources/filesystem.py:241`<br>`_InventoryBuilder.add` | 11 / 24 | no-change | Directory selection applies the language filter before cohort classification and then records configured/ignored/unsupported outcomes or reads source. |
| 66 | `src/slop_measure/sources/git.py:155`<br>`_GitInventory.add` | 13 / 31 | no-change | Committed-tree selection mirrors language/cohort/exclusion policies, rejects unsupported modes, and reads immutable blobs. Generated markers are applied consistently. |
| 67 | `tests/fixtures/erosion/high.py:1`<br>`high` | 11 / 2 | no-change | The high complexity is the fixture's purpose. Rewriting it would remove the boundary condition under test. The metric correctly counts short-circuit decisions and two SLOC; it does not establish a defect. |
| 68 | `tests/golden/test_scan_basic.py:63`<br>`test_basic_scan_matches_hand_counted_manifest_and_never_executes_source` | 11 / 69 | no-change | This is one coherent end-to-end report contract, with explicit expected values outside the implementation. The projection branches are necessary to compare heterogeneous measured/unavailable states. Complexity accurately describes that work; splitting it solely for the score would distribute the same work across helpers without improving the contract. |
| 69 | `tests/unit/scoring/test_calibration_contract.py:136`<br>`test_profile_rejects_inconsistent_model_population_and_provenance` | 14 / 34 | no-change | The branching is a test-case generator, not complex production behavior. Every branch names a separate rejected contract state, and each parameter creates a fresh payload. The test verifies useful independent invariants. A dispatch-table rewrite would lower the reported function CC without adding correctness evidence. |
| 70 | `src/slop_measure/languages/python/model_review.py:89`<br>`_fields` | 11 / 20 | no-change | The field collector needs distinct guards for annotation form, unique binding and class-local bool shadowing. The new guard prevents a reproduced false type proof. CC11 is correctly measured; crossing the threshold does not justify removing a correctness condition or splitting it to move the score. |
| D1 | `tests/fixtures/basic/bad.py:1`<br>`broken` | n/a | no-change | This is intentional invalid source used to verify partial results, error evidence and strict failure. Reporting a parse error is correct. Repairing the fixture would remove a required failure-path test. |
| P1 | `tests/fixtures/patterns/overlap.py:1`<br>`py.boolean-conditional` | n/a | no-change | The expression selects True/False from a condition and matches the boolean-conditional rule. This is an intentional positive regression fixture; simplifying it would erase the test case rather than improve production behavior. |
| P2 | `tests/fixtures/patterns/overlap.py:1`<br>`py.literal-fstring` | n/a | no-change | The f-string contains no formatted value and is a genuine literal-fstring match. It deliberately overlaps P1 to verify that native findings remain distinct while M2 unions their source lines. |

## Coverage and interpretation

- Both pattern findings deliberately overlap one source line in a test fixture.
  They are valid positive controls. Keep the fixture and the one-line M2 union.
- The malformed file verifies partial analysis and strict failure. Keep its error
  visible. Test-cohort project scores remain unavailable when that fixture is in
  scope. Do not exclude it merely to make this self-scan look clean.
- Zero clone groups does not mean no repeated design. The three experimental
  orchestrators have similar structure but distinct retained names and literals.
  The declared exact/consistent-local-renaming detector does not equate those
  candidates. This is a documented coverage limit, not a reason to change it for
  these three files.
- Calibration remains `py-2026.3` with the same six historical projects. Valid
  measurement arithmetic is not proof of representative calibration or correctness.
- Existing generated-file markers and source exclusions were not changed.

## Retained decisions

[The native review ledger](self-review-2026-09-21.reviews.json) contains 72 current
decisions against the final source report: 70 callable reviews and two pattern
reviews. The diagnostic has a separate entry in the complete record because the
native ledger does not yet review diagnostics. Initial actionable decisions remain
in history. Changed source anchors were explicitly re-reviewed after the fixes and
their tests, rather than automatically approved.

To recheck against current source from PowerShell:

```powershell
.\.venv\Scripts\slop.exe score . --lang py --scope all --json | Set-Content -Encoding utf8 .tmp/self-review-current.json
.\.venv\Scripts\slop.exe review-report show --report .tmp/self-review-current.json --store .specs/python-slop-detector/self-review-2026-09-21.reviews.json
```

Use a fresh report. The ledger describes reviewed source and does not make an
unchanged no-change decision a general quality approval. Comment-only member edits
still stale reviews. Do not bulk reapprove decisions to clear those warnings.

## Validation

- Full Windows Python 3.12 suite: **1,505 passed**, four artifact cases run
  separately. Branch-inclusive coverage: **94.63 percent**.
- Four clean wheel/source installation tests passed. All 52 model/query tests also
  passed on Python 3.13 and 3.14.
- Ruff lint/format, Pyright with the project interpreter, and all five import
  contracts passed. No dependencies changed.
- Final self-scan: 70 complexity hotspots, two pattern findings, one deliberate
  parse diagnostic, zero clone groups. No unreviewed new hotspot remains.
- The current ordinary score JSON exactly equals released v0.4.0 on the same final
  source tree. The earlier and final source trees differ, so their score delta must
  not be called an evaluator improvement or tuning result.
- Raw reports, measurement checks, probes, and the final native resolution remain
  under `.tmp/self-review-20260921/`. No private external corpus was accessed.

The fixes and review record are committed locally. They have not been pushed or
released as part of this review.
