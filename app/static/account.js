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
})();
