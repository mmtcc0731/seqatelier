import { useState } from "react";
import type { PlasmidData } from "../types";
import { downloadGenBank, getHistory, importGenBank, restoreRevision, setAccessToken } from "../api";
import type { Revision } from "../api";
import { isOAuthEnabled, signOut } from "../auth";

export function WorkspaceTools({ data, onUpdated }: {
  data: PlasmidData | null; onUpdated: (data: PlasmidData) => void;
}) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [history, setHistory] = useState<Revision[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function perform(action: () => Promise<void>) {
    setError(""); setBusy(true);
    try { await action(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }

  return <>
    <button className="btn" onClick={() => { setOpen(true); setHistory([]); setError(""); }}>データ・接続</button>
    {open && <div className="modal-backdrop">
      <section className="modal" role="dialog" aria-modal="true" aria-label="データ・接続" style={{ maxHeight: "85vh", overflow: "auto" }}>
        <h2>データ・接続</h2>
        <p>GenBankを取り込み、編集履歴を残せます。下書きは再起動後も残り、「保存」で確定版になります。</p>
        <label className="field">GenBankを取り込む
          <input type="file" accept=".gb,.gbk,.genbank" disabled={busy} onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            void perform(async () => {
              if (file.size > 10 * 1024 * 1024) throw new Error("10 MiB以下のファイルを選んでください。");
              const imported = await importGenBank(await file.text());
              onUpdated(imported); setHistory([]); setOpen(false);
            });
          }} />
        </label>
        {data && <>
          <p>{data.name} {data.dirty ? "（下書きあり）" : "（保存済み）"}</p>
          <button className="btn" disabled={busy} onClick={() => void perform(() => downloadGenBank(data.id))}>GenBankを書き出す</button>
          <button className="btn" disabled={busy} onClick={() => void perform(async () => setHistory(await getHistory(data.id)))}>履歴を表示</button>
          <ul>{history.map((revision) => <li key={revision.revision}>
            <span>{new Date(revision.created).toLocaleString()} — {revision.message} {revision.saved ? "（保存）" : "（下書き）"}</span>
            <button className="btn" disabled={busy || revision.revision === data.revision} onClick={() => {
              if (!window.confirm("この版を新しい確定版として復元します。現在の版も履歴に残ります。続けますか？")) return;
              void perform(async () => {
                const updated = await restoreRevision(data, revision.revision);
                onUpdated(updated); setHistory(await getHistory(data.id));
              });
            }}>復元</button>
          </li>)}</ul>
        </>}
        {isOAuthEnabled() ? <button className="btn" onClick={() => void perform(signOut)}>ログアウト</button> : <form onSubmit={(e) => { e.preventDefault(); setAccessToken(token.trim()); window.location.reload(); }}>
          <label className="field">接続トークン（サーバーで設定されている場合）
            <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
          </label>
          <p>このタブのセッション内に保存します。空欄で適用すると削除します。</p>
          <button className="btn" type="submit">接続設定を適用</button>
        </form>}
        {error && <p role="alert" className="tm-error">{error}</p>}
        <div className="modal-actions"><button className="btn" onClick={() => setOpen(false)}>閉じる</button></div>
      </section>
    </div>}
  </>;
}
