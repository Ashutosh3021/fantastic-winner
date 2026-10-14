/**
 * Vendored webfonts (§5.5).
 *
 * Two surfaces, two different problems.
 *
 * **Shadow root** — inside a shadow root `url()` resolves against the *host
 * page's* base URL, so a relative `/fonts/…` would be fetched from
 * `leetcode.com`. The `@font-face` rules are read from the packaged stylesheet
 * and re-injected as a `<style>` with absolute `chrome-extension://` URLs. The
 * files are declared as web-accessible resources so the page may load them.
 *
 * **Extension pages** (the popup) — an extension document is already served
 * from `chrome-extension://<id>/`, so a plain `<link>` to the packaged
 * stylesheet resolves correctly and no rewriting is needed.
 *
 * Failure is silent and harmless in both cases: the stack in `styles.css`
 * falls back to system fonts, which is exactly what happened before the
 * webfonts shipped.
 */

const STYLESHEET_PATH = "fonts/fonts.css";

export async function injectFonts(shadow: ShadowRoot): Promise<void> {
  try {
    const response = await fetch(chrome.runtime.getURL(STYLESHEET_PATH));
    if (!response.ok) return;

    const css = await response.text();
    const base = chrome.runtime.getURL("fonts/");

    const style = document.createElement("style");
    style.dataset.codementor = "fonts";
    style.textContent = css.replaceAll("/fonts/", base);
    shadow.appendChild(style);
  } catch {
    // Font loading is an enhancement; never let it break the overlay.
  }
}

/** Idempotent — safe to call on every popup render. */
export function injectDocumentFonts(): void {
  if (document.querySelector('link[data-codementor="fonts"]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = chrome.runtime.getURL(STYLESHEET_PATH);
  link.dataset.codementor = "fonts";
  document.head.appendChild(link);
}