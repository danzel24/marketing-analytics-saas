(function () {
  const email = document.getElementById("registerEmail");
  const password = document.getElementById("registerPassword");
  const clientName = document.getElementById("registerClientName");
  const btn = document.getElementById("registerBtn");
  const err = document.getElementById("registerError");
  const loading = document.getElementById("registerLoading");

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
  }

  async function submit() {
    err.textContent = "";
    const em = email.value.trim();
    const pw = password.value;
    const cn = clientName.value.trim();
    if (!em || !pw || !cn) {
      err.textContent = "Vyplňte všechna pole.";
      return;
    }
    if (pw.length < 8) {
      err.textContent = "Heslo musí mít alespoň 8 znaků.";
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: em,
          password: pw,
          client_name: cn,
        }),
      });
      const data = await res.json().catch(() => ({}));
      const fresh = res.headers.get("x-access-token");
      if (fresh) window.setToken(fresh);
      if (!res.ok) {
        if (res.status === 409 && data && data.error && data.error.code === "CLIENT_NAME_ALREADY_TAKEN") {
          err.textContent =
            "Tento název firmy nebo pracovního prostoru je již obsazený. Zvolte prosím jiný název.";
          return;
        }
        err.textContent = window.apiErrorMessage(data);
        return;
      }
      if (data.access_token) window.setToken(data.access_token);
      window.location.href = "/dashboard";
    } catch (e) {
      err.textContent = String(e.message || e || "Registrace selhala.");
    } finally {
      setLoading(false);
    }
  }

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    submit();
  });
})();
