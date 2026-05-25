(function () {
  const emailInput = document.getElementById("forgotEmail");
  const btn = document.getElementById("forgotBtn");
  const err = document.getElementById("forgotError");
  const loading = document.getElementById("forgotLoading");
  const form = document.getElementById("forgotForm");
  const success = document.getElementById("forgotSuccess");

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
  }

  async function submit() {
    if (err) err.textContent = "";
    const em = emailInput ? emailInput.value.trim() : "";
    if (!em) {
      if (err) err.textContent = "Zadejte e-mailovou adresu.";
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: em }),
      });
      // Always show success — even if email doesn't exist (security)
      if (form) form.classList.add("hidden");
      if (success) success.classList.remove("hidden");
    } catch (e) {
      if (err) err.textContent = "Nepodařilo se odeslat. Zkuste to prosím znovu.";
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
  if (emailInput) {
    emailInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
  }
})();
