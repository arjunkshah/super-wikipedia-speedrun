"""Wikipedia Speedrun solver package."""

from .solver import Page, SearchResult, WikiClient, solve, solve_auto

__all__ = ["Page", "SearchResult", "WikiClient", "solve", "solve_auto"]
