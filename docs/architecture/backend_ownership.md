# Backend module ownership

The dependency direction is `main/app -> application -> domains -> infrastructure`.
Domain stores do not import `main` and do not call HTTP routes.

| Area | Owner modules | Owns | Does not own |
|---|---|---|---|
| HTTP assembly | `main.py`, `app/api/` | FastAPI wiring and request contracts | retrieval algorithms |
| Unified retrieval | `application/knowledge_retriever.py` | source coordination, quotas, degradation | source truth or storage |
| Personal memory | `domains/memory/` | evidence-backed user/self/shared memories | authored canon |
| Shared history | `domains/persona/shared_history.py`, `canonical_history.py` | authored and lived shared-past boundary | character behavior |
| Character evidence | `domains/persona/character_corpus.py` | reviewed behavior evidence and ranking | real shared history |
| World | `domains/world/` | Libra life events and current state | user memories |
| Affect | `domains/affect/` | emotion state and appraisal | canonical facts |
| Turn orchestration | `application/turn_*` | response policy and delivery | persistent domain schemas |
| Content knowledge | `domains/content/` | scoped content retrieval | identity/persona truth |
| Persistence/adapters | `infrastructure/` | SQLite, model, embedding and weather implementations | prompt assembly |
| Operations | `scripts/` | imports, backfills, diagnostics and maintenance | online request handling |

## Naming rules

- A `*Store` owns persistent records or a durable index.
- A `*Retriever` coordinates read-only retrieval across stores.
- A `*_api.py` module owns HTTP endpoints only.
- `context_for()` renders bounded prompt context; `search()` returns structured records.
- Version suffixes belong to schemas and data formats, not permanent module names.

Compatibility modules may re-export an old name, but new production imports use the canonical name.

## Stable entrypoints

`backend/main.py` is the stable ASGI entrypoint for `uvicorn main:app`. Administrative
script launchers may remain at the backend root when an existing deployment invokes
their file paths. Domain and infrastructure compatibility aliases are not allowed;
production code and tests import canonical package paths directly.
