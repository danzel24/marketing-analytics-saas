(function () {
  const CLEAR_CONFIRM = "DELETE_IMPORTED_DATA";

  const ENDPOINTS = {
    orders: { preview: "/api/v1/upload/multi/orders/preview", import: "/api/v1/upload/multi/orders" },
    meta: { preview: "/api/v1/upload/multi/meta/preview", import: "/api/v1/upload/multi/meta" },
    google: { preview: "/api/v1/upload/multi/google/preview", import: "/api/v1/upload/multi/google" },
  };

  const FILE_INPUTS = {
    orders: () => document.getElementById("fileOrders"),
    meta: () => document.getElementById("fileMeta"),
    google: () => document.getElementById("fileGoogle"),
  };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function blockForSource(source) {
    const root = document.querySelector(`section.multi-upload-block[data-source="${source}"]`);
    if (!root) return null;
    return {
      root,
      loading: root.querySelector(".js-loading"),
      err: root.querySelector(".js-err"),
      ok: root.querySelector(".js-ok"),
      panel: root.querySelector(".js-preview-panel"),
    };
  }

  function setLoading(source, on) {
    const b = blockForSource(source);
    if (!b) return;
    b.loading.classList.toggle("hidden", !on);
    b.root.querySelectorAll(".js-preview, .js-import").forEach((btn) => {
      btn.disabled = on;
    });
  }

  function clearAlerts(source) {
    const b = blockForSource(source);
    if (!b) return;
    b.err.classList.add("hidden");
    b.err.textContent = "";
    b.ok.classList.add("hidden");
    b.ok.textContent = "";
  }

  function formatPeriod(p) {
    if (!p || !p.date_min || !p.date_max) return "—";
    return `${escapeHtml(p.date_min)} → ${escapeHtml(p.date_max)}`;
  }

  /** ISO date → d.m.yyyy (same idea as unified upload.js). */
  function formatCsIsoDate(iso) {
    if (!iso || typeof iso !== "string") return String(iso || "");
    const parts = iso.split("-");
    if (parts.length !== 3) return iso;
    const y = parts[0];
    const m = parts[1];
    const d = parts[2];
    return `${parseInt(d, 10)}.${parseInt(m, 10)}.${y}`;
  }

  function renderPreview(source, data) {
    const b = blockForSource(source);
    if (!b || !b.panel) return;
    const status = escapeHtml(data.validation_status || "—");
    const typeLabel = escapeHtml(data.detected_file_type_label_cs || data.detected_file_type || "—");
    const rows = Number(data.row_count) || 0;
    const kf = Array.isArray(data.key_fields) ? data.key_fields : [];
    const kfHtml = kf
      .map((x) => `${escapeHtml(x.role || "")}: <code>${escapeHtml(x.column || "")}</code>`)
      .join("<br />");

    let prevTable = "";
    const pr = data.preview_rows || [];
    if (pr.length) {
      prevTable += '<div class="upload-preview__table-wrap"><table><thead><tr>';
      if (source === "orders") {
        prevTable += "<th>Řádek</th><th>Datum</th><th>Tržba</th><th>OK</th></tr></thead><tbody>";
        for (const r of pr) {
          prevTable += `<tr><td>${r.row}</td><td>${escapeHtml(r.parsed_date || "—")}</td><td>${escapeHtml(
            r.parsed_revenue != null ? String(r.parsed_revenue) : "—",
          )}</td><td>${r.ok ? "✓" : "✗"}</td></tr>`;
        }
      } else {
        prevTable += "<th>Řádek</th><th>Datum</th><th>Výdaj</th><th>OK</th></tr></thead><tbody>";
        for (const r of pr) {
          prevTable += `<tr><td>${r.row}</td><td>${escapeHtml(r.parsed_date || "—")}</td><td>${escapeHtml(
            r.parsed_spend != null ? String(r.parsed_spend) : "—",
          )}</td><td>${r.ok ? "✓" : "✗"}</td></tr>`;
        }
      }
      prevTable += "</tbody></table></div>";
    }

    const errSample = Array.isArray(data.validation_errors_sample) ? data.validation_errors_sample : [];
    let errBlock = "";
    if (errSample.length) {
      errBlock = '<p class="upload-preview__meta">Ukázka problémů:</p><ul style="font-size:12px">';
      for (const e of errSample.slice(0, 6)) {
        errBlock += `<li>Řádek ${escapeHtml(String(e.row))}: ${escapeHtml(String(e.reason || ""))}</li>`;
      }
      errBlock += "</ul>";
    }

    b.panel.innerHTML =
      `<p class="upload-preview__title">Náhled</p>` +
      `<p class="upload-preview__meta"><strong>Typ:</strong> ${typeLabel}<br />` +
      `<strong>Řádků dat:</strong> ${rows}<br />` +
      `<strong>Období v datech:</strong> ${formatPeriod(data.period)}<br />` +
      `<strong>Validace:</strong> ${status}</p>` +
      (kfHtml ? `<p class="upload-preview__meta"><strong>Klíčové sloupce:</strong><br />${kfHtml}</p>` : "") +
      errBlock +
      prevTable;
    b.panel.classList.remove("hidden");
  }

  async function postFile(url, file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await window.fetchWithAuth(url, { method: "POST", body: fd });
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json() : {};
    const fresh = res.headers.get("x-access-token");
    if (fresh) window.setToken(fresh);
    return { res, data };
  }

  async function onPreview(source) {
    const input = FILE_INPUTS[source]();
    const file = input && input.files && input.files[0];
    const b = blockForSource(source);
    if (!file) {
      if (b) {
        b.err.classList.remove("hidden");
        b.err.textContent = "Vyberte soubor CSV.";
      }
      return;
    }
    clearAlerts(source);
    if (b && b.panel) {
      b.panel.innerHTML = "";
      b.panel.classList.add("hidden");
    }
    setLoading(source, true);
    try {
      const { res, data } = await postFile(ENDPOINTS[source].preview, file);
      if (res.status === 401) {
        window.clearToken();
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        if (b) {
          b.err.classList.remove("hidden");
          b.err.textContent = window.apiErrorMessage(data);
        }
        return;
      }
      renderPreview(source, data);
    } catch (ex) {
      if (b) {
        b.err.classList.remove("hidden");
        b.err.textContent = String(ex.message || ex);
      }
    } finally {
      setLoading(source, false);
    }
  }

  async function onImport(source) {
    const input = FILE_INPUTS[source]();
    const file = input && input.files && input.files[0];
    const b = blockForSource(source);
    if (!file) {
      if (b) {
        b.err.classList.remove("hidden");
        b.err.textContent = "Vyberte soubor CSV.";
      }
      return;
    }
    clearAlerts(source);
    setLoading(source, true);
    try {
      const { res, data } = await postFile(ENDPOINTS[source].import, file);
      if (res.status === 401) {
        window.clearToken();
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        if (b) {
          b.err.classList.remove("hidden");
          b.err.textContent = window.apiErrorMessage(data);
        }
        return;
      }
      const st = data.validation_status || "";
      const imp = Number(data.imported_metrics) || 0;
      if (st === "invalid" || imp === 0) {
        if (b) {
          b.err.classList.remove("hidden");
          b.err.textContent =
            "Žádný platný řádek nebyl uložen. Zkuste náhled nebo zkontrolujte formát exportu.";
        }
        return;
      }
      const defDays = data.channel_overview_default_window_days ?? 30;
      const outside = data.import_outside_default_channel_overview_window === true;
      const sug = Math.min(
        366,
        Math.max(1, parseInt(String(data.suggested_channel_overview_days || defDays), 10) || defDays),
      );
      const href = outside ? `/channel-overview?days=${sug}` : "/channel-overview";
      const dmin = data.import_metric_date_min;
      const dmax = data.import_metric_date_max;
      let periodLine = "";
      if (dmin && dmax) {
        periodLine =
          `<p class="upload-success__detail">Rozpětí uložených dat: <strong>${escapeHtml(formatCsIsoDate(dmin))} – ${escapeHtml(formatCsIsoDate(dmax))}</strong>.</p>`;
      }
      let windowLine = "";
      if (outside) {
        windowLine =
          `<p class="upload-success__detail upload-success__detail--warn">Výchozí přehled kanálů ukazuje posledních <strong>${defDays} dní</strong> — tato data by tam nemusela být vidět. ` +
          `Za chvíli otevřeme přehled s oknem <strong>${sug} dní</strong>.</p>`;
      } else {
        windowLine =
          `<p class="upload-success__detail">Přehled kanálů otevřeme se standardním oknem (<strong>${defDays} dní</strong>).</p>`;
      }
      let honesty = "";
      if (data.import_booking_honesty_note_cs) {
        honesty = `<p class="upload-success__detail">${escapeHtml(String(data.import_booking_honesty_note_cs))}</p>`;
      }
      try {
        sessionStorage.setItem(
          "channelOverviewAfterImport",
          JSON.stringify({
            periodMin: dmin || "",
            periodMax: dmax || "",
            days: outside ? sug : defDays,
            windowAdjusted: outside,
            honestyNote: data.import_booking_honesty_note_cs || "",
          }),
        );
      } catch (_e) {
        /* ignore */
      }
      if (b) {
        b.ok.classList.remove("hidden");
        b.ok.innerHTML =
          `<strong>Uloženo.</strong> Záznamů metrik: ${escapeHtml(String(data.imported_metrics || 0))}. ` +
          `Přeskočeno řádků: ${escapeHtml(String(data.skipped_rows || 0))}.` +
          periodLine +
          windowLine +
          honesty +
          `<p class="upload-success__detail"><a href="${escapeHtml(href)}">Otevřít přehled kanálů</a></p>`;
      }
      const delayMs = Number(data.skipped_rows) > 0 ? 4200 : 1700;
      setTimeout(() => {
        window.location.href = href;
      }, delayMs);
    } catch (ex) {
      if (b) {
        b.err.classList.remove("hidden");
        b.err.textContent = String(ex.message || ex);
      }
    } finally {
      setLoading(source, false);
    }
  }

  document.querySelectorAll(".js-preview").forEach((btn) => {
    btn.addEventListener("click", () => onPreview(btn.getAttribute("data-source")));
  });
  document.querySelectorAll(".js-import").forEach((btn) => {
    btn.addEventListener("click", () => onImport(btn.getAttribute("data-source")));
  });

  const clearBtn = document.getElementById("clearMultiBtn");
  const clearErr = document.getElementById("clearMultiErr");
  const clearLoad = document.getElementById("clearMultiLoading");
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      if (clearErr) {
        clearErr.classList.add("hidden");
        clearErr.textContent = "";
      }
      if (!window.confirm("Opravdu smazat všechna CSV data (včetně sjednoceného importu)?")) return;
      if (clearLoad) clearLoad.classList.remove("hidden");
      clearBtn.disabled = true;
      try {
        await window.authFetchJson("/api/v1/upload/clear-imported", {
          method: "POST",
          body: JSON.stringify({ confirm: CLEAR_CONFIRM }),
        });
        window.location.href = "/upload/multi?cleared=1";
      } catch (ex) {
        if (clearErr) {
          clearErr.classList.remove("hidden");
          clearErr.textContent = String(ex.message || ex);
        }
      } finally {
        if (clearLoad) clearLoad.classList.add("hidden");
        clearBtn.disabled = false;
      }
    });
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
    const params = new URLSearchParams(window.location.search);
    if (params.get("cleared") === "1") {
      const ge = document.getElementById("multiGlobalError");
      if (ge) {
        ge.classList.remove("hidden");
        ge.classList.remove("alert--error");
        ge.classList.add("alert--success");
        ge.textContent = "CSV data byla vymazána.";
      }
      const url = new URL(window.location.href);
      url.searchParams.delete("cleared");
      window.history.replaceState({}, "", url.pathname + (url.search || "") + url.hash);
    }
  }

  boot();
})();
