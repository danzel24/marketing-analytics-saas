(function () {
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatCZK(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    return (
      new Intl.NumberFormat("cs-CZ", {
        style: "currency",
        currency: "CZK",
        maximumFractionDigits: 2,
      }).format(x) || String(x)
    );
  }

  function formatPeriod(p) {
    if (!p || !p.date_min || !p.date_max) return "—";
    return `${escapeHtml(p.date_min)} → ${escapeHtml(p.date_max)}`;
  }

  function formatCsIsoDate(iso) {
    if (!iso || typeof iso !== "string") return String(iso || "");
    const parts = iso.split("-");
    if (parts.length !== 3) return escapeHtml(iso);
    const y = parts[0];
    const m = parts[1];
    const d = parts[2];
    return `${parseInt(d, 10)}.${parseInt(m, 10)}.${escapeHtml(y)}`;
  }

  function showPostImportBanner() {
    const el = document.getElementById("coImportBanner");
    if (!el) return;
    let raw = null;
    try {
      raw = sessionStorage.getItem("channelOverviewAfterImport");
    } catch (_e) {
      return;
    }
    if (!raw) return;
    try {
      sessionStorage.removeItem("channelOverviewAfterImport");
    } catch (_e) {
      /* ignore */
    }
    let b = null;
    try {
      b = JSON.parse(raw);
    } catch (_e) {
      return;
    }
    if (!b || !b.periodMin || !b.periodMax) return;
    let html =
      `<strong>Po importu.</strong> Uložená data v souboru: <strong>${formatCsIsoDate(b.periodMin)} – ${formatCsIsoDate(b.periodMax)}</strong>. `;
    if (b.windowAdjusted) {
      html += `Přehled je nastaven na posledních <strong>${escapeHtml(String(b.days))}</strong> dní, aby šla data v okně vidět. `;
    }
    if (b.honestyNote) {
      html += `<span class="upload-file-hint">${escapeHtml(b.honestyNote)}</span>`;
    }
    el.innerHTML = html;
    el.classList.remove("hidden");
  }

  async function load() {
    showPostImportBanner();
    const params = new URLSearchParams(window.location.search);
    const days = Math.min(366, Math.max(1, parseInt(String(params.get("days") || "30"), 10) || 30));
    const hint = document.getElementById("coWindowHint");
    if (hint) hint.textContent = `Okno: posledních ${days} dní.`;

    const adsBody = document.getElementById("coAdsBody");
    const shopBody = document.getElementById("coShopBody");
    const disc = document.getElementById("coDisclaimers");
    const notShown = document.getElementById("coNotShown");

    try {
      const data = await window.authFetchJson(`/api/v1/dashboard/channel-overview?days=${days}`);
      if (disc && Array.isArray(data.disclaimers)) {
        disc.innerHTML = data.disclaimers.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
      }
      const ads = data.ad_channels || {};
      const meta = ads.meta_ads || {};
      const goog = ads.google_ads_csv || {};
      if (adsBody) {
        adsBody.innerHTML =
          `<p><strong>${escapeHtml(meta.label || "Meta")}:</strong> ` +
          `${meta.has_data ? formatCZK(meta.spend_czk) : "žádná data v okně"}</p>` +
          `<p class="upload-file-hint">Období v datech: ${formatPeriod(meta.period_in_data)}</p>` +
          `<p><strong>${escapeHtml(goog.label || "Google")}:</strong> ` +
          `${goog.has_data ? formatCZK(goog.spend_czk) : "žádná data v okně"}</p>` +
          `<p class="upload-file-hint">Období v datech: ${formatPeriod(goog.period_in_data)}</p>`;
      }
      const shop = data.e_shop || {};
      if (shopBody) {
        const basis = escapeHtml(shop.order_or_row_basis || "");
        shopBody.innerHTML =
          `<p><strong>Tržby celkem:</strong> ${shop.has_data ? formatCZK(shop.total_revenue_czk) : "žádná data v okně"}</p>` +
          `<p><strong>Počet objednávek:</strong> ${shop.has_data ? escapeHtml(String(shop.order_or_row_count ?? "—")) : "—"}</p>` +
          `<p class="upload-file-hint">${basis}</p>` +
          `<p class="upload-file-hint">Období v datech: ${formatPeriod(shop.period_in_data)}</p>`;
      }
      const ns = data.not_shown || {};
      if (notShown) {
        notShown.innerHTML = "";
        if (ns.channel_shop_revenue) {
          notShown.innerHTML += `<li>${escapeHtml(ns.channel_shop_revenue)}</li>`;
        }
        if (ns.channel_roas_pno) {
          notShown.innerHTML += `<li>${escapeHtml(ns.channel_roas_pno)}</li>`;
        }
      }
      if (!data.has_any_multi_source_data && hint) {
        hint.textContent += " Zatím nemáte nahrané oddělené CSV — použijte /upload/multi.";
      }
    } catch (e) {
      if (hint) hint.textContent = String(e.message || e);
    }
  }

  async function boot() {
    const b = await window.bootstrapSession();
    if (!window.getToken() && !b) {
      window.location.href = "/login";
      return;
    }
    if (!window.getToken()) {
      window.location.href = "/login";
      return;
    }
    await load();
  }

  boot();
})();
