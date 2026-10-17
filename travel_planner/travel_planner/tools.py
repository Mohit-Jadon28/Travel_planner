
from __future__ import annotations

from typing import Any, Optional

import requests
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch

from .config import CONFIG, COMPRESSION, GROQ_API_KEY, TAVILY_API_KEY
from .memory_store import MEMORY
from .utils import call_with_retry

# --- LLM client -----------------------------------------------------------

llm = ChatGroq(
    model=CONFIG["model"],
    temperature=CONFIG["temperature"],
    max_tokens=CONFIG["max_tokens"],
    api_key=GROQ_API_KEY or None,
)

search_tool = TavilySearch(
    max_results=COMPRESSION["search_results_kept"],
    search_depth="basic",
    tavily_api_key=TAVILY_API_KEY or None,
)

_STRUCTURED_LLM_CACHE: dict[type, Any] = {}


def structured_llm(schema: type):
    """Cached with_structured_output binding, one per schema — avoids
    re-building the tool-calling wrapper (and its schema tokens) every call."""
    if schema not in _STRUCTURED_LLM_CACHE:
        _STRUCTURED_LLM_CACHE[schema] = llm.with_structured_output(schema, include_raw=True)
    return _STRUCTURED_LLM_CACHE[schema]


# --- Web search (cached + compressed) --------------------------------------

_SEARCH_CACHE: dict[str, Any] = {}


def compress_search_results(raw: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(raw, dict):
        return []
    results = raw.get("results", [])[: COMPRESSION["search_results_kept"]]
    return [
        {"title": r.get("title", ""), "snippet": (r.get("content") or "")[: COMPRESSION["search_snippet_chars"]]}
        for r in results
    ]


def perform_research(query: str, force_refresh: bool = False) -> list[dict[str, str]]:
    """Web search with two layers of caching: in-process (this run) and
    on-disk (across runs), so repeat queries never re-spend a Tavily call."""
    if not force_refresh and query in _SEARCH_CACHE:
        return _SEARCH_CACHE[query]

    mem_key = f"search::{MEMORY.fingerprint(query)}"
    if not force_refresh:
        cached = MEMORY.get(mem_key)
        if cached is not None:
            _SEARCH_CACHE[query] = cached
            return cached

    if force_refresh:
        print(f"   Fresh tool call: Tavily search for '{query}'")

    try:
        raw = call_with_retry(search_tool.invoke, {"query": query})
        compact = compress_search_results(raw)
    except Exception as e:  # noqa: BLE001
        compact = [{"title": "error", "snippet": str(e)}]
    _SEARCH_CACHE[query] = compact
    MEMORY.set(mem_key, compact)
    return compact


# --- Weather (Open-Meteo, free & keyless) -----------------------------------

def get_destination_weather(destination: str, days: int = 5) -> str:
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": destination, "count": 1}, timeout=6,
        ).json()
        results = geo.get("results") or []
        if not results:
            return ""
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        wx = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon, "timezone": "auto",
                "forecast_days": min(days, 7),
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            }, timeout=6,
        ).json()
        daily = wx.get("daily") or {}
        dates = daily.get("time", [])
        if not dates:
            return ""
        parts = []
        for i, d in enumerate(dates[:days]):
            tmax = daily["temperature_2m_max"][i]
            tmin = daily["temperature_2m_min"][i]
            rain = (daily.get("precipitation_probability_max") or [0] * len(dates))[i]
            parts.append(f"{d}: {tmin}-{tmax}C rain {rain}%")
        return "; ".join(parts)[: COMPRESSION["weather_chars"]]
    except Exception:
        return ""


# --- Currency conversion (free API + offline fallback table) ---------------

_FALLBACK_RATES_TO_USD = {
    "INR": 1 / 83.0, "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "AED": 0.27, "JPY": 1 / 148.0,
}


def convert_currency(amount: float, from_ccy: str, to_ccy: str) -> Optional[float]:
    if not amount or from_ccy == to_ccy:
        return amount
    try:
        r = requests.get(
            "https://api.exchangerate.host/convert",
            params={"from": from_ccy, "to": to_ccy, "amount": amount}, timeout=6,
        ).json()
        result = r.get("result")
        if result is not None:
            return round(float(result), 2)
    except Exception:
        pass
    fu, tu = _FALLBACK_RATES_TO_USD.get(from_ccy), _FALLBACK_RATES_TO_USD.get(to_ccy)
    if fu and tu:
        return round(amount * fu / tu, 2)
    return None
