import { useEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { SearchMatch } from "../search";

export interface SearchBarProps {
  pattern: string;
  onPatternChange: (v: string) => void;
  options: { mismatches: 0 | 1; bothStrands: boolean };
  onOptionsChange: (v: { mismatches: 0 | 1; bothStrands: boolean }) => void;
  matches: readonly SearchMatch[];
  currentIdx: number;
  onJump: (idx: number) => void;
  onClose: () => void;
  error: string | null;
  truncated: boolean;
  narrow: boolean;
  gotoInput: string | null;
  onGotoChange?: (v: string) => void;
  onGotoSubmit?: () => void;
  gotoError: string | null;
}

function isComposingEvent(e: ReactKeyboardEvent): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}

export function SearchBar({
  pattern,
  onPatternChange,
  options,
  onOptionsChange,
  matches,
  currentIdx,
  onJump,
  onClose,
  error,
  truncated,
  narrow,
  gotoInput,
  onGotoChange,
  onGotoSubmit,
  gotoError,
}: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = inputRef.current;
    if (el) {
      el.focus();
      el.select();
    }
  }, []);

  const countLabel =
    matches.length === 0 && !error
      ? "一致なし"
      : `${matches.length === 0 ? 0 : currentIdx + 1} / ${matches.length}${truncated ? "+" : ""}`;

  return (
    <div className="searchbar-wrap">
      <div className="searchbar" role="search">
        <input
          ref={inputRef}
          type="search"
          placeholder="パターン (IUPAC 可)"
          value={pattern}
          onChange={(e) => onPatternChange(e.target.value)}
          onKeyDown={(e) => {
            if (isComposingEvent(e)) return;
            if (e.key === "Enter") {
              e.preventDefault();
              if (matches.length === 0) return;
              if (e.shiftKey) onJump(currentIdx - 1);
              else onJump(currentIdx + 1);
            } else if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
          aria-label="パターン検索"
        />
        <label>
          <input
            type="checkbox"
            checked={options.bothStrands}
            onChange={(e) =>
              onOptionsChange({ ...options, bothStrands: e.target.checked })
            }
          />
          両鎖
        </label>
        <label>
          ミスマッチ
          <select
            value={options.mismatches}
            onChange={(e) =>
              onOptionsChange({
                ...options,
                mismatches: Number(e.target.value) === 1 ? 1 : 0,
              })
            }
          >
            <option value={0}>0</option>
            <option value={1}>1</option>
          </select>
        </label>
        {narrow && gotoInput !== null && (
          <input
            id="goto-input-searchbar"
            type="text"
            placeholder="Goto: 123 or 100..200"
            value={gotoInput}
            onChange={(e) => onGotoChange?.(e.target.value)}
            onKeyDown={(e) => {
              if (isComposingEvent(e)) return;
              if (e.key === "Enter") {
                e.preventDefault();
                onGotoSubmit?.();
              }
            }}
            className={gotoError ? "goto-input error" : "goto-input"}
            aria-label="位置ジャンプ"
          />
        )}
        <span className="match-count">{countLabel}</span>
        <button
          className="btn"
          onClick={() => onJump(currentIdx - 1)}
          disabled={matches.length === 0}
          aria-label="前へ"
        >
          前
        </button>
        <button
          className="btn"
          onClick={() => onJump(currentIdx + 1)}
          disabled={matches.length === 0}
          aria-label="次へ"
        >
          次
        </button>
        <button
          onClick={onClose}
          aria-label="閉じる"
          className="btn btn-icon"
        >
          Close
        </button>
      </div>
      {error && (
        <div className="searchbar-error" role="alert">
          {error}
        </div>
      )}
      {narrow && gotoError && (
        <div className="searchbar-error" role="alert">
          {gotoError}
        </div>
      )}
    </div>
  );
}

export interface MatchesPanelProps {
  matches: readonly SearchMatch[];
  currentIdx: number;
  truncated: boolean;
  totalLength: number;
  onJump: (idx: number) => void;
}

export function MatchesPanel({
  matches,
  currentIdx,
  truncated,
  totalLength,
  onJump,
}: MatchesPanelProps) {
  return (
    <div className="matches-panel">
      <h3>マッチ一覧</h3>
      {matches.length === 0 ? (
        <p className="matches-empty">一致なし</p>
      ) : (
        <ul>
          {matches.map((m, i) => {
            const overrun = m.end > totalLength;
            const end1 = overrun ? m.end - totalLength : m.end;
            const label = overrun
              ? `${m.start + 1}..${totalLength} + 1..${end1}`
              : `${m.start + 1}..${m.end}`;
            return (
              <li
                key={i}
                className={i === currentIdx ? "active" : ""}
                onClick={() => onJump(i)}
              >
                <span className="m-range">{label}</span>
                <span className="m-strand">{m.strand === 1 ? "+" : "-"}</span>
              </li>
            );
          })}
        </ul>
      )}
      {truncated && (
        <p className="matches-truncated">
          マッチ数が上限に達しました（鎖ごと最大 500 件）。パターンを絞ってください。
        </p>
      )}
    </div>
  );
}
