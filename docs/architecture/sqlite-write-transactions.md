# SQLite write admission

The service attaches the core, content and cognition databases to connections
whose main schema may differ. Previously, implicit transactions could reserve
only their first written shard: a message writer held core while an event worker
held cognition, then each requested the other database. SQLite reported
`database is locked`; retrying the statement in the same transaction could not
resolve the cycle.

Routed production connections now reserve their attached databases with
`BEGIN IMMEDIATE` before the first INSERT/UPDATE/DELETE/REPLACE, including cursor,
executemany and CTE writes. Explicit BEGIN statements use the same admission path.
A process-wide gate serializes reservation attempts, not whole transactions or
reads. Once admitted, SQLite owns the locks through commit, rollback or close.
Standalone test/backup databases keep their original behavior.

The configured connection timeout is honored by SQLite. Waiting for the
admission gate consumes that same reservation budget. Statements and partially
consumed executemany iterators are no longer blindly retried five times after
SQLite has already waited. An external writer or genuinely long transaction can
still exhaust the budget; this is not a promise that all lock errors disappear.

Calendar snapshots and phone timeline ingestion use explicit transactions and
finally-close their connections, including validation failures. Connection setup
also closes partially configured connections on error. Keep model/network work
outside database transactions, and pass the current connection to helpers that
write as part of that transaction instead of opening a second writer.

The gate coordinates threads in the current backend process. It is not a
cross-process distributed lock. Runtime schema migrations / executescript remain
startup or maintenance operations, not concurrent request operations.

Regression coverage: `backend/tests/test_sqlite_writer_contention.py` reproduces
the old partial-lock cycle on isolated databases and verifies admitted writers,
three-shard concurrency, rollback, failed-BEGIN recovery, cleanup and time budgets.
