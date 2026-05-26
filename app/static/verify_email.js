(function () {
  const loading = document.getElementById("verifyLoading");
  const success = document.getElementById("verifySuccess");
  const errorBox = document.getElementById("verifyError");
  const errorText = document.getElementById("verifyErrorText");

  function show(el) {
    [loading, success, errorBox].forEach((e) => {
      if (e) e.classList.toggle("hidden", e !== el);
    });
  }

  async function verify() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) {
      if (errorText) errorText.textContent = "Chybí ověřovací token v odkazu.";
      show(errorBox);
      return;
    }

    try {
      const res = await fetch("/api/v1/auth/verify-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (res.ok) {
        show(success);
      } else {
        const data = await res.json().catch(() => ({}));
        if (errorText)
          errorText.textContent =
            (data && data.error && data.error.message) ||
            "Odkaz pro ověření je neplatný nebo vypršel.";
        show(errorBox);
      }
    } catch (e) {
      if (errorText) errorText.textContent = String(e.message || e || "Chyba při ověřování.");
      show(errorBox);
    }
  }

  verify();
})();
