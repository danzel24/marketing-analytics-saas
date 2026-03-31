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
  const clearLoading = document.getElementById("clearImportLoading");
  const clearedBanner = document.getElementById("uploadClearedBanner");

  function setUploadAlertsVisible(successVisible, errorVisible) {
    if (ok) ok.classList.toggle("hidden", !successVisible);
    if (err) err.classList.toggle("hidden", !errorVisible);
  }

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
    if (file) file.disabled = on;
  }

  function setClearLoading(on) {
    if (clearLoading) clearLoading.classList.toggle("hidden", !on);
    if (clearBtn) clearBtn.disabled = on;
    if (btn) btn.disabled = on;
    if (file) file.disabled = on;
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
  }

  const CLEAR_CONFIRM = "DELETE_IMPORTED_DATA";

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

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setUploadAlertsVisible(false, false);
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
          err.textContent = window.apiErrorMessage(data);
        }
        return;
      }
      const imp = data.imported ?? 0;
      const upd = data.updated ?? 0;
      const sk = data.skipped ?? 0;
      const campaigns = data.campaigns_in_import ?? 0;
      if (ok) {
        ok.classList.remove("hidden");
        ok.innerHTML = `
          <strong>Import proběhl úspěšně.</strong>
          Nové řádky metrik: ${imp}. Aktualizace: ${upd}. Přeskočeno: ${sk}.
          Kampaní v souboru (různé názvy): ${campaigns}.
          Za okamžik přejdeme na přehled…`;
      }
      setTimeout(() => {
        window.location.href = "/dashboard";
      }, 1400);
    } catch (ex) {
      if (err) {
        err.classList.remove("hidden");
        err.textContent = String(ex.message || ex || "Nahrání selhalo.");
      }
    } finally {
      setLoading(false);
    }
  });

  init();
})();
