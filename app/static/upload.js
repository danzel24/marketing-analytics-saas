(function () {
  const form = document.getElementById("uploadForm");
  const file = document.getElementById("csvFile");
  const btn = document.getElementById("uploadBtn");
  const err = document.getElementById("uploadError");
  const ok = document.getElementById("uploadSuccess");
  const loading = document.getElementById("uploadLoading");
  const clearBtn = document.getElementById("clearImportBtn");
  const clearOk = document.getElementById("clearImportStatus");
  const clearErr = document.getElementById("clearImportError");

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
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
  }

  const CLEAR_CONFIRM = "DELETE_IMPORTED_DATA";

  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      if (clearOk) clearOk.textContent = "";
      if (clearErr) clearErr.textContent = "";
      const ok = window.confirm(
        "Opravdu chcete vymazat všechna importovaná CSV data pro váš účet? Tuto akci nelze vrátit zpět.",
      );
      if (!ok) return;
      if (clearBtn) clearBtn.disabled = true;
      try {
        const data = await window.authFetchJson("/api/v1/upload/clear-imported", {
          method: "POST",
          body: JSON.stringify({ confirm: CLEAR_CONFIRM }),
        });
        const md = data.metrics_deleted ?? 0;
        const cd = data.campaigns_deleted ?? 0;
        if (clearOk) {
          clearOk.textContent = `Smazáno: ${md} metrik, ${cd} kampaní. Můžete nahrát nový CSV.`;
        }
        setTimeout(() => {
          window.location.href = "/dashboard";
        }, 1500);
      } catch (ex) {
        if (clearErr) clearErr.textContent = String(ex.message || ex || "Akce selhala.");
      } finally {
        if (clearBtn) clearBtn.disabled = false;
      }
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    ok.textContent = "";
    const f = file.files && file.files[0];
    if (!f) {
      err.textContent = "Vyberte soubor CSV.";
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
        err.textContent = window.apiErrorMessage(data);
        return;
      }
      const imp = data.imported ?? 0;
      const upd = data.updated ?? 0;
      const sk = data.skipped ?? 0;
      ok.textContent = `Hotovo: ${imp} nových řádků, ${upd} aktualizací, ${sk} přeskočeno. Přecházím na přehled…`;
      setTimeout(() => {
        window.location.href = "/dashboard";
      }, 1200);
    } catch (ex) {
      err.textContent = String(ex.message || ex || "Nahrání selhalo.");
    } finally {
      setLoading(false);
    }
  });

  init();
})();
