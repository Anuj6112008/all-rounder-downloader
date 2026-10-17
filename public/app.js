/* IGDesk Downloader — Instagram-focused frontend logic.
   Vanilla JS, no framework. Handles: instant platform badge, fetch, tabs
   (sliding clay indicator), downloads (progress/success/error/retry),
   copy/share, opt-in local history, EN + Hinglish i18n, theme toggle,
   reveal-on-scroll, and a success confetti burst. Never sends history anywhere.
*/
"use strict";

const $ = (id) => document.getElementById(id);
const API = "/api";

/* ---------------- i18n (English + Hinglish) ---------------- */
const I18N = {
  en: {
    install: "Install",
    badge: "✨ 100% Free · No Login",
    title: 'Download Instagram <span class="grad">videos &amp; reels</span>',
    subtitle: "Paste any public Instagram link to save video, MP3 audio and thumbnails in HD. Public content only — download what you own or have permission for.",
    urllabel: "Paste media link",
    placeholder: "https://www.instagram.com/reel/…",
    paste: "Paste", fetch: "Fetch", clear: "Clear",
    copylink: "Copy link", share: "Share",
    tab_video: "🎬 Video", tab_audio: "🎧 Audio", tab_thumb: "🖼️ Thumb",
    step1: "Copy an Instagram link", step2: "Paste it above", step3: "Tap to download",
    features_title: "Why IGDesk?",
    feat1_t: "Lightning fast", feat1_d: "Direct, optimized downloads — no waiting around.",
    feat2_t: "No login ever", feat2_d: "Works on public links only. We never ask for your account.",
    feat3_t: "Video + MP3", feat3_d: "Grab HD video with audio, or convert straight to MP3.",
    feat4_t: "Private by design", feat4_d: "Nothing you download is stored. Links stay on your device.",
    history_title: "🕘 Recent", history_clear: "Clear",
    history_optin: "Save recent links on this device (never sent to a server)",
    nav_about: "About", nav_faq: "FAQ", nav_terms: "Terms", nav_privacy: "Privacy", nav_dmca: "DMCA",
    footer_note: "IGDesk Downloader · Public content only · Built with open-source yt-dlp",
    fetching: "Fetching media info…",
    paste_first: "Please paste a link first.",
    invalid_url: "That doesn't look like a valid http(s) link.",
    empty_url: "Please enter a link.",
    copied: "Link copied!",
    share_unsupported: "Sharing isn't supported on this device — link copied instead.",
    download_started: "Download started…",
    download_done: "Saved! ✅",
    retry: "Retry",
    thumb_hint: "Best resolution, downloadable as JPG / PNG / WEBP",
    mp3_note: "converted", native_note: "native audio",
    best: "best resolution", lossless: "lossless", smallest: "smallest",
    err_default: "Something went wrong. Please try again.",
    unsupported_platform: "Only Instagram links are supported right now.",
  },
  hi: {
    install: "App install karein",
    badge: "✨ 100% Free · Bina Login",
    title: 'Instagram <span class="grad">videos &amp; reels</span> download karein',
    subtitle: "Koi bhi public Instagram link paste karein aur HD me video, MP3 audio aur thumbnails save karein. Sirf public content — jo aapke paas hai ya jiski permission hai wahi download karein.",
    urllabel: "Media link paste karein",
    placeholder: "https://www.instagram.com/reel/…",
    paste: "Paste", fetch: "Fetch karein", clear: "Saaf karein",
    copylink: "Link copy", share: "Share",
    tab_video: "🎬 Video", tab_audio: "🎧 Audio", tab_thumb: "🖼️ Thumb",
    step1: "Instagram link copy karein", step2: "Upar paste karein", step3: "Download ke liye tap karein",
    features_title: "IGDesk kyun?",
    feat1_t: "Tez raftaar", feat1_d: "Seedha optimized download — koi intezaar nahi.",
    feat2_t: "Kabhi login nahi", feat2_d: "Sirf public links par chalta hai. Hum kabhi account nahi maangte.",
    feat3_t: "Video + MP3", feat3_d: "HD video audio ke saath, ya seedha MP3 me convert.",
    feat4_t: "Private by design", feat4_d: "Jo download karte hain wo store nahi hota. Links sirf aapke device par.",
    history_title: "🕘 Recent", history_clear: "Saaf karein",
    history_optin: "Recent links is device par save karein (kabhi server par nahi bheji jaati)",
    nav_about: "About", nav_faq: "FAQ", nav_terms: "Terms", nav_privacy: "Privacy", nav_dmca: "DMCA",
    footer_note: "IGDesk Downloader · Sirf public content · Open-source yt-dlp se bana",
    fetching: "Media info le rahe hain…",
    paste_first: "Pehle ek link paste karein.",
    invalid_url: "Yeh sahi http(s) link nahi lagta.",
    empty_url: "Kripya ek link daalein.",
    copied: "Link copy ho gaya!",
    share_unsupported: "Is device par share supported nahi — link copy kar diya gaya.",
    download_started: "Download shuru…",
    download_done: "Save ho gaya! ✅",
    retry: "Dobara",
    thumb_hint: "Best resolution, JPG / PNG / WEBP me download",
    mp3_note: "converted", native_note: "native audio",
    best: "best resolution", lossless: "lossless", smallest: "smallest",
    err_default: "Kuch galat ho gaya. Dobara try karein.",
    unsupported_platform: "Abhi sirf Instagram links supported hain.",
  },
};
let lang = localStorage.getItem("igdesk.lang") || "en";
const t = (k) => (I18N[lang] && I18N[lang][k]) || I18N.en[k] || k;

/* ---------------- Theme ---------------- */
const themeBtn = $("themeBtn");
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeBtn.textContent = theme === "dark" ? "🌙" : "☀️";
  localStorage.setItem("igdesk.theme", theme);
}
applyTheme(localStorage.getItem("igdesk.theme") || "dark");
themeBtn.addEventListener("click", () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"));

/* ---------------- Language ---------------- */
function applyLang() {
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.innerHTML = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  $("langBtn").innerHTML = lang === "en" ? "EN&nbsp;|&nbsp;हिं" : "हिं&nbsp;|&nbsp;EN";
}
applyLang();
$("langBtn").addEventListener("click", () => {
  lang = lang === "en" ? "hi" : "en";
  localStorage.setItem("igdesk.lang", lang);
  applyLang();
});

/* ---------------- Helpers ---------------- */
function toast(msg, kind = "") {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast " + kind;
  clearTimeout(el._timer);
  requestAnimationFrame(() => el.classList.add("show"));
  el._timer = setTimeout(() => el.classList.remove("show"), 3500);
}
function setStatus(msg, kind = "") {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + kind;
}
function fmtBytes(n) {
  if (n == null) return "";
  const mb = n / (1024 * 1024);
  if (mb >= 1024) return (n / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  if (mb >= 1) return mb.toFixed(1) + " MB";
  return Math.round(n / 1024) + " KB";
}
function fmtDuration(s) {
  if (s == null) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/* Reveal-on-scroll for .reveal sections */
const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

/* Client-side instant badge (Instagram-only). */
const IG_RE = /instagram\.com|instagr\.am/i;
const urlInput = $("urlInput");
const platformBadge = $("platformBadge");
urlInput.addEventListener("input", () => {
  if (IG_RE.test(urlInput.value.trim())) {
    platformBadge.classList.remove("hidden");
    $("platformIcon").textContent = "📸";
    $("platformName").textContent = "Instagram";
  } else {
    platformBadge.classList.add("hidden");
  }
});

/* ---------------- Paste / Clear / Fetch ---------------- */
$("pasteBtn").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) { urlInput.value = text.trim(); urlInput.dispatchEvent(new Event("input")); urlInput.focus(); }
  } catch {
    toast("Clipboard access blocked — please paste manually.", "err");
  }
});
$("clearBtn").addEventListener("click", () => {
  urlInput.value = "";
  platformBadge.classList.add("hidden");
  $("result").classList.add("hidden");
  setStatus("");
  urlInput.focus();
});

let currentInfo = null;

$("fetchBtn").addEventListener("click", doFetch);
urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") doFetch(); });

async function doFetch() {
  const url = urlInput.value.trim();
  if (!url) { setStatus(t("empty_url"), "error"); return; }
  if (!/^https?:\/\//i.test(url) && !/\./.test(url)) { setStatus(t("invalid_url"), "error"); return; }

  const btn = $("fetchBtn");
  btn.disabled = true;
  setStatus(t("fetching"), "loading");
  try {
    const res = await fetch(`${API}/info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data?.error?.message || t("err_default"));
    }
    currentInfo = { ...data, requestUrl: url };
    renderResult(currentInfo);
    setStatus("", "");
    addHistory(url, data.title);
  } catch (err) {
    setStatus(err.message || t("err_default"), "error");
    $("result").classList.add("hidden");
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- Render result ---------------- */
function renderResult(info) {
  $("result").classList.remove("hidden");
  $("rThumb").src = info.thumbnail_url || "/icons/icon-192.png";
  $("rTitle").textContent = info.title;
  $("rUploader").textContent = info.uploader || "—";
  $("rDuration").textContent = fmtDuration(info.duration_seconds);
  $("rPlatform").textContent = `📸 ${info.platform.name}`;

  const vlist = $("videoList");
  vlist.innerHTML = "";
  (info.video_options || []).forEach((o) => vlist.appendChild(videoRow(o)));

  const alist = $("audioList");
  alist.innerHTML = "";
  (info.audio_options || []).forEach((o) => alist.appendChild(audioRow(o)));

  const tp = $("thumbPreview");
  if (info.thumbnail_url) tp.src = info.thumbnail_url;

  $("shareBtn").classList.toggle("hidden", !navigator.share);
  switchTab("video");
}

function videoRow(o) {
  const li = document.createElement("li");
  const btn = document.createElement("button");
  btn.className = "fmt-row dl-btn";
  btn.type = "button";
  btn.dataset.kind = "video";
  btn.dataset.formatId = o.id;
  btn.innerHTML = `
    <span class="fmt-main">
      <span class="fmt-label">${o.label}</span>
      <span class="fmt-note">${o.note || o.ext}${o.fps ? " · " + Math.round(o.fps) + "fps" : ""}</span>
    </span>
    <span class="fmt-side">
      <span class="fmt-size">${fmtBytes(o.filesize_bytes)}</span>
      <span class="dl-ic">⬇️</span>
    </span>`;
  li.appendChild(btn);
  return li;
}

function audioRow(o) {
  const li = document.createElement("li");
  const btn = document.createElement("button");
  btn.className = "fmt-row dl-btn";
  btn.type = "button";
  btn.dataset.kind = o.kind === "mp3" ? "mp3" : "audio";
  btn.dataset.formatId = o.id;
  btn.innerHTML = `
    <span class="fmt-main">
      <span class="fmt-label">${o.label}</span>
      <span class="fmt-note">${o.note || o.ext}</span>
    </span>
    <span class="fmt-side">
      <span class="fmt-size">${fmtBytes(o.filesize_bytes)}</span>
      <span class="dl-ic">⬇️</span>
    </span>`;
  li.appendChild(btn);
  return li;
}

/* ---------------- Tabs (sliding clay indicator) ---------------- */
const tabsEl = document.querySelector(".tabs");
const indicator = document.querySelector(".tab-indicator");
function moveIndicator(tab) {
  if (!indicator || !tab) return;
  const r = tab.getBoundingClientRect();
  const pr = tabsEl.getBoundingClientRect();
  indicator.style.width = r.width + "px";
  indicator.style.transform = `translateX(${r.left - pr.left - 6}px)`;
}
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tb) => {
    const on = tb.dataset.tab === name;
    tb.classList.toggle("active", on);
    tb.setAttribute("aria-selected", on ? "true" : "false");
    if (on) moveIndicator(tb);
  });
  ["video", "audio", "thumb"].forEach((p) => $(`panel-${p}`).classList.toggle("hidden", p !== name));
}
window.addEventListener("resize", () => {
  const active = document.querySelector(".tab.active");
  if (active) moveIndicator(active);
});
setTimeout(() => moveIndicator(document.querySelector(".tab.active")), 60);

/* ---------------- Downloads (event delegation) ---------------- */
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".dl-btn");
  if (!btn) return;
  if (!currentInfo) return;

  if (btn.dataset.kind === "thumb") {
    await downloadThumb(btn.dataset.ext, btn);
    return;
  }
  await downloadMedia(btn.dataset.kind, btn.dataset.formatId, btn);
});

async function downloadMedia(kind, formatId, btn) {
  const url = currentInfo.requestUrl;
  const qs = new URLSearchParams({ url, format_id: formatId, kind });
  setLoading(btn, true);
  try {
    const res = await fetch(`${API}/download?${qs.toString()}`);
    if (!res.ok) {
      let msg = t("err_default");
      try { msg = (await res.json())?.error?.message || msg; } catch {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const fname = parseFilename(cd) || `download.${kind === "mp3" ? "mp3" : "mp4"}`;
    triggerSave(blob, fname);
    markDone(btn);
    toast(t("download_done"), "ok");
    burstConfetti();
  } catch (err) {
    markFail(btn, () => downloadMedia(kind, formatId, btn));
    toast(err.message || t("err_default"), "err");
  } finally {
    setLoading(btn, false);
  }
}

async function downloadThumb(ext, btn) {
  const url = currentInfo.requestUrl;
  const qs = new URLSearchParams({ url, type: ext });
  setLoading(btn, true);
  try {
    const res = await fetch(`${API}/thumb?${qs.toString()}`);
    if (!res.ok) {
      let msg = t("err_default");
      try { msg = (await res.json())?.error?.message || msg; } catch {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const fname = parseFilename(cd) || `thumbnail.${ext}`;
    triggerSave(blob, fname);
    toast(t("download_done"), "ok");
    burstConfetti();
  } catch (err) {
    toast(err.message || t("err_default"), "err");
  } finally {
    setLoading(btn, false);
  }
}

function parseFilename(cd) {
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="([^"]+)"/i.exec(cd);
  if (plain) return plain[1];
  return null;
}

/* Save via object URL + anchor (works for blobs, keeps native save dialog). */
function triggerSave(blob, filename) {
  const a = document.createElement("a");
  const objUrl = URL.createObjectURL(blob);
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
}

function setLoading(btn, on) {
  btn.disabled = on;
  const side = btn.querySelector(".fmt-side");
  if (!side) return;
  if (on) {
    btn._orig = side.innerHTML;
    side.innerHTML = `<span class="spin" aria-hidden="true"></span>`;
    btn.classList.remove("done", "fail");
  } else if (btn._orig) {
    side.innerHTML = btn._orig;
  }
}
function markDone(btn) { btn.classList.add("done"); btn.classList.remove("fail"); }
function markFail(btn, retryFn) {
  btn.classList.add("fail");
  btn.classList.remove("done");
  const side = btn.querySelector(".fmt-side");
  if (side && !side.querySelector(".retry-tag")) {
    const r = document.createElement("button");
    r.className = "btn btn-ghost btn-sm retry-tag";
    r.type = "button";
    r.textContent = t("retry");
    r.addEventListener("click", (ev) => { ev.stopPropagation(); r.remove(); retryFn(); });
    side.appendChild(r);
  }
}

/* Success confetti burst (Instagram gradient colors) */
function burstConfetti() {
  const colors = ["#feda75", "#fa7e1e", "#d62976", "#962fbf", "#4f5bd5"];
  const cx = window.innerWidth / 2, cy = window.innerHeight * 0.4;
  for (let i = 0; i < 26; i++) {
    const c = document.createElement("div");
    c.className = "confetti";
    c.style.left = cx + "px";
    c.style.top = cy + "px";
    c.style.background = colors[i % colors.length];
    document.body.appendChild(c);
    const ang = Math.random() * Math.PI * 2;
    const dist = 90 + Math.random() * 140;
    const dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist - 60;
    c.animate([
      { transform: "translate(0,0) rotate(0deg)", opacity: 1 },
      { transform: `translate(${dx}px, ${dy + 220}px) rotate(${Math.random()*720-360}deg)`, opacity: 0 },
    ], { duration: 1100 + Math.random() * 500, easing: "cubic-bezier(.2,.7,.4,1)" }).onfinish = () => c.remove();
  }
}

/* ---------------- Copy / Share ---------------- */
$("copyBtn").addEventListener("click", async () => {
  if (!currentInfo) return;
  try {
    await navigator.clipboard.writeText(currentInfo.webpage_url || currentInfo.requestUrl);
    toast(t("copied"), "ok");
  } catch { toast("Copy failed", "err"); }
});
$("shareBtn").addEventListener("click", async () => {
  if (!currentInfo) return;
  const data = { title: currentInfo.title, url: currentInfo.webpage_url || currentInfo.requestUrl };
  try {
    if (navigator.share) await navigator.share(data);
  } catch { /* user cancelled or unsupported */ }
});

/* ---------------- Opt-in local history (never sent to server) ---------------- */
const HKEY = "igdesk.history";
const HMAX = 10;
function historyEnabled() { return localStorage.getItem("igdesk.history.enabled") === "1"; }
function getHistory() { try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch { return []; } }
function addHistory(url, title) {
  if (!historyEnabled()) return;
  const list = getHistory().filter((h) => h.url !== url);
  list.unshift({ url, title: title || url, ts: Date.now() });
  localStorage.setItem(HKEY, JSON.stringify(list.slice(0, HMAX)));
  renderHistory();
}
function renderHistory() {
  const sec = $("historySection");
  sec.classList.remove("hidden");
  const ul = $("historyList");
  const clearBtn = $("clearHistoryBtn");
  ul.innerHTML = "";
  if (!historyEnabled()) {
    clearBtn.classList.add("hidden");
    const hint = document.createElement("li");
    hint.className = "history-hint";
    hint.textContent = lang === "hi"
      ? "Neeche switch on karein taaki recent links is device par save hon."
      : "Flip the switch below to save recent links on this device.";
    ul.appendChild(hint);
    return;
  }
  clearBtn.classList.remove("hidden");
  getHistory().forEach((h) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = "#"; a.textContent = h.title; a.title = h.url;
    a.addEventListener("click", (e) => { e.preventDefault(); urlInput.value = h.url; urlInput.dispatchEvent(new Event("input")); doFetch(); });
    li.appendChild(a);
    ul.appendChild(li);
  });
}
const historyToggle = $("historyToggle");
historyToggle.checked = historyEnabled();
historyToggle.addEventListener("change", () => {
  localStorage.setItem("igdesk.history.enabled", historyToggle.checked ? "1" : "0");
  if (!historyToggle.checked) localStorage.removeItem(HKEY);
  renderHistory();
});
$("clearHistoryBtn").addEventListener("click", () => { localStorage.removeItem(HKEY); renderHistory(); });
renderHistory();

/* ---------------- Platform registry from API ---------------- */
async function loadPlatforms() {
  try {
    const res = await fetch(`${API}/platforms`);
    const data = await res.json();
    const ul = $("platformList");
    ul.innerHTML = "";
    (data.platforms || []).forEach((p) => {
      const li = document.createElement("li");
      li.className = p.enabled ? "ok" : "soon";
      li.innerHTML = `<span aria-hidden="true">${p.icon}</span> ${p.name} <span class="p-status">${p.enabled ? "✓" : t("coming_soon") || "soon"}</span>`;
      ul.appendChild(li);
    });
  } catch { /* non-fatal */ }
}
loadPlatforms();

/* ---------------- PWA install prompt ---------------- */
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  $("installBtn").classList.remove("hidden");
});
$("installBtn").addEventListener("click", async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  $("installBtn").classList.add("hidden");
});
