# Shared chat session continuity

Chat and proactive messages always resume the same saved provider session. Waking up no longer clears or rotates that session. Daily persona refresh may update instructions within the existing session.

Startup recovers an unfinished legacy rotation from previous_main_thread_id when the current pointer is absent, then clears start_fresh_thread. An existing current pointer takes precedence. Historical memory provenance is unchanged. Obsolete daily rotation settings are no longer read or written.

Only an installation with no saved or recoverable session creates an initial shared session. Resume failures do not silently replace an existing session.

The backend must restart to load this change.
