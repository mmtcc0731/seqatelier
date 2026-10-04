// fetchラッパー。全て /api 配下を叩く（dev時はvite.config.tsのproxyで
// FastAPI(127.0.0.1:8765)へ転送、build後はFastAPI自身が同一オリジンで
// frontend/distを配信するため、常に相対パスで完結する）。

import type {
  CodonTableResponse,
  PlasmidData,
  PlasmidSummary,
  SaveResult,
  TmResult,
} from "./types";

const BASE = "/api";
import { accessToken } from "./auth";

export function setAccessToken(token: string): void {
  if (token) sessionStorage.setItem("seqatelier.token", token);
  else sessionStorage.removeItem("seqatelier.token");
}

async function headers(): Promise<Record<string, string>> {
  const token = await accessToken();
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: await headers(),
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // レスポンスがJSONでない場合はstatusTextのまま
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function getPlasmids(): Promise<PlasmidSummary[]> {
  return request<PlasmidSummary[]>("/plasmids");
}

export function getPlasmid(id: string): Promise<PlasmidData> {
  return request<PlasmidData>(`/plasmid/${encodeURIComponent(id)}`);
}

export function calcTm(sequence: string): Promise<TmResult> {
  return request<TmResult>("/tm", {
    method: "POST",
    body: JSON.stringify({ sequence }),
  });
}

export function mutateCodon(
  plasmidId: string,
  position: number,
  newCodon: string,
  expectedRevision: string,
): Promise<PlasmidData> {
  return request<PlasmidData>("/mutate", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, position, new_codon: newCodon, expected_revision: expectedRevision }),
  });
}

export function savePlasmid(plasmidId: string, expectedRevision: string): Promise<SaveResult> {
  return request<SaveResult>("/save", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, expected_revision: expectedRevision }),
  });
}

export function reloadPlasmid(plasmidId: string, expectedRevision: string): Promise<PlasmidData> {
  return request<PlasmidData>("/reload", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, expected_revision: expectedRevision }),
  });
}

export function getHosts(): Promise<string[]> {
  return request<string[]>("/hosts");
}

export function getCodonTable(host: string): Promise<CodonTableResponse> {
  return request<CodonTableResponse>(`/codon-table?host=${encodeURIComponent(host)}`);
}

export interface FeatureInput {
  type: string;
  label: string;
  start: number;
  end: number;
  strand: 1 | -1;
}

export function addFeature(plasmidId: string, feature: FeatureInput, expectedRevision: string): Promise<PlasmidData> {
  return request<PlasmidData>("/annotate", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, action: "add", feature, expected_revision: expectedRevision }),
  });
}

export function deleteFeature(plasmidId: string, index: number, expectedRevision: string): Promise<PlasmidData> {
  return request<PlasmidData>("/annotate", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, action: "delete", index, expected_revision: expectedRevision }),
  });
}

export function updateFeature(
  plasmidId: string,
  index: number,
  feature: FeatureInput,
  expectedRevision: string,
): Promise<PlasmidData> {
  return request<PlasmidData>("/annotate", {
    method: "POST",
    body: JSON.stringify({ plasmid_id: plasmidId, action: "update", index, feature, expected_revision: expectedRevision }),
  });
}

export interface TranslateResult {
  protein: string;
  length_aa: number;
  length_nt: number;
  strand: 1 | -1;
  has_stop: boolean;
  warning?: string;
}

export function translateSequence(
  sequence: string,
  strand: 1 | -1 = 1,
): Promise<TranslateResult> {
  return request<TranslateResult>("/translate", {
    method: "POST",
    body: JSON.stringify({ sequence, strand }),
  });
}

export interface Revision {
  revision: string;
  created: string;
  message: string;
  saved: number;
}

export function getHistory(id: string): Promise<Revision[]> {
  return request(`/plasmid/${encodeURIComponent(id)}/history`);
}

export function restoreRevision(data: PlasmidData, revision: string): Promise<PlasmidData> {
  return request("/restore", { method: "POST", body: JSON.stringify({
    plasmid_id: data.id, expected_revision: data.revision, revision,
  }) });
}

export function importGenBank(genbank: string): Promise<PlasmidData> {
  return request("/import", { method: "POST", body: JSON.stringify({ genbank }) });
}

export async function downloadGenBank(id: string): Promise<void> {
  const response = await fetch(`${BASE}/plasmid/${encodeURIComponent(id)}/genbank`, { headers: await headers() });
  if (!response.ok) throw new Error(`Export failed: ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `${id}.gb`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
