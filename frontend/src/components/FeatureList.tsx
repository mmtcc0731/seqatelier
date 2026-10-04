import type { FeatureData, Selection } from "../types";

interface FeatureListProps {
  features: FeatureData[];
  selection: Selection | null;
  onSelectFeature: (feature: FeatureData, index: number) => void;
}

export function FeatureList({ features, selection, onSelectFeature }: FeatureListProps) {
  return (
    <div className="feature-list">
      <h3>Features（{features.length}）</h3>
      <ul>
        {features.map((f, i) => {
          const isActive =
            selection !== null && selection.start === f.start && selection.end === f.end;
          return (
            <li
              key={i}
              className={isActive ? "active" : ""}
              onClick={() => onSelectFeature(f, i)}
            >
              <span className="swatch" style={{ background: f.color }} />
              <span className="label" title={f.label}>
                {f.label}
              </span>
              <span className="type">{f.type}</span>
              <span className="range">
                {f.start + 1}-{f.end}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
