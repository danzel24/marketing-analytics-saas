(function () {
  const email = document.getElementById("loginEmail");
  const password = document.getElementById("loginPassword");
  const remember = document.getElementById("loginRemember");
  const btn = document.getElementById("loginBtn");
  const err = document.getElementById("loginError");
  const loading = document.getElementById("loginLoading");

  function setLoading(on) {
    if (loading) loading.classList.toggle("hidden", !on);
    if (btn) btn.disabled = on;
  }

  async function submit() {
    err.textContent = "";
    const em = email.value.trim();
    const pw = password.value;
    if (!em || !pw) {
      err.textContent = "Vyplňte email i heslo.";
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: em,
          password: pw,
          remember_me: remember && remember.checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      const fresh = res.headers.get("x-access-token");
      if (fresh) window.setToken(fresh);
      if (!res.ok) {
        err.textContent = window.apiErrorMessage(data);
        return;
      }
      if (data.access_token) window.setToken(data.access_token);
      window.location.href = "/dashboard";
    } catch (e) {
      err.textContent = String(e.message || e || "Přihlášení selhalo.");
    } finally {
      setLoading(false);
    }
  }

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    submit();
  });
  password.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
})();
