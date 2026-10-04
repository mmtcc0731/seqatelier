import { useEffect, useMemo, useState } from "react";
import type { CodonTableEntry, PlasmidData } from "../types";
import { getCodonTable, getHosts, mutateCodon } from "../api";

interface CodonMutatorProps {
  plasmidId: string;
  revision: string;
  sequence: string;
  position: number; // 0-based, コドン開始位置候補（selection.start）
  length: number; // 選択範囲の長さ(bp)。3以外なら単一コドン編集不可を案内する。
  onApplied: (updated: PlasmidData) => void;
  onClose: () => void;
}

export function CodonMutator({
  plasmidId,
  revision,
  sequence,
  position,
  length,
  onApplied,
  onClose,
}: CodonMutatorProps) {
  const [hosts, setHosts] = useState<string[]>([]);
  const [host, setHost] = useState("ecoli_k12");
  const [strand, setStrand] = useState<1 | -1>(1);
  const [table, setTable] = useState<CodonTableEntry[]>([]);
  const [selectedCodon, setSelectedCodon] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHosts()
      .then(setHosts)
      .catch(() => setHosts([]));
  }, []);

  useEffect(() => {
    getCodonTable(host)
      .then((res) => setTable(res.codons))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [host]);

  const reverseComplement = (value: string) => value.split("").reverse().map((base) =>
    ({ A: "T", T: "A", G: "C", C: "G" }[base] ?? "N")).join("");
  const genomicCodon = sequence.slice(position, position + 3).toUpperCase();
  const currentCodon = strand === 1 ? genomicCodon : reverseComplement(genomicCodon);
  const currentAa = table.find((c) => c.codon === currentCodon)?.amino_acid ?? "?";

  const synonymous = useMemo(
    () =>
      table
        .filter((c) => c.amino_acid === currentAa)
        .slice()
        .sort((a, b) => b.frequency - a.frequency),
    [table, currentAa],
  );

  const groupedByAa = useMemo(() => {
    const byAa = new Map<string, CodonTableEntry[]>();
    for (const c of table) {
      const list = byAa.get(c.amino_acid) ?? [];
      list.push(c);
      byAa.set(c.amino_acid, list);
    }
    return [...byAa.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([aa, codons]) => [aa, codons.slice().sort((a, b) => b.frequency - a.frequency)] as const);
  }, [table]);

  if (length !== 3) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal codon-mutator" onClick={(e) => e.stopPropagation()}>
          <h3>コドン変異</h3>
          <p>選択範囲が{length}ntです。コドン変異は1コドン（3nt）を選択したときに使用できます。</p>
          <div className="modal-actions">
            <button className="btn" onClick={onClose}>
              閉じる
            </button>
          </div>
        </div>
      </div>
    );
  }

  async function handleApply() {
    if (!selectedCodon) return;
    setApplying(true);
    setError(null);
    try {
      const replacement = strand === 1 ? selectedCodon : reverseComplement(selectedCodon);
      const updated = await mutateCodon(plasmidId, position, replacement, revision);
      onApplied(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal codon-mutator" onClick={(e) => e.stopPropagation()}>
        <h3>コドン変異</h3>
        <p className="mutator-current">
          位置 {position + 1}-{position + 3}: 現在のコドン <code>{currentCodon}</code> ({currentAa})
        </p>

        <label className="field">
          読み方向（選択した3塩基）
          <select value={strand} onChange={(e) => { setStrand(Number(e.target.value) as 1 | -1); setSelectedCodon(null); }}>
            <option value={1}>正鎖 →</option>
            <option value={-1}>逆鎖 ←</option>
          </select>
        </label>
        <label className="field">
          ホスト
          <select value={host} onChange={(e) => setHost(e.target.value)}>
            {hosts.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>

        <h4>同義コドン（{currentAa}）</h4>
        <div className="codon-grid">
          {synonymous.map((c) => (
            <button
              key={c.codon}
              type="button"
              className={c.codon === selectedCodon ? "codon-chip selected" : "codon-chip"}
              onClick={() => setSelectedCodon(c.codon)}
            >
              {c.codon}
              <span className="freq">{(c.frequency * 100).toFixed(0)}%</span>
            </button>
          ))}
        </div>

        <details className="full-codon-table">
          <summary>コドン表全体（別のアミノ酸へ変異）</summary>
          {groupedByAa.map(([aa, codons]) => (
            <div key={aa} className="codon-table-row">
              <span className="aa-label">{aa}</span>
              <div className="codon-grid">
                {codons.map((c) => (
                  <button
                    key={c.codon}
                    type="button"
                    className={c.codon === selectedCodon ? "codon-chip selected" : "codon-chip"}
                    onClick={() => setSelectedCodon(c.codon)}
                  >
                    {c.codon}
                    <span className="freq">{(c.frequency * 100).toFixed(0)}%</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </details>

        {error && <p className="tm-error">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose} disabled={applying}>
            キャンセル
          </button>
          <button
            className="btn btn-accent"
            onClick={handleApply}
            disabled={!selectedCodon || selectedCodon === currentCodon || applying}
          >
            {applying ? "適用中..." : "適用"}
          </button>
        </div>
      </div>
    </div>
  );
}
