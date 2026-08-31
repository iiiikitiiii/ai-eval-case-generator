import { api } from "./client";

/** Response contract shared by the case-scoped dynamic Query endpoint. */
export interface DynamicNextTurnResult {
  conversation_id: string;
  round: number;
  messages: string[];
  images: number[];
  done: boolean;
  stop_reason: string | null;
}

export type DynamicConversationStatus =
  | "awaiting_response"
  | "generating"
  | "generation_failed"
  | "completed"
  | "abandoned";

export interface DynamicConversationTurnRecord {
  round: number;
  messages: string[];
  images: number[];
  tested_response: string | null;
  tested_response_image_count: number;
  tested_response_raw_content: string | null;
  created_at: string;
  answered_at: string | null;
}

/** Durable account-owned run used by the page for history switching. */
export interface DynamicConversationRecord {
  conversation_id: string;
  variant_id: string;
  name: string | null;
  status: DynamicConversationStatus;
  current_round: number;
  stop_reason: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  turns: DynamicConversationTurnRecord[];
}

/** Load every test run for the exact query/persona selected by the user. */
export function listDynamicConversations(caseId: string, queryId: string, variantId: string) {
  const params = new URLSearchParams({ variant_id: variantId });
  return api.get<DynamicConversationRecord[]>(
    `/cases/${caseId}/queries/${queryId}/dynamic-conversations?${params.toString()}`,
  );
}

/** Start a distinct run without changing any earlier unfinished test. */
export function startDynamicConversation(caseId: string, queryId: string, variantId: string) {
  return api.post<DynamicConversationRecord>(
    `/cases/${caseId}/queries/${queryId}/dynamic-conversations`,
    { variant_id: variantId },
  );
}

/** Set or clear the current account's display name for one test record. */
export function renameDynamicConversation(
  caseId: string,
  queryId: string,
  conversationId: string,
  name: string | null,
) {
  return api.patch<DynamicConversationRecord>(
    `/cases/${caseId}/queries/${queryId}/dynamic-conversations/${conversationId}`,
    { name },
  );
}

/** Submit one dynamic turn without exposing URLs, tokens or multipart details to pages. */
export function advanceDynamicQuery(
  caseId: string,
  queryId: string,
  variantId: string,
  latestResponse: string | null,
  responseImages: File[],
  conversationId: string,
) {
  const form = new FormData();
  form.append("variant_id", variantId);
  // Web creation has a dedicated endpoint, so advancement always targets one
  // exact persisted run instead of relying on actor/query lookup semantics.
  form.append("conversation_id", conversationId);
  if (latestResponse?.trim()) form.append("latest_response", latestResponse.trim());
  for (const image of responseImages) form.append("response_images", image, image.name);
  return api.postForm<DynamicNextTurnResult>(
    `/cases/${caseId}/queries/${queryId}/next-turn`,
    form,
  );
}
