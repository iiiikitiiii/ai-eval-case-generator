import { api } from "./client";

export interface AuditLogOut {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string;
}

export function getAuditLog(params: { action_prefix?: string; entity_type?: string; limit?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.action_prefix) qs.set("action_prefix", params.action_prefix);
  if (params.entity_type) qs.set("entity_type", params.entity_type);
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return api.get<AuditLogOut[]>(`/settings/audit-log${suffix}`);
}
