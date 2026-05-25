const form = document.querySelector("#solve-form");
const button = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");
const metricsEl = document.querySelector("#metrics");
const pathEl = document.querySelector("#path");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoading(true);
  clearResult();

  const payload = {
    start: document.querySelector("#start").value,
    target: document.querySelector("#target").value,
    timeLimit: Number(document.querySelector("#timeLimit").value),
    beam: Number(document.querySelector("#beam").value),
    maxPages: Number(document.querySelector("#maxPages").value),
    maxDepth: Number(document.querySelector("#maxDepth").value),
  };

  statusEl.textContent = "Searching live Wikipedia...";

  try {
    const response = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Request failed.");
    }
    renderResult(data);
  } catch (error) {
    statusEl.textContent = error.message;
    statusEl.className = "status fail";
  } finally {
    setLoading(false);
  }
});

function setLoading(loading) {
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
}

function clearResult() {
  statusEl.className = "status";
  metricsEl.hidden = true;
  metricsEl.innerHTML = "";
  pathEl.innerHTML = "";
}

function renderResult(data) {
  metricsEl.hidden = false;
  metricsEl.innerHTML = [
    metric("elapsed", `${formatSeconds(data.elapsed)}s`),
    metric("fetches", data.fetches),
    metric("limit", `${data.settings.timeLimit}s`),
  ].join("");

  if (!data.found) {
    statusEl.textContent = "No path found inside the budget.";
    statusEl.className = "status fail";
    return;
  }

  statusEl.textContent = `${data.clicks} click${data.clicks === 1 ? "" : "s"} found.`;
  statusEl.className = "status win";
  metricsEl.insertAdjacentHTML("afterbegin", metric("clicks", data.clicks));
  pathEl.innerHTML = data.path
    .map(
      (step) => `
        <li>
          <a href="${escapeAttr(step.url)}" target="_blank" rel="noreferrer">
            ${escapeHtml(step.title)}
          </a>
        </li>
      `
    )
    .join("");
}

function metric(label, value) {
  return `<span class="metric">${escapeHtml(label)}: <strong>${escapeHtml(String(value))}</strong></span>`;
}

function formatSeconds(value) {
  return Number(value || 0).toFixed(2);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]
  );
}

function escapeAttr(value) {
  return escapeHtml(value);
}
