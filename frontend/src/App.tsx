import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { FeatureData, PlasmidData, PlasmidSummary, Selection } from "./types";
import {
  getPlasmid,
  getPlasmids,
  reloadPlasmid,
  savePlasmid,
} from "./api";
import { PlasmidSelector } from "./components/PlasmidSelector";
import { SequenceViewer } from "./components/SequenceViewer";
import { SelectionInfo, useDebouncedValue } from "./components/SelectionInfo";
import { CodonMutator } from "./components/CodonMutator";
import { FeatureList } from "./components/FeatureList";
import { FeatureEditor } from "./components/FeatureEditor";
import { WorkspaceTools } from "./components/WorkspaceTools";
import { DISPLAY_NAME } from "./branding";
import { MatchesPanel, SearchBar } from "./components/SearchBar";
import { GROUP_SIZE } from "./layout";
import { parseGoto } from "./coords";
import { findMatches, validatePattern } from "./search";
import type { SearchMatch } from "./search";
import "./styles/index.css";

const LINE_NUMBER_PX = 68;
const SIDEBAR_PX = 260;
const SIDE_PANEL_PX = 300;
const PADDING_PX = 40;
const NARROW_BREAKPOINT = 900;
const SEARCH_BAR_HEIGHT = 44;
const SEARCH_DEBOUNCE_MS = 300;
const SAVE_MESSAGE_TIMEOUT_MS = 4000;

const EMPTY_MATCHES: readonly SearchMatch[] = [];

function calcLineWidth(
  windowWidth: number,
  charWidthPx: number,
  showGrouping: boolean,
): number {
  const sidebars = windowWidth < NARROW_BREAKPOINT ? 0 : SIDEBAR_PX + SIDE_PANEL_PX;
  const available = windowWidth - sidebars - LINE_NUMBER_PX - PADDING_PX;
  const charsAvailable = Math.floor(available / charWidthPx);
  if (showGrouping) {
    const spacers = Math.floor(charsAvailable / (GROUP_SIZE + 1));
    const bases = charsAvailable - spacers;
    const rounded = Math.floor(bases / GROUP_SIZE) * GROUP_SIZE;
    return Math.max(GROUP_SIZE, rounded);
  }
  // 区切りOFF: 行幅を GROUP_SIZE 単位で丸める（表示座標の安定性のため）
  const rounded = Math.floor(charsAvailable / GROUP_SIZE) * GROUP_SIZE;
  return Math.max(GROUP_SIZE, rounded);
}

export default function App() {
  const [plasmids, setPlasmids] = useState<PlasmidSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [data, setData] = useState<PlasmidData | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mutatorPosition, setMutatorPosition] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [lineWidth, setLineWidth] = useState(60);
  const [editingFeature, setEditingFeature] = useState<{
    feature: FeatureData;
    index: number;
  } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchPattern, setSearchPattern] = useState("");
  const [searchOptions, setSearchOptions] = useState<{
    mismatches: 0 | 1;
    bothStrands: boolean;
  }>({ mismatches: 0, bothStrands: true });
  const [matches, setMatches] = useState<readonly SearchMatch[]>(EMPTY_MATCHES);
  const [currentMatchIdx, setCurrentMatchIdx] = useState(0);
  const [matchesTruncated, setMatchesTruncated] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [sidePanelTab, setSidePanelTab] = useState<"info" | "matches">("info");
  const [gotoInput, setGotoInput] = useState("");
  const [gotoError, setGotoError] = useState<string | null>(null);
  const [narrow, setNarrow] = useState(
    typeof window !== "undefined" && window.innerWidth < NARROW_BREAKPOINT,
  );
  const [showGrouping, setShowGrouping] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const stored = window.localStorage.getItem("seqatelier.showGrouping");
    return stored === null ? true : stored === "true";
  });

  const charMeasureRef = useRef<HTMLSpanElement>(null);
  const viewerRef = useRef<HTMLElement>(null);
  const prevSearchOpenRef = useRef(searchOpen);

  const measureAndSetLineWidth = useCallback(() => {
    const el = charMeasureRef.current;
    if (!el) return;
    const charW = el.getBoundingClientRect().width;
    if (charW > 0) {
      setLineWidth(calcLineWidth(window.innerWidth, charW, showGrouping));
    }
    setNarrow(window.innerWidth < NARROW_BREAKPOINT);
  }, [showGrouping]);

  useEffect(() => {
    measureAndSetLineWidth();
    window.addEventListener("resize", measureAndSetLineWidth);
    return () => window.removeEventListener("resize", measureAndSetLineWidth);
  }, [measureAndSetLineWidth]);

  const handleToggleGrouping = useCallback(() => {
    setShowGrouping((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem("seqatelier.showGrouping", String(next));
      }
      return next;
    });
  }, []);

  useEffect(() => {
    getPlasmids()
      .then((list) => {
        setPlasmids(list);
        setSelectedId((prev) => prev ?? (list.length > 0 ? list[0].id : null));
      })
      .catch((err: unknown) =>
        setLoadError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setLoading(true);
    setSelection(null);
    setSaveMessage(null);
    setEditingFeature(null);
    setMatches(EMPTY_MATCHES);
    setSearchOpen(false);
    setSearchPattern("");
    setSearchError(null);
    setGotoInput("");
    setGotoError(null);
    setSidePanelTab("info");
    getPlasmid(selectedId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        // server 側の `dirty` フラグを信頼して復元する。ブラウザリロード後や
        // プラスミド切替後でも、メモリ上に未保存編集があれば dirty を保つ。
        setDirty(d.dirty ?? false);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // saveMessage を一定時間で自動消去
  useEffect(() => {
    if (saveMessage === null) return;
    const handle = setTimeout(
      () => setSaveMessage(null),
      SAVE_MESSAGE_TIMEOUT_MS,
    );
    return () => clearTimeout(handle);
  }, [saveMessage]);

  const handleUpdated = useCallback((updated: PlasmidData) => {
    setData(updated);
    setMutatorPosition(null);
    setDirty(true);
  }, []);

  const handleSelectPlasmid = useCallback(
    (id: string) => {
      if (id === selectedId) return;
      if (dirty) {
        const ok = window.confirm(
          "未保存の変更があります。プラスミドを切り替えると変更が失われるように見えますが、サーバ側では保持されます。切り替えますか?",
        );
        if (!ok) return;
      }
      setSelectedId(id);
    },
    [dirty, selectedId],
  );

  // 未保存編集がある状態でタブを閉じる/リロードする際に警告を出す。
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const scrollToPosition = useCallback(
    (pos: number) => {
      const viewer = viewerRef.current;
      if (!viewer) return;
      const lineIndex = Math.floor(pos / lineWidth);
      const lineElements = viewer.querySelectorAll(".seq-line");
      if (lineIndex < lineElements.length) {
        lineElements[lineIndex].scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
    },
    [lineWidth],
  );

  const handleSelectFeatureFromList = useCallback(
    (feature: FeatureData, index: number) => {
      setSelection({ start: feature.start, end: feature.end });
      setEditingFeature({ feature, index });
      scrollToPosition(feature.start);
    },
    [scrollToPosition],
  );

  const handleSelectFeatureFromViewer = useCallback(
    (feature: FeatureData) => {
      setSelection({ start: feature.start, end: feature.end });
      const index = data?.features.indexOf(feature) ?? -1;
      if (index >= 0) {
        setEditingFeature({ feature, index });
      }
    },
    [data],
  );

  const handleFeatureUpdated = useCallback((updated: PlasmidData) => {
    setData(updated);
    setEditingFeature(null);
    setDirty(true);
  }, []);

  // 配列ビューア側から発生する選択変更（ドラッグ、塩基クリック、コドン
  // クリック）はいずれも「新しい範囲を張る」意図なので、開いている
  // FeatureEditor は閉じて SelectionInfo に戻す。
  const handleViewerSelectionChange = useCallback(
    (sel: Selection | null) => {
      setSelection(sel);
      if (sel !== null) setEditingFeature(null);
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (!data) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const res = await savePlasmid(data.id, data.revision);
      setData((current) => current?.revision === data.revision ? { ...current, revision: res.revision, dirty: false } : current);
      setSaveMessage(`保存しました: ${res.path}`);
      setDirty(false);
    } catch (err) {
      setSaveMessage(
        `保存失敗: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
    }
  }, [data]);

  const handleReload = useCallback(async () => {
    if (!data) return;
    if (dirty) {
      const ok = window.confirm(
        "下書きを破棄し、最後に保存した版に戻しますか? 現在の下書きも履歴に残ります。",
      );
      if (!ok) return;
    }
    try {
      const updated = dirty ? await reloadPlasmid(data.id, data.revision) : await getPlasmid(data.id);
      setData(updated);
      setDirty(updated.dirty ?? false);
      setEditingFeature(null);
      setSelection(null);
      setMatches(EMPTY_MATCHES);
      setSearchError(null);
      setSaveMessage("再読み込みしました");
    } catch (err) {
      setSaveMessage(
        `再読み込み失敗: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }, [data, dirty]);

  const handleGotoSubmit = useCallback(() => {
    if (!data) return;
    const res = parseGoto(gotoInput, data.length);
    if (!res.ok) {
      setGotoError(res.reason);
      return;
    }
    setGotoError(null);
    if (res.value.kind === "point") {
      const p = res.value.pos0;
      setSelection({ start: p, end: p + 1 });
      scrollToPosition(p);
    } else {
      setSelection({ start: res.value.start0, end: res.value.end0 });
      scrollToPosition(res.value.start0);
    }
    setEditingFeature(null);
  }, [data, gotoInput, scrollToPosition]);

  const handleJumpToMatch = useCallback(
    (idx: number) => {
      if (matches.length === 0) return;
      const clamped = ((idx % matches.length) + matches.length) % matches.length;
      setCurrentMatchIdx(clamped);
      const m = matches[clamped];
      // circular で原点跨ぎのマッチの場合、m.end は seqLen を超える値のまま
      // 保持する。SelectionInfo / SequenceViewer 側で wraparound を扱う。
      setSelection({ start: m.start, end: m.end });
      setEditingFeature(null);
      scrollToPosition(m.start);
    },
    [matches, scrollToPosition],
  );

  // Search（debounced）
  const debouncedPattern = useDebouncedValue(searchPattern, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    if (!data) {
      setMatches(EMPTY_MATCHES);
      setMatchesTruncated(false);
      setSearchError(null);
      return;
    }
    if (!debouncedPattern) {
      setMatches(EMPTY_MATCHES);
      setMatchesTruncated(false);
      setSearchError(null);
      return;
    }
    const v = validatePattern(debouncedPattern);
    if (!v.ok) {
      setSearchError(v.reason);
      setMatches(EMPTY_MATCHES);
      setMatchesTruncated(false);
      return;
    }
    try {
      const result = findMatches(data.sequence, debouncedPattern, {
        mismatches: searchOptions.mismatches,
        bothStrands: searchOptions.bothStrands,
        topology: data.topology,
      });
      setMatches(result.matches);
      setMatchesTruncated(result.truncated);
      setSearchError(null);
      setCurrentMatchIdx(0);
      // タブ自動切替はここでは行わない（毎回のパターン変更で切り替えると
      // ユーザーが手動で info タブに戻しても即座に上書きされてしまうため）。
      // 検索バーを新しく開いたタイミングでのみ切り替える（別 effect）。
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : String(err));
      setMatches(EMPTY_MATCHES);
      setMatchesTruncated(false);
    }
  }, [
    data,
    debouncedPattern,
    searchOptions.mismatches,
    searchOptions.bothStrands,
  ]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.isComposing || e.keyCode === 229) return;
      // モーダル表示中は全ショートカット無効
      if (mutatorPosition !== null) return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const isEditable =
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        (target?.isContentEditable ?? false);
      const mod = e.ctrlKey || e.metaKey;

      if (mod && e.key.toLowerCase() === "f") {
        e.preventDefault();
        // VS Code / ブラウザ標準に合わせ、Ctrl+F は「開く/再フォーカス」。
        // 閉じるのは Escape。既に開いている場合はパターン入力を再選択する。
        if (searchOpen) {
          const el = document.querySelector<HTMLInputElement>(
            ".searchbar input[type=\"search\"]",
          );
          el?.focus();
          el?.select();
        } else {
          setSearchOpen(true);
        }
        return;
      }
      if (mod && e.key.toLowerCase() === "g") {
        e.preventDefault();
        if (narrow) {
          setSearchOpen(true);
          // 次フレームで goto input を focus
          setTimeout(() => {
            const el = document.getElementById(
              "goto-input-searchbar",
            ) as HTMLInputElement | null;
            el?.focus();
            el?.select();
          }, 0);
        } else {
          const el = document.getElementById(
            "goto-input",
          ) as HTMLInputElement | null;
          el?.focus();
          el?.select();
        }
        return;
      }
      if (e.key === "Escape" && searchOpen) {
        e.preventDefault();
        setSearchOpen(false);
        return;
      }
      if (isEditable) return;
      if (searchOpen && e.key === "F3") {
        e.preventDefault();
        if (e.shiftKey) handleJumpToMatch(currentMatchIdx - 1);
        else handleJumpToMatch(currentMatchIdx + 1);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [
    searchOpen,
    handleJumpToMatch,
    currentMatchIdx,
    mutatorPosition,
    narrow,
  ]);

  // SearchBar 開閉時の scrollTop 補正
  useLayoutEffect(() => {
    const prev = prevSearchOpenRef.current;
    if (prev === searchOpen) {
      prevSearchOpenRef.current = searchOpen;
      return;
    }
    const viewer = viewerRef.current;
    if (viewer) {
      viewer.scrollTop = viewer.scrollTop + (searchOpen ? SEARCH_BAR_HEIGHT : -SEARCH_BAR_HEIGHT);
    }
    prevSearchOpenRef.current = searchOpen;
  }, [searchOpen]);

  // 検索バーを「新しく開いた」タイミングでのみ、既にヒットがあれば matches
  // タブに切り替える。パターン変更のたびに切り替わって info タブの手動選択が
  // 潰される問題（毎 debounce ごとの上書き）を避けるための1回限りの発火。
  const prevSearchOpenForTabRef = useRef(searchOpen);
  useEffect(() => {
    const prev = prevSearchOpenForTabRef.current;
    if (!prev && searchOpen && matches.length > 0) {
      setSidePanelTab((cur) => (cur === "info" ? "matches" : cur));
    }
    prevSearchOpenForTabRef.current = searchOpen;
  }, [searchOpen, matches.length]);

  const selectionLength = selection ? selection.end - selection.start : 0;

  const saveButtonClass = `btn btn-accent${dirty ? " dirty" : ""}`;
  const saveButtonLabel = saving
    ? "保存中..."
    : dirty
      ? "保存 ●"
      : "保存";

  return (
    <div className="app-shell">
      <span
        ref={charMeasureRef}
        className="char-measure"
        aria-hidden="true"
      >
        0
      </span>
      <header className="toolbar">
        <h1 title="配列の設計と管理">{DISPLAY_NAME}</h1>
        <PlasmidSelector
          plasmids={plasmids}
          selectedId={selectedId}
          onSelect={handleSelectPlasmid}
        />
        <div className="toolbar-spacer" />
        <WorkspaceTools data={data} onUpdated={(updated) => {
          setData(updated); setDirty(updated.dirty ?? false); setSelectedId(updated.id);
          setEditingFeature(null); setSelection(null); setLoadError(null);
          void getPlasmids().then(setPlasmids).catch((error: unknown) => setLoadError(String(error)));
        }} />
        <div className="goto-group">
          <input
            id="goto-input"
            className={gotoError ? "goto-input error" : "goto-input"}
            type="text"
            placeholder="Goto: 123 or 100..200"
            value={gotoInput}
            onChange={(e) => {
              setGotoInput(e.target.value);
              if (gotoError) setGotoError(null);
            }}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
              if (e.key === "Enter") {
                e.preventDefault();
                handleGotoSubmit();
              }
            }}
            aria-label="位置ジャンプ"
          />
          {gotoError && (
            <span className="goto-error" role="alert">
              {gotoError}
            </span>
          )}
        </div>
        <button
          type="button"
          className="btn btn-find"
          onClick={() => setSearchOpen(true)}
          aria-label="検索/ジャンプ"
          title="検索 (Ctrl+F)"
        >
          Find
        </button>
        <button
          type="button"
          className={`btn btn-toggle${showGrouping ? " active" : ""}`}
          onClick={handleToggleGrouping}
          title={showGrouping ? "10塩基区切り: ON" : "10塩基区切り: OFF"}
          aria-pressed={showGrouping}
        >
          {showGrouping ? "10bp区切り ●" : "10bp区切り ○"}
        </button>
        <button
          className={saveButtonClass}
          onClick={handleSave}
          disabled={!data || saving}
        >
          {saveButtonLabel}
        </button>
        <button
          className="btn"
          onClick={handleReload}
          disabled={!data || saving}
        >
          再読み込み
        </button>
        {saveMessage && <span className="save-message">{saveMessage}</span>}
      </header>

      {loadError && <div className="banner error">{loadError}</div>}

      {data ? (
        <div className="main-layout">
          <aside className="sidebar">
            <div className="plasmid-meta">
              <div className="plasmid-meta-name">{data.name}</div>
              <div className="plasmid-meta-detail">
                {data.length.toLocaleString()} bp /{" "}
                {data.topology === "circular" ? "環状" : "線状"}
              </div>
            </div>
            <FeatureList
              features={data.features}
              selection={selection}
              onSelectFeature={handleSelectFeatureFromList}
            />
          </aside>

          <main className="viewer-panel" ref={viewerRef}>
            {searchOpen && (
              <SearchBar
                pattern={searchPattern}
                onPatternChange={setSearchPattern}
                options={searchOptions}
                onOptionsChange={setSearchOptions}
                matches={matches}
                currentIdx={currentMatchIdx}
                onJump={handleJumpToMatch}
                onClose={() => setSearchOpen(false)}
                error={searchError}
                truncated={matchesTruncated}
                narrow={narrow}
                gotoInput={narrow ? gotoInput : null}
                onGotoChange={
                  narrow
                    ? (v) => {
                        setGotoInput(v);
                        if (gotoError) setGotoError(null);
                      }
                    : undefined
                }
                onGotoSubmit={narrow ? handleGotoSubmit : undefined}
                gotoError={narrow ? gotoError : null}
              />
            )}
            {loading ? (
              <p className="loading-message">読み込み中...</p>
            ) : (
              <SequenceViewer
                data={data}
                selection={selection}
                onSelectionChange={handleViewerSelectionChange}
                onSelectFeature={handleSelectFeatureFromViewer}
                lineWidth={lineWidth}
                matches={matches}
                currentMatchIdx={currentMatchIdx}
                showGrouping={showGrouping}
              />
            )}
          </main>

          <aside className="side-panel">
            {editingFeature ? (
              <FeatureEditor
                revision={data.revision}
                plasmidId={data.id}
                feature={editingFeature.feature}
                featureIndex={editingFeature.index}
                sequence={data.sequence}
                onUpdated={handleFeatureUpdated}
                onClose={() => setEditingFeature(null)}
              />
            ) : (
              <>
                <div className="side-tabs" role="tablist">
                  <button
                    role="tab"
                    aria-selected={sidePanelTab === "info"}
                    className={
                      sidePanelTab === "info" ? "tab active" : "tab"
                    }
                    onClick={() => setSidePanelTab("info")}
                  >
                    選択情報
                  </button>
                  <button
                    role="tab"
                    aria-selected={sidePanelTab === "matches"}
                    className={
                      sidePanelTab === "matches" ? "tab active" : "tab"
                    }
                    onClick={() => setSidePanelTab("matches")}
                  >
                    マッチ ({matches.length}
                    {matchesTruncated ? "+" : ""})
                  </button>
                </div>
                {sidePanelTab === "matches" ? (
                  <MatchesPanel
                    matches={matches}
                    currentIdx={currentMatchIdx}
                    truncated={matchesTruncated}
                    totalLength={data.length}
                    onJump={handleJumpToMatch}
                  />
                ) : (
                  <SelectionInfo
                    data={data}
                    selection={selection}
                    onOpenMutator={setMutatorPosition}
                    onDataUpdated={handleUpdated}
                  />
                )}
              </>
            )}
          </aside>
        </div>
      ) : (
        !loadError && (
          <p className="loading-message">プラスミドを選択してください。</p>
        )
      )}

      {mutatorPosition !== null && data && (
        <CodonMutator
          revision={data.revision}
          plasmidId={data.id}
          sequence={data.sequence}
          position={mutatorPosition}
          length={selectionLength}
          onApplied={handleUpdated}
          onClose={() => setMutatorPosition(null)}
        />
      )}
    </div>
  );
}
