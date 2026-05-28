(function () {
  const email = document.getElementById("registerEmail");
  const password = document.getElementById("registerPassword");
  const confirmPassword = document.getElementById("registerConfirmPassword");
  const clientName = document.getElementById("registerClientName");
  const btn = document.getElementById("registerBtn");
  const err = document.getElementById("registerError");
  const passwordErr = document.getElementById("registerPasswordErr");
  const confirmErr = document.getElementById("registerConfirmErr");
  const loading = document.getElementById("registerLoading");

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
  }

  function clearErrors() {
    if (err) err.textContent = "";
    if (passwordErr) passwordErr.textContent = "";
    if (confirmErr) confirmErr.textContent = "";
  }

  async function submit() {
    clearErrors();
    const em = email.value.trim();
    const pw = password.value;
    const cpw = confirmPassword ? confirmPassword.value : "";
    const cn = clientName.value.trim();

    // General completeness check (catches empty password / email / client name)
    if (!em || !pw || !cpw || !cn) {
      if (err) err.textContent = "Vyplňte všechna pole.";
      return;
    }

    // Inline field validation — errors shown directly under the relevant input
    if (pw.length < 8) {
      if (passwordErr) passwordErr.textContent = "Heslo musí mít alespoň 8 znaků.";
      return;
    }
    if (pw !== cpw) {
      if (confirmErr) confirmErr.textContent = "Hesla se neshodují.";
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        // confirm_password is intentionally not sent — backend only needs password
        body: JSON.stringify({ email: em, password: pw, client_name: cn }),
      });
      const data = await res.json().catch(() => ({}));
      const fresh = res.headers.get("x-access-token");
      if (fresh) window.setToken(fresh);
      if (!res.ok) {
        if (res.status === 409 && data && data.error && data.error.code === "CLIENT_NAME_ALREADY_TAKEN") {
          if (err) err.textContent =
            "Tento název firmy nebo pracovního prostoru je již obsazený. Zvolte prosím jiný název.";
          return;
        }
        if (err) err.textContent = window.apiErrorMessage(data);
        return;
      }
      if (data.access_token) window.setToken(data.access_token);
      window.location.href = "/upload?onboarding=1";
    } catch (e) {
      if (err) err.textContent = String(e.message || e || "Registrace selhala.");
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

  // Submit on Enter from confirm field (natural form flow)
  if (confirmPassword) {
    confirmPassword.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
    // REG-2: clear "Hesla se neshodují" as soon as user starts re-typing
    confirmPassword.addEventListener("input", () => {
      if (confirmErr) confirmErr.textContent = "";
    });
  }
  if (password) {
    password.addEventListener("input", () => {
      if (passwordErr) passwordErr.textContent = "";
      if (confirmErr) confirmErr.textContent = "";
    });
  }
})();
