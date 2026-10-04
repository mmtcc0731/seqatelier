import { useEffect, useMemo, useState } from "react";
import type { PlasmidData, Selection, Strand } from "../types";
import { addFeature, calcTm, translateSequence } from "../api";
import type { FeatureInput, TranslateResult } from "../api";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

const COPY_ONLY_THRESHOLD = 120;
const TM_DEBOUNCE_MS = 300;

const FEATURE_TYPES = [
  "CDS",
  "misc_feature",
  "promoter",
  "primer",
  "primer_bind",
  "rep_origin",
  "terminator",
  "polyA_signal",
  "regulatory",
  "protein_bind",
];

interface SelectionInfoProps {
  data: PlasmidData;
  selection: Selection | null;
  onOpenMutator: (position: number) => void;
  onDataUpdated?: (data: PlasmidData) => void;
}

export function SelectionInfo({
  data,
  selection,
  onOpenMutator,
  onDataUpdated,
}: SelectionInfoProps) {
  const subsequence = useMemo(() => {
    if (!selection) return "";
    // circular で原点を跨ぐマッチは `end > sequence.length` となりうるため、
    // 2 セグメントを連結して返す（Tm / GC / 翻訳がマッチ長と一致するように）。
    if (selection.end > data.sequence.length) {
      const head = data.sequence.slice(selection.start);
      const tail = data.sequence.slice(0, selection.end - data.sequence.length);
      return head + tail;
    }
    return data.sequence.slice(selection.start, selection.end);
  }, [data, selection]);

  const debouncedSeq = useDebouncedValue(subsequence, TM_DEBOUNCE_MS);
  const [tmCelsius, setTmCelsius] = useState<number | null>(null);
  const [gcPercent, setGcPercent] = useState<number | null>(null);
  const [tmError, setTmError] = useState<string | null>(null);
  const [tmLoading, setTmLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Translation
  const [translateResult, setTranslateResult] = useState<TranslateResult | null>(null);
  const [translateStrand, setTranslateStrand] = useState<Strand>(1);
  const [showTranslation, setShowTranslation] = useState(false);

  // New annotation
  const [showAnnotationForm, setShowAnnotationForm] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newType, setNewType] = useState("misc_feature");
  const [newStrand, setNewStrand] = useState<Strand>(1);
  const [annotating, setAnnotating] = useState(false);
  const [annotateError, setAnnotateError] = useState<string | null>(null);

  useEffect(() => {
    if (!debouncedSeq) {
      setTmCelsius(null);
      setGcPercent(null);
      setTmError(null);
      return;
    }
    let cancelled = false;
    setTmLoading(true);
    calcTm(debouncedSeq)
      .then((res) => {
        if (cancelled) return;
        setTmCelsius(res.tm_celsius);
        setGcPercent(res.gc_percent);
        setTmError(res.error);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setTmError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setTmLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSeq]);

  useEffect(() => {
    setCopied(false);
    setShowTranslation(false);
    setTranslateResult(null);
    setShowAnnotationForm(false);
    setAnnotateError(null);
  }, [selection]);

  // Translate when requested
  useEffect(() => {
    if (!showTranslation || !subsequence) {
      setTranslateResult(null);
      return;
    }
    let cancelled = false;
    translateSequence(subsequence, translateStrand)
      .then((res) => {
        if (!cancelled) setTranslateResult(res);
      })
      .catch(() => {
        if (!cancelled) setTranslateResult(null);
      });
    return () => {
      cancelled = true;
    };
  }, [showTranslation, subsequence, translateStrand]);

  if (!selection) {
    return (
      <div className="selection-info empty">
        <p>配列上をクリック、またはドラッグして範囲を選択してください。</p>
      </div>
    );
  }

  const bpCount = selection.end - selection.start;
  const isCodonAligned = bpCount > 0 && bpCount % 3 === 0;
  const wraps = selection.end > data.sequence.length;
  const displayEnd = wraps ? selection.end - data.sequence.length : selection.end;

  async function handleCopy() {
    await navigator.clipboard.writeText(subsequence);
    setCopied(true);
  }

  async function handleAddAnnotation() {
    if (!selection || !newLabel.trim()) return;
    if (wraps) {
      setAnnotateError(
        "原点を跨ぐ範囲へのアノテーション追加は未対応です。範囲を分割してください。",
      );
      return;
    }
    setAnnotating(true);
    setAnnotateError(null);
    try {
      const feature: FeatureInput = {
        type: newType,
        label: newLabel.trim(),
        start: selection.start,
        end: selection.end,
        strand: newStrand,
      };
      const updated = await addFeature(data.id, feature, data.revision);
      onDataUpdated?.(updated);
      setShowAnnotationForm(false);
      setNewLabel("");
    } catch (err) {
      setAnnotateError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnnotating(false);
    }
  }

  return (
    <div className="selection-info">
      <h3>選択範囲</h3>
      <dl className="info-grid">
        <dt>位置</dt>
        <dd>
          {wraps
            ? `${selection.start + 1}..${data.sequence.length} + 1..${displayEnd}`
            : `${selection.start + 1} - ${selection.end}`}
        </dd>
        <dt>塩基数</dt>
        <dd>{bpCount} bp</dd>
        <dt>GC%</dt>
        <dd>{gcPercent !== null ? `${gcPercent.toFixed(1)}%` : "-"}</dd>
        <dt>Tm</dt>
        <dd>
          {tmLoading
            ? "計算中..."
            : tmCelsius !== null
              ? `${tmCelsius.toFixed(1)} °C`
              : "-"}
        </dd>
      </dl>
      {tmError && <p className="tm-error">{tmError}</p>}

      {bpCount <= COPY_ONLY_THRESHOLD ? (
        <pre className="seq-preview">{subsequence}</pre>
      ) : (
        <p className="seq-preview-note">{bpCount}bp（長いため配列表示は省略）</p>
      )}

      <div className="action-buttons">
        <button className="btn" onClick={handleCopy}>
          {copied ? "コピー済" : "配列コピー"}
        </button>

        {isCodonAligned && (
          <button
            className="btn btn-accent"
            onClick={() => onOpenMutator(selection.start)}
          >
            コドン変異
          </button>
        )}

        <button
          className="btn"
          onClick={() => setShowTranslation(!showTranslation)}
        >
          {showTranslation ? "翻訳を閉じる" : "翻訳"}
        </button>

        <button
          className="btn"
          onClick={() => setShowAnnotationForm(!showAnnotationForm)}
        >
          {showAnnotationForm ? "キャンセル" : "アノテーション追加"}
        </button>
      </div>

      {/* Translation panel */}
      {showTranslation && (
        <div className="translate-panel">
          <div className="translate-header">
            <h4>翻訳</h4>
            <select
              value={translateStrand}
              onChange={(e) =>
                setTranslateStrand(Number(e.target.value) as Strand)
              }
            >
              <option value={1}>+ 鎖 (Forward)</option>
              <option value={-1}>- 鎖 (Reverse complement)</option>
            </select>
          </div>
          {translateResult ? (
            <>
              <pre className="translate-result">{translateResult.protein}</pre>
              <div className="translate-meta">
                {translateResult.length_aa} aa / {translateResult.length_nt} nt
                {translateResult.has_stop && " (終止コドンあり)"}
              </div>
              {translateResult.warning && (
                <p className="tm-error">{translateResult.warning}</p>
              )}
            </>
          ) : (
            <p className="translate-meta">翻訳中...</p>
          )}
        </div>
      )}

      {/* New annotation form */}
      {showAnnotationForm && (
        <div className="annotate-form">
          <h4>新規アノテーション</h4>
          <div className="editor-field">
            <label>ラベル</label>
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="例: GFP, T7 promoter"
            />
          </div>
          <div className="editor-field-row">
            <div className="editor-field">
              <label>タイプ</label>
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
              >
                {FEATURE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div className="editor-field">
              <label>鎖</label>
              <select
                value={newStrand}
                onChange={(e) =>
                  setNewStrand(Number(e.target.value) as Strand)
                }
              >
                <option value={1}>+ Forward</option>
                <option value={-1}>- Reverse</option>
              </select>
            </div>
          </div>
          <div className="editor-info">
            位置: {selection.start + 1}-{selection.end} ({bpCount} bp)
          </div>
          {annotateError && <p className="editor-error">{annotateError}</p>}
          <button
            className="btn btn-accent"
            onClick={handleAddAnnotation}
            disabled={annotating || !newLabel.trim()}
            style={{ width: "100%" }}
          >
            {annotating ? "追加中..." : "追加"}
          </button>
        </div>
      )}
    </div>
  );
}
