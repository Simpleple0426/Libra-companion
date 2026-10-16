# Unified application tool execution

`backend/application/tool_contracts.py` is the catalogue for registered
application tools, including the emotion wait gate and life content tools. Each entry declares its
adapter, required/optional argument types and ranges, allowed result types,
deadline, and execution policy. Model/tool selection and write authorization
remain in their existing callers; registration never grants permission.

`ToolExecutor.call(name, *args, **kwargs)` always returns a `ToolResult` for
ordinary execution errors, including invalid arguments and unknown tools:

```python
result = executor.call('xiaohongshu.search', query='coffee', num_notes=3)
if result.ok:
    use_notes(result.data)
else:
    record_failure(result.error['code'])
```

`result.to_dict()` has the same fields for success and failure: `call_id`,
`tool`, `ok`, `status`, `data`, `error`, `duration_ms`, `timeout_seconds`,
`deadline_exceeded`. Status is `completed`, `failed`, `timeout`, or `busy`.
An error contains a stable `code`, exception `type`, and `outcome_unknown`.
Codes are `unsupported_tool`, `invalid_arguments`, `adapter_unavailable`,
`execution_failed`, `invalid_result`, `timeout`, and `capacity_exhausted`.
Exception messages and argument/result payloads are omitted from execution logs.

The `data` field retains the domain payload (for example, search notes versus
weather data); a completed invocation does not imply that a search found results
or an optional action was requested. Existing business receipts such as
`not_requested`, `unavailable`, and `needs_clarification` retain their meaning.
Internal callers explicitly use `.unwrap()` when they need the payload and the
original domain exception for existing recovery handling. The result and
execution receipt are created first, even when unwrap raises.

## Deadline policy

Default seconds are declared in the catalogue. Trusted hosts can override them
with `ToolExecutor(..., timeouts={'weather.fetch': 20})`; unknown keys, non-finite,
zero and negative values are rejected. Nested calls inherit the earlier deadline.

- Reads run on at most 16 daemon workers across executors. A timed-out read
  returns promptly; late completion cannot change its result or emit a second
  receipt. Saturation returns `busy` without queuing more work. Python threads
  cannot forcibly cancel an in-flight library operation; the worker retains its
  slot until that operation exits.
- Network, browser subprocess and model CLI adapters use `remaining_timeout()`
  so their own waits respect the inherited budget. Existing subprocess cleanup
  remains responsible for killing timed-out child processes.
- Writes and the emotion context merge stay on the caller thread. Database
  connections and transaction ownership never cross threads. Their deadlines
  are cooperative: the executor will not abandon a write and report it failed
  while it may still commit. A known late success remains `completed` with
  `deadline_exceeded=true`. An exception after entering a write sets
  `outcome_unknown=true`; callers must check persisted domain receipts before
  deciding whether it is safe to try again. There are no automatic retries.
- This is not a hard interruption mechanism for arbitrary synchronous database
  or lock operations. Adapters must retain database/network/lock timeouts, and
  newly added blocking operations must participate in the deadline budget.

Callers continue to own durable idempotency keys, authorization, and commit /
rollback. An optional telemetry sink failure cannot change a completed outcome.

## Adding a tool

Add a `ToolSpec`, bind its adapter, and add argument/result/deadline tests. Route
chat and background invocations through `ToolExecutor`, consuming either the
result explicitly or `.unwrap()` at a domain boundary. Do not put secrets or
private arguments in error messages destined for telemetry. HTTP route handlers
and ordinary internal helper functions are not automatically AI tools.

No MCP server is introduced by this change.

## Life content tools

The movie and quotation features use this same boundary through
`application/content_tools.py`. `Douban.call`, `add_candidate`, `Sources.collect`,
the per-source searches and the allowed-page fetcher all enter `ToolExecutor`.
Private transport/parsing helpers remain in their existing domain modules.

Registered operations are `movies.search`, `movies.detail`, `movies.reviews`,
`movies.chart`, `movies.add`, `books.search`, `books.detail`, `quotes.collect`,
`quotes.book`, `quotes.wiki`, and `quotes.fetch`. The movie argument names match
the life agent's query / douban_id / count / runtime_index interface; its
decision policy remains separate from the chat decision policy. These shared
contracts do not automatically expose new choices to the chat model.

`movies.add` is a local write and runs on the caller thread. Its nested detail
read inherits its deadline; the adapter checks the deadline before beginning
the write transaction. Review/notebook persistence remains in existing domain
transactions. All external reads and subprocess waits use the shared remaining
budget. Quotation fallback emits individual source failure receipts even if
the overall collection returns an empty list. Movie timeout/busy failures retain
the existing `DoubanUnavailable` domain fallback after emitting their receipt.

Cookies, queries, quoted text and review bodies never enter tool execution
receipts. Existing domain caches and model audit records keep their prior
semantics. Domain cache hits still pass through tool execution and emit a receipt.

Run `python -m scripts.check_content_tools --quotes` from `backend` for a real,
read-only check of movie details, short comments and current library quotation
sources. It uses an isolated temporary cache and prints metadata/counts only.
