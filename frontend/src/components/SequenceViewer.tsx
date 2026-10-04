import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";
import type { FeatureData, PlasmidData, Selection } from "../types";
import { GROUP_SIZE, buildLines } from "../layout";
import type { LineInfo } from "../layout";
import type { SearchMatch } from "../search";

type MatchRange = readonly [number, number, boolean];
const EMPTY_LOCAL_MATCHES: readonly MatchRange[] = [];
const EMPTY_MATCHES_DEFAULT: readonly SearchMatch[] = [];

/**
 * 行内の各塩基位置に、どの feature が重なっているかを計算する。
 * 複数 feature が重なる場合は、feature ごとに独立した行（track）に分ける。
 */
interface FeatureTrack {
  feature: FeatureData;
  localStart: number;
  localEnd: number;
}

function computeFeatureTracks(
  features: PlasmidData["features"],
  line: LineInfo,
): FeatureTrack[][] {
  const overlapping: FeatureTrack[] = [];
  for (const feature of features) {
    for (const part of feature.parts ?? [feature]) {
    if (part.start < line.endPos && part.end > line.startPos) {
      overlapping.push({
        feature,
        localStart: Math.max(part.start, line.startPos) - line.startPos,
        localEnd: Math.min(part.end, line.endPos) - line.startPos,
      });
    }
    }
  }

  // Greedy interval packing into non-overlapping tracks
  const tracks: FeatureTrack[][] = [];
  const trackEnds: number[] = [];
  for (const seg of overlapping) {
    let placed = false;
    for (let t = 0; t < tracks.length; t++) {
      if (trackEnds[t] <= seg.localStart) {
        tracks[t].push(seg);
        trackEnds[t] = seg.localEnd;
        placed = true;
        break;
      }
    }
    if (!placed) {
      tracks.push([seg]);
      trackEnds.push(seg.localEnd);
    }
  }
  return tracks;
}

/**
 * CDS feature の翻訳を行内の塩基位置にマップする。
 * コドンの先頭塩基の位置にアミノ酸文字を配置する。
 */
function computeTranslationLine(
  features: PlasmidData["features"],
  line: LineInfo,
  totalLength: number,
): Map<number, { aa: string; color: string; codonStart: number }> {
  const marks = new Map<
    number,
    { aa: string; color: string; codonStart: number }
  >();
  for (const feature of features) {
    if (feature.type !== "CDS" || !feature.translation) continue;
    // Joined CDS remains available as metadata; do not place amino acids over introns.
    if (feature.parts?.length > 1) continue;
    if (feature.start >= line.endPos || feature.end <= line.startPos) continue;

    const codonCount = Math.min(
      Math.floor((feature.end - feature.start) / 3),
      feature.translation.length,
    );
    for (let k = 0; k < codonCount; k++) {
      let codonStart: number;
      if (feature.strand === -1) {
        codonStart = feature.end - (feature.codon_start - 1) - (k + 1) * 3;
      } else {
        codonStart = feature.start + (feature.codon_start - 1) + k * 3;
      }
      if (codonStart < 0 || codonStart + 2 >= totalLength) continue;
      // コドンの真ん中（2番目の塩基）に AA 文字を配置する。
      // クリック時のコドン範囲選択は元の codonStart を使う。
      const middleGlobal = codonStart + 1;
      const localIdx = middleGlobal - line.startPos;
      if (localIdx >= 0 && localIdx < line.bases.length) {
        marks.set(localIdx, {
          aa: feature.translation[k],
          color: feature.color,
          codonStart,
        });
      }
    }
  }
  return marks;
}

// --------------------------------------------------------------------------
// アミノ酸の残基別カラーリング
// --------------------------------------------------------------------------

/** 化学性質ベースの残基スタイル。
 * 1文字幅の狭い pill 表示を目立たせるため、背景は full opacity、
 * テキスト色は背景明度に応じて白/黒を切り替える（yellow/orange/grey/histidine の
 * ような明るい bg では黒テキストの方がコントラストが取れる）。 */
type AaStyle = { bg: string; fg: string };

const AA_STYLES: Record<string, AaStyle> = {
  // 酸性（負電荷）: 赤
  D: { bg: "#E74C3C", fg: "#fff" },
  E: { bg: "#E74C3C", fg: "#fff" },
  // 塩基性（正電荷）: 青
  K: { bg: "#2980B9", fg: "#fff" },
  R: { bg: "#2980B9", fg: "#fff" },
  H: { bg: "#5DADE2", fg: "#0a0a0f" },
  // 極性（無電荷）: 緑
  S: { bg: "#27AE60", fg: "#fff" },
  T: { bg: "#27AE60", fg: "#fff" },
  N: { bg: "#27AE60", fg: "#fff" },
  Q: { bg: "#27AE60", fg: "#fff" },
  // 芳香族: 紫
  F: { bg: "#8E44AD", fg: "#fff" },
  Y: { bg: "#8E44AD", fg: "#fff" },
  W: { bg: "#8E44AD", fg: "#fff" },
  // 疎水（脂肪族）: 橙
  A: { bg: "#F39C12", fg: "#0a0a0f" },
  V: { bg: "#F39C12", fg: "#0a0a0f" },
  I: { bg: "#F39C12", fg: "#0a0a0f" },
  L: { bg: "#F39C12", fg: "#0a0a0f" },
  M: { bg: "#F39C12", fg: "#0a0a0f" },
  // システイン: 黄
  C: { bg: "#F1C40F", fg: "#0a0a0f" },
  // グリシン: 灰
  G: { bg: "#BDC3C7", fg: "#0a0a0f" },
  // プロリン: 桃
  P: { bg: "#E91E63", fg: "#fff" },
  // 終止: 濃灰
  "*": { bg: "#34495E", fg: "#fff" },
};
const AA_UNKNOWN_STYLE: AaStyle = { bg: "#7F8C8D", fg: "#fff" };

function aaStyle(aa: string): AaStyle {
  return AA_STYLES[aa.toUpperCase()] ?? AA_UNKNOWN_STYLE;
}

// --------------------------------------------------------------------------
// AA残基番号ルーラー（翻訳行の直上、10残基ごとに残基番号を表示）
// --------------------------------------------------------------------------

const AA_RULER_INTERVAL = 10;

/** CDS feature の残基番号を、対応するコドン先頭の 0-based bp カラムに右揃えで
 * 埋め込む。数字の最終桁が該当bpに来る（例: 残基#10 のコドン先頭が bp X のとき、
 * chars[X-lineStartPos] = '0', chars[X-lineStartPos-1] = '1'）。 */
function buildAaRulerChars(
  features: PlasmidData["features"],
  line: LineInfo,
  totalLength: number,
): string[] {
  const chars = Array(line.bases.length).fill(" ");
  for (const feature of features) {
    if (feature.type !== "CDS" || !feature.translation) continue;
    if (feature.start >= line.endPos || feature.end <= line.startPos) continue;

    const codonCount = Math.min(
      Math.floor((feature.end - feature.start) / 3),
      feature.translation.length,
    );

    for (let k = 0; k < codonCount; k++) {
      const residueNum = k + 1;
      if (residueNum % AA_RULER_INTERVAL !== 0) continue;

      let codonStart: number;
      if (feature.strand === -1) {
        codonStart = feature.end - (k + 1) * 3;
      } else {
        codonStart = feature.start + k * 3;
      }
      if (codonStart < 0 || codonStart + 2 >= totalLength) continue;

      // AA 番号の右端は、AA 文字と同じ「コドンの真ん中」に置く。
      const endIdx = codonStart + 1 - line.startPos;
      if (endIdx < 0 || endIdx >= line.bases.length) continue;

      const label = String(residueNum);
      const startIdx = endIdx - label.length + 1;
      if (startIdx < 0) continue;

      // 隣接ラベルとの衝突を回避
      let clash = false;
      for (let i = startIdx; i <= endIdx; i++) {
        if (chars[i] !== " ") {
          clash = true;
          break;
        }
      }
      if (clash) continue;

      for (let i = 0; i < label.length; i++) {
        chars[startIdx + i] = label[i];
      }
    }
  }
  return chars;
}

function renderAaRulerLine(
  features: PlasmidData["features"],
  line: LineInfo,
  totalLength: number,
  showGrouping: boolean,
): ReactNode | null {
  const chars = buildAaRulerChars(features, line, totalLength);
  const hasAny = chars.some((c) => c !== " ");
  if (!hasAny) return null;

  const out: string[] = [];
  for (let i = 0; i < line.bases.length; i++) {
    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      out.push(" ");
    }
    out.push(chars[i]);
  }
  return <div className="text-track aa-ruler-track">{out.join("")}</div>;
}

// --------------------------------------------------------------------------
// Feature bar line — text-based rendering (no absolute positioning)
// --------------------------------------------------------------------------

/** セグメント範囲を、矢印文字とラベル文字を混在させた形で `chars` に書き込み、
 * ラベル位置を `isLabel` に記録する。
 *
 * ラベルは feature の bar 内にセンター配置で埋め込まれ、両側を矢印で挟む形になる:
 *   width=20, label="SIDT2"  → "  >>>>>>SIDT2>>>>>>>"
 *
 * ラベルが bar 幅に収まらない場合は末尾 `…` で切り詰め、極端に狭い場合（4文字未満）は
 * 矢印のみ表示する（ホバー tooltip で完全名を確認できる）。矢印方向は strand に従う。
 *
 * `isLabel` は、その位置が「ラベル文字（矢印ではなく）」かどうかを表し、
 * 描画時にラベル文字だけをピル背景付きの span に分けるために使う。 */
function fillSegmentChars(
  seg: FeatureTrack,
  chars: string[],
  isLabel: boolean[],
): void {
  const width = seg.localEnd - seg.localStart;
  if (width <= 0) return;

  const label = seg.feature.label;
  const arrow = seg.feature.strand === -1 ? "<" : ">";

  // 一旦 seg 範囲を矢印で埋める
  for (let i = seg.localStart; i < seg.localEnd; i++) {
    chars[i] = arrow;
  }

  // ラベルが幅に収まるなら中央配置で上書き
  if (label.length <= width) {
    const padTotal = width - label.length;
    const leftPad = Math.floor(padTotal / 2);
    const labelStart = seg.localStart + leftPad;
    for (let i = 0; i < label.length; i++) {
      chars[labelStart + i] = label[i];
      isLabel[labelStart + i] = true;
    }
    return;
  }

  // ラベルが幅を超える: 幅4以上なら省略記号付きで切り詰める
  if (width >= 4) {
    const truncated = label.slice(0, width - 1) + "…";
    for (let i = 0; i < truncated.length; i++) {
      chars[seg.localStart + i] = truncated[i];
      isLabel[seg.localStart + i] = true;
    }
    return;
  }

  // 幅3以下: 矢印のみ（ラベルは tooltip で確認）
}

function findSegAtPosition(
  track: FeatureTrack[],
  pos: number,
): FeatureTrack | null {
  for (const seg of track) {
    if (seg.localStart <= pos && pos < seg.localEnd) return seg;
  }
  return null;
}

function renderFeatureBarLine(
  track: FeatureTrack[],
  lineLength: number,
  showGrouping: boolean,
  onSelectFeature: (f: FeatureData) => void,
): ReactNode {
  // ラベルを埋め込みつつ矢印で塗る
  const chars: string[] = Array(lineLength).fill(" ");
  const isLabel: boolean[] = Array(lineLength).fill(false);
  for (const seg of track) {
    fillSegmentChars(seg, chars, isLabel);
  }

  // 各文字位置について「現在の seg」と「ラベル文字か否か」を判定し、
  // 変化するたびに flushBuffer して別 span を切る。これによりラベル部分だけ
  // ピル背景付きの span として着色できる（矢印部分は plain colored text）。
  // seg → seg（同トラックで別 feature に切り替わる境目）の場合、新 span の
  // 左端に boundary-left クラスを付け、CSS で背景色を透かせて境目を可視化する。
  const spans: ReactNode[] = [];
  let activeSeg: FeatureTrack | null = null;
  let activeIsLabel = false;
  let buffer: string[] = [];
  let boundaryLeftPending = false;

  function flushBuffer() {
    if (buffer.length === 0) return;
    const text = buffer.join("");
    if (activeSeg) {
      const f = activeSeg.feature;
      const boundaryCls = boundaryLeftPending ? " feat-boundary-left" : "";
      if (activeIsLabel) {
        spans.push(
          <span
            key={`l${spans.length}`}
            className={"feat-label-pill" + boundaryCls}
            style={{
              backgroundColor: `${f.color}55`,
              color: "var(--text)",
            }}
            title={`${f.label} (${f.type}) ${f.start + 1}-${f.end}`}
            onClick={() => onSelectFeature(f)}
          >
            {text}
          </span>,
        );
      } else {
        spans.push(
          <span
            key={`a${spans.length}`}
            className={"feat-arrow" + boundaryCls}
            style={{ color: f.color }}
            title={`${f.label} (${f.type}) ${f.start + 1}-${f.end}`}
            onClick={() => onSelectFeature(f)}
          >
            {text}
          </span>,
        );
      }
    } else {
      spans.push(<span key={`s${spans.length}`}>{text}</span>);
    }
    buffer = [];
    boundaryLeftPending = false;
  }

  for (let i = 0; i < lineLength; i++) {
    const currentSeg = findSegAtPosition(track, i);
    const currentIsLabel = currentSeg ? isLabel[i] : false;

    if (currentSeg !== activeSeg || currentIsLabel !== activeIsLabel) {
      const prevSeg = activeSeg;
      flushBuffer();
      activeSeg = currentSeg;
      activeIsLabel = currentIsLabel;
      // 同トラックで隣接する feature 同士（両方非 null かつ別 feature）の
      // 境目のみ boundary マーカーを付ける。segment 内での label ↔ arrow 遷移、
      // seg → 非 seg（feature の終わり）、非 seg → seg（gap 後の feature 開始）
      // では境目を描かない（それぞれ視覚的に既に区別されるため）。
      if (prevSeg && currentSeg && prevSeg !== currentSeg) {
        boundaryLeftPending = true;
      }
    }

    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      buffer.push(" ");
    }
    buffer.push(chars[i]);
  }
  flushBuffer();

  return <div className="text-track feat-track">{spans}</div>;
}

// --------------------------------------------------------------------------
// Ruler line — 20塩基ごとの位置番号を右揃えで表示する
// --------------------------------------------------------------------------

const RULER_TICK_EVERY = 20;

/** 行の bp 番号を、対応する 0-based 塩基位置に右揃えで配置した文字列を作る。
 * 数字の最終桁が該当塩基のカラムに来る（例: bp=20 なら chars[19]='0', chars[18]='2'）。
 * 3桁以上の数字は左方向に伸び、直前のマークと衝突するようなら描画をスキップする。 */
function buildRulerChars(lineStartPos: number, lineLength: number): string[] {
  const chars = Array(lineLength).fill(" ");
  const firstBp = lineStartPos + 1;
  const lastBp = lineStartPos + lineLength;
  const firstTick =
    Math.ceil(firstBp / RULER_TICK_EVERY) * RULER_TICK_EVERY;
  for (let tick = firstTick; tick <= lastBp; tick += RULER_TICK_EVERY) {
    const label = String(tick);
    // 番号の視覚中心（奇数桁は中央文字、偶数桁は文字間ギャップ）が tick に
    // 最も近づく位置に配置する。偶数桁の場合は tick の右へ 0.5 コラム分ずれる。
    const tickCol = tick - lineStartPos - 1;
    const startIdx = tickCol - Math.floor((label.length - 1) / 2);
    const endIdx = startIdx + label.length - 1;
    if (startIdx < 0 || endIdx >= lineLength) continue;
    // 隣接ラベルとの衝突を避ける（極端に大きな bp 番号でのみ発生する保険）。
    let clash = false;
    for (let i = startIdx; i <= endIdx; i++) {
      if (chars[i] !== " ") {
        clash = true;
        break;
      }
    }
    if (clash) continue;
    for (let i = 0; i < label.length; i++) {
      chars[startIdx + i] = label[i];
    }
  }
  return chars;
}

function renderRulerLine(
  lineStartPos: number,
  lineLength: number,
  showGrouping: boolean,
): ReactNode {
  const chars = buildRulerChars(lineStartPos, lineLength);
  const out: string[] = [];
  for (let i = 0; i < lineLength; i++) {
    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      out.push(" ");
    }
    out.push(chars[i]);
  }
  return <div className="text-track ruler-track">{out.join("")}</div>;
}

/** ルーラー数字の直下に描画する横罫線 + 20塩基ごとのティック `┬`。
 * 罫線は showGrouping 時のスペーサー位置にも `─` を入れて連続させ、
 * 実質的に上下行の区切り線として機能する。 */
function buildRulerTickChars(
  lineStartPos: number,
  lineLength: number,
): string[] {
  const chars: string[] = Array(lineLength).fill("─");
  const firstBp = lineStartPos + 1;
  const lastBp = lineStartPos + lineLength;
  const firstTick =
    Math.ceil(firstBp / RULER_TICK_EVERY) * RULER_TICK_EVERY;
  for (let tick = firstTick; tick <= lastBp; tick += RULER_TICK_EVERY) {
    const idx = tick - lineStartPos - 1;
    if (idx >= 0 && idx < lineLength) {
      chars[idx] = "┬";
    }
  }
  return chars;
}

function renderRulerTickLine(
  lineStartPos: number,
  lineLength: number,
  showGrouping: boolean,
): ReactNode {
  const chars = buildRulerTickChars(lineStartPos, lineLength);
  const out: string[] = [];
  for (let i = 0; i < lineLength; i++) {
    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      // グループスペーサー位置も罫線を継続させ、行区切り線として連続感を出す
      out.push("─");
    }
    out.push(chars[i]);
  }
  return <div className="text-track ruler-tick-track">{out.join("")}</div>;
}

// --------------------------------------------------------------------------
// Translation line — text-based rendering
// --------------------------------------------------------------------------

function renderTranslationLine(
  marks: Map<number, { aa: string; color: string; codonStart: number }>,
  lineLength: number,
  showGrouping: boolean,
  onCodonClick: (globalStart: number) => void,
): ReactNode | null {
  if (marks.size === 0) return null;

  const spans: ReactNode[] = [];

  for (let i = 0; i < lineLength; i++) {
    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      spans.push(<span key={`sp${i}`}> </span>);
    }
    const mark = marks.get(i);
    if (mark) {
      const { bg, fg } = aaStyle(mark.aa);
      spans.push(
        <span
          key={`aa${i}`}
          className="aa-char"
          style={{ backgroundColor: bg, color: fg }}
          onClick={() => onCodonClick(mark.codonStart)}
        >
          {mark.aa}
        </span>
      );
    } else {
      spans.push(<span key={`e${i}`}> </span>);
    }
  }

  return <div className="text-track trans-track">{spans}</div>;
}

// --------------------------------------------------------------------------
// LineRow
// --------------------------------------------------------------------------

interface LineRowProps {
  line: LineInfo;
  features: PlasmidData["features"];
  totalLength: number;
  localSelStart: number | null;
  localSelEnd: number | null;
  matchRanges: readonly MatchRange[];
  showGrouping: boolean;
  onBaseMouseDown: (globalPos: number, shiftKey: boolean) => void;
  onBaseMouseEnter: (globalPos: number) => void;
  onSelectFeature: (feature: FeatureData) => void;
  onCodonClick: (globalStart: number) => void;
}

const LineRow = memo(function LineRow({
  line,
  features,
  totalLength,
  localSelStart,
  localSelEnd,
  matchRanges,
  showGrouping,
  onBaseMouseDown,
  onBaseMouseEnter,
  onSelectFeature,
  onCodonClick,
}: LineRowProps) {
  // Sequence line with clickable bases
  const baseSpans: ReactNode[] = [];
  for (let i = 0; i < line.bases.length; i++) {
    const globalPos = line.startPos + i;
    const selected =
      localSelStart !== null &&
      localSelEnd !== null &&
      i >= localSelStart &&
      i < localSelEnd;

    let inMatch = false;
    let isCurrent = false;
    if (matchRanges.length > 0) {
      for (const [ms, me, cur] of matchRanges) {
        if (i >= ms && i < me) {
          inMatch = true;
          if (cur) {
            isCurrent = true;
            break;
          }
        }
      }
    }

    if (showGrouping && i > 0 && i % GROUP_SIZE === 0) {
      baseSpans.push(<span key={`s${i}`} className="base-spacer"> </span>);
    }

    const cls = ["base"];
    if (inMatch) cls.push("search-match");
    if (isCurrent) cls.push("current");
    if (selected) cls.push("selected");

    baseSpans.push(
      <span
        key={`b${i}`}
        className={cls.join(" ")}
        onMouseDown={(e) => {
          e.preventDefault();
          onBaseMouseDown(globalPos, e.shiftKey);
        }}
        onMouseEnter={() => onBaseMouseEnter(globalPos)}
      >
        {line.bases[i]}
      </span>,
    );
  }

  // Feature tracks
  const tracks = useMemo(
    () => computeFeatureTracks(features, line),
    [features, line],
  );

  // Translation marks
  const translationMarks = useMemo(
    () => computeTranslationLine(features, line, totalLength),
    [features, line, totalLength],
  );

  // 選択範囲の領域オーバーレイ位置（全トラックにまたがるハイライト矩形）。
  // GROUP_SIZE スペーサーを visual col に足し込むことで、DNA 行の各列位置と
  // 完全に一致した左右位置を得る。GROUP_SIZE 境界を跨ぐ選択はスペーサーも
  // 覆う 1 つの連続矩形として描画する。
  const overlayCh = useMemo(() => {
    if (
      localSelStart === null ||
      localSelEnd === null ||
      localSelStart >= localSelEnd
    ) {
      return null;
    }
    const spacersBeforeFirst = showGrouping
      ? Math.floor(localSelStart / GROUP_SIZE)
      : 0;
    const visualStart = localSelStart + spacersBeforeFirst;
    const lastPos = localSelEnd - 1;
    const spacersBeforeLast = showGrouping
      ? Math.floor(lastPos / GROUP_SIZE)
      : 0;
    const visualLastEndExclusive = lastPos + spacersBeforeLast + 1;
    return {
      start: visualStart,
      width: Math.max(1, visualLastEndExclusive - visualStart),
    };
  }, [localSelStart, localSelEnd, showGrouping]);

  return (
    <div className="seq-line">
      <div className="line-number">{line.startPos + 1}</div>
      <div className="seq-tracks">
        {renderRulerTickLine(line.startPos, line.bases.length, showGrouping)}
        {renderRulerLine(line.startPos, line.bases.length, showGrouping)}
        <div className="text-track seq-row">{baseSpans}</div>
        {tracks.map((track, ti) => (
          <div key={`track${ti}`}>
            {renderFeatureBarLine(track, line.bases.length, showGrouping, onSelectFeature)}
          </div>
        ))}
        {renderAaRulerLine(features, line, totalLength, showGrouping)}
        {renderTranslationLine(translationMarks, line.bases.length, showGrouping, onCodonClick)}
        {overlayCh && (
          <div
            className="selection-overlay"
            style={{
              left: `${overlayCh.start}ch`,
              width: `${overlayCh.width}ch`,
            }}
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  );
});

// --------------------------------------------------------------------------
// SequenceViewer
// --------------------------------------------------------------------------

interface SequenceViewerProps {
  data: PlasmidData;
  selection: Selection | null;
  onSelectionChange: (sel: Selection | null) => void;
  onSelectFeature: (feature: FeatureData) => void;
  lineWidth?: number;
  matches?: readonly SearchMatch[];
  currentMatchIdx?: number;
  showGrouping?: boolean;
}

export function SequenceViewer({
  data,
  selection,
  onSelectionChange,
  onSelectFeature,
  lineWidth = 60,
  matches = EMPTY_MATCHES_DEFAULT,
  currentMatchIdx = -1,
  showGrouping = true,
}: SequenceViewerProps) {
  const lines = useMemo(
    () => buildLines(data.sequence, lineWidth),
    [data.sequence, lineWidth],
  );

  const anchorRef = useRef<number | null>(null);
  const draggingRef = useRef(false);

  // selection prop の外部変更（Goto ジャンプ、検索 next、Feature クリック、
  // プラスミド切替）で anchor を同期する。これを怠ると、外部ジャンプ後の
  // shift+click が古い anchor から巨大な範囲を選択してしまう。ドラッグ中は
  // ユーザーが動かしている anchor を尊重するので同期しない。
  useEffect(() => {
    if (draggingRef.current) return;
    anchorRef.current = selection ? selection.start : null;
  }, [selection]);

  const handleCodonClick = useCallback(
    (globalStart: number) => {
      onSelectionChange({ start: globalStart, end: globalStart + 3 });
      anchorRef.current = globalStart;
    },
    [onSelectionChange],
  );

  const handleBaseMouseDown = useCallback(
    (globalPos: number, shiftKey: boolean) => {
      if (shiftKey && anchorRef.current !== null) {
        const anchor = anchorRef.current;
        onSelectionChange({
          start: Math.min(anchor, globalPos),
          end: Math.max(anchor, globalPos) + 1,
        });
        draggingRef.current = true;
        return;
      }
      anchorRef.current = globalPos;
      draggingRef.current = true;
      onSelectionChange({ start: globalPos, end: globalPos + 1 });
    },
    [onSelectionChange],
  );

  const handleBaseMouseEnter = useCallback(
    (globalPos: number) => {
      if (!draggingRef.current || anchorRef.current === null) return;
      const anchor = anchorRef.current;
      onSelectionChange({
        start: Math.min(anchor, globalPos),
        end: Math.max(anchor, globalPos) + 1,
      });
    },
    [onSelectionChange],
  );

  useEffect(() => {
    function handleMouseUp() {
      draggingRef.current = false;
    }
    document.addEventListener("mouseup", handleMouseUp);
    return () => document.removeEventListener("mouseup", handleMouseUp);
  }, []);

  const selectionByLine = useMemo(() => {
    return lines.map(
      (line): readonly [number | null, number | null] => {
        if (!selection) return [null, null];
        const s = Math.max(selection.start, line.startPos);
        const e = Math.min(selection.end, line.endPos);
        if (s >= e) return [null, null];
        return [s - line.startPos, e - line.startPos];
      },
    );
  }, [lines, selection]);

  const matchesByLine = useMemo(() => {
    const src = matches;
    const totalLen = data.length;
    return lines.map((line): readonly MatchRange[] => {
      const local: MatchRange[] = [];
      for (let mi = 0; mi < src.length; mi++) {
        const m = src[mi];
        const segments: Array<[number, number]> = [];
        if (m.end <= totalLen) {
          segments.push([m.start, m.end]);
        } else {
          segments.push([m.start, totalLen]);
          segments.push([0, m.end - totalLen]);
        }
        for (const [gs, ge] of segments) {
          const s = Math.max(gs, line.startPos);
          const e = Math.min(ge, line.endPos);
          if (s < e) {
            local.push([
              s - line.startPos,
              e - line.startPos,
              mi === currentMatchIdx,
            ] as const);
          }
        }
      }
      return local.length === 0 ? EMPTY_LOCAL_MATCHES : local;
    });
  }, [lines, matches, currentMatchIdx, data.length]);

  return (
    <div className="sequence-viewer">
      {lines.map((line, i) => (
        <LineRow
          key={line.index}
          line={line}
          features={data.features}
          totalLength={data.length}
          localSelStart={selectionByLine[i][0]}
          localSelEnd={selectionByLine[i][1]}
          matchRanges={matchesByLine[i]}
          showGrouping={showGrouping}
          onBaseMouseDown={handleBaseMouseDown}
          onBaseMouseEnter={handleBaseMouseEnter}
          onSelectFeature={onSelectFeature}
          onCodonClick={handleCodonClick}
        />
      ))}
    </div>
  );
}
