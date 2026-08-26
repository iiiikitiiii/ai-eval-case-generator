import { api } from "./client";

export interface LlmProviderOut {
  provider: string;
  options: string[];
}

export function getLlmProvider() {
  return api.get<LlmProviderOut>("/settings/llm-provider");
}

export function setLlmProvider(provider: string) {
  return api.put<LlmProviderOut>("/settings/llm-provider", { provider });
}
