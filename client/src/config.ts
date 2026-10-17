/**
 * Runtime configuration.
 *
 * The API base URL used to be a hardcoded "http://127.0.0.1:8000" in three
 * places. On a phone that resolves to the phone itself, so the app only
 * worked on the developer's laptop. It now comes from the build environment
 * and defaults to "" (same-origin), which is what a single reverse-proxied
 * deployment wants.
 *
 * Vite inlines import.meta.env at build time, so this stays a static string
 * and costs nothing at runtime.
 */

// Read import.meta.env.VITE_* directly rather than stashing import.meta in a
// variable and dereferencing it later. Vite replaces each of these exact
// expressions at build time, so the result is still a literal string and the
// branch is eliminated. It also works under tools that serve these modules
// through a runner (the jsdom smoke harness), which reject dynamic access to
// the env object outright.
const rawBase = (import.meta.env?.VITE_API_BASE_URL ?? "").trim();

/**
 * API origin, without a trailing slash. Empty means "same origin", which is
 * correct behind a single NGINX/ingress that serves both the SPA and /api.
 */
export const API_BASE_URL = rawBase.replace(/\/+$/, "");

const rawEnv = (import.meta.env?.VITE_APP_ENV ?? "").trim().toLowerCase();

/**
 * True for a real deployment. Governs dev-only affordances and the console
 * warning below. Determined from the flag, and treated as production by
 * default: a misconfigured build should fail closed, not ship dev behaviour.
 */
export const IS_PRODUCTION =
  rawEnv === "production" || rawEnv === "prod";

/**
 * Whether the page is being served over HTTPS. Browsers only honour HTTP
 * Range requests on secure origins for media, so a plain-http deployment
 * gets full-body responses instead. Reported so the UI can explain it rather
 * than silently serving an unseekable video.
 */
export const IS_HTTPS =
  (import.meta.env?.VITE_FORCE_HTTPS ?? "").toLowerCase() === "true" ||
  (typeof window !== "undefined" &&
    window.location?.protocol === "https:");

if (IS_PRODUCTION && API_BASE_URL === "") {
  // Not fatal: same-origin is a legitimate production topology. Worth saying
  // once, because the far more common mistake is a forgotten base URL.
  console.info(
    "[tdac] production build with no VITE_API_BASE_URL: assuming the API is " +
      "served from the same origin as this page.",
  );
} else if (API_BASE_URL) {
  console.info(`[tdac] API base: ${API_BASE_URL} (${IS_PRODUCTION ? "production" : "development"})`);
}
