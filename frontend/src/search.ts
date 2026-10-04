// 配列パターン検索の純粋関数（IUPAC 展開、reverse complement、ミスマッチ ≤ 1、
// 両鎖、上限 200 件切り捨て、circular 対応）。UI・DOM に依存しない。

export const IUPAC_MAP: Readonly<Record<string, string>> = Object.freeze({
  A: "A",
  C: "C",
  G: "G",
  T: "T",
  U: "T",
  R: "AG",
  Y: "CT",
  S: "GC",
  W: "AT",
  K: "GT",
  M: "AC",
  B: "CGT",
  D: "AGT",
  H: "ACT",
  V: "ACG",
  N: "ACGT",
});

const COMPLEMENT: Readonly<Record<string, string>> = Object.freeze({
  A: "T",
  T: "A",
  C: "G",
  G: "C",
  U: "A",
  R: "Y",
  Y: "R",
  S: "S",
  W: "W",
  K: "M",
  M: "K",
  B: "V",
  V: "B",
  D: "H",
  H: "D",
  N: "N",
});

export type Strand = 1 | -1;

export interface SearchMatch {
  start: number;
  end: number;
  strand: Strand;
}

export interface SearchOptions {
  mismatches: 0 | 1;
  bothStrands: boolean;
  topology: "linear" | "circular";
}

export interface SearchResult {
  matches: readonly SearchMatch[];
  truncated: boolean;
  totalScanned: number;
}

// 各鎖ごとに MAX_MATCHES_PER_STRAND 件までを許容する。両鎖検索の場合、
// forward が上限に達しても reverse は独立して同じ上限まで拾える（forward が
// 埋め尽くして reverse が黙って捨てられる、という非対称を避ける）。
export const MAX_MATCHES_PER_STRAND = 500;
// 合算後の総 UI 上限。両鎖検索なら最大 MAX_MATCHES_PER_STRAND × 2。
export const MAX_MATCHES = MAX_MATCHES_PER_STRAND * 2;
// 実用上のパターン長上限。長すぎるパターンでメインスレッドをブロックしないため。
const MAX_PATTERN_LEN = 1000;

export function normalizePattern(pattern: string): string {
  return pattern.toUpperCase().replace(/\s+/g, "");
}

export type ValidationResult = { ok: true } | { ok: false; reason: string };

export function validatePattern(pattern: string): ValidationResult {
  const p = normalizePattern(pattern);
  if (p.length === 0) {
    return { ok: false, reason: "検索パターンを入力してください。" };
  }
  if (p.length > MAX_PATTERN_LEN) {
    return { ok: false, reason: "パターンが長すぎます。" };
  }
  for (let i = 0; i < p.length; i++) {
    const c = p[i];
    if (!(c in IUPAC_MAP)) {
      return { ok: false, reason: `無効な IUPAC 文字: ${c}` };
    }
  }
  return { ok: true };
}

export function reverseComplementIUPAC(pattern: string): string {
  let out = "";
  for (let i = pattern.length - 1; i >= 0; i--) {
    const c = pattern[i];
    const comp = COMPLEMENT[c];
    if (comp === undefined) {
      throw new Error(`reverseComplementIUPAC: unsupported IUPAC code '${c}'`);
    }
    out += comp;
  }
  return out;
}

export function baseMatches(seqBase: string, patternCode: string): boolean {
  // 配列側の N は「どのパターンにも一致しない」（IUPAC で厳密対応）
  if (seqBase === "N") return false;
  const allowed = IUPAC_MAP[patternCode];
  if (allowed === undefined) return false;
  return allowed.includes(seqBase);
}

function scanStrand(
  upperSeq: string,
  pattern: string,
  strand: Strand,
  options: SearchOptions,
  out: SearchMatch[],
  maxCount: number,
): boolean {
  const seqLen = upperSeq.length;
  const patLen = pattern.length;
  if (patLen === 0 || patLen > seqLen) return false;
  const allowedMismatch = options.mismatches;
  const maxStart =
    options.topology === "circular" ? seqLen : seqLen - patLen + 1;
  const startCount = out.length;
  for (let i = 0; i < maxStart; i++) {
    let mismatchCount = 0;
    let ok = true;
    for (let j = 0; j < patLen; j++) {
      const idx = i + j;
      const seqBase = idx < seqLen ? upperSeq[idx] : upperSeq[idx - seqLen];
      if (!baseMatches(seqBase, pattern[j])) {
        mismatchCount++;
        if (mismatchCount > allowedMismatch) {
          ok = false;
          break;
        }
      }
    }
    if (ok) {
      out.push({ start: i, end: i + patLen, strand });
      if (out.length - startCount >= maxCount) return true;
    }
  }
  return false;
}

export function findMatches(
  sequence: string,
  pattern: string,
  options: SearchOptions,
): SearchResult {
  const normalized = normalizePattern(pattern);
  const v = validatePattern(normalized);
  if (!v.ok) throw new Error(v.reason);
  const upperSeq = sequence.toUpperCase();
  if (normalized.length > upperSeq.length) {
    return { matches: [], truncated: false, totalScanned: 0 };
  }
  const matches: SearchMatch[] = [];
  const truncatedForward = scanStrand(
    upperSeq,
    normalized,
    1,
    options,
    matches,
    MAX_MATCHES_PER_STRAND,
  );
  let truncated = truncatedForward;
  if (options.bothStrands) {
    const rc = reverseComplementIUPAC(normalized);
    const truncatedRev = scanStrand(
      upperSeq,
      rc,
      -1,
      options,
      matches,
      MAX_MATCHES_PER_STRAND,
    );
    truncated = truncated || truncatedRev;
  }
  // 位置順にソートして 'Next' が配列上を単調に進むようにする。
  matches.sort((a, b) => a.start - b.start || a.strand - b.strand);
  return { matches, truncated, totalScanned: matches.length };
}
