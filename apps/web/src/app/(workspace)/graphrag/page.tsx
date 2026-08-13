import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/** GraphRAG admin merged into /graph — preserve deep links. */
export default function GraphragRedirectPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const p = new URLSearchParams();
  p.set("view", "graphrag");
  for (const [k, v] of Object.entries(searchParams)) {
    if (k === "view") continue;
    if (Array.isArray(v)) v.forEach((item) => p.append(k, item));
    else if (v) p.set(k, v);
  }
  redirect(`/graph?${p.toString()}`);
}
