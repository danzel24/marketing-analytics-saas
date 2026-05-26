(function () {
  "use strict";

  // Redirect to login if not authenticated
  if (!window.isAuthenticated()) {
    window.location.href = "/login";
    return;
  }

  var btn = document.getElementById("changePasswordBtn");
  var loadingEl = document.getElementById("changePasswordLoading");
  var successEl = document.getElementById("changePasswordSuccess");
  var errorEl = document.getElementById("changePasswordError");
  var errorMsgEl = document.getElementById("changePasswordErrorMsg");
  var currentPwdEl = document.getElementById("currentPassword");
  var newPwdEl = document.getElementById("newPassword");
  var newPwdConfirmEl = document.getElementById("newPasswordConfirm");

  // Logout button (same pattern as dashboard.js)
  var logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", function () {
      var token = window.getToken();
      var headers = new Headers();
      if (token) headers.set("Authorization", "Bearer " + token);
      fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: headers,
        credentials: "include",
        keepalive: true,
      }).catch(function () {});
      window.clearToken();
      window.location.href = "/login";
    });
  }

  function showError(msg) {
    if (successEl) successEl.classList.add("hidden");
    if (errorEl) errorEl.classList.remove("hidden");
    if (errorMsgEl && msg) errorMsgEl.textContent = msg;
  }

  function showSuccess() {
    if (errorEl) errorEl.classList.add("hidden");
    if (successEl) successEl.classList.remove("hidden");
    if (currentPwdEl) currentPwdEl.value = "";
    if (newPwdEl) newPwdEl.value = "";
    if (newPwdConfirmEl) newPwdConfirmEl.value = "";
  }

  function setLoading(on) {
    if (btn) btn.disabled = on;
    if (loadingEl) loadingEl.classList.toggle("hidden", !on);
  }

  if (btn) {
    btn.addEventListener("click", async function () {
      if (successEl) successEl.classList.add("hidden");
      if (errorEl) errorEl.classList.add("hidden");

      var current = currentPwdEl ? currentPwdEl.value : "";
      var next = newPwdEl ? newPwdEl.value : "";
      var confirm = newPwdConfirmEl ? newPwdConfirmEl.value : "";

      if (!current) { showError("Zadejte současné heslo."); return; }
      if (next.length < 8) { showError("Nové heslo musí mít alespoň 8 znaků."); return; }
      if (next !== confirm) { showError("Nová hesla se neshodují."); return; }

      setLoading(true);
      try {
        var res = await window.fetchWithAuth("/api/v1/auth/change-password", {
          method: "POST",
          body: JSON.stringify({ current_password: current, new_password: next }),
        });
        var data = await res.json();
        if (!res.ok) {
          showError(window.apiErrorMessage(data));
          return;
        }
        // fetchWithAuth already stores x-access-token from header; also store from body as fallback
        if (data.access_token) window.setToken(data.access_token);
        showSuccess();
      } catch (err) {
        showError(err.message || "Nepodařilo se změnit heslo.");
      } finally {
        setLoading(false);
      }
    });
  }

  // ── Delete account ────────────────────────────────────────────────────────
  var deleteShowBtn = document.getElementById("deleteAccountShowBtn");
  var deleteForm = document.getElementById("deleteAccountForm");
  var deleteCancelBtn = document.getElementById("deleteAccountCancelBtn");
  var deleteConfirmBtn = document.getElementById("deleteAccountConfirmBtn");
  var deletePasswordEl = document.getElementById("deletePassword");
  var deleteErrorEl = document.getElementById("deleteAccountError");
  var deleteErrorMsgEl = document.getElementById("deleteAccountErrorMsg");
  var deleteLoadingEl = document.getElementById("deleteAccountLoading");

  if (deleteShowBtn) {
    deleteShowBtn.addEventListener("click", function () {
      deleteShowBtn.classList.add("hidden");
      if (deleteForm) deleteForm.classList.remove("hidden");
      if (deletePasswordEl) deletePasswordEl.focus();
    });
  }

  if (deleteCancelBtn) {
    deleteCancelBtn.addEventListener("click", function () {
      if (deleteForm) deleteForm.classList.add("hidden");
      deleteShowBtn.classList.remove("hidden");
      if (deletePasswordEl) deletePasswordEl.value = "";
      if (deleteErrorEl) deleteErrorEl.classList.add("hidden");
    });
  }

  if (deleteConfirmBtn) {
    deleteConfirmBtn.addEventListener("click", async function () {
      if (deleteErrorEl) deleteErrorEl.classList.add("hidden");
      var pwd = deletePasswordEl ? deletePasswordEl.value : "";
      if (!pwd) {
        if (deleteErrorEl) deleteErrorEl.classList.remove("hidden");
        if (deleteErrorMsgEl) deleteErrorMsgEl.textContent = "Zadejte heslo pro potvrzení.";
        return;
      }

      deleteConfirmBtn.disabled = true;
      if (deleteCancelBtn) deleteCancelBtn.disabled = true;
      if (deleteLoadingEl) deleteLoadingEl.classList.remove("hidden");

      try {
        var res = await window.fetchWithAuth("/api/v1/auth/delete-account", {
          method: "POST",
          body: JSON.stringify({ password: pwd }),
        });
        var data = await res.json();
        if (!res.ok) {
          if (deleteErrorEl) deleteErrorEl.classList.remove("hidden");
          if (deleteErrorMsgEl) deleteErrorMsgEl.textContent = window.apiErrorMessage(data);
          deleteConfirmBtn.disabled = false;
          if (deleteCancelBtn) deleteCancelBtn.disabled = false;
          return;
        }
        // Success — clear session and redirect to login
        window.clearToken();
        window.location.href = "/login";
      } catch (err) {
        if (deleteErrorEl) deleteErrorEl.classList.remove("hidden");
        if (deleteErrorMsgEl) deleteErrorMsgEl.textContent = err.message || "Nepodařilo se smazat účet.";
        deleteConfirmBtn.disabled = false;
        if (deleteCancelBtn) deleteCancelBtn.disabled = false;
      } finally {
        if (deleteLoadingEl) deleteLoadingEl.classList.add("hidden");
      }
    });
  }
})();
