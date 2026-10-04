// 座標変換の唯一の正本。1-based 入力/表示 と 0-based half-open 内部座標
// の相互変換ユーティリティ。Goto パース・表示用フォーマット・範囲妥当性判定。

export type ParsedGoto =
  | { kind: "point"; pos0: number }
  | { kind: "range"; start0: number; end0: number };

export type ParseResult =
  | { ok: true; value: ParsedGoto }
  | { ok: false; reason: string };

export function toOneBased(pos0: number): number {
  return pos0 + 1;
}

export function fromOneBased(pos1: number): number {
  return pos1 - 1;
}

export function parseGoto(input: string, seqLen: number): ParseResult {
  const raw = input.normalize("NFKC").trim();
  if (raw.length === 0) {
    return { ok: false, reason: "値を入力してください。" };
  }
  const parts = raw.split("..");
  if (parts.length === 1) {
    const s = parts[0].trim();
    if (!/^\d+$/.test(s)) {
      return {
        ok: false,
        reason: "数字または A..B 形式で入力してください。",
      };
    }
    const pos1 = parseInt(s, 10);
    if (pos1 < 1 || pos1 > seqLen) {
      return {
        ok: false,
        reason: `1〜${seqLen} の範囲で入力してください。`,
      };
    }
    return { ok: true, value: { kind: "point", pos0: pos1 - 1 } };
  }
  if (parts.length !== 2) {
    return {
      ok: false,
      reason: "数字または A..B 形式で入力してください。",
    };
  }
  const aStr = parts[0].trim();
  const bStr = parts[1].trim();
  if (!/^\d+$/.test(aStr) || !/^\d+$/.test(bStr)) {
    return {
      ok: false,
      reason: "数字または A..B 形式で入力してください。",
    };
  }
  let a = parseInt(aStr, 10);
  let b = parseInt(bStr, 10);
  if (a > b) {
    const tmp = a;
    a = b;
    b = tmp;
  }
  if (a < 1 || b > seqLen) {
    return {
      ok: false,
      reason: `1〜${seqLen} の範囲で入力してください。`,
    };
  }
  const start0 = a - 1;
  const end0 = b;
  if (end0 <= start0) {
    return { ok: false, reason: "範囲が不正です。" };
  }
  return { ok: true, value: { kind: "range", start0, end0 } };
}

export function formatRange0(start0: number, end0: number): string {
  return `${start0 + 1}..${end0}`;
}

export function formatPoint0(pos0: number): string {
  return `${pos0 + 1}`;
}
