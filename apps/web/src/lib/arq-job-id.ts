/** Parse arq ``in-progress`` suffixes into pipeline job ids (``graphrag:{uuid}``, ``{id}:graph``, …). */
const ARQ_FUNCTION_SUFFIXES = [
  ":run_graphrag_index_job",
  ":generate_atomic_notes",
  ":extract_graph",
  ":parse_document",
  ":slack_import",
  ":parse",
  ":notes",
  ":graph",
] as const;

export function arqEntryJobId(entry: string): string {
  if (entry.startsWith("cron:")) return entry;
  for (const suffix of ARQ_FUNCTION_SUFFIXES) {
    if (entry.endsWith(suffix)) return entry.slice(0, -suffix.length);
  }
  return entry;
}

export function isGraphExtractionJobId(jobId: string): boolean {
  return (
    jobId.endsWith(":graph") ||
    jobId.startsWith("graphrag:") ||
    jobId.includes(":extract_graph")
  );
}
