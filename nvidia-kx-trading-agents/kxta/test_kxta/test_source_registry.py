from unittest.mock import patch

from kxta.source_agents.registry import SourceRegistry, RagSource, KdbSource


def test_rag_source_available_when_collection_present():
    reg = SourceRegistry()
    # RAG is now gated on server reachability too; mock the probe as reachable.
    with patch("kxta.source_agents.registry._rag_reachable", return_value=True):
        enabled = reg.enabled_sources({"use_rag": True, "collection": "demo"})
    assert any(s.name == "rag" for s in enabled)


def test_rag_source_unavailable_when_server_unreachable():
    reg = SourceRegistry()
    with patch("kxta.source_agents.registry._rag_reachable", return_value=False):
        enabled = reg.enabled_sources({"use_rag": True, "collection": "demo"})
    assert all(s.name != "rag" for s in enabled)


def test_rag_source_unavailable_without_collection():
    reg = SourceRegistry()
    enabled = reg.enabled_sources({"use_rag": True, "collection": ""})
    assert all(s.name != "rag" for s in enabled)


def test_kdb_source_gated_by_availability_flag():
    reg = SourceRegistry()
    with patch("kxta.source_agents.registry._kdb_available", return_value=False):
        enabled = reg.enabled_sources({"use_kdb": True, "collection": "demo"})
        assert all(s.name != "kdb" for s in enabled)
    with patch("kxta.source_agents.registry._kdb_available", return_value=True):
        enabled = reg.enabled_sources({"use_kdb": True, "collection": "demo"})
        assert any(s.name == "kdb" for s in enabled)


def test_kdb_source_enabled_via_env_auto_detect():
    """use_kdb=None (legacy) + KDB_ENABLED env -> KDB included when mcp available."""
    reg = SourceRegistry()
    with patch("kxta.source_agents.registry.KDB_ENABLED", True), \
         patch("kxta.source_agents.registry._kdb_available", return_value=True):
        enabled = reg.enabled_sources({"collection": "demo"})  # use_kdb absent -> None
        assert any(s.name == "kdb" for s in enabled)


def test_all_sources_lists_registered_names():
    reg = SourceRegistry()
    names = {s.name for s in reg.all_sources()}
    assert {"rag", "kdb"} <= names


def test_agent_sources_registered():
    from kxta.source_agents.registry import SourceRegistry
    names = {s.name for s in SourceRegistry().all_sources()}
    assert {"web_search", "market_data", "news_headlines", "fundamentals"} <= names


def test_web_search_not_enabled_without_key(monkeypatch):
    from kxta.source_agents.registry import SourceRegistry
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    enabled = SourceRegistry().enabled_sources({"use_web_search": True, "collection": "demo"})
    assert all(s.name != "web_search" for s in enabled)


def test_market_data_enabled_only_when_flag_and_available(monkeypatch):
    import importlib.util
    from kxta.source_agents.registry import SourceRegistry
    # market_data needs yfinance AND an Alpha Vantage key (its tools use Alpha Vantage).
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "x")
    enabled = SourceRegistry().enabled_sources({"use_market_data": True, "collection": "demo"})
    has_yf = importlib.util.find_spec("yfinance") is not None
    assert ("market_data" in {s.name for s in enabled}) == has_yf


def test_market_data_needs_alphavantage_key(monkeypatch):
    from kxta.source_agents.registry import SourceRegistry
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    enabled = SourceRegistry().enabled_sources({"use_market_data": True, "collection": "demo"})
    assert "market_data" not in {s.name for s in enabled}


def test_tool_backed_sources_registered():
    from kxta.source_agents.registry import SourceRegistry
    names = {s.name for s in SourceRegistry().all_sources()}
    assert {"sec_filings", "macro_economic"} <= names


def test_enabled_sources_honors_per_source_flag(monkeypatch):
    import importlib.util
    from kxta.source_agents.registry import SourceRegistry
    monkeypatch.setenv("FRED_API_KEY", "x")
    reg = SourceRegistry()
    cfg = {"collection": "demo", "use_rag": True, "use_macro_economic": True}
    enabled_names = {s.name for s in reg.enabled_sources(cfg)}
    if importlib.util.find_spec("fredapi") is not None:
        assert "macro_economic" in enabled_names
    else:
        assert "macro_economic" not in enabled_names


def test_describe_sources_states(monkeypatch):
    from kxta.source_agents.registry import SourceRegistry
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    described = {d["name"]: d for d in SourceRegistry().describe_sources()}
    # macro_economic: module may be missing -> unavailable; if fredapi present but no key -> needs_key
    macro = described["macro_economic"]
    assert macro["state"] in {"unavailable", "needs_key"}
    if macro["state"] == "needs_key":
        assert macro["missing_key"] == "FRED_API_KEY"
    # rag is always describable
    assert described["rag"]["state"] in {"available", "unavailable"}
    # every entry carries name + label + state
    for d in described.values():
        assert {"name", "label", "state"} <= set(d)
    # 11 registry source agents (rag, kdb, kdb_docs, kdb_pit, onetick, web_search,
    # market_data, news_headlines, fundamentals, sec_filings, macro_economic)
    # + 1 synthetic Tavily 'web' entry = 12
    expected = {"rag", "kdb", "kdb_docs", "kdb_pit", "onetick", "web_search",
                "market_data", "news_headlines", "fundamentals", "sec_filings",
                "macro_economic", "web"}
    assert set(described) == expected
    assert len(described) == 12
    # synthetic Tavily entry reflects key presence
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    described2 = {d["name"]: d for d in SourceRegistry().describe_sources()}
    assert described2["web"]["label"] == "Web Search (Tavily)"
    assert described2["web"]["state"] == "needs_key"
    assert described2["web"]["missing_key"] == "TAVILY_API_KEY"
