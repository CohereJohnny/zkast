import { z } from "zod";

export const PIPELINE_DEFAULTS = {
  chunk_size: 512,
  max_notes_per_document: 500,
  language: "en",
  default_llm_provider: "cohere" as const,
  small_model: "command-r7b-12-2024",
  large_model: "command-a-plus-05-2026",
  embed_model: "embed-v4.0",
  rerank_model: "rerank-v4.0-fast",
  include_provenance_subgraph_default: true,
  north_base_url: "",
};

const northBaseUrlSchema = z.union([z.literal(""), z.string().url().max(2048)]);

export const pipelineSettingsSchema = z.object({
  chunk_size: z.number().int().min(128).max(8192),
  max_notes_per_document: z.number().int().min(1).max(100_000),
  language: z.string().min(2).max(16),
  default_llm_provider: z.literal("cohere"),
  small_model: z.string().min(1).max(128),
  large_model: z.string().min(1).max(128),
  embed_model: z.string().min(1).max(128),
  rerank_model: z.string().min(1).max(128),
  include_provenance_subgraph_default: z.boolean(),
  /** North Agents API base URL (https). Empty string = unset. */
  north_base_url: northBaseUrlSchema,
});

export const pipelineSettingsPatchSchema = pipelineSettingsSchema.partial();

export type PipelineSettings = z.infer<typeof pipelineSettingsSchema>;

export function mergePipelineSettings(raw: unknown): PipelineSettings {
  const base = { ...PIPELINE_DEFAULTS };
  if (!raw || typeof raw !== "object") {
    return pipelineSettingsSchema.parse(base);
  }
  const merged = { ...base, ...(raw as Record<string, unknown>) };
  // Never surface legacy plaintext North tokens via Settings GET (FR-30).
  delete (merged as { north_bearer_token?: unknown }).north_bearer_token;
  const parsed = pipelineSettingsSchema.safeParse(merged);
  if (!parsed.success) {
    return pipelineSettingsSchema.parse(base);
  }
  return parsed.data;
}
