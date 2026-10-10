# Evidence (submission)

`make evidence` runs the demo arc with a fixed clock, exports the hash-chained audit log to `sandbox-logs/audit.jsonl`, and writes JUnit test results to `test-results/junit.xml`.

| Folder | Deliverable |
|---|---|
| `sandbox-logs/` | Sandbox operation logs and audit exports (execution evidence) |
| `test-results/` | Security, suitability and golden test results |
| `screenshots/` | UI captures for the deck and the docs |

Generated files are git-ignored; commit only the final export for the submission.
