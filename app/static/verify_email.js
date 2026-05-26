(function () {
  "use strict";

  var loadingEl = document.getElementById("verifyLoading");
  var successEl = document.getElementById("verifySuccess");
  var errorEl = document.getElementById("verifyError");
  var errorMsgEl = document.getElementById("verifyErrorMsg");

  function showError(msg) {
    if (loadingEl) loadingEl.classList.add("hidden");
    if (successEl) successEl.classList.add("hidden");
    if (errorEl) errorEl.classList.remove("hidden");
    if (errorMsgEl && msg) errorMsgEl.textContent = msg;
  }

  function showSuccess() {
    if (loadingEl) loadingEl.classList.add("hidden");
    if (errorEl) errorEl.classList.add("hidden");
    if (successEl) successEl.classList.remove("hidden");
    setTimeout(function () {
      window.location.href = "/login";
    }, 2500);
  }

  var params = new URLSearchParams(window.location.search);
  var token = params.get("token");

  if (!token) {
    showError("Chybí ověřovací token. Zkontrolujte odkaz v e-mailu.");
    return;
  }

  fetch("/api/v1/auth/verify-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token }),
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, data: data };
      });
    })
    .then(function (result) {
      if (result.ok) {
        showSuccess();
      } else {
        var msg =
          (result.data && result.data.error && result.data.error.message) ||
          "Odkaz pro ověření je neplatný nebo vypršel.";
        showError(msg);
      }
    })
    .catch(function () {
      showError("Nepodařilo se ověřit e-mail. Zkuste to prosím znovu.");
    });
})();
