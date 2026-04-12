/* global Chart */

const els = {
  dashboardSection: document.getElementById("dashboardSection"),
  logoutBtn: document.getElementById("logoutBtn"),
  adminBtn: document.getElementById("admin-btn"),

  status: document.getElementById("status"),
  kpiRevenue: document.getElementById("kpiRevenue"),
  kpiSpend: document.getElementById("kpiSpend"),
  kpiProfit: document.getElementById("kpiProfit"),
  kpiRoas: document.getElementById("kpiRoas"),
  kpiRoasMeta: document.getElementById("kpiRoasMeta"),
  kpiBreakEvenRoas: document.getElementById("kpiBreakEvenRoas"),
  marginInfo: document.getElementById("marginInfo"),
  marginFallbackInfo: document.getElementById("marginFallbackInfo"),
  kpiLoss: document.getElementById("kpiLoss"),
  kpiLossMeta: document.getElementById("kpiLossMeta"),
  kpiLossCard: document.getElementById("kpiLossCard"),
  headlineBanner: document.getElementById("headlineBanner"),
  headlineText: document.getElementById("headlineText"),
  riskBanner: document.getElementById("riskBanner"),
  riskBannerText: document.getElementById("riskBannerText"),
  riskBannerSub: document.getElementById("riskBannerSub"),
  primaryAction: document.getElementById("primaryAction"),
  insightsList: document.getElementById("insightsList"),
  actionBoxToday: document.getElementById("actionBoxToday"),
  actionBoxTodayList: document.getElementById("actionBoxTodayList"),
  primaryRecommendationCard: document.getElementById("primaryRecommendationCard"),
  kpiProfitImpact: document.getElementById("kpiProfitImpact"),
  kpiProfitLabel: document.getElementById("kpiProfitLabel"),
  dataTrustStrip: document.getElementById("dataTrustStrip"),
  dataTrustWindow: document.getElementById("dataTrustWindow"),
  dataTrustSources: document.getElementById("dataTrustSources"),
  dataTrustUpdated: document.getElementById("dataTrustUpdated"),
  kpiTrustMicrocopy: document.getElementById("kpiTrustMicrocopy"),
  tbody: document.getElementById("campaignTbody"),
  revenueCanvas: document.getElementById("revenueChart"),
  spendCanvas: document.getElementById("spendChart"),
  marginPercentInput: document.getElementById("marginPercentInput"),
  marginApplyBtn: document.getElementById("marginApplyBtn"),
  marginSaveStatus: document.getElementById("marginSaveStatus"),
};

let charts = { revenue: null, spend: null, profit: null };
let selectedDays = 30;

const chartDefaults = {
  color: "rgba(255,255,255,0.5)",
  borderColor: "rgba(255,255,255,0.08)",
};

Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;

/* ── Formatters ─────────────────────────────────────────── */

function money(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n) + " Kč";
}

/* Explicit +/- sign — use for profit column or when sign conveys information */
function signedMoney(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return sign + new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n) + " Kč";
}

/* Absolute value, no sign — use when the surrounding text already says "ztráta"/"prodělává" */
function absMoney(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.abs(n)) + " Kč";
}

function roasFmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n) + "×";
}

function percentFmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${Math.round(Number(n) * 100)} %`;
}

function setStatus(text, kind = "info") {
  els.status.textContent = text || "";
  els.status.dataset.kind = kind;
}

function toFiniteNumber(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function hasPartialData(data) {
  const revenueLabels = data?.revenue_trend?.labels ?? [];
  const revenueValues = data?.revenue_trend?.revenue ?? data?.revenue_trend?.values ?? [];
  const spendLabels = data?.spend_trend?.labels ?? [];
  const spendValues = data?.spend_trend?.spend ?? data?.spend_trend?.values ?? [];
  if (revenueLabels.length !== revenueValues.length) return true;
  if (spendLabels.length !== spendValues.length) return true;
  const bad = (v) => v !== null && v !== undefined && !Number.isFinite(Number(v));
  return revenueValues.some(bad) || spendValues.some(bad);
}

function findScenario(scenarios, targetMargin) {
  const safe = Array.isArray(scenarios) ? scenarios : [];
  return safe.find((s) => Math.abs(Number(s?.margin) - targetMargin) < 0.001);
}

function extractScenarioProfits(data) {
  const scenarios = Array.isArray(data?.scenarios) ? data.scenarios : [];
  const s04 = findScenario(scenarios, 0.4);
  const s06 = findScenario(scenarios, 0.6);
  const s07 = findScenario(scenarios, 0.7);
  return {
    profit_0_4: Number.isFinite(Number(s04?.profit)) ? Number(s04.profit) : null,
    profit_0_6: Number.isFinite(Number(s06?.profit)) ? Number(s06.profit) : null,
    profit_0_7: Number.isFinite(Number(s07?.profit)) ? Number(s07.profit) : null,
  };
}

function formatCZK(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Number(value))} Kč`;
}

function renderScenarioInsights(container, scenarioProfits) {
  if (!container) return;
  container.className = "scenario-insights-wrap";
  container.style.marginBottom = "10px";
  const p40 = Number(scenarioProfits?.profit_0_4);
  const p60 = Number(scenarioProfits?.profit_0_6);
  const p70 = Number(scenarioProfits?.profit_0_7);
  const marginInfoText = document.getElementById("marginInfo")?.textContent || "";
  const marginMatch = marginInfoText.match(/(\d+)\s*%/);
  const currentMargin = marginMatch ? Number(marginMatch[1]) / 100 : null;

  const colorFor = (v) => {
    if (!Number.isFinite(v)) return "rgba(255,255,255,0.65)";
    return v < 0 ? "var(--red)" : "var(--green)";
  };
  const rowStyleForMargin = (targetMargin) => {
    if (currentMargin === null) return "";
    return Math.abs(currentMargin - targetMargin) < 0.001
      ? "padding:2px 6px;border-radius:8px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.35);"
      : "";
  };
  let interpretation = "Maržové scénáře doplníme, až budou data.";
  if (Number.isFinite(p40) && Number.isFinite(p60)) {
    if (p40 < 0 && p60 > 0) {
      interpretation = "Při vyšší marži by číslo pod čarou bylo lepší (orientačně).";
    } else if (p40 < 0 && p60 < 0) {
      interpretation = "I při vyšší marži zůstává zisk pod tlakem (orientačně).";
    } else {
      interpretation = "Při této marži vychází orientační zisk z přehledu.";
    }
  }
  container.innerHTML = `
    <details class="scenario-box scenario-box--collapsible card">
      <summary class="scenario-box__summary">Zobrazit scénáře marže</summary>
      <div class="scenario-box__body">
        <div class="kpi__label scenario-box__label">Marže (orientace)</div>
        <div style="${rowStyleForMargin(0.4)}">Při marži 40 %: <strong style="color:${colorFor(p40)};">${formatCZK(scenarioProfits?.profit_0_4)}</strong></div>
        <div style="${rowStyleForMargin(0.6)}">Při marži 60 %: <strong style="color:${colorFor(p60)};">${formatCZK(scenarioProfits?.profit_0_6)}</strong></div>
        <div style="${rowStyleForMargin(0.7)}">Při marži 70 %: <strong style="color:${colorFor(p70)};">${formatCZK(scenarioProfits?.profit_0_7)}</strong></div>
        <div class="kpi__helper scenario-box__foot">${interpretation}</div>
      </div>
    </details>
  `;
}

/* ── Auth helpers ───────────────────────────────────────── */
/* Use window.getToken / clearToken from common.js only — do not declare global
   function getToken() here: it would overwrite window.getToken and recurse. */

function forceRelogin() {
  window.clearToken();
  destroyCharts();
  resetDashboardUi();
  window.location.href = "/login";
}

async function authFetch(url, options = {}) {
  try {
    return await window.authFetchJson(url, options);
  } catch (e) {
    const msg = String(e.message || "");
    if (msg.includes("Vypršela") || msg.includes("relace")) {
      forceRelogin();
    }
    throw e;
  }
}

function fetchJson(url) {
  return authFetch(url);
}

async function loadCurrentUser() {
  try {
    const me = await fetchJson("/api/v1/auth/me");
    if (els.marginPercentInput && me && me.margin_percent != null) {
      const p = Number(me.margin_percent);
      if (Number.isFinite(p) && p >= 1 && p <= 99) {
        els.marginPercentInput.value = String(Math.round(p));
      }
    }
    if (els.marginSaveStatus) els.marginSaveStatus.textContent = "";
    if (els.adminBtn && me?.is_admin === true) {
      els.adminBtn.style.display = "inline-block";
      els.adminBtn.onclick = () => {
        window.location.href = "/admin";
      };
    } else if (els.adminBtn) {
      els.adminBtn.style.display = "none";
      els.adminBtn.onclick = null;
    }
  } catch {
    if (els.marginSaveStatus) els.marginSaveStatus.textContent = "";
    if (els.adminBtn) {
      els.adminBtn.style.display = "none";
      els.adminBtn.onclick = null;
    }
  }
}

function initMarginBar() {
  if (!els.marginApplyBtn || !els.marginPercentInput) return;
  els.marginApplyBtn.addEventListener("click", () => {
    applyMarginFromInput();
  });
  els.marginPercentInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      applyMarginFromInput();
    }
  });
}

async function applyMarginFromInput() {
  const inp = els.marginPercentInput;
  const st = els.marginSaveStatus;
  if (!inp || !st) return;
  const raw = parseInt(String(inp.value).trim(), 10);
  if (!Number.isFinite(raw) || raw < 1 || raw > 99) {
    st.textContent = "Zadejte celé číslo 1–99 (marže v %).";
    return;
  }
  st.textContent = "Ukládám…";
  try {
    await window.authFetchJson("/api/v1/client/margin", {
      method: "PATCH",
      body: JSON.stringify({ margin_percent: raw }),
    });
    st.textContent = "";
    await loadDashboard();
  } catch (e) {
    st.textContent = String(e.message || e || "Nepodařilo se uložit marži.");
  }
}

/* ── Charts ─────────────────────────────────────────────── */

function destroyCharts() {
  Object.keys(charts).forEach((k) => {
    if (charts[k]) { charts[k].destroy(); charts[k] = null; }
  });
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function campaignStrong(name) {
  return `<strong class="campaign-strong">${escapeHtml(name || "Kampaň")}</strong>`;
}

function moneyStrong(text) {
  return `<strong class="money-strong">${escapeHtml(text)}</strong>`;
}

function profitPhrase(value) {
  return `${signedMoney(toFiniteNumber(value))} zisku po reklamě`;
}

function lossPhrase(value) {
  return `ztráta ${absMoney(value)}`;
}

function getStatusMeta(status) {
  switch (status) {
    case "loss":
      return { label: "Ztrátová", class: "roas-low", insightType: "danger", icon: "❌" };
    case "at_risk":
      return {
        label: "Mírně pod bodem zvratu",
        class: "roas-medium",
        insightType: "warning",
        icon: "⚠️",
      };
    case "profitable":
      return { label: "Zisková", class: "roas-high", insightType: "positive", icon: "✅" };
    case "insufficient_data":
      return {
        label: "⚪ Nedostatek dat — zatím nedoporučujeme akci",
        class: "",
        insightType: "info",
        icon: "",
      };
    default:
      return { label: "Neznámé", class: "", insightType: "info", icon: "❓" };
  }
}

/** ROAS KPI barva podle ``average_roas_status`` z API (bez výpočtů pásem na klientovi). */
function roasKpiClassFromApiStatus(band) {
  const b = String(band || "");
  if (b === "profitable") return "roas-high";
  if (b === "loss") return "roas-low";
  return "roas-medium";
}

/** Jedna hlavní akce bez emoji (Škálovat, Upravit, …). */
function stripLeadingEmoji(s) {
  return String(s || "")
    .replace(/^[\s\uFE0F✅❌⚠️ℹ️🚀🔥⚪]+/gu, "")
    .trim();
}

/** Rozdělí rec_reason na střední a drobný řádek (oddělovač „ · “). */
function splitRecReason(raw) {
  const s = String(raw || "").trim();
  if (!s) return { mid: "", small: "" };
  const sep = " · ";
  const i = s.indexOf(sep);
  if (i === -1) return { mid: s.replace(/\.$/, ""), small: "" };
  return {
    mid: s.slice(0, i).trim().replace(/\.$/, ""),
    small: s.slice(i + sep.length).trim().replace(/\.$/, ""),
  };
}

/** Slabší technické názvy (google_ads → Google Ads). */
function humanizeCampaignName(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (/^[a-z0-9_.-]+$/i.test(s) && /[_-]/.test(s)) {
    return s
      .split(/[_-]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }
  return s;
}

/** Krátký důvod do tabulky (skenuje se okem). */
function shortTableReason(status) {
  const st = String(status || "");
  if (st === "profitable") return "ROAS nad BE";
  if (st === "at_risk") return "Mírně pod BE";
  if (st === "loss") return "ROAS pod BE";
  if (st === "insufficient_data") return "—";
  return "—";
}

/* ── Render: Headline banner ─────────────────────────────── */

function renderHeadline(_data) {
  if (els.headlineBanner) {
    els.headlineBanner.classList.add("hidden");
    els.headlineBanner.setAttribute("aria-hidden", "true");
  }
  if (els.headlineText) els.headlineText.textContent = "";
  const sub = document.getElementById("headlineSub");
  if (sub) sub.textContent = "";
  const oldHint = document.getElementById("headlineHint");
  if (oldHint) oldHint.remove();
}

/* ── Onboarding / summary strip (below headline) ─────────── */

function renderOnboardingInsight(_overview) {
  const el = document.getElementById("onboardingInsight");
  if (el) {
    el.classList.add("hidden");
    el.textContent = "";
  }
}

function resetOnboardingInsight() {
  const el = document.getElementById("onboardingInsight");
  if (!el) return;
  el.classList.add("hidden");
  el.textContent = "";
}

/* ── Charts: empty state ─────────────────────────────────── */

function setChartsEmptyState(isEmpty) {
  const grid = document.querySelector(".charts-grid");
  if (!grid) return;

  let msg = document.getElementById("chartsEmptyMessage");
  if (!msg) {
    msg = document.createElement("div");
    msg.id = "chartsEmptyMessage";
    msg.className = "card";
    msg.style.gridColumn = "1 / -1";
    msg.style.textAlign = "center";
    msg.style.padding = "24px";
    grid.insertBefore(msg, grid.firstChild);
  }

  grid.querySelectorAll(".chart-container").forEach((c) => {
    c.classList.toggle("hidden", Boolean(isEmpty));
  });

  if (isEmpty) {
    destroyCharts();
    msg.textContent = "Nahrajte CSV — zobrazíme trendy v čase.";
    msg.classList.remove("hidden");
  } else {
    msg.classList.add("hidden");
    msg.textContent = "";
  }
}

function resetChartsSection() {
  setChartsEmptyState(false);
}

/* ── Render: Risk banner (revenue at risk) ────────────── */

function campaignCountWord(n) {
  const k = Math.abs(Number(n)) || 0;
  if (k === 1) return "kampaň";
  if (k >= 2 && k <= 4) return "kampaně";
  return "kampaní";
}

/**
 * ``at_risk`` = buffer kolem bodu zvratu (backend). Banner rozliší, jestli už jde o ROAS pod BE
 * nebo záporný příspěvek — bez přepočtu pásem, jen čtení polí z řádků.
 */
function renderRiskBanner(campaigns, breakEven) {
  const be = toFiniteNumber(breakEven ?? 2.5);
  const safe = Array.isArray(campaigns) ? campaigns : [];
  const atRisk = safe.filter((c) => String(c.status || "") === "at_risk");

  let revenueAtRisk = 0;
  for (const c of atRisk) {
    revenueAtRisk += toFiniteNumber(c.revenue);
  }

  if (atRisk.length === 0 || revenueAtRisk <= 0) {
    els.riskBanner.classList.add("hidden");
    return;
  }

  let anyBelowBe = false;
  let anyNegativeContribution = false;
  for (const c of atRisk) {
    const roas = toFiniteNumber(c.roas);
    const cbe = toFiniteNumber(c.break_even_roas || be);
    const profit = toFiniteNumber(
      c.profit ?? c.contribution_profit ?? c.marketing_profit,
    );
    if (cbe > 0 && roas < cbe - 1e-9) anyBelowBe = true;
    if (profit < 0) anyNegativeContribution = true;
  }

  const n = atRisk.length;
  const cw = campaignCountWord(n);
  const moneyPart = `${moneyStrong(money(revenueAtRisk))} tržeb u ${n} ${cw}`;

  if (anyBelowBe || anyNegativeContribution) {
    els.riskBannerText.innerHTML = `⚠️ ${moneyPart} — mírně pod bodem zvratu nebo už v záporném příspěvku`;
    els.riskBannerSub.textContent = `Cílový ROAS je ${roasFmt(be)}. Pod touto hranou se ztráta z marketingu prohlubuje.`;
  } else {
    els.riskBannerText.innerHTML = `⚠️ ${moneyPart} — těsně u bodu zvratu`;
    els.riskBannerSub.textContent = `Držte ROAS kolem ${roasFmt(be)} — pod ním hrozí prohloubení ztráty.`;
  }
  els.riskBanner.classList.remove("hidden");
}

/* ── Render: KPIs ───────────────────────────────────────── */

function formatTrustTimestamp(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("cs-CZ", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return String(iso);
  }
}

function renderTrustStrip(trust) {
  if (!els.dataTrustStrip) return;
  if (!trust || typeof trust !== "object") {
    els.dataTrustStrip.classList.add("hidden");
    return;
  }
  const desc = String(trust.window_description || "").trim() || "—";
  const sources = Array.isArray(trust.sources) ? trust.sources.filter(Boolean) : [];
  const srcLine =
    sources.length > 0
      ? `Zdroj: ${sources.join(", ")}`
      : "Zdroj: —";
  const lastM = trust.last_metric_date ? `Poslední den v datech: ${trust.last_metric_date}` : "Poslední den v datech: —";
  const comp = trust.computed_at
    ? `Výpočet přehledu: ${formatTrustTimestamp(trust.computed_at)}`
    : "Výpočet přehledu: —";
  if (els.dataTrustWindow) els.dataTrustWindow.textContent = desc;
  if (els.dataTrustSources) els.dataTrustSources.textContent = srcLine;
  if (els.dataTrustUpdated) els.dataTrustUpdated.textContent = `${lastM} · ${comp}`;
  els.dataTrustStrip.classList.remove("hidden");
}

function renderPrimaryRecommendation(pr) {
  const el = els.primaryRecommendationCard;
  if (!el) return;
  if (!pr || typeof pr !== "object") {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  const recAction = String(pr.rec_action || "").trim();
  const text = String(pr.text || "").trim();
  if (!recAction && !text) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  const title = escapeHtml(String(pr.title || ""));
  const icon = escapeHtml(String(pr.icon || "🔥"));
  const campRaw = humanizeCampaignName(String(pr.campaign || ""));
  const campaign = campRaw ? escapeHtml(campRaw) : "";
  const impact = escapeHtml(String(pr.impact_text || "").trim());
  const recReasonRaw = String(pr.rec_reason || "").trim();
  const actionLabelRaw = String(pr.action_label || "").trim();
  const confidence = escapeHtml(String(pr.confidence_label || "").trim());
  const isOpp = String(pr.title || "").includes("příležitost");
  el.className = isOpp
    ? "primary-recommendation-card primary-recommendation-card--opportunity primary-recommendation-card--compact"
    : "primary-recommendation-card primary-recommendation-card--compact";
  const eyebrowInner = [icon, title].filter(Boolean).join(" ").trim();
  const verb = stripLeadingEmoji(actionLabelRaw) || stripLeadingEmoji(recAction) || text;
  const { mid, small } = splitRecReason(recReasonRaw);
  const lineMid = escapeHtml(mid);
  const lineSmall = escapeHtml(small);
  const verbHtml = escapeHtml(verb).toUpperCase();
  const bodyLines = [];
  if (lineMid) bodyLines.push(`<p class="primary-recommendation-card__mid">${lineMid}</p>`);
  if (lineSmall) bodyLines.push(`<p class="primary-recommendation-card__small">${lineSmall}</p>`);
  if (!lineMid && recReasonRaw) {
    bodyLines.push(`<p class="primary-recommendation-card__mid">${escapeHtml(recReasonRaw)}</p>`);
  }
  const campLine = campaign
    ? `<div class="primary-recommendation-card__campaign">${campaign}</div>`
    : "";
  const confLine = confidence
    ? `<p class="primary-recommendation-card__confidence">${confidence}</p>`
    : "";
  const stepsRaw = String(pr.action_steps || "").trim();
  const stepsLine = stepsRaw
    ? `<p class="primary-recommendation-card__action-steps">${escapeHtml(stepsRaw)}</p>`
    : "";
  const trustLines = `<div class="primary-recommendation-card__trust"><p>Na základě dat za posledních ${selectedDays} dní.</p><p>Model nebere v úvahu fixní náklady.</p></div>`;
  el.innerHTML = `
    <div class="primary-recommendation-card__eyebrow">${eyebrowInner}</div>
    ${campLine}
    <p class="primary-recommendation-card__verb" aria-label="Co udělat">${verbHtml}</p>
    ${confLine}
    <div class="primary-recommendation-card__body">${bodyLines.join("")}</div>
    ${stepsLine}
    ${impact ? `<p class="primary-recommendation-card__footer">${impact}</p>` : ""}
    ${trustLines}
  `;
  el.classList.remove("hidden");
}

function renderActionBoxToday(items, primaryRec) {
  const box = els.actionBoxToday;
  const list = els.actionBoxTodayList;
  if (!box || !list) return;
  const safe = Array.isArray(items) ? items : [];
  const hasPrimary =
    primaryRec &&
    typeof primaryRec === "object" &&
    (String(primaryRec.rec_action || primaryRec.text || "").trim().length > 0);
  list.innerHTML = "";
  if (safe.length === 0 && !hasPrimary) {
    box.classList.add("hidden");
    return;
  }
  for (const it of safe) {
    const li = document.createElement("li");
    const sev = it.severity || "info";
    const isHold =
      sev === "info" && String(it.text || "").includes("Nedostatek dat");
    li.className = isHold
      ? "action-box-today__item action-box-today__item--hold"
      : `action-box-today__item action-box-today__item--${sev}`;
    const icon = escapeHtml(String(it.icon || (isHold ? "" : "•")));
    const rs = String(it.rec_status || "").trim();
    const ra = String(it.rec_action || "").trim();
    const rr = String(it.rec_reason || "").trim();
    const fallback = String(it.text || "");
    const impact = escapeHtml(String(it.impact_text || "").trim());
    const camp = escapeHtml(humanizeCampaignName(String(it.campaign || "")));
    let block = "";
    if (ra && rr) {
      const verb = stripLeadingEmoji(String(it.action_label || "")) || stripLeadingEmoji(ra);
      const { mid, small } = splitRecReason(rr);
      const l2 = small
        ? `<div class="action-box-today__item-reason"><span class="action-box-today__item-mid">${escapeHtml(mid)}</span><span class="action-box-today__item-small">${escapeHtml(small)}</span></div>`
        : `<div class="action-box-today__item-reason">${escapeHtml(rr)}</div>`;
      block = `<div class="action-box-today__item-structured">
        <div class="action-box-today__item-main">${icon ? `${icon} ` : ""}<strong>${escapeHtml(verb)}</strong>${camp ? ` · ${camp}` : ""}</div>
        ${l2}
      </div>`;
    } else {
      const text = escapeHtml(fallback);
      const mainLine = icon ? `${icon} ${text}` : text;
      block = `<div class="action-box-today__item-main">${mainLine}${camp ? ` · ${camp}` : ""}</div>`;
    }
    const showImpact = impact && !(ra && rr);
    li.innerHTML = `${block}${showImpact ? `<div class="action-box-today__item-impact">${impact}</div>` : ""}`;
    list.appendChild(li);
  }
  box.classList.remove("hidden");
}

function renderKpis(overview, lossSummary) {
  els.kpiRevenue.textContent = money(overview.total_revenue);
  els.kpiSpend.textContent = money(overview.total_spend);

  const marginPct = Number(overview.margin ?? overview.margin_used);
  if (els.kpiProfitLabel) {
    if (Number.isFinite(marginPct) && marginPct > 0 && marginPct <= 1) {
      const p = Math.round(marginPct * 100);
      els.kpiProfitLabel.innerHTML = `Zisk (po marži ${p} %) <span class="tooltip" data-tip="Zisk počítáme jako: tržby × marže − náklady na reklamu. Nejde o účetní čistý zisk (bez DPH, logistiky apod.).">?</span>`;
    } else {
      els.kpiProfitLabel.innerHTML = `Zisk (po marži … %) <span class="tooltip" data-tip="Zisk počítáme jako: tržby × marže − náklady na reklamu. Nejde o účetní čistý zisk (bez DPH, logistiky apod.).">?</span>`;
    }
  }

  const profit = toFiniteNumber(
    overview.total_marketing_profit ?? overview.total_profit
  );
  els.kpiProfit.textContent = signedMoney(profit);
  els.kpiProfit.style.color = "";
  els.kpiProfit.classList.remove("kpi__value--loss-hero", "kpi__value--gain-hero");
  if (els.kpiProfitImpact) {
    if (profit < 0) {
      els.kpiProfitImpact.textContent = "ZTRÁCÍTE";
      els.kpiProfitImpact.className = "kpi-profit-impact kpi-profit-impact--loss";
      els.kpiProfit.classList.add("kpi__value--loss-hero");
    } else if (profit > 0) {
      els.kpiProfitImpact.textContent = "VYDĚLÁVÁTE";
      els.kpiProfitImpact.className = "kpi-profit-impact kpi-profit-impact--gain";
      els.kpiProfit.classList.add("kpi__value--gain-hero");
    } else {
      els.kpiProfitImpact.textContent = "";
      els.kpiProfitImpact.className = "kpi-profit-impact";
    }
  }

  const beRaw = Number(overview.break_even_roas);
  const beDisplay = Number.isFinite(beRaw) && beRaw > 0 ? beRaw : null;
  els.kpiBreakEvenRoas.textContent = beDisplay === null ? "—" : roasFmt(beDisplay);

  const avg = toFiniteNumber(overview.average_roas);
  const be = toFiniteNumber(overview.break_even_roas ?? 2.5);
  const band = String(overview.average_roas_status || "");
  const cls = roasKpiClassFromApiStatus(band);

  els.kpiRoas.classList.remove("roas-high", "roas-medium", "roas-low");
  els.kpiRoas.classList.add(cls);
  els.kpiRoas.textContent = roasFmt(avg);

  let badgeClass;
  let badgeLabel;
  if (band === "profitable") {
    badgeClass = "kpi__badge--profit";
    badgeLabel = "Nad cílem";
  } else if (band === "loss") {
    badgeClass = "kpi__badge--loss";
    badgeLabel = "Pod cílem";
  } else if (band === "insufficient_data") {
    badgeClass = "kpi__badge--breakeven";
    badgeLabel = "Bez dat";
  } else {
    badgeClass = "kpi__badge--breakeven";
    badgeLabel = "Mírně pod BE";
  }
  const roasInfo = `<span id="roasInfo" class="kpi__helper">Bod zvratu: ${beDisplay === null ? "—" : roasFmt(beDisplay)}</span>`;
  els.kpiRoasMeta.innerHTML = `<span class="kpi__badge ${badgeClass}">${badgeLabel}</span>${roasInfo}`;

  const totalLoss = toFiniteNumber(lossSummary?.total_loss);
  const lossCount = toFiniteNumber(lossSummary?.loss_count);
  els.kpiLoss.style.color = "";
  if (lossCount > 0) {
    els.kpiLoss.textContent = absMoney(totalLoss);
    els.kpiLossMeta.textContent = `${lossCount} kampan${lossCount === 1 ? "ě" : lossCount < 5 ? "ě" : "í"} pod bodem zvratu`;
  } else {
    els.kpiLoss.textContent = "0 Kč";
    els.kpiLoss.style.color = "var(--green)";
    els.kpiLossMeta.textContent = lossSummary?.message || "Žádné kampaně pod bodem zvratu";
  }

  const trustEl = els.kpiTrustMicrocopy || document.getElementById("kpiTrustMicrocopy");
  if (trustEl) {
    trustEl.textContent = `Výkon za posledních ${selectedDays} dní podle nahraných dat.`;
  }

  const partialEl = document.getElementById("partialDataNote");
  if (partialEl) {
    if (overview.has_partial_data === true) {
      partialEl.textContent = "Poslední den může být neúplný.";
      partialEl.classList.remove("hidden");
    } else {
      partialEl.textContent = "";
      partialEl.classList.add("hidden");
    }
  }
}

function renderPeriodComparison(overview) {
  const wrap = document.getElementById("kpiPeriodComparison");
  if (!wrap) return;
  const ok =
    overview.prior_period_available === true && overview.prior_period_has_comparisons === true;
  if (!ok) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }
  const rows = [];
  const addRow = (label, key) => {
    const raw = overview[key];
    if (raw === null || raw === undefined) return;
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    const sign = n >= 0 ? "+" : "";
    const cls = n >= 0 ? "kpi-period-comparison__pct--pos" : "kpi-period-comparison__pct--neg";
    rows.push(
      `<div class="kpi-period-comparison__row"><span class="kpi-period-comparison__label">${escapeHtml(label)}</span><span class="kpi-period-comparison__pct ${cls}">${sign}${n} % vs minulé období</span></div>`,
    );
  };
  addRow("Tržby", "revenue_change_pct");
  addRow("Náklady", "spend_change_pct");
  addRow("Čistý zisk", "profit_change_pct");
  addRow("ROAS", "roas_change_pct");
  if (rows.length === 0) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = `<div class="kpi-period-comparison card">${rows.join("")}</div>`;
}

function dataReliabilityTip(tier) {
  const t = String(tier || "");
  if (t === "high") {
    return "Odhad výkonu je spolehlivější (více dat, stabilnější vzorek).";
  }
  if (t === "medium") {
    return "Orientační odhad — krátší období nebo méně bodů v datech.";
  }
  return "Slabší signál — málo dat nebo krátké okno; vyhodnocujte opatrně.";
}

function renderDataReliabilityBadge(overview) {
  const el = document.getElementById("dataReliabilityBadge");
  if (!el) return;
  const label = String(overview.data_reliability_label_cs || "").trim();
  if (!label) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("data-reliability-badge--high", "data-reliability-badge--med", "data-reliability-badge--low");
  const tier = String(overview.data_reliability || "");
  if (tier === "high") el.classList.add("data-reliability-badge--high");
  else if (tier === "medium") el.classList.add("data-reliability-badge--med");
  else el.classList.add("data-reliability-badge--low");

  const tip = dataReliabilityTip(tier);
  const tipEsc = escapeHtml(tip);
  const ariaShort = escapeHtml(`Spolehlivost dat ${label}: ${tip}`);
  el.classList.remove("hidden");
  el.innerHTML = `<span class="data-reliability-badge__label">Spolehlivost dat: ${escapeHtml(label)}</span> <button type="button" class="tooltip tooltip--btn" data-tip="${tipEsc}" aria-label="${ariaShort}">i</button>`;
}

function setDashboardLoading(on) {
  document.querySelectorAll(".filter-btn").forEach((b) => {
    b.disabled = on;
  });
  const hint = document.getElementById("dashboardLoadHint");
  if (hint) hint.classList.toggle("hidden", !on);
}

function renderDashboardEmptyBanner(show) {
  const el = document.getElementById("dashboardEmptyBanner");
  if (!el) return;
  el.classList.toggle("hidden", !show);
  const main = document.getElementById("dashboardSection");
  if (main) main.classList.toggle("dashboard-section--empty", Boolean(show));
}

function renderMarginInfo(data) {
  const marginFromOverview = data?.overview?.margin_used;
  const marginFromMeta = data?.meta?.margin_used;
  const marginRaw = marginFromOverview ?? marginFromMeta;
  const margin = Number(marginRaw);

  if (els.marginInfo) {
    if (Number.isFinite(margin) && margin > 0 && margin <= 1) {
      els.marginInfo.textContent = `Použitá marže: ${percentFmt(margin)}`;
    } else {
      els.marginInfo.textContent = "Použitá marže: —";
    }
  }

  if (els.marginFallbackInfo) {
    const marginMissing = marginFromOverview == null && marginFromMeta == null;
    // TODO: Bez explicitního backend příznaku nelze spolehlivě odlišit výchozí marži od klientsky nastavené.
    if (marginMissing) els.marginFallbackInfo.classList.remove("hidden");
    else els.marginFallbackInfo.classList.add("hidden");
  }
}

/* ── Render: Table ──────────────────────────────────────── */

function renderTopCampaigns(topCampaigns, breakEven) {
  els.tbody.innerHTML = "";
  if (!topCampaigns || topCampaigns.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="10" class="empty-row">Zatím nemáte nahraná data. Nahrajte CSV pro přehled kampaní a ROAS.</td>`;
    els.tbody.appendChild(tr);
    return;
  }

  const be = toFiniteNumber(breakEven ?? 2.5);

  /* Pořadí z API (např. nejhorší zisk první) — bez dalšího řazení na klientovi */
  const sorted = [...topCampaigns];

  for (const c of sorted) {
    const rv = toFiniteNumber(c.roas);
    const pv = toFiniteNumber(c.profit);
    const status = String(c.status || "");
    const statusMeta = getStatusMeta(status);
    const campaignBreakEven = toFiniteNumber(c.break_even_roas || be);

    // Profit cell colour from backend status (single source of truth)
    let profitClass;
    if (status === "loss") profitClass = "profit-negative";
    else if (status === "at_risk") profitClass = "profit-neutral";
    else if (status === "profitable") profitClass = "profit-positive";
    else profitClass = "";

    // Status badge: always includes financial amount, sign-correct
    const statusLabel = statusMeta.label;
    const statusCls = statusMeta.class;
    const statusPrefix = statusMeta.icon ? `${statusMeta.icon} ` : "";

    const actionLabel = escapeHtml(String(c.decision_label ?? "—"));
    const reasonCell = escapeHtml(shortTableReason(status));
    const impactCell = escapeHtml(String(c.impact_text ?? "").trim() || "—");
    const rawRec = String(c?.recommendation?.message || "").trim();
    const titleAttr = rawRec ? ` title="${escapeHtml(rawRec)}"` : "";
    const tr = document.createElement("tr");
    const cpaVal = toFiniteNumber(c.cpa);
    const conversions = Number(c.conversions);
    const hasConversionData = Number.isFinite(conversions) && conversions > 0;
    const cpaEmpty = cpaVal === 0 && !hasConversionData;
    const cpaCell = cpaEmpty
      ? `<span class="cell-cpa-empty" aria-hidden="true"></span>`
      : `<span class="cell-money__value">${money(cpaVal)}</span>`;
    tr.innerHTML = `
      <td class="cell-campaign"><span class="cell-campaign__name">${escapeHtml(humanizeCampaignName(String(c.campaign || "")))}</span></td>
      <td class="num cell-money"><span class="cell-money__value">${money(c.cost ?? c.spend)}</span></td>
      <td class="num cell-money"><span class="cell-money__value">${money(c.revenue)}</span></td>
      <td class="num cell-money ${profitClass}"><span class="cell-money__value"><strong>${signedMoney(pv)}</strong></span></td>
      <td class="num cell-roas"><span class="roas-secondary roas-secondary--inline">${roasFmt(c.roas)} <span class="roas-secondary__be">(BE: ${roasFmt(campaignBreakEven)})</span></span></td>
      <td class="num cell-cpa-dim cell-money">${cpaCell}</td>
      <td class="cell-status"><span class="cell-status__flex"><span class="status-badge ${statusCls}">${statusPrefix}${statusLabel}</span></span></td>
      <td class="cell-reason">${reasonCell}</td>
      <td class="cell-impact">${impactCell}</td>
      <td class="action-cell action-cell--bold"${titleAttr}><strong>${actionLabel}</strong></td>`;
    els.tbody.appendChild(tr);
  }
}

/* ── Render: Insights (copy z API, bez business logiky) ─ */

function renderInsightsFromApi(lines) {
  els.insightsList.innerHTML = "";
  if (els.primaryAction) {
    els.primaryAction.classList.add("hidden");
    els.primaryAction.innerHTML = "";
  }

  const safe = Array.isArray(lines) ? lines : [];
  if (!safe.length) {
    const li = document.createElement("li");
    li.className = "insight-item";
    li.textContent = "Zatím bez poznámek.";
    els.insightsList.appendChild(li);
    return;
  }

  for (const raw of safe) {
    const li = document.createElement("li");
    li.className = "insight-item";
    const s = String(raw);
    if (s.startsWith("✅") || s.startsWith("📈")) li.classList.add("insight-positive");
    else if (s.startsWith("⚠️") || s.startsWith("⚠")) li.classList.add("insight-warning");
    else if (s.startsWith("❌") || s.startsWith("📉")) li.classList.add("insight-danger");
    li.textContent = s;
    els.insightsList.appendChild(li);
  }
}

/* ── Render: Charts ─────────────────────────────────────── */

function formatChartTickDate(raw) {
  const s = String(raw ?? "");
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s.length > 10 ? s.slice(0, 10) : s;
  return `${m[3]}.${m[2]}.`;
}

/** Stejný formát data jako u „Poslední den v datech“ (čitelné, bez času). */
function formatMetricDateCs(raw) {
  const s = String(raw ?? "").trim();
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s || "—";
  return `${Number(m[3])}. ${Number(m[2])}. ${m[1]}`;
}

/**
 * Indexy kategorií na ose X: nejvýše ``maxTicks`` štítků, vždy včetně prvního a posledního dne
 * (poslední den v datasetu zůstane na ose čitelně označený).
 */
function buildSparseCategoryTickIndices(labelCount, maxTicks) {
  const n = Math.max(0, Math.floor(Number(labelCount) || 0));
  if (n <= 0) return [];
  if (n === 1) return [0];
  const cap = Math.min(Math.max(2, maxTicks), n);
  if (cap >= n) {
    return Array.from({ length: n }, (_, i) => i);
  }
  const out = new Set();
  for (let k = 0; k < cap; k += 1) {
    const idx = Math.round((k * (n - 1)) / (cap - 1));
    out.add(Math.min(n - 1, Math.max(0, idx)));
  }
  return [...out].sort((a, b) => a - b);
}

let _dashboardSparseXPluginRegistered = false;

/** Nahradí výchozí category ticky řídkou sadou — řeší překrývající se denní labely. */
function registerDashboardSparseXAxisPlugin() {
  if (typeof Chart === "undefined" || _dashboardSparseXPluginRegistered) return;
  Chart.register({
    id: "dashboardSparseXAxis",
    afterBuildTicks(chart, args) {
      const scale = args?.scale;
      if (!scale || scale.id !== "x" || scale.type !== "category") return;
      const labels = chart.data?.labels;
      if (!Array.isArray(labels) || labels.length === 0) return;
      const ticks = args.ticks;
      if (!Array.isArray(ticks)) return;
      const indices = buildSparseCategoryTickIndices(labels.length, 8);
      if (indices.length === 0) return;
      ticks.splice(0, ticks.length);
      for (const value of indices) {
        ticks.push({ value });
      }
    },
  });
  _dashboardSparseXPluginRegistered = true;
}

function makeChartOptions(tooltipLineFormatter) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "rgba(15,23,42,0.92)",
        titleColor: "rgba(255,255,255,0.85)",
        bodyColor: "#fff",
        borderColor: "rgba(255,255,255,0.1)",
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        callbacks: {
          title(items) {
            if (!items?.length) return "";
            return formatChartTickDate(items[0].label);
          },
          label(ctx) {
            const y = ctx.parsed?.y;
            if (y === null || y === undefined || Number.isNaN(Number(y))) {
              return `${ctx.dataset.label}: bez dat`;
            }
            return tooltipLineFormatter(ctx);
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          font: { size: 10 },
          color: "rgba(255,255,255,0.4)",
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
          callback(tickValue, index) {
            const chart = this.chart;
            const labels = chart?.data?.labels ?? [];
            const i = Number.isFinite(Number(tickValue)) ? Number(tickValue) : index;
            const lbl = labels[i] ?? tickValue;
            return formatChartTickDate(lbl);
          },
        },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(255,255,255,0.06)" },
        ticks: { font: { size: 11 }, color: "rgba(255,255,255,0.4)" },
      },
    },
  };
}

function renderCharts(data) {
  registerDashboardSparseXAxisPlugin();
  destroyCharts();
  const rev = data?.revenue_trend ?? {};
  const spe = data?.spend_trend ?? {};
  const prof = data?.profit_trend;
  const revValsRaw = rev.revenue ?? rev.values ?? [];
  const speValsRaw = spe.spend ?? spe.values ?? [];

  const sanitizeSeries = (labels, values) => {
    const ls = Array.isArray(labels) ? labels : [];
    const vs = Array.isArray(values) ? values : [];
    const len = Math.min(ls.length, vs.length);
    const outLabels = [];
    const outValues = [];
    for (let i = 0; i < len; i += 1) {
      const raw = vs[i];
      outLabels.push(ls[i] != null ? String(ls[i]) : "");
      if (raw === null || raw === undefined) {
        outValues.push(null);
        continue;
      }
      const n = Number(raw);
      outValues.push(Number.isFinite(n) ? Math.round(n) : null);
    }
    return { labels: outLabels, values: outValues };
  };

  const revenueSeries = sanitizeSeries(rev.labels, revValsRaw);
  const spendSeries = sanitizeSeries(spe.labels, speValsRaw);

  let profitLabels = [];
  let profitVals = [];
  const profLabels = prof?.labels;
  const profVals = prof?.profit ?? prof?.values;
  if (
    prof &&
    Array.isArray(profLabels) &&
    Array.isArray(profVals) &&
    profLabels.length === profVals.length
  ) {
    const ps = sanitizeSeries(profLabels, profVals);
    profitLabels = ps.labels;
    profitVals = ps.values;
  } else {
    /* Bez profit_trend z API nespouštíme výpočet zisku na klientovi — jediný zdroj pravdy je backend. */
    profitLabels = Array.isArray(rev.labels) ? rev.labels.map((x) => String(x ?? "")) : [];
    profitVals = profitLabels.map(() => null);
  }

  if (!els.revenueCanvas || !els.spendCanvas) return;
  const profitCanvas = document.getElementById("profitChart");
  if (!profitCanvas) return;

  charts.revenue = new Chart(els.revenueCanvas, {
    type: "line",
    data: {
      labels: revenueSeries.labels,
      datasets: [{
        label: "Tržby (Kč)",
        data: revenueSeries.values,
        borderColor: "rgba(59,130,246,0.55)",
        backgroundColor: "rgba(59,130,246,0.06)",
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: true,
        spanGaps: false,
      }],
    },
    options: makeChartOptions((ctx) => `Tržby: ${money(ctx.parsed.y)}`),
  });

  charts.spend = new Chart(els.spendCanvas, {
    type: "line",
    data: {
      labels: spendSeries.labels,
      datasets: [{
        label: "Náklady (Kč)",
        data: spendSeries.values,
        borderColor: "#f59e0b",
        backgroundColor: "rgba(245,158,11,0.15)",
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: true,
        spanGaps: false,
      }],
    },
    options: makeChartOptions((ctx) => `Náklady: ${money(ctx.parsed.y)}`),
  });

  charts.profit = new Chart(profitCanvas, {
    type: "line",
    data: {
      labels: profitLabels,
      datasets: [{
        label: "Čistý zisk (Kč)",
        data: profitVals,
        borderColor: "rgba(16,185,129,0.5)",
        backgroundColor: "rgba(16,185,129,0.06)",
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: true,
        spanGaps: false,
      }],
    },
    options: makeChartOptions((ctx) => `Čistý zisk: ${money(ctx.parsed.y)}`),
  });
}

/* ── Filter bar ─────────────────────────────────────────── */

function initFilterBar() {
  const btns = document.querySelectorAll(".filter-btn");
  btns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const days = parseInt(btn.dataset.days, 10);
      if (days === selectedDays) return;
      selectedDays = days;
      btns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (window.getToken()) loadDashboard();
    });
  });
}

/* ── Dashboard loader ───────────────────────────────────── */

async function loadDashboard() {
  setDashboardLoading(true);
  setStatus("Načítám dashboard…", "info");
  els.dashboardSection.style.opacity = "0.92";
  try {
    const [data, insightsData] = await Promise.all([
      fetchJson(`/api/v1/dashboard/full?days=${selectedDays}`),
      fetchJson(`/api/v1/dashboard/insights?days=${selectedDays}`),
    ]);
    const scenarioProfits = extractScenarioProfits(data);

    const be = data?.overview?.break_even_roas;
    const overview = data?.overview ?? {};
    const revTotal = toFiniteNumber(overview.total_revenue);
    const spendTotal = toFiniteNumber(overview.total_spend);
    const isEmptyMetrics = revTotal === 0 && spendTotal === 0;
    const hasCampaignRows = Array.isArray(data.campaign_table) && data.campaign_table.length > 0;

    renderDashboardEmptyBanner(isEmptyMetrics || !hasCampaignRows);

    renderPrimaryRecommendation(data.primary_recommendation);
    renderActionBoxToday(data.daily_recommendations, data.primary_recommendation);
    renderHeadline(data);
    renderOnboardingInsight(overview);
    const campaignsForSignals =
      Array.isArray(data.campaign_table) && data.campaign_table.length > 0
        ? data.campaign_table
        : data.top_campaigns;
    renderRiskBanner(campaignsForSignals, be);
    renderTrustStrip(data.trust);
    renderKpis(data.overview, data.loss_summary);
    renderPeriodComparison(data.overview);
    renderDataReliabilityBadge(data.overview);
    let scenarioContainer = document.getElementById("scenario-insights");
    if (!scenarioContainer) {
      scenarioContainer = document.createElement("div");
      scenarioContainer.id = "scenario-insights";
      const kpiGrid = document.querySelector(".kpi-grid");
      if (kpiGrid && kpiGrid.parentNode) {
        kpiGrid.parentNode.insertBefore(scenarioContainer, kpiGrid.nextSibling);
      }
    }
    renderScenarioInsights(scenarioContainer, scenarioProfits);
    renderMarginInfo(data);
    renderTopCampaigns(data.campaign_table || data.top_campaigns, be);

    const chartsAxisHint = document.getElementById("chartsAxisHint");
    if (isEmptyMetrics) {
      setChartsEmptyState(true);
      if (chartsAxisHint) {
        chartsAxisHint.textContent = "";
        chartsAxisHint.classList.add("hidden");
      }
    } else {
      setChartsEmptyState(false);
      renderCharts(data);
      if (chartsAxisHint) {
        const last = data?.trust?.last_metric_date;
        chartsAxisHint.textContent = last
          ? `Poslední den v grafu odpovídá ${formatMetricDateCs(last)} (srovnejte s pruhem „Důvěra v data“).`
          : "Konec křivky odpovídá poslednímu dni v nahraných datech.";
        chartsAxisHint.classList.remove("hidden");
      }
    }

    renderInsightsFromApi(insightsData.insights || []);

    const sub = document.getElementById("insightsSubtitle");
    if (sub) sub.textContent = `Trendy za posledních ${selectedDays} dní`;
    if (!Array.isArray(campaignsForSignals) || campaignsForSignals.length === 0) {
      setStatus("Nahrajte CSV pro přehled výkonu.", "info");
      return;
    }
    if (isEmptyMetrics) {
      setStatus("", "success");
      return;
    }
    if (hasPartialData(data)) {
      setStatus("Některá data chybí – výsledky mohou být nepřesné", "info");
      return;
    }
    setStatus("", "success");
  } catch (e) {
    destroyCharts();
    resetDashboardUi();
    const message = String(e.message || e || "");
    if (message.includes("Vypršela") || message.includes("relace")) {
      forceRelogin();
      return;
    }
    setStatus("Nepodařilo se načíst data. Zkuste to prosím znovu.", "error");
  } finally {
    setDashboardLoading(false);
    els.dashboardSection.style.opacity = "1";
  }
}

/* ── Auth flow ──────────────────────────────────────────── */

function resetDashboardUi() {
  resetChartsSection();
  resetOnboardingInsight();
  els.tbody.innerHTML = "";
  els.kpiRevenue.textContent = "—";
  els.kpiSpend.textContent = "—";
  els.kpiProfit.textContent = "—";
  els.kpiRoas.textContent = "—";
  els.kpiRoasMeta.innerHTML = "";
  els.kpiBreakEvenRoas.textContent = "—";
  els.kpiLoss.textContent = "—";
  els.kpiLoss.style.color = "";
  els.kpiLossMeta.textContent = "";
  els.insightsList.innerHTML = "";
  if (els.actionBoxToday) els.actionBoxToday.classList.add("hidden");
  if (els.actionBoxTodayList) els.actionBoxTodayList.innerHTML = "";
  if (els.primaryRecommendationCard) {
    els.primaryRecommendationCard.classList.add("hidden");
    els.primaryRecommendationCard.innerHTML = "";
  }
  if (els.dataTrustStrip) els.dataTrustStrip.classList.add("hidden");
  const trustMc = els.kpiTrustMicrocopy || document.getElementById("kpiTrustMicrocopy");
  if (trustMc) trustMc.textContent = "";
  const partialReset = document.getElementById("partialDataNote");
  if (partialReset) {
    partialReset.textContent = "";
    partialReset.classList.add("hidden");
  }
  const cmpReset = document.getElementById("kpiPeriodComparison");
  if (cmpReset) {
    cmpReset.innerHTML = "";
    cmpReset.classList.add("hidden");
  }
  const axisHintReset = document.getElementById("chartsAxisHint");
  if (axisHintReset) {
    axisHintReset.textContent = "";
    axisHintReset.classList.add("hidden");
  }
  const relReset = document.getElementById("dataReliabilityBadge");
  if (relReset) {
    relReset.innerHTML = "";
    relReset.classList.add("hidden");
  }
  const emptyBanner = document.getElementById("dashboardEmptyBanner");
  if (emptyBanner) emptyBanner.classList.add("hidden");
  const main = document.getElementById("dashboardSection");
  if (main) main.classList.remove("dashboard-section--empty");
  if (els.kpiProfitImpact) {
    els.kpiProfitImpact.textContent = "";
    els.kpiProfitImpact.className = "kpi-profit-impact";
  }
  if (els.kpiProfit) {
    els.kpiProfit.classList.remove("kpi__value--loss-hero", "kpi__value--gain-hero");
  }
  els.headlineText.textContent = "";
  const sub = document.getElementById("headlineSub");
  if (sub) sub.textContent = "";
  if (els.headlineBanner) {
    els.headlineBanner.className = "headline-banner hidden";
    els.headlineBanner.setAttribute("aria-hidden", "true");
  }
  if (els.riskBanner) els.riskBanner.classList.add("hidden");
  if (els.primaryAction) {
    els.primaryAction.classList.add("hidden");
    els.primaryAction.innerHTML = "";
  }
  const scenarioBox = document.getElementById("scenario-insights");
  if (scenarioBox) scenarioBox.innerHTML = "";
}

async function handleLogout() {
  const token = window.getToken();
  try {
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      headers,
      credentials: "include",
    });
  } catch {
    // Fail-safe: clear local state even if backend fails.
  } finally {
    window.clearToken();
    destroyCharts();
    resetDashboardUi();
    window.location.href = "/login";
  }
}

/* ── Init ───────────────────────────────────────────────── */

els.logoutBtn.addEventListener("click", (e) => {
  e.preventDefault();
  handleLogout();
});

function applyDaysFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("days");
    if (raw == null || raw === "") return;
    const d = parseInt(raw, 10);
    if (!Number.isFinite(d) || d < 1) return;
    selectedDays = Math.min(d, 366);
    const btns = document.querySelectorAll(".filter-btn");
    let matched = false;
    btns.forEach((btn) => {
      const btnDays = parseInt(btn.dataset.days, 10);
      const on = btnDays === selectedDays;
      btn.classList.toggle("active", on);
      if (on) matched = true;
    });
    if (!matched) btns.forEach((b) => b.classList.remove("active"));
  } catch (_e) {
    /* ignore */
  }
}

window.addEventListener("load", async () => {
  initFilterBar();
  initMarginBar();
  applyDaysFromUrl();
  await window.bootstrapSession();
  if (!window.getToken()) {
    window.location.href = "/login";
    return;
  }
  els.dashboardSection.classList.remove("hidden");
  els.logoutBtn.classList.remove("hidden");
  await loadCurrentUser();
  loadDashboard();
});
