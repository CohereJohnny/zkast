import { WikiPanel } from "@/components/wiki-panel";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function WikiPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const workspace = await getCurrentWorkspace();
  const params = (await searchParams) ?? {};
  const rawSpace = params.space_id ?? params.spaceId;
  const rawSlug = params.slug;
  const initialSpaceId = Array.isArray(rawSpace) ? rawSpace[0] : rawSpace;
  const initialSlug = Array.isArray(rawSlug) ? rawSlug[0] : rawSlug;
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <WikiPanel
        workspaceId={workspace.id}
        initialSpaceId={initialSpaceId ?? null}
        initialSlug={initialSlug ?? null}
      />
    </div>
  );
}
