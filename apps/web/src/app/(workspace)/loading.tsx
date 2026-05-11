export default function WorkspaceLoading() {
  return (
    <div className="animate-pulse space-y-6 p-8" aria-busy="true" aria-label="Loading">
      <div className="h-10 max-w-xs rounded-md bg-surface-raised" />
      <div className="h-4 max-w-full rounded bg-surface-raised" />
      <div className="h-4 max-w-[90%] rounded bg-surface-raised" />
      <div className="h-4 max-w-[70%] rounded bg-surface-raised" />
    </div>
  );
}
