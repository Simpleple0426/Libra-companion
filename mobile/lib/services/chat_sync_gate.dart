/// History establishes the cursor before any incremental request is allowed.
class ChatSyncGate {
  bool ready = false;
  bool loading = false;
  int revision = 0;
  DateTime? retryAfter;

  bool beginHistory(DateTime now) {
    if (loading || (retryAfter != null && now.isBefore(retryAfter!))) {
      return false;
    }
    loading = true;
    ready = false;
    revision++;
    return true;
  }

  void finishHistory({required bool success, required DateTime now}) {
    loading = false;
    ready = success;
    retryAfter = success ? null : now.add(const Duration(seconds: 10));
  }

  bool acceptsUpdates(int requestRevision) =>
      ready && !loading && requestRevision == revision;
}
