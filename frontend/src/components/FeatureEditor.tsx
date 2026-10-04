import { useEffect, useState } from "react";
import type { FeatureData, PlasmidData, Strand } from "../types";
import { deleteFeature, updateFeature } from "../api";
import type { FeatureInput } from "../api";

interface FeatureEditorProps {
  plasmidId: string;
  revision: string;
  feature: FeatureData;
  featureIndex: number;
  sequence: string;
  onUpdated: (data: PlasmidData) => void;
  onClose: () => void;
}

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

export function FeatureEditor({
  plasmidId,
  revision,
  feature,
  featureIndex,
  sequence,
  onUpdated,
  onClose,
}: FeatureEditorProps) {
  const [label, setLabel] = useState(feature.label);
  const [type, setType] = useState(feature.type);
  const [start1, setStart1] = useState(feature.start + 1);
  const [end, setEnd] = useState(feature.end);
  const [strand, setStrand] = useState<Strand>(feature.strand);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLabel(feature.label);
    setType(feature.type);
    setStart1(feature.start + 1);
    setEnd(feature.end);
    setStrand(feature.strand);
    setError(null);
  }, [feature]);

  const bpCount = end - (start1 - 1);
  const featureSeq =
    bpCount > 0 && bpCount <= 200
      ? sequence.slice(start1 - 1, end)
      : null;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const input: FeatureInput = {
        type,
        label,
        start: start1 - 1,
        end,
        strand,
      };
      const updated = await updateFeature(plasmidId, featureIndex, input, revision);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Feature "${feature.label}" を削除しますか？`)) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await deleteFeature(plasmidId, featureIndex, revision);
      onUpdated(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="feature-editor">
      <div className="editor-header">
        <h3>Feature 編集</h3>
        <button className="btn btn-small" onClick={onClose}>
          閉じる
        </button>
      </div>

      <div className="editor-field">
        <label>ラベル</label>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>

      <div className="editor-field">
        <label>タイプ</label>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {FEATURE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
          {!FEATURE_TYPES.includes(type) && (
            <option value={type}>{type}</option>
          )}
        </select>
      </div>

      <div className="editor-field-row">
        <div className="editor-field">
          <label>開始 (1-based)</label>
          <input
            type="number"
            min={1}
            max={sequence.length}
            value={start1}
            onChange={(e) => setStart1(Number(e.target.value))}
          />
        </div>
        <div className="editor-field">
          <label>終了</label>
          <input
            type="number"
            min={1}
            max={sequence.length}
            value={end}
            onChange={(e) => setEnd(Number(e.target.value))}
          />
        </div>
        <div className="editor-field">
          <label>鎖</label>
          <select
            value={strand}
            onChange={(e) => setStrand(Number(e.target.value) as Strand)}
          >
            <option value={1}>+ (Forward)</option>
            <option value={-1}>- (Reverse)</option>
          </select>
        </div>
      </div>

      <div className="editor-info">
        {bpCount} bp
        {strand === -1 && " (reverse complement)"}
      </div>

      {featureSeq && (
        <pre className="editor-seq-preview">{featureSeq}</pre>
      )}

      {error && <p className="editor-error">{error}</p>}

      <div className="editor-actions">
        <button
          className="btn btn-accent"
          onClick={handleSave}
          disabled={saving || !label.trim()}
        >
          {saving ? "保存中..." : "更新"}
        </button>
        <button
          className="btn btn-danger"
          onClick={handleDelete}
          disabled={saving}
        >
          削除
        </button>
      </div>
    </div>
  );
}
