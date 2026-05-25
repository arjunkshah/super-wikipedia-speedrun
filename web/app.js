const form = document.querySelector("#solve-form");
const button = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");
const metricsEl = document.querySelector("#metrics");
const pathEl = document.querySelector("#path");
const stopwatchEl = document.querySelector("#stopwatch");
const watchTimeEl = document.querySelector("#watch-time");

let watchTimer = null;
let watchStartedAt = 0;
let lastBrowserElapsed = 0;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoading(true);
  clearResult();
  startStopwatch();

  const payload = {
    start: document.querySelector("#start").value,
    target: document.querySelector("#target").value,
  };

  statusEl.textContent = "Finding the fastest route...";

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
    stopStopwatch();
    renderResult(data);
  } catch (error) {
    stopStopwatch();
    statusEl.textContent = error.message;
    statusEl.className = "status fail";
    metricsEl.hidden = false;
    metricsEl.innerHTML = [metric("browser wait", `${formatSeconds(lastBrowserElapsed)}s`)].join("");
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
  const stage = data.auto?.stage || data.settings?.mode || "auto";
  metricsEl.hidden = false;
  metricsEl.innerHTML = [
    metric("browser wait", `${formatSeconds(lastBrowserElapsed)}s`),
    metric("backend solve", `${formatSeconds(data.elapsed)}s`),
    metric("fetches", data.fetches),
    metric("mode", stage),
  ].join("");

  if (!data.found) {
    statusEl.textContent = "No path found after a deep search.";
    statusEl.className = "status fail";
    renderAttempts(data.auto?.attempts || []);
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
  renderAttempts(data.auto?.attempts || []);
}

function startStopwatch() {
  watchStartedAt = performance.now();
  lastBrowserElapsed = 0;
  stopwatchEl.hidden = false;
  tickStopwatch();
  clearInterval(watchTimer);
  watchTimer = setInterval(tickStopwatch, 50);
}

function stopStopwatch() {
  tickStopwatch();
  clearInterval(watchTimer);
  watchTimer = null;
}

function tickStopwatch() {
  lastBrowserElapsed = (performance.now() - watchStartedAt) / 1000;
  watchTimeEl.textContent = `${formatSeconds(lastBrowserElapsed)}s`;
}

function renderAttempts(attempts) {
  if (!attempts.length) return;
  const attemptText = attempts
    .map((attempt) => `${attempt.name}: ${formatSeconds(attempt.elapsed)}s`)
    .join("  /  ");
  metricsEl.insertAdjacentHTML("beforeend", metric("passes", attemptText));
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
