// 配列行のレイアウト計算。等幅フォント前提で、1文字=1ch。
//
// 配列は`GROUP_SIZE`塩基ごとにスペースで区切って表示する。feature バー・
// 翻訳行は個々の塩基spanを使わず、CSSの`ch`単位で絶対配置することで
// DOMノード数を抑える（大きいプラスミドでもfeature数×行数程度で済む）。
// `baseColumn`はその配置計算の唯一の正本。

export const GROUP_SIZE = 10;

/** 行内ローカル塩基インデックス(0-based)を、区切りスペースを考慮した表示上の列番号に変換する。 */
export function baseColumn(localIndex: number, groupSize: number = GROUP_SIZE): number {
  return localIndex + Math.floor(localIndex / groupSize);
}

export interface LineInfo {
  index: number;
  startPos: number; // 0-based, グローバル
  endPos: number; // 0-based, グローバル、exclusive
  bases: string;
}

export function buildLines(sequence: string, lineWidth: number): LineInfo[] {
  const lines: LineInfo[] = [];
  for (let start = 0; start < sequence.length; start += lineWidth) {
    const end = Math.min(start + lineWidth, sequence.length);
    lines.push({ index: lines.length, startPos: start, endPos: end, bases: sequence.slice(start, end) });
  }
  if (lines.length === 0) {
    lines.push({ index: 0, startPos: 0, endPos: 0, bases: "" });
  }
  return lines;
}

/** 行内で区切りスペースも含めた総表示幅（ch単位）。 */
export function lineDisplayWidth(lineLength: number): number {
  if (lineLength <= 0) return 0;
  return baseColumn(lineLength - 1) + 1;
}
