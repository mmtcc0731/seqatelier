// SeqAtelier Viewer の型定義。
//
// 座標規約: サーバー(server.py)のJSON APIは全て0-based half-open。
// 画面表示（行番号等）のみ1-basedに変換して見せる。

export type Strand = 1 | -1;

export interface FeatureData {
  type: string;
  label: string;
  start: number; // 0-based, inclusive
  end: number; // 0-based, exclusive
  strand: Strand;
  color: string;
  translation: string | null;
  codon_start: number;
  parts: { start: number; end: number; strand: number | null }[];
}

export interface PlasmidData {
  id: string;
  name: string;
  length: number;
  topology: "circular" | "linear";
  sequence: string;
  features: FeatureData[];
  revision: string;
  saved_revision: string;
  // 下書きは再起動後も復元される。保存は確定版を更新する。
  dirty?: boolean;
}

export interface PlasmidSummary {
  id: string;
  name: string;
  kind: string;
  path: string;
  length: number;
  description: string;
  tags: string;
  created: string;
}

export interface TmResult {
  sequence: string;
  length: number;
  tm_celsius: number | null;
  gc_percent: number | null;
  error: string | null;
}

export interface SaveResult {
  plasmid_id: string;
  path: string;
  length: number;
  saved: boolean;
  revision: string;
}

export interface CodonTableEntry {
  codon: string;
  amino_acid: string;
  frequency: number;
}

export interface CodonTableResponse {
  host: string;
  codons: CodonTableEntry[];
}

// 選択範囲: 0-based half-open [start, end)。
export interface Selection {
  start: number;
  end: number;
}
