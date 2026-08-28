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

/** Submit one dynamic turn without exposing URLs, tokens or multipart details to pages. */
export function advanceDynamicQuery(
  caseId: string,
  queryId: string,
  variantId: string,
  latestResponse: string | null,
  responseImages: File[],
) {
  const form = new FormData();
  form.append("variant_id", variantId);
  if (latestResponse?.trim()) form.append("latest_response", latestResponse.trim());
  for (const image of responseImages) form.append("response_images", image, image.name);
  return api.postForm<DynamicNextTurnResult>(
    `/cases/${caseId}/queries/${queryId}/next-turn`,
    form,
  );
}
