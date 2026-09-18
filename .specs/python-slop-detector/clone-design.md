# TB-4 clone evidence contract

This contract narrows the initial clone detector to complete statement blocks.
Tree-sitter observations are retained in `tests/learning/test_tree_sitter_roles.py`.

Each parsed file has one explicit clone outcome. A failed analyzer cannot masquerade
as a successful file with no duplicates.

```datamodel
name: CloneAnalysis
store: in-memory
summary: A tagged analyzed or failed outcome for one parsed file.
fields:
  - { name: state, type: analyzed | failed, required: true }
  - { name: path, type: ProjectPath, required: true }
  - { name: candidates, type: tuple[CloneCandidate], description: Present only in the analyzed variant }
  - { name: diagnostic, type: Diagnostic, description: Same-file ERROR present only in the failed variant }
```

Candidates retain normalized tokens so a hash collision cannot establish equality.
The fingerprint is a checked projection of the version and canonical token encoding.

```datamodel
name: CloneCandidate
store: in-memory
summary: One eligible block and its exact physical source-line ownership.
fields:
  - { name: path, type: ProjectPath, required: true }
  - { name: span, type: SourceSpan, required: true }
  - { name: statement_count, type: positive strict integer, required: true }
  - { name: sloc_lines, type: sorted unique tuple[positive integer], required: true }
  - { name: normalization_version, type: nonempty string, required: true }
  - { name: normalized_tokens, type: nonempty tuple[string], required: true }
  - { name: fingerprint, type: sha256, description: Derived from version and tokens }
```

Groups partition candidates by language, cohort, normalization version, and tokens.
Their members contain evidence references rather than parser objects.

```datamodel
name: CloneGroup
store: immutable report evidence
summary: At least two distinct instances of the same normalized block.
fields:
  - { name: language, type: LanguageId, required: true }
  - { name: cohort, type: production | test, required: true }
  - { name: normalization_version, type: nonempty string, required: true }
  - { name: fingerprint, type: sha256, required: true }
  - { name: members, type: tuple[CloneMember], required: true, description: Unique members with path and span and exact SLOC lines }
relationships:
  - { relation: wrapped by, target: ReportCloneGroup, cardinality: "1:1", description: Stable ID and current or baseline source ownership }
```

`LanguageEvidence.clone_analyses` is authoritative. Its `clone_candidates` property
flattens successful outcomes. Evidence validation requires one outcome per parsed
file when clones are supported. Candidate and member SLOC must equal the owning
file's SLOC intersection with the span. Report groups must stay within one language,
cohort, and source state. These shapes prevent duplicate mutable collections and
prevent analyzer failure from becoming a measured zero.

The initial extraction and normalization rules are explicit:

| Concern | Version-one policy |
|---|---|
| Candidate boundary | Complete consecutive executable sibling runs in module or block suites |
| Run separators | Imports, actual docstrings, function definitions, class definitions, decorated definitions |
| Nested suites | Analyze independently |
| Thresholds | Inclusive configured statement and exact SLOC minima |
| Trivia | Remove whitespace and comments |
| Local renaming | Normalize consistently bound local names and enclosing callable parameters |
| Semantics retained | Operators, literal values and types, external names, attributes, keyword names |
| Uncertain binding | Retain exact spelling instead of guessing identity |
| Parser recovery | Fail clone analysis for the file, retain other successful analysis families |
| Self-overlap | A group needs two nonoverlapping instances, possibly in different files |
| Containment | Remove a smaller group only when all members map to distinct containing members of one larger group |

> [!NOTE]
> This version does not promise matches for arbitrary partial subranges inside
> unequal larger runs. It avoids enumerating a quadratic number of statement windows.
> Wider matching requires a new normalization or metric version and its own fixtures.

M3 counts the union of clone member `(path, line)` identities. Combined verbosity
counts the union of pattern and clone identities. File measurement accepts cross-file
groups and counts only that file's members. Project measurement uses only its own
population. Clone failures make M3 and combined verbosity unavailable for the file
and cohort. Pattern failures also make combined verbosity unavailable. M2 and M4
remain independent.
