#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import heapq
import math
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, unquote, urlparse

from html import unescape

import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table


BASE_URL = "https://en.wikipedia.org"
API_URL = f"{BASE_URL}/w/api.php"
VECTOR_DIMS = 4096
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']+", re.I)
NAMESPACE_RE = re.compile(
    r"^(Special|Help|Talk|User|User_talk|Wikipedia|Wikipedia_talk|File|File_talk|"
    r"MediaWiki|Template|Template_talk|Category|Category_talk|Portal|Draft|TimedText):",
    re.I,
)
STOPWORDS = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class Link:
    title: str
    anchor: str
    url: str


@dataclass
class Page:
    title: str
    url: str
    text: str
    links: list[Link]


@dataclass
class SearchResult:
    path: list[str]
    urls: list[str]
    pages_fetched: int
    elapsed: float


class HashVectorizer:
    def __init__(self, dims: int = VECTOR_DIMS) -> None:
        self.dims = dims
        self.vector_cache: dict[str, dict[int, float]] = {}

    def tokens(self, text: str) -> list[str]:
        return [token.lower().strip("-'") for token in TOKEN_RE.findall(text)]

    def vectorize(self, text: str) -> dict[int, float]:
        cached = self.vector_cache.get(text)
        if cached is not None:
            return cached

        counts: dict[int, float] = {}
        for token in self.tokens(text):
            if len(token) <= 2 or token in STOPWORDS:
                continue
            idx = stable_hash(token) % self.dims
            counts[idx] = counts.get(idx, 0.0) + 1.0

        norm = math.sqrt(sum(value * value for value in counts.values()))
        if not norm:
            self.vector_cache[text] = {}
            return {}
        vector = {idx: value / norm for idx, value in counts.items()}
        self.vector_cache[text] = vector
        return vector

    def cosine(self, left: dict[int, float], right: dict[int, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(idx, 0.0) for idx, value in left.items())


def stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest())


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if not path.startswith("/wiki/"):
        return url
    article = path.removeprefix("/wiki/").replace(" ", "_")
    return f"{BASE_URL}/wiki/{quote(article, safe='()_%')}"


def clean_title_from_url(url: str) -> str:
    return unquote(urlparse(url).path.removeprefix("/wiki/")).replace("_", " ")


def title_to_url(title: str) -> str:
    return f"{BASE_URL}/wiki/{quote(title.replace(' ', '_'), safe='()_%')}"


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", unquote(title).replace("_", " ")).strip().casefold()


def title_similarity(left: str, right: str) -> float:
    left_tokens = set(TOKEN_RE.findall(left.casefold())) - STOPWORDS
    right_tokens = set(TOKEN_RE.findall(right.casefold())) - STOPWORDS
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def target_aliases(target_page: Page) -> set[str]:
    aliases = {
        normalize_title(target_page.title),
        normalize_title(clean_title_from_url(target_page.url)),
    }
    for token in (" - Wikipedia",):
        aliases.add(normalize_title(target_page.title.removesuffix(token)))
    return aliases


def keyword_query(text: str, *, max_terms: int = 6) -> str:
    counts: dict[str, int] = {}
    for token in TOKEN_RE.findall(text.casefold()):
        if len(token) <= 2 or token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return " ".join(token for token, _ in ranked[:max_terms])


def is_article_href(href: str) -> bool:
    if not href.startswith("/wiki/"):
        return False
    target = unquote(href.removeprefix("/wiki/")).split("#", 1)[0]
    if not target or target.startswith("Main_Page"):
        return False
    return not NAMESPACE_RE.match(target)


def parse_page_html(url: str, html: str, *, lite: bool = False) -> Page:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.select_one("#firstHeading")
    title = heading.get_text(" ", strip=True) if heading else clean_title_from_url(url)

    text_parts: list[str] = [title]
    if not lite:
        content = soup.select_one("#mw-content-text") or soup
        for bad in content.select(
            "style, script, table.navbox, .metadata, .mw-editsection, .reference, "
            ".reflist, .hatnote, .ambox, .sidebar, .vertical-navbox"
        ):
            bad.decompose()
        for node in content.select("p, h2, h3, li"):
            piece = node.get_text(" ", strip=True)
            if piece:
                text_parts.append(piece)
            if len(" ".join(text_parts)) > 5000:
                break

    seen: set[str] = set()
    links: list[Link] = []
    body = soup.select_one("#mw-content-text .mw-parser-output") or soup.select_one("#mw-content-text") or soup
    for anchor in body.select("a[href]"):
        href = anchor.get("href", "")
        if not is_article_href(href):
            continue
        clean_href = href.split("#", 1)[0]
        absolute = canonical_url(f"{BASE_URL}{clean_href}")
        if absolute in seen:
            continue
        label = unescape(anchor.get_text(" ", strip=True))
        if not label:
            continue
        seen.add(absolute)
        links.append(Link(title=clean_title_from_url(absolute), anchor=label, url=absolute))

    return Page(title=title, url=canonical_url(url), text="\n".join(text_parts), links=links)


def is_valid_article_title(title: str) -> bool:
    if not title or title.startswith("#"):
        return False
    return not NAMESPACE_RE.match(title.replace(" ", "_"))


class WikiClient:
    """MediaWiki API client with in-session dedup only (no cross-run persistence)."""

    def __init__(self, *, min_interval: float = 0.18) -> None:
        self.min_interval = min_interval
        self.deadline: float | None = None
        self.last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "wiki-speedrun-solver/0.2 "
                    "(educational local project; MediaWiki API)"
                )
            }
        )
        self.network_fetches = 0
        self._session_pages: dict[str, Page] = {}

    def resolve_url(self, article: str) -> str:
        article = article.strip()
        if article.startswith("http://") or article.startswith("https://"):
            return canonical_url(article)
        article = article.replace(" ", "_")
        return f"{BASE_URL}/wiki/{quote(article, safe='()_%')}"

    def clear_session(self) -> None:
        self._session_pages.clear()

    def fetch(self, article_or_url: str, *, full: bool = True) -> Page:
        url = self.resolve_url(article_or_url)
        is_random = "Special:Random" in article_or_url or "Special%3ARandom" in url
        cache_key = f"{url}|{'full' if full else 'links'}"
        if not is_random:
            cached = self._session_pages.get(cache_key)
            if cached is not None:
                return cached

        if is_random:
            response = self._get(url)
            response.raise_for_status()
            url = canonical_url(response.url)
            cache_key = f"{url}|{'full' if full else 'links'}"

        page = self._fetch_via_html(url, lite=not full)
        self._session_pages[cache_key] = page
        self._session_pages[page.url] = page
        if page.url != url:
            self._session_pages[f"{url}|{'full' if full else 'links'}"] = page
        return page

    def _check_deadline(self) -> None:
        if self.deadline is not None and time.perf_counter() >= self.deadline:
            raise TimeoutError("Race time limit reached")

    def _request_timeout(self) -> float:
        if self.deadline is None:
            return 4.0
        remaining = self.deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError("Race time limit reached")
        return max(0.35, min(4.0, remaining))

    def _get(self, url: str, *, params: dict | None = None) -> requests.Response:
        self._check_deadline()
        wait = self.min_interval - (time.perf_counter() - self.last_request_at)
        if wait > 0:
            if self.deadline is not None:
                wait = min(wait, max(0.0, self.deadline - time.perf_counter()))
            if wait > 0:
                time.sleep(wait)
        timeout = self._request_timeout()
        try:
            if params is not None:
                response = self.session.get(url, params=params, timeout=(1.0, timeout))
            else:
                response = self.session.get(url, timeout=(1.0, timeout), allow_redirects=True)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            raise TimeoutError("Race time limit reached") from exc
        self.last_request_at = time.perf_counter()
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                delay = 1.25
            if self.deadline is not None:
                delay = min(delay, max(0.0, self.deadline - time.perf_counter() - 0.05))
            if delay <= 0:
                raise TimeoutError("Wikipedia rate limit reached")
            time.sleep(delay)
            return self._get(url, params=params)
        return response

    def _api(self, **params: object) -> dict:
        self._check_deadline()
        self.network_fetches += 1
        response = self._get(API_URL, params={"format": "json", **params})
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload

    def fetch_summary(self, title: str) -> tuple[str, str]:
        slug = quote(title.replace(" ", "_"), safe="()_%")
        self.network_fetches += 1
        response = self._get(f"{BASE_URL}/api/rest_v1/page/summary/{slug}")
        if response.status_code == 404:
            return title, title
        response.raise_for_status()
        payload = response.json()
        resolved = payload.get("title", title)
        extract = payload.get("extract", payload.get("description", resolved))
        return resolved, extract

    def fetch_race_pages(self, start: str, target: str) -> tuple[Page, Page]:
        start_page = self.fetch(start, full=False)
        target_guess = clean_title_from_url(self.resolve_url(target))
        target_title, summary = self.fetch_summary(target_guess)
        target_page = Page(
            title=target_title,
            url=title_to_url(target_title),
            text=f"{target_title}\n{summary}",
            links=[],
        )
        self._session_pages[target_page.url] = target_page
        return start_page, target_page

    def _fetch_via_html(self, url: str, *, lite: bool) -> Page:
        self._check_deadline()
        self.network_fetches += 1
        response = self._get(url)
        response.raise_for_status()
        final_url = canonical_url(response.url)
        return parse_page_html(final_url, response.text, lite=lite)

    def discover_bridges(self, target_page: Page, *, limit: int = 18) -> set[str]:
        queries = [
            keyword_query(f"{target_page.title}\n{target_page.text}", max_terms=8),
            target_page.title,
        ]
        bridges: set[str] = set()
        for query in queries:
            query = query.strip()
            if not query:
                continue
            payload = self._api(
                action="query",
                list="search",
                srsearch=query,
                srlimit=min(limit, 20),
                srnamespace=0,
            )
            for hit in payload.get("query", {}).get("search", []):
                title = hit.get("title", "")
                if is_valid_article_title(title):
                    bridges.add(normalize_title(title))
            if len(bridges) >= limit:
                break
        return bridges


MEDIA_HUB_RE = re.compile(
    r"\b(the times|the guardian|the economist|financial times|bbc news|"
    r"guardian|economist|telegraph|magazine|gazette|herald|journal)\b",
    re.I,
)
SCIENCE_TARGET_TOKENS = frozenset(
    {
        "physics",
        "quantum",
        "chemistry",
        "biology",
        "science",
        "mathematics",
        "engineering",
        "technology",
        "computer",
        "mechanics",
        "molecule",
        "atom",
        "energy",
        "photosynthesis",
        "semiconductor",
        "fusion",
        "dna",
        "mars",
        "climate",
    }
)
REGION_HUB_RE = re.compile(
    r"\b(united states|united kingdom|france|germany|china|india|europe|africa|asia|"
    r"world war|history of|international|national|republic|empire)\b",
    re.I,
)
SCIENCE_HUB_RE = re.compile(
    r"\b(science|physics|chemistry|mathematics|engineering|technology|computer|"
    r"quantum|biology|medicine|economics)\b",
    re.I,
)


HISTORY_TARGET_TOKENS = frozenset(
    {
        "war",
        "climate",
        "history",
        "exploration",
        "philosophy",
        "bitcoin",
        "blockchain",
        "mars",
        "space",
        "world",
        "culture",
        "art",
        "music",
        "literature",
        "language",
        "model",
        "learning",
        "intelligence",
        "photosynthesis",
        "semiconductor",
        "fusion",
    }
)


def target_is_science(target_tokens: set[str]) -> bool:
    return bool(target_tokens & SCIENCE_TARGET_TOKENS)


def target_is_history(target_tokens: set[str]) -> bool:
    return bool(target_tokens & HISTORY_TARGET_TOKENS)


def misleading_keyword_penalty(title: str, target_tokens: set[str]) -> float:
    link_tokens = set(TOKEN_RE.findall(title.casefold())) - STOPWORDS
    trap_tokens = {
        "gears",
        "game",
        "games",
        "movie",
        "film",
        "song",
        "album",
        "band",
        "minecraft",
        "swift",
        "lego",
        "dungeons",
        "modding",
        "speedrunning",
    }
    if link_tokens & trap_tokens:
        return -0.85
    if not (link_tokens & target_tokens):
        return 0.0
    if hub_likeness(title) >= 0.7 or MEDIA_HUB_RE.search(title) or REGION_HUB_RE.search(title):
        return 0.0
    if "(" in title or ")" in title:
        return -0.35
    return 0.0


def same_topic_penalty(link: Link, start_tokens: set[str], target_tokens: set[str]) -> float:
    link_tokens = set(TOKEN_RE.findall(link.title.casefold())) - STOPWORDS
    if not link_tokens or not start_tokens:
        return 0.0
    if not (start_tokens & link_tokens):
        return 0.0
    if target_tokens & link_tokens:
        return 0.0
    if hub_likeness(link.title) >= 0.7 or structural_hub_bonus(link.title, target_tokens) > 0.4:
        return 0.0
    return -0.7


def structural_hub_bonus(title: str, target_tokens: set[str]) -> float:
    science_target = target_is_science(target_tokens)
    history_target = target_is_history(target_tokens)
    bonus = 0.0
    if MEDIA_HUB_RE.search(title):
        if history_target:
            bonus += 0.8
        elif science_target:
            bonus += 0.25
        else:
            bonus += 0.55
    if REGION_HUB_RE.search(title):
        bonus += 0.55 if history_target else (0.5 if science_target else 0.45)
    if SCIENCE_HUB_RE.search(title):
        bonus += 0.75 if science_target else 0.4
    return bonus


def hub_likeness(title: str) -> float:
    """Prefer short, general article titles that often bridge unrelated topics."""
    if "(" in title or ")" in title:
        return 0.0
    words = [word for word in TOKEN_RE.findall(title) if word not in STOPWORDS]
    if not words:
        return 0.0
    if len(words) == 1:
        return 0.45
    if len(words) == 2:
        return 0.95
    if len(words) == 3:
        return 0.7
    if len(words) <= 5:
        return 0.25
    return 0.0


def cheap_link_score(link: Link, target_tokens: set[str], bridge_keys: set[str]) -> float:
    link_key = normalize_title(link.title)
    if link_key in bridge_keys:
        return 4.0
    link_tokens = set(TOKEN_RE.findall(link.title.casefold())) - STOPWORDS
    overlap = len(link_tokens & target_tokens)
    return (
        overlap
        + hub_likeness(link.title)
        + structural_hub_bonus(link.title, target_tokens)
        + (0.08 * min(len(link_tokens), 6))
    )


def rank_links(
    page: Page,
    *,
    target_page: Page,
    target_vector: dict[int, float],
    vectorizer: HashVectorizer,
    target_tokens: set[str],
    start_tokens: set[str],
    bridge_keys: set[str],
    category_text: str,
    beam: int,
) -> list[tuple[float, Link]]:
    candidates = select_link_candidates(
        page.links,
        target_page=target_page,
        target_tokens=target_tokens,
        bridge_keys=bridge_keys,
        limit=max(beam * 12, 320),
    )
    fast_ranked = sorted(
        (
            (
                fast_link_score(
                    link,
                    target_page,
                    bridge_keys=bridge_keys,
                    target_tokens=target_tokens,
                    start_tokens=start_tokens,
                ),
                link,
            )
            for link in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )[: max(beam * 3, 90)]
    return sorted(
        (
            (
                score_link(
                    link,
                    target_page,
                    target_vector,
                    vectorizer,
                    bridge_keys=bridge_keys,
                    category_text=category_text,
                    start_tokens=start_tokens,
                ),
                link,
            )
            for _, link in fast_ranked
        ),
        key=lambda item: item[0],
        reverse=True,
    )[:beam]


def target_token_overlap(title: str, target_tokens: set[str]) -> float:
    link_tokens = set(TOKEN_RE.findall(title.casefold())) - STOPWORDS
    if not link_tokens or not target_tokens:
        return 0.0
    return len(link_tokens & target_tokens) / len(target_tokens)


def fast_link_score(
    link: Link,
    target_page: Page,
    *,
    bridge_keys: set[str],
    target_tokens: set[str],
    start_tokens: set[str],
) -> float:
    target_title = normalize_title(target_page.title)
    link_title = normalize_title(link.title)
    exact_bonus = 3.0 if link_title == target_title else 0.0
    contains_bonus = 0.45 if target_title in link_title or link_title in target_title else 0.0
    bridge_bonus = 0.9 if link_title in bridge_keys else 0.0
    list_bonus = 0.55 if link.title.casefold().startswith("list of") else 0.0
    start_overlap = target_token_overlap(link.title, start_tokens) if start_tokens else 0.0
    topic_penalty = same_topic_penalty(link, start_tokens, target_tokens)
    keyword_penalty = misleading_keyword_penalty(link.title, target_tokens)
    return (
        exact_bonus
        + contains_bonus
        + bridge_bonus
        + list_bonus
        + topic_penalty
        + keyword_penalty
        + hub_likeness(link.title)
        + structural_hub_bonus(link.title, target_tokens)
        + title_similarity(link.title, target_page.title)
        + (1.1 * target_token_overlap(link.title, target_tokens))
        + (0.35 * start_overlap)
    )


def select_link_candidates(
    links: list[Link],
    *,
    target_page: Page,
    target_tokens: set[str],
    bridge_keys: set[str],
    limit: int,
) -> list[Link]:
    bridge_links = [link for link in links if normalize_title(link.title) in bridge_keys]
    hub_links = sorted(
        [link for link in links if hub_likeness(link.title) >= 0.7],
        key=lambda link: (
            hub_likeness(link.title),
            cheap_link_score(link, target_tokens, bridge_keys),
        ),
        reverse=True,
    )[:140]
    cheap_links = sorted(
        links,
        key=lambda link: cheap_link_score(link, target_tokens, bridge_keys),
        reverse=True,
    )[: max(limit, 260)]

    chosen: list[Link] = []
    seen: set[str] = set()
    for link in bridge_links + hub_links + cheap_links:
        if link.url in seen:
            continue
        seen.add(link.url)
        chosen.append(link)
        if len(chosen) >= limit:
            break
    return chosen


def score_link(
    link: Link,
    target_page: Page,
    target_vector: dict[int, float],
    vectorizer: HashVectorizer,
    *,
    bridge_keys: set[str],
    category_text: str,
    start_tokens: set[str],
) -> float:
    link_text = f"{link.title} {link.anchor}"
    vec_score = vectorizer.cosine(vectorizer.vectorize(link_text), target_vector)
    title_score = title_similarity(link.title, target_page.title)
    target_title = normalize_title(target_page.title)
    link_title = normalize_title(link.title)
    exact_bonus = 3.0 if link_title == target_title else 0.0
    contains_bonus = 0.45 if target_title in link_title or link_title in target_title else 0.0
    bridge_bonus = 0.9 if link_title in bridge_keys else 0.0
    category_bonus = 0.0
    if category_text:
        category_bonus = 0.35 * title_similarity(link.title, category_text)
    hub_bonus = hub_likeness(link.title)
    list_bonus = 0.55 if link.title.casefold().startswith("list of") else 0.0
    target_title_tokens = set(TOKEN_RE.findall(target_page.title.casefold())) - STOPWORDS
    overlap_bonus = 1.1 * target_token_overlap(link.title, target_title_tokens)
    start_overlap = 0.35 * target_token_overlap(link.title, start_tokens) if start_tokens else 0.0
    topic_penalty = same_topic_penalty(link, start_tokens, target_title_tokens)
    keyword_penalty = misleading_keyword_penalty(link.title, target_title_tokens)
    return (
        exact_bonus
        + contains_bonus
        + bridge_bonus
        + category_bonus
        + hub_bonus
        + topic_penalty
        + keyword_penalty
        + structural_hub_bonus(link.title, target_title_tokens)
        + list_bonus
        + overlap_bonus
        + start_overlap
        + (1.45 * vec_score)
        + (0.95 * title_score)
    )


def solve(
    client: WikiClient,
    start: str,
    target: str,
    *,
    beam: int,
    max_pages: int,
    max_depth: int,
    time_limit: float,
    console: Console,
) -> SearchResult | None:
    started = time.perf_counter()
    deadline = started + time_limit
    client.deadline = deadline
    vectorizer = HashVectorizer()

    try:
        start_page, target_page = client.fetch_race_pages(start, target)
    except TimeoutError:
        client.deadline = None
        return None
    known_pages = {start_page.url: start_page, target_page.url: target_page}
    aliases = target_aliases(target_page)
    bridge_keys: set[str] = set()
    if time.perf_counter() + 0.75 < deadline:
        try:
            bridge_keys = client.discover_bridges(target_page)
        except (TimeoutError, RuntimeError):
            bridge_keys = set()
    category_text = " ".join(
        part.removeprefix("Category:")
        for part in TOKEN_RE.findall(target_page.text)
        if part not in STOPWORDS
    )
    target_vector = vectorizer.vectorize(target_page.text)
    target_tokens = set(TOKEN_RE.findall(target_page.title.casefold())) - STOPWORDS
    target_tokens |= set(TOKEN_RE.findall(keyword_query(target_page.text, max_terms=12)))
    start_tokens = set(TOKEN_RE.findall(start_page.title.casefold())) - STOPWORDS

    if normalize_title(start_page.title) in aliases:
        client.deadline = None
        return SearchResult(
            [start_page.title],
            [start_page.url],
            client.network_fetches,
            time.perf_counter() - started,
        )

    # Direct hit from the start page.
    for link in start_page.links:
        if normalize_title(link.title) in aliases:
            client.deadline = None
            return SearchResult(
                [start_page.title, target_page.title],
                [start_page.url, target_page.url],
                client.network_fetches,
                time.perf_counter() - started,
            )

    queue: list[tuple[float, int, int, str, str, list[str], list[str]]] = []
    counter = 0
    best_depth: dict[str, int] = {start_page.url: 0}
    expanded = 0

    def enqueue_links(
        page: Page,
        depth: int,
        path: list[str],
        urls: list[str],
    ) -> SearchResult | None:
        nonlocal counter
        ranked = rank_links(
            page,
            target_page=target_page,
            target_vector=target_vector,
            vectorizer=vectorizer,
            target_tokens=target_tokens,
            start_tokens=start_tokens,
            bridge_keys=bridge_keys,
            category_text=category_text,
            beam=beam,
        )
        for rank, (link_score, link) in enumerate(ranked):
            next_title_key = normalize_title(link.title)
            if next_title_key in aliases or link.url == target_page.url:
                client.deadline = None
                return SearchResult(
                    path + [target_page.title],
                    urls + [target_page.url],
                    client.network_fetches,
                    time.perf_counter() - started,
                )
            next_depth = depth + 1
            if best_depth.get(link.url, 10**9) <= next_depth:
                continue
            best_depth[link.url] = next_depth
            priority = (next_depth * 0.1) - link_score + (rank * 0.001)
            counter += 1
            heapq.heappush(
                queue,
                (
                    priority,
                    next_depth,
                    counter,
                    link.url,
                    link.title,
                    path + [link.title],
                    urls + [link.url],
                ),
            )
        return None

    found = enqueue_links(start_page, 0, [start_page.title], [start_page.url])
    if found is not None:
        return found

    while queue and expanded < max_pages:
        if time.perf_counter() >= deadline:
            break
        _, depth, _, page_url, page_title, path, urls = heapq.heappop(queue)
        if depth >= max_depth:
            continue

        if time.perf_counter() >= deadline:
            break

        page = known_pages.get(page_url)
        if page is None:
            try:
                page = client.fetch(page_url, full=False)
                known_pages[page_url] = page
            except (TimeoutError, Exception) as exc:
                if isinstance(exc, TimeoutError):
                    break
                console.print(f"[dim]skip {page_title}: {exc}[/dim]")
                continue

        if time.perf_counter() >= deadline:
            break
        expanded += 1

        found = enqueue_links(page, depth, path, urls)
        if found is not None:
            return found

        if expanded % 12 == 0:
            console.print(
                f"[dim]expanded={expanded} queued={len(queue)} "
                f"network={client.network_fetches} depth={depth}[/dim]"
            )

    client.deadline = None
    return None


def print_result(result: SearchResult, console: Console) -> None:
    table = Table(title="Wikipedia Speedrun Path")
    table.add_column("#", justify="right")
    table.add_column("Article")
    table.add_column("URL")
    for idx, (title, url) in enumerate(zip(result.path, result.urls), start=1):
        table.add_row(str(idx), title, url)
    console.print(table)
    console.print(
        f"[bold]Clicks:[/bold] {len(result.path) - 1}  "
        f"[bold]Network fetches:[/bold] {result.pages_fetched}  "
        f"[bold]Elapsed:[/bold] {result.elapsed:.2f}s"
    )


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast Wikipedia speedrun solver.")
    parser.add_argument("start", help="Start Wikipedia article title or URL")
    parser.add_argument("target", help="Target Wikipedia article title or URL")
    parser.add_argument("--beam", type=int, default=40, help="Promising links to expand per page")
    parser.add_argument("--max-pages", type=int, default=24, help="Maximum pages to expand")
    parser.add_argument("--max-depth", type=int, default=6, help="Maximum click depth")
    parser.add_argument(
        "--time-limit",
        type=float,
        default=3.6,
        help="Wall-clock seconds before giving up on this race",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    console = Console()
    client = WikiClient()

    console.print(
        f"[bold]Race:[/bold] {args.start} [dim]->[/dim] {args.target} "
        f"[dim](beam={args.beam}, max_pages={args.max_pages}, "
        f"max_depth={args.max_depth}, time_limit={args.time_limit}s)[/dim]"
    )
    try:
        result = solve(
            client,
            args.start,
            args.target,
            beam=args.beam,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            time_limit=args.time_limit,
            console=console,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    if result is None:
        console.print("[red]No path found within the search budget.[/red]")
        return 1

    print_result(result, console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
