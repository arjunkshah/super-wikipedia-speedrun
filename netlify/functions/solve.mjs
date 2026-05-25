const BASE_URL = "https://en.wikipedia.org";
const API_URL = `${BASE_URL}/w/api.php`;
const USER_AGENT = "super-wikipedia-speedrun/0.1 (Netlify Function)";
const TOKEN_RE = /[a-z0-9][a-z0-9\-']+/gi;
const NAMESPACE_RE =
  /^(Special|Help|Talk|User|User_talk|Wikipedia|Wikipedia_talk|File|File_talk|MediaWiki|Template|Template_talk|Category|Category_talk|Portal|Draft|TimedText):/i;

const STOPWORDS = new Set([
  "the",
  "and",
  "for",
  "with",
  "from",
  "that",
  "this",
  "were",
  "was",
  "are",
  "has",
  "have",
  "had",
  "into",
  "also",
  "its",
  "their",
  "than",
  "other",
  "which",
  "about",
  "between",
  "during",
  "after",
  "before",
  "over",
  "under",
  "such",
  "more",
  "most",
  "some",
  "only",
  "when",
  "where",
  "while",
  "being",
  "been",
  "may",
  "can",
  "not",
  "but",
  "all",
  "any",
  "one",
  "two",
  "new",
  "old",
  "first",
  "last",
  "year",
  "years",
  "list",
  "history",
  "wikipedia",
]);

const AUTO_STAGES = [
  { name: "scout", timeLimit: 1.2, beam: 42, maxPages: 12, maxDepth: 6 },
  { name: "wide", timeLimit: 5.0, beam: 72, maxPages: 72, maxDepth: 8 },
  { name: "deep", timeLimit: 8.0, beam: 90, maxPages: 100, maxDepth: 8 },
  { name: "max", timeLimit: 16.0, beam: 120, maxPages: 220, maxDepth: 9 },
];

class RaceClient {
  constructor(deadline) {
    this.deadline = deadline;
    this.fetches = 0;
    this.pages = new Map();
    this.summaries = new Map();
    this.bridges = new Map();
  }

  timeLeft() {
    return this.deadline - performance.now();
  }

  checkTime() {
    if (this.timeLeft() <= 0) throw new Error("timeout");
  }

  async get(url, options = {}) {
    this.checkTime();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), Math.max(350, Math.min(4500, this.timeLeft() - 50)));
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          "User-Agent": USER_AGENT,
          Accept: options.accept || "*/*",
          ...(options.headers || {}),
        },
      });
      return response;
    } finally {
      clearTimeout(timeout);
    }
  }

  async fetchSummary(titleOrUrl) {
    const guess = cleanTitleFromUrl(resolveUrl(titleOrUrl));
    const key = normalizeTitle(guess);
    if (this.summaries.has(key)) return this.summaries.get(key);

    this.fetches += 1;
    const slug = encodeURIComponent(guess.replaceAll(" ", "_")).replace(/%28/g, "(").replace(/%29/g, ")");
    const response = await this.get(`${BASE_URL}/api/rest_v1/page/summary/${slug}`, {
      accept: "application/json",
    });
    if (!response.ok) {
      const fallback = { title: guess, url: titleToUrl(guess), text: guess };
      this.summaries.set(key, fallback);
      return fallback;
    }
    const payload = await response.json();
    const page = {
      title: payload.title || guess,
      url: titleToUrl(payload.title || guess),
      text: `${payload.title || guess}\n${payload.extract || payload.description || ""}`,
    };
    this.summaries.set(key, page);
    this.summaries.set(normalizeTitle(page.title), page);
    return page;
  }

  async fetchPage(titleOrUrl) {
    const url = resolveUrl(titleOrUrl);
    const key = canonicalUrl(url);
    if (this.pages.has(key)) return this.pages.get(key);

    this.fetches += 1;
    const response = await this.get(url, { accept: "text/html" });
    if (!response.ok) throw new Error(`fetch failed ${response.status}`);
    const finalUrl = canonicalUrl(response.url || url);
    if (this.pages.has(finalUrl)) return this.pages.get(finalUrl);
    const html = await response.text();
    const page = parsePage(finalUrl, html);
    this.pages.set(key, page);
    this.pages.set(finalUrl, page);
    return page;
  }

  async discoverBridges(targetPage, limit = 18) {
    const key = `${normalizeTitle(targetPage.title)}|${limit}`;
    if (this.bridges.has(key)) return this.bridges.get(key);
    const bridges = new Set();

    try {
      this.fetches += 1;
      const backlinks = await this.api({
        action: "query",
        list: "backlinks",
        bltitle: targetPage.title,
        blnamespace: "0",
        bllimit: String(Math.min(Math.max(limit * 8, 80), 250)),
        blfilterredir: "nonredirects",
      });
      for (const hit of backlinks.query?.backlinks || []) {
        if (isValidArticleTitle(hit.title)) bridges.add(normalizeTitle(hit.title));
      }
    } catch {}

    for (const query of [keywordQuery(targetPage.text, 8), targetPage.title]) {
      if (!query) continue;
      try {
        this.fetches += 1;
        const search = await this.api({
          action: "query",
          list: "search",
          srsearch: query,
          srlimit: String(Math.min(limit, 20)),
          srnamespace: "0",
        });
        for (const hit of search.query?.search || []) {
          if (isValidArticleTitle(hit.title)) bridges.add(normalizeTitle(hit.title));
        }
      } catch {}
      if (bridges.size >= limit) break;
    }

    this.bridges.set(key, bridges);
    return bridges;
  }

  async api(params) {
    const url = new URL(API_URL);
    url.searchParams.set("format", "json");
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
    const response = await this.get(url, { accept: "application/json" });
    if (!response.ok) throw new Error(`api failed ${response.status}`);
    return response.json();
  }
}

export async function handler(event) {
  if (event.httpMethod !== "POST") {
    return json({ ok: false, error: "POST required" }, 405);
  }

  let payload;
  try {
    payload = JSON.parse(event.body || "{}");
  } catch {
    return json({ ok: false, error: "Invalid JSON" }, 400);
  }

  const start = String(payload.start || "").trim();
  const target = String(payload.target || "").trim();
  if (!start || !target) return json({ ok: false, error: "Both start and target are required." }, 400);

  const started = performance.now();
  const client = new RaceClient(started + 24000);
  const attempts = [];

  for (const stage of AUTO_STAGES) {
    const stageStarted = performance.now();
    const beforeFetches = client.fetches;
    client.deadline = performance.now() + stage.timeLimit * 1000;
    const result = await solveStage(client, start, target, stage).catch(() => null);
    const attempt = {
      name: stage.name,
      elapsed: seconds(performance.now() - stageStarted),
      fetches: client.fetches - beforeFetches,
      found: Boolean(result),
      beam: stage.beam,
      maxPages: stage.maxPages,
      maxDepth: stage.maxDepth,
      timeLimit: stage.timeLimit,
    };
    attempts.push(attempt);
    if (result) {
      return json({
        ok: true,
        found: true,
        path: result.path,
        clicks: result.path.length - 1,
        elapsed: seconds(performance.now() - started),
        wallElapsed: seconds(performance.now() - started),
        fetches: client.fetches,
        auto: { mode: "auto", stage: stage.name, attempts, elapsed: seconds(performance.now() - started) },
      });
    }
  }

  return json({
    ok: true,
    found: false,
    elapsed: seconds(performance.now() - started),
    fetches: client.fetches,
    auto: { mode: "auto", stage: null, attempts, elapsed: seconds(performance.now() - started) },
  });
}

async function solveStage(client, start, target, stage) {
  const startPage = await client.fetchPage(start);
  const targetPage = await client.fetchSummary(target);
  const aliases = new Set([normalizeTitle(targetPage.title), normalizeTitle(cleanTitleFromUrl(targetPage.url))]);
  const bridges = await client.discoverBridges(targetPage);
  const targetTokens = new Set([...tokens(targetPage.title), ...tokens(keywordQuery(targetPage.text, 12))]);
  const startTokens = new Set(tokens(startPage.title));

  if (aliases.has(normalizeTitle(startPage.title))) return result([startPage], targetPage);
  for (const link of startPage.links) {
    if (aliases.has(normalizeTitle(link.title))) return result([startPage, linkToPage(link)], targetPage);
  }

  const queue = [];
  const bestDepth = new Map([[startPage.url, 0]]);
  let expanded = 0;
  let counter = 0;

  enqueue(startPage, 0, [startPage], startTokens);

  while (queue.length && expanded < stage.maxPages) {
    client.checkTime();
    queue.sort((a, b) => a.priority - b.priority || a.counter - b.counter);
    const item = queue.shift();
    if (item.depth >= stage.maxDepth) continue;
    const page = await client.fetchPage(item.link.url);
    expanded += 1;
    if (aliases.has(normalizeTitle(page.title))) return result([...item.path, page], targetPage);
    const direct = page.links.find((link) => aliases.has(normalizeTitle(link.title)));
    if (direct) return result([...item.path, page, linkToPage(direct)], targetPage);
    enqueue(page, item.depth, [...item.path, page], startTokens);
  }

  return null;

  function enqueue(page, depth, path, localStartTokens) {
    const ranked = page.links
      .map((link, index) => ({
        link,
        index,
        score: scoreLink(link, targetPage, targetTokens, localStartTokens, bridges),
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, stage.beam);

    for (const [rank, item] of ranked.entries()) {
      const link = item.link;
      if (aliases.has(normalizeTitle(link.title))) {
        queue.unshift({
          priority: -9999,
          counter: counter++,
          depth: depth + 1,
          link,
          path,
        });
        continue;
      }
      const nextDepth = depth + 1;
      if ((bestDepth.get(link.url) ?? 1e9) <= nextDepth) continue;
      bestDepth.set(link.url, nextDepth);
      queue.push({
        priority: nextDepth * 0.1 - item.score + rank * 0.001,
        counter: counter++,
        depth: nextDepth,
        link,
        path,
      });
    }
  }
}

function scoreLink(link, targetPage, targetTokens, startTokens, bridges) {
  const title = normalizeTitle(link.title);
  const linkTokens = new Set(tokens(link.title));
  const targetTitle = normalizeTitle(targetPage.title);
  const overlap = intersectionSize(linkTokens, targetTokens);
  let score = 0;
  if (title === targetTitle) score += 10;
  if (bridges.has(title)) score += 5.5;
  if (targetTitle.includes(title) || title.includes(targetTitle)) score += 1.0;
  score += overlap * 1.8;
  score += titleSimilarity(link.title, targetPage.title) * 1.2;
  score += hubLikeness(link.title);
  score += structuralHubBonus(link.title, targetTokens);
  if (link.title.toLowerCase().startsWith("list of")) score += 0.55;
  if (intersectionSize(linkTokens, startTokens) && !overlap && hubLikeness(link.title) < 0.7) score -= 0.55;
  return score;
}

function parsePage(url, html) {
  const heading = stripTags((html.match(/<h1[^>]*id=["']firstHeading["'][^>]*>([\s\S]*?)<\/h1>/i) || [null, cleanTitleFromUrl(url)])[1]);
  const links = [];
  const seen = new Set();
  const content = (html.match(/<div[^>]+id=["']mw-content-text["'][^>]*>([\s\S]*?)<noscript/i) || html.match(/<div[^>]+id=["']mw-content-text["'][^>]*>([\s\S]*)/i) || [null, html])[1];
  const linkRe = /<a\b([^>]*?)href=["']\/wiki\/([^"'#:]+(?:\([^"'#]*\))?[^"'#]*)["']([^>]*)>([\s\S]*?)<\/a>/gi;
  let match;
  while ((match = linkRe.exec(content))) {
    const rawTitle = decodeURIComponentSafe(match[2]).replaceAll("_", " ");
    if (!isValidArticleTitle(rawTitle) || rawTitle === "Main Page") continue;
    const label = stripTags(match[4]).trim();
    if (!label) continue;
    const linkUrl = titleToUrl(rawTitle);
    if (seen.has(linkUrl)) continue;
    seen.add(linkUrl);
    links.push({ title: rawTitle, anchor: label, url: linkUrl });
  }
  return { title: heading, url: canonicalUrl(url), text: heading, links };
}

function result(pages, targetPage) {
  const finalPages = pages.at(-1)?.title === targetPage.title ? pages : [...pages, targetPage];
  return { path: finalPages.map((page) => ({ title: page.title, url: page.url })) };
}

function linkToPage(link) {
  return { title: link.title, url: link.url, text: link.title, links: [] };
}

function tokens(text) {
  return (text.match(TOKEN_RE) || []).map((token) => token.toLowerCase()).filter((token) => token.length > 2 && !STOPWORDS.has(token));
}

function keywordQuery(text, maxTerms = 6) {
  const counts = new Map();
  for (const token of tokens(text)) counts.set(token, (counts.get(token) || 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length || a[0].localeCompare(b[0]))
    .slice(0, maxTerms)
    .map(([token]) => token)
    .join(" ");
}

function titleSimilarity(left, right) {
  const a = new Set(tokens(left));
  const b = new Set(tokens(right));
  if (!a.size || !b.size) return 0;
  return intersectionSize(a, b) / new Set([...a, ...b]).size;
}

function intersectionSize(a, b) {
  let count = 0;
  for (const value of a) if (b.has(value)) count += 1;
  return count;
}

function hubLikeness(title) {
  if (title.includes("(") || title.includes(")")) return 0;
  const words = tokens(title);
  if (words.length === 1) return 0.45;
  if (words.length === 2) return 0.95;
  if (words.length === 3) return 0.7;
  if (words.length <= 5) return 0.25;
  return 0;
}

function structuralHubBonus(title, targetTokens) {
  const lower = title.toLowerCase();
  let score = 0;
  if (/\b(the times|the guardian|the economist|bbc news|magazine|gazette|journal)\b/i.test(lower)) score += 0.55;
  if (/\b(united states|united kingdom|france|germany|china|india|europe|africa|asia|world war|international|national|republic|empire)\b/i.test(lower)) score += 0.55;
  if (/\b(science|physics|chemistry|mathematics|engineering|technology|computer|quantum|biology|medicine|economics|cricket)\b/i.test(lower)) score += 0.65;
  if (targetTokens.has("cricketer") || targetTokens.has("cricket") || targetTokens.has("indian")) {
    if (/\b(india|cricket|sports?)\b/i.test(lower)) score += 1.5;
  }
  return score;
}

function resolveUrl(article) {
  const value = String(article || "").trim();
  if (/^https?:\/\//i.test(value)) return canonicalUrl(value);
  return titleToUrl(value);
}

function canonicalUrl(url) {
  const parsed = new URL(url);
  if (!parsed.pathname.startsWith("/wiki/")) return url;
  return `${BASE_URL}/wiki/${encodeURIComponent(decodeURIComponentSafe(parsed.pathname.slice(6)).replaceAll(" ", "_")).replace(/%28/g, "(").replace(/%29/g, ")")}`;
}

function titleToUrl(title) {
  return `${BASE_URL}/wiki/${encodeURIComponent(String(title).replaceAll(" ", "_")).replace(/%28/g, "(").replace(/%29/g, ")")}`;
}

function cleanTitleFromUrl(url) {
  const parsed = new URL(url);
  return decodeURIComponentSafe(parsed.pathname.replace(/^\/wiki\//, "")).replaceAll("_", " ");
}

function normalizeTitle(title) {
  return decodeURIComponentSafe(String(title)).replaceAll("_", " ").replace(/\s+/g, " ").trim().toLowerCase();
}

function isValidArticleTitle(title) {
  return title && !title.startsWith("#") && !NAMESPACE_RE.test(title.replaceAll(" ", "_"));
}

function stripTags(html) {
  return decodeHtml(String(html).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}

function decodeHtml(text) {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function decodeURIComponentSafe(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function seconds(ms) {
  return Math.round((ms / 1000) * 1000) / 1000;
}

function json(payload, statusCode = 200) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
    body: JSON.stringify(payload),
  };
}
