(function () {
  const passwordInput = document.getElementById("resetPassword");
  const confirmInput = document.getElementById("resetPasswordConfirm");
  const btn = document.getElementById("resetBtn");
  const err = document.getElementById("resetError");
  const loading = document.getElementById("resetLoading");
  const form = document.getElementById("resetForm");
  const invalidBanner = document.getElementById("resetInvalidToken");

  // Extract token from URL
  function getToken() {
    try {
      return new URLSearchParams(window.location.search).get("token") || "";
    } catch (_) {
      return "";
    }
  }

  const token = getToken();

  // If no token in URL, show invalid banner immediately
  if (!token) {
    if (form) form.classList.add("hidden");
    if (invalidBanner) invalidBanner.classList.remove("hidden");
  }

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
  }

  async function submit() {
    if (err) err.textContent = "";
    const pw = passwordInput ? passwordInput.value : "";
    const confirm = confirmInput ? confirmInput.value : "";

    if (!pw || pw.length < 8) {
      if (err) err.textContent = "Heslo musí mít alespoň 8 znaků.";
      return;
    }
    if (pw !== confirm) {
      if (err) err.textContent = "Hesla se neshodují.";
      return;
    }
    if (!token) {
      if (err) err.textContent = "Chybí token pro obnovení hesla.";
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, new_password: pw }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        // Token invalid / expired
        if (form) form.classList.add("hidden");
        if (invalidBanner) invalidBanner.classList.remove("hidden");
        return;
      }

      // Success — redirect to login with success message
      window.location.href = "/login?reset=1";
    } catch (e) {
      if (err) err.textContent = "Nepodařilo se uložit heslo. Zkuste to prosím znovu.";
    } finally {
      setLoading(false);
    }
  }

  if (btn) {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      submit();
    });
  }
  if (confirmInput) {
    confirmInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
  }
})();
