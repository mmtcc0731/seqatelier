import type { PlasmidSummary } from "../types";

interface PlasmidSelectorProps {
  plasmids: PlasmidSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function PlasmidSelector({ plasmids, selectedId, onSelect }: PlasmidSelectorProps) {
  return (
    <select
      className="plasmid-selector"
      value={selectedId ?? ""}
      onChange={(e) => onSelect(e.target.value)}
    >
      {plasmids.length === 0 && <option value="">(プラスミドがありません)</option>}
      {plasmids.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name} ({p.length.toLocaleString()} bp)
        </option>
      ))}
    </select>
  );
}
