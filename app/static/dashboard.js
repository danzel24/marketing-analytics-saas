/* global Chart */

const els = {
  tenant: document.getElementById("tenantSelect"),
  refresh: document.getElementById("refreshBtn"),
  status: document.getElementById("status"),

  kpiRevenue: document.getElementById("kpiRevenue"),
  kpiSpend: document.getElementById("kpiSpend"),
  kpiProfit: document.getElementById("kpiProfit"),
  kpiRoas: document.getElementById("kpiRoas"),

  tbody: document.getElementById("campaignTbody"),

  revenueCanvas: document.getElementById("revenueChart"),
  profitCanvas: document.getElementById("profitChart"),
  spendPieCanvas: document.getElementById("spendPieChart"),
};

let charts = {
  revenue: null,
  profit: null,
  spendPie: null,
};

function money(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // český formát: 1 234,56 Kč
  return (
    new Intl.NumberFormat("cs-CZ", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(n) + " Kč"
  );
}

function roas(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return (
    new Intl.NumberFormat("cs-CZ", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 4,
    }).format(n) + "×"
  );
}

function setStatus(text, kind = "info") {
  els.status.textContent = text || "";
  els.status.dataset.kind = kind;
}

function headersForTenant(tenantId) {
  return {
    "X-Tenant-Id": tenantId,
  };
}

async function fetchJson(url, tenantId) {
  const res = await fetch(url, {
    headers: headersForTenant(tenantId),
  });
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const message =
      typeof body === "object" && body && body.detail
        ? JSON.stringify(body.detail)
        : typeof body === "string"
          ? body
          : JSON.stringify(body);
    throw new Error(`${res.status} ${res.statusText}: ${message}`);
  }
  return body;
}

function destroyCharts() {
  for (const key of Object.keys(charts)) {
    if (charts[key]) {
      charts[key].destroy();
      charts[key] = null;
    }
  }
}

function renderKpis(metrics) {
  els.kpiRevenue.textContent = money(metrics.total_revenue);
  els.kpiSpend.textContent = money(metrics.total_spend);
  els.kpiProfit.textContent = money(metrics.total_profit);
  els.kpiRoas.textContent = roas(metrics.average_roas);
}

function renderTable(campaigns) {
  els.tbody.innerHTML = "";

  for (const c of campaigns) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(c.campaign)}</td>
      <td class="num">${money(c.spend)}</td>
      <td class="num">${money(c.revenue)}</td>
      <td class="num">${money(c.profit)}</td>
      <td class="num">${roas(c.roas)}</td>
    `;
    els.tbody.appendChild(tr);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderCharts(campaigns) {
  destroyCharts();

  const labels = campaigns.map((c) => c.campaign);
  const revenue = campaigns.map((c) => c.revenue);
  const profit = campaigns.map((c) => c.profit);
  const spend = campaigns.map((c) => c.spend);

  charts.revenue = new Chart(els.revenueCanvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Tržby",
          data: revenue,
          backgroundColor: "rgba(59, 130, 246, 0.7)",
          borderColor: "rgba(59, 130, 246, 1)",
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Tržby: ${money(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });

  charts.profit = new Chart(els.profitCanvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Zisk",
          data: profit,
          backgroundColor: "rgba(16, 185, 129, 0.7)",
          borderColor: "rgba(16, 185, 129, 1)",
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Zisk: ${money(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });

  charts.spendPie = new Chart(els.spendPieCanvas, {
    type: "pie",
    data: {
      labels,
      datasets: [
        {
          label: "Náklady",
          data: spend,
          backgroundColor: [
            "rgba(59, 130, 246, 0.75)",
            "rgba(16, 185, 129, 0.75)",
            "rgba(244, 63, 94, 0.75)",
            "rgba(234, 179, 8, 0.75)",
            "rgba(168, 85, 247, 0.75)",
            "rgba(20, 184, 166, 0.75)",
          ],
          borderColor: "rgba(255,255,255,0.9)",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right" },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${money(ctx.parsed)}`,
          },
        },
      },
    },
  });
}

async function loadDashboard() {
  const tenantId = els.tenant.value;
  setStatus("Loading…", "info");

  try {
    const [metrics, campaigns] = await Promise.all([
      fetchJson("/v1/metrics", tenantId),
      fetchJson("/v1/campaigns", tenantId),
    ]);

    renderKpis(metrics);
    renderTable(campaigns);
    renderCharts(campaigns);
    setStatus(`Načteno pro tenant „${tenantId}“`, "success");
  } catch (e) {
    destroyCharts();
    els.tbody.innerHTML = "";
    els.kpiRevenue.textContent = "—";
    els.kpiSpend.textContent = "—";
    els.kpiProfit.textContent = "—";
    els.kpiRoas.textContent = "—";
    setStatus(`Chyba při načítání: ${String(e.message || e)}`, "error");
  }
}

els.tenant.addEventListener("change", () => {
  loadDashboard();
});

els.refresh.addEventListener("click", () => {
  loadDashboard();
});

loadDashboard();

