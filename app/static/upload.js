(function () {
  const form = document.getElementById("uploadForm");
  const file = document.getElementById("csvFile");
  const btn = document.getElementById("uploadBtn");
  const previewBtn = document.getElementById("previewBtn");
  const err = document.getElementById("uploadError");
  const ok = document.getElementById("uploadSuccess");
  const warn = document.getElementById("uploadWarning");
  const loading = document.getElementById("uploadLoading");
  const previewLoading = document.getElementById("previewLoading");
  const uploadPreview = document.getElementById("uploadPreview");
  const uploadFileHint = document.getElementById("uploadFileHint");
  const clearBtn = document.getElementById("clearImportBtn");
  const clearOk = document.getElementById("clearImportStatus");
  const clearErr = document.getElementById("clearImportError");
  const clearLoading = document.getElementById("clearImportLoading");
  const clearedBanner = document.getElementById("uploadClearedBanner");

  const PREVIEW_LABELS = {
    date: "Datum",
    campaign: "Kampaň / ID",
    revenue: "Tržby",
    spend: "Náklady",
  };

  /** Short tips when API code is known but body is missing or generic (upload/preview only). */
  const CSV_ERR_HINTS = {
    CSV_NO_DATA: "Soubor je prázdný nebo po vynechání řádků neobsahuje data. Přidejte hlavičku a datové řádky.",
    CSV_HEADER_MISSING:
      "Chybí řádek s názvy sloupců. Na prvním neprázdném řádku musí být např. date, campaign, revenue, spend.",
    CSV_UNSUPPORTED_FORMAT:
      "Hlavička neodpovídá podporovanému tvaru. Porovnejte ji s ukázkou na stránce nebo stáhněte ukázkové CSV.",
    CSV_DELIMITER_MISMATCH:
      "Soubor se načetl jako jeden sloupec — zkuste uložit CSV znovu s oddělovačem čárka, středník nebo tabulátor.",
    CSV_ENCODING: "Soubor musí být UTF-8. V Excelu zvolte „CSV UTF-8“; v Tabulkách Soubor → Stáhnout → CSV.",
    CSV_TOO_LARGE: "Soubor překračuje limit 15 MB — zmenšete export nebo ho rozdělte.",
    CSV_NOT_LOADED: "Soubor se nepodařilo odeslat. Vyberte ho znovu a zkuste ještě jednou.",
  };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setUploadAlertsVisible(successVisible, errorVisible) {
    if (ok) ok.classList.toggle("hidden", !successVisible);
    if (err) err.classList.toggle("hidden", !errorVisible);
  }

  function formatUploadFailure(res, ct, data) {
    if (!ct.includes("application/json")) {
      if (res.status === 413) {
        return "Soubor je příliš velký pro nahrání. Zkuste menší soubor (limit 15 MB).";
      }
      return (
        `Server nevrátil popis chyby (HTTP ${res.status}). ` +
        "Zkuste znovu, ověřte UTF-8 CSV, nebo použijte Náhled pro rychlou kontrolu."
      );
    }
    const code = data && data.error && data.error.code;
    const serverMsg = data && data.error && data.error.message ? String(data.error.message).trim() : "";
    let msg = window.apiErrorMessage(data);
    const generic = msg === "Požadavek selhal." || !serverMsg;
    if (generic && code && CSV_ERR_HINTS[code]) {
      return CSV_ERR_HINTS[code];
    }
    if (generic) {
      return "Import se nezdařil. Zkuste Náhled nebo zkontrolujte formát CSV podle nápovědy na stránce.";
    }
    return msg;
  }

  function scrollAlertIntoView(el) {
    if (!el || el.classList.contains("hidden")) return;
    try {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (_e) {
      el.scrollIntoView();
    }
  }

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
    if (file) file.disabled = on;
    if (previewBtn) previewBtn.disabled = on || !(file && file.files && file.files[0]);
  }

  function setPreviewLoading(on) {
    if (previewLoading) previewLoading.classList.toggle("hidden", !on);
    if (previewBtn) previewBtn.disabled = on || !(file && file.files && file.files[0]);
    if (btn) btn.disabled = on;
    if (file) file.disabled = on;
  }

  function setClearLoading(on) {
    if (clearLoading) clearLoading.classList.toggle("hidden", !on);
    if (clearBtn) clearBtn.disabled = on;
    if (btn) btn.disabled = on;
    if (file) file.disabled = on;
    if (previewBtn) previewBtn.disabled = on || !(file && file.files && file.files[0]);
  }

  function clearPreviewPanel() {
    if (uploadPreview) {
      uploadPreview.innerHTML = "";
      uploadPreview.classList.add("hidden");
    }
  }

  function updateFileHint() {
    const f = file && file.files && file.files[0];
    if (!uploadFileHint) return;
    if (!f) {
      uploadFileHint.textContent =
        "Podporujeme UTF-8 a oddělovač čárka, středník nebo tabulátor.";
      return;
    }
    const kb = f.size / 1024;
    const sizeStr = kb < 1024 ? `${Math.round(kb)} KB` : `${(kb / 1024).toFixed(1)} MB`;
    uploadFileHint.textContent = `${f.name} (${sizeStr})`;
  }

  function renderPreview(data) {
    if (!uploadPreview) return;
    const rows = data.preview_rows || [];
    const total = data.total_data_rows ?? 0;
    const desc = escapeHtml(data.format_description || "");
    const fmt = escapeHtml(data.detected_format || "");

    let table =
      '<p class="upload-preview__title">Náhled parsování (první řádky)</p>' +
      `<p class="upload-preview__meta"><strong>Rozpoznaný typ:</strong> ${desc} ` +
      `<span style="opacity:0.75">(${fmt})</span><br />` +
      `<strong>Datových řádků v souboru:</strong> ${total}</p>`;

    if (!rows.length) {
      table += "<p class=\"upload-preview__meta\">Žádné datové řádky k zobrazení.</p>";
      uploadPreview.innerHTML = table;
      uploadPreview.classList.remove("hidden");
      return;
    }

    const order = ["date", "campaign", "revenue", "spend"];
    let head = "<tr><th>Řádek</th>";
    for (const key of order) {
      head += `<th>${escapeHtml(PREVIEW_LABELS[key] || key)}</th>`;
    }
    head += "</tr>";

    let body = "";
    for (const pr of rows) {
      const cells = pr.cells || {};
      body += `<tr><td>${pr.row}</td>`;
      for (const key of order) {
        const c = cells[key] || {};
        const bad = c.ok === false;
        const cls = bad ? "upload-preview__cell--bad" : "";
        const main = escapeHtml(c.raw != null ? String(c.raw) : "—");
        let sub = "";
        if (c.parsed != null && String(c.parsed) !== String(c.raw)) {
          sub += `<span class="upload-preview__detail">→ ${escapeHtml(String(c.parsed))}</span>`;
        }
        if (c.detail) {
          sub += `<span class="upload-preview__detail">${escapeHtml(c.detail)}</span>`;
        }
        body += `<td${cls ? ` class="${cls}"` : ""}>${main}${sub}</td>`;
      }
      body += "</tr>";
    }

    table +=
      '<div class="upload-preview__table-wrap"><table><thead>' +
      head +
      "</thead><tbody>" +
      body +
      "</tbody></table></div>" +
      '<p class="upload-preview__meta">Náhled nekontroluje oprávnění k ID kampaní — při importu může řádek selhat, pokud ID nepatří vašemu účtu.</p>';

    uploadPreview.innerHTML = table;
    uploadPreview.classList.remove("hidden");
  }

  function showClearedFromQuery() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("cleared") !== "1") return;
    if (clearedBanner) {
      clearedBanner.classList.remove("hidden");
      clearedBanner.textContent =
        "Importovaná data byla smazána. Můžete nahrát nový dataset.";
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("cleared");
    const next = url.pathname + (url.search || "") + url.hash;
    window.history.replaceState({}, "", next);
  }

  async function init() {
    const boot = await window.bootstrapSession();
    if (!window.getToken() && !boot) {
      window.location.href = "/login";
      return;
    }
    if (!window.getToken()) {
      window.location.href = "/login";
      return;
    }
    showClearedFromQuery();
    updateFileHint();
  }

  const CLEAR_CONFIRM = "DELETE_IMPORTED_DATA";

  if (file) {
    file.addEventListener("change", () => {
      clearPreviewPanel();
      setUploadAlertsVisible(false, false);
      if (err) {
        err.textContent = "";
        err.classList.add("hidden");
      }
      if (warn) {
        warn.textContent = "";
        warn.classList.add("hidden");
      }
      if (ok) {
        ok.textContent = "";
        ok.classList.add("hidden");
      }
      updateFileHint();
      if (previewBtn) previewBtn.disabled = !(file.files && file.files[0]);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      if (clearOk) {
        clearOk.classList.add("hidden");
        clearOk.textContent = "";
      }
      if (clearErr) {
        clearErr.classList.add("hidden");
        clearErr.textContent = "";
      }
      const confirmed = window.confirm(
        "Opravdu chcete vymazat všechna importovaná CSV data pro váš účet? Tuto akci nelze vrátit zpět.",
      );
      if (!confirmed) return;
      setClearLoading(true);
      try {
        await window.authFetchJson("/api/v1/upload/clear-imported", {
          method: "POST",
          body: JSON.stringify({ confirm: CLEAR_CONFIRM }),
        });
        window.location.href = "/upload?cleared=1";
      } catch (ex) {
        if (clearErr) {
          clearErr.classList.remove("hidden");
          clearErr.textContent = String(ex.message || ex || "Akce selhala.");
        }
      } finally {
        setClearLoading(false);
      }
    });
  }

  if (previewBtn) {
    previewBtn.addEventListener("click", async () => {
      const f = file.files && file.files[0];
      if (!f) {
        if (err) {
          err.classList.remove("hidden");
          err.textContent = "Vyberte soubor CSV.";
        }
        return;
      }
      if (err) {
        err.classList.add("hidden");
        err.textContent = "";
      }
      if (warn) {
        warn.classList.add("hidden");
        warn.textContent = "";
      }
      clearPreviewPanel();
      setPreviewLoading(true);
      try {
        const fd = new FormData();
        fd.append("file", f);
        const res = await window.fetchWithAuth("/api/v1/upload/revenue-csv/preview", {
          method: "POST",
          body: fd,
        });
        const ct = res.headers.get("content-type") || "";
        const data = ct.includes("application/json") ? await res.json() : {};
        const fresh = res.headers.get("x-access-token");
        if (fresh) window.setToken(fresh);
        if (res.status === 401) {
          window.clearToken();
          window.location.href = "/login";
          return;
        }
        if (!res.ok) {
          if (err) {
            err.classList.remove("hidden");
            err.textContent = formatUploadFailure(res, ct, data);
            scrollAlertIntoView(err);
          }
          return;
        }
        renderPreview(data);
      } catch (ex) {
        if (err) {
          err.classList.remove("hidden");
          err.textContent = String(ex.message || ex || "Náhled selhal.");
          scrollAlertIntoView(err);
        }
      } finally {
        setPreviewLoading(false);
        updateFileHint();
        if (previewBtn) previewBtn.disabled = !(file.files && file.files[0]);
      }
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setUploadAlertsVisible(false, false);
    if (warn) {
      warn.classList.add("hidden");
      warn.textContent = "";
    }
    if (err) err.textContent = "";
    if (ok) ok.textContent = "";
    const f = file.files && file.files[0];
    if (!f) {
      if (err) {
        err.classList.remove("hidden");
        err.textContent = "Vyberte soubor CSV.";
      }
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await window.fetchWithAuth("/api/v1/upload/revenue-csv", {
        method: "POST",
        body: fd,
      });
      const ct = res.headers.get("content-type") || "";
      const data = ct.includes("application/json") ? await res.json() : {};
      const fresh = res.headers.get("x-access-token");
      if (fresh) window.setToken(fresh);
      if (res.status === 401) {
        window.clearToken();
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        if (err) {
          err.classList.remove("hidden");
          err.textContent = formatUploadFailure(res, ct, data);
          scrollAlertIntoView(err);
        }
        return;
      }
      const imp = data.imported ?? 0;
      const upd = data.updated ?? 0;
      const sk = data.skipped ?? 0;
      const campaigns = data.campaigns_in_import ?? 0;
      const rowErrors = Array.isArray(data.errors) ? data.errors : [];
      const errSample = rowErrors.slice(0, 5);

      const nothingSaved = imp === 0 && upd === 0;

      if (nothingSaved) {
        if (ok) {
          ok.classList.add("hidden");
          ok.textContent = "";
        }
        if (warn) {
          warn.classList.remove("hidden");
          if (rowErrors.length > 0) {
            let w =
              "<strong>Nebyl uložen žádný platný řádek.</strong> " +
              `Počet chybových řádků v odpovědi: ${rowErrors.length}. ` +
              "Ukázka prvních hlášek:";
            w += "<ul style=\"margin:8px 0 0 1.1rem;padding:0;font-size:12px;line-height:1.45\">";
            for (const it of errSample) {
              const r = it.row != null ? it.row : "?";
              const reason = escapeHtml(String(it.reason || "Neznámá chyba"));
              w += `<li>Řádek ${r}: ${reason}</li>`;
            }
            if (rowErrors.length > errSample.length) {
              w += `<li>… a další (${rowErrors.length - errSample.length} řádků)</li>`;
            }
            w += "</ul>";
            w +=
              `<p style="margin:10px 0 0;font-size:12px;line-height:1.45">Přeskočeno celkem: ${sk}. ` +
              "Zkuste náhled bez uložení nebo upravte CSV podle nápovědy.</p>";
            warn.innerHTML = w;
          } else {
            warn.innerHTML =
              "<strong>Nebyla uložena žádná data.</strong> " +
              `Přeskočeno řádků: ${sk}. Zkuste Náhled, upravte CSV podle nápovědy a nahrajte znovu.`;
          }
          scrollAlertIntoView(warn);
        }
        return;
      }

      const partial = rowErrors.length > 0;

      if (ok) {
        ok.classList.remove("hidden");
        const summary = `Nově uloženo: ${imp} řádků. Aktualizováno: ${upd}. Přeskočeno: ${sk}. Kampaní v souboru (různé názvy): ${campaigns}.`;
        if (partial) {
          ok.innerHTML =
            "<strong>Import částečně proběhl.</strong> " +
            summary +
            " Níže najdete varování u řádků, které se nepodařilo zpracovat.";
        } else {
          ok.innerHTML = "<strong>Import proběhl.</strong> " + summary;
        }
      }

      if (partial && warn) {
        warn.classList.remove("hidden");
        let w =
          "<strong>Část řádků se nepodařila naimportovat.</strong> " +
          `Uloženo v tomto běhu: ${imp} nových, ${upd} aktualizovaných. ` +
          `Přeskočeno celkem: ${sk}. Řádků s hláškou v odpovědi: ${rowErrors.length}. ` +
          "Ukázka prvních problémů:";
        w += "<ul style=\"margin:8px 0 0 1.1rem;padding:0;font-size:12px;line-height:1.45\">";
        for (const it of errSample) {
          const r = it.row != null ? it.row : "?";
          const reason = escapeHtml(String(it.reason || "Neznámá chyba"));
          w += `<li>Řádek ${r}: ${reason}</li>`;
        }
        if (rowErrors.length > errSample.length) {
          w += `<li>… a další (${rowErrors.length - errSample.length} řádků)</li>`;
        }
        w += "</ul>";
        w +=
          '<p style="margin:10px 0 0;font-size:12px;line-height:1.45">' +
          "Zkontrolujte datum a čísla ve sloupcích (tržby, náklady). Příště můžete nejdřív použít Náhled.</p>";
        warn.innerHTML = w;
        scrollAlertIntoView(warn);
      }

      const delayMs = partial ? 4500 : 1400;
      setTimeout(() => {
        window.location.href = "/dashboard";
      }, delayMs);
    } catch (ex) {
        if (err) {
          err.classList.remove("hidden");
          err.textContent = String(ex.message || ex || "Nahrání selhalo.");
          scrollAlertIntoView(err);
        }
      } finally {
        setLoading(false);
        updateFileHint();
      }
  });

  init();
})();
