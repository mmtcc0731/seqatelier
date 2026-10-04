import { Auth0Client } from "@auth0/auth0-spa-js";

type AuthConfig = { mode: "local" | "oauth"; issuer?: string; client_id?: string; audience?: string; scope?: string };
let client: Auth0Client | null = null;
let oauth = false;

export function isOAuthEnabled(): boolean { return oauth; }

export async function initializeAuth(): Promise<boolean> {
  const response = await fetch("/auth/config", { cache: "no-store" });
  if (!response.ok) throw new Error("接続設定を読み込めませんでした。");
  const config: AuthConfig = await response.json();
  if (config.mode === "local") return true;
  if (config.mode !== "oauth" || !config.issuer || !config.client_id || !config.audience || !config.scope) {
    throw new Error("サーバーのログイン設定が不完全です。");
  }
  oauth = true;
  client = new Auth0Client({
    domain: new URL(config.issuer).host,
    clientId: config.client_id,
    authorizationParams: {
      audience: config.audience,
      scope: `openid profile ${config.scope}`,
      redirect_uri: window.location.origin,
    },
    cacheLocation: "memory",
    useRefreshTokens: true,
    useRefreshTokensFallback: true,
  });
  const params = new URLSearchParams(window.location.search);
  if (params.has("state") && (params.has("code") || params.has("error"))) {
    try { await client.handleRedirectCallback(); }
    finally { window.history.replaceState({}, document.title, window.location.pathname); }
  } else {
    await client.checkSession();
  }
  if (!await client.isAuthenticated()) return false;
  const token = await client.getTokenSilently();
  const check = await fetch("/api/session", { headers: { Authorization: `Bearer ${token}` } });
  if (check.status === 403) throw new Error("このワークスペースへのアクセスが許可されていません。登録済みのGitHubアカウントでログインしてください。");
  if (!check.ok) throw new Error("ログインを確認できませんでした。もう一度ログインしてください。");
  return true;
}

export async function signIn(): Promise<void> {
  if (!client) throw new Error("ログイン設定を読み込めませんでした。");
  await client.loginWithRedirect();
}

export async function signOut(): Promise<void> {
  if (client) await client.logout({ logoutParams: { returnTo: window.location.origin } });
}

export async function accessToken(): Promise<string | null> {
  if (client) return (await client.getTokenSilently()) ?? null;
  return sessionStorage.getItem("seqatelier.token");
}
