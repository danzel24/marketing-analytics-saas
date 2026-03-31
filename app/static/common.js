/**
 * Shared auth helpers: HttpOnly refresh cookie + access token in localStorage.
 * All API fetches use credentials: "include" and persist x-access-token from middleware.
 */
(function () {
  const TOKEN_KEY = "token";

  window.getToken = function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  };

  window.setToken = function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  };

  window.clearToken = function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  };

  window.isAuthenticated = function isAuthenticated() {
    return Boolean(window.getToken());
  };

  /** Parse FastAPI AppError JSON shape. */
  window.apiErrorMessage = function apiErrorMessage(data) {
    if (data && data.error && data.error.message) return String(data.error.message);
    if (typeof data?.message === "string") return data.message;
    return "Požadavek selhal.";
  };

  /**
   * If no access token in storage, try /auth/me with cookies only — middleware may inject
   * Bearer from refresh and return x-access-token.
   */
  window.bootstrapSession = async function bootstrapSession() {
    if (window.getToken()) return true;
    const res = await fetch("/api/v1/auth/me", { credentials: "include" });
    const x = res.headers.get("x-access-token");
    if (x) {
      window.setToken(x);
      return true;
    }
    return res.ok;
  };

  window.fetchWithAuth = async function fetchWithAuth(url, options) {
    const opts = options || {};
    const headers = new Headers(opts.headers || {});
    const t = window.getToken();
    if (t) headers.set("Authorization", "Bearer " + t);
    const method = (opts.method || "GET").toUpperCase();
    const isFormData =
      typeof FormData !== "undefined" && opts.body instanceof FormData;
    if (
      !isFormData &&
      !headers.has("Content-Type") &&
      method !== "GET" &&
      method !== "HEAD" &&
      opts.body &&
      typeof opts.body === "string"
    ) {
      headers.set("Content-Type", "application/json");
    }
    const res = await fetch(url, { ...opts, headers, credentials: "include" });
    const fresh = res.headers.get("x-access-token");
    if (fresh) window.setToken(fresh);
    return res;
  };

  window.authFetchJson = async function authFetchJson(url, options) {
    const res = await window.fetchWithAuth(url, options || {});
    const ct = res.headers.get("content-type") || "";
    const isJson = ct.includes("application/json");
    const body = isJson ? await res.json() : await res.text();
    if (res.status === 401) {
      window.clearToken();
      throw new Error("Vaše relace vypršela. Přihlaste se prosím znovu.");
    }
    if (!res.ok) throw new Error(window.apiErrorMessage(body));
    return body;
  };
})();
