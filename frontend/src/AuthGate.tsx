import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { initializeAuth, isOAuthEnabled, signIn, signOut } from "./auth";
import { DISPLAY_NAME } from "./branding";

// Share one initialization across React StrictMode's effect replay.
let initialization: Promise<boolean> | null = null;

export function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<"loading" | "login" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    initialization ??= initializeAuth();
    initialization.then(
      (ready) => { if (active) setStatus(ready ? "ready" : "login"); },
      (err: unknown) => { if (active) { setError(String(err instanceof Error ? err.message : err)); setStatus("error"); } },
    );
    return () => { active = false; };
  }, []);
  if (status === "ready") return children;
  async function run(action: () => Promise<void>) {
    try { await action(); }
    catch (err) { setError(String(err instanceof Error ? err.message : err)); setStatus("error"); }
  }
  return <main style={{ maxWidth: 520, margin: "15vh auto", padding: 24 }}>
    <h1>{DISPLAY_NAME}</h1>
    <p>配列の設計と編集履歴を、どこからでも。</p>
    {status === "loading" ? <p>接続を確認しています…</p> : <>
      <p>このワークスペースを使うには、許可されたGitHubアカウントでログインしてください。</p>
      {error && <p role="alert" className="tm-error">{error}</p>}
      {isOAuthEnabled() && <>
        <button className="btn" onClick={() => void run(signIn)}>GitHubでログイン</button>
        {status === "error" && <button className="btn" onClick={() => void run(signOut)}>ログアウト</button>}
      </>}
      <button className="btn" onClick={() => window.location.reload()}>再読み込み</button>
    </>}
  </main>;
}
