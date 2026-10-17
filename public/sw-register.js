/* Register the service worker (PWA app-shell caching). */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* SW registration failure is non-fatal */
    });
  });
}
