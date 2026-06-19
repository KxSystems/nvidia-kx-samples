from kxta.source_agents.registry import RagSource, KdbSource
from kxta.source_agents.routing import select_sources


def test_financial_query_selects_kdb_and_keeps_rag():
    enabled = [RagSource(), KdbSource()]
    chosen = select_sources("What is the average trade volume for the stock", enabled, llm=None)
    names = {s.name for s in chosen}
    assert "kdb" in names
    assert "rag" in names  # RAG floor


def test_nonfinancial_query_selects_rag_only():
    enabled = [RagSource(), KdbSource()]
    chosen = select_sources("Summarize the clinical trial methodology", enabled, llm=None)
    names = {s.name for s in chosen}
    assert names == {"rag"}


def test_rag_only_enabled_returns_rag():
    enabled = [RagSource()]
    chosen = select_sources("anything at all", enabled, llm=None)
    assert [s.name for s in chosen] == ["rag"]


def test_no_floor_no_match_falls_back_to_all():

    class SpecialistOnly:
        name = "special"
        keywords = ["niche"]

    s = SpecialistOnly()
    chosen = select_sources("unrelated query", [s], llm=None)
    assert chosen == [s]


from kxta.source_agents.web_search import WebSearchSource
from kxta.source_agents.market_data import MarketDataSource


def test_routes_financial_query_to_market_data_with_rag_floor():
    enabled = [RagSource(), MarketDataSource(), WebSearchSource()]
    chosen = {s.name for s in select_sources("the stock price and trading volume", enabled, llm=None)}
    assert "market_data" in chosen and "rag" in chosen
    assert "web_search" not in chosen  # no web keyword in this query


from kxta.source_agents.sec_filings import SecFilingsSource
from kxta.source_agents.macro_economic import MacroEconomicSource


def test_macro_query_routes_to_macro_source():
    enabled = [RagSource(), MacroEconomicSource(), SecFilingsSource()]
    chosen = {s.name for s in select_sources("what is the latest US inflation rate", enabled, llm=None)}
    assert "macro_economic" in chosen and "rag" in chosen


def test_filings_query_routes_to_sec_source():
    enabled = [RagSource(), SecFilingsSource()]
    chosen = {s.name for s in select_sources("risk factors in the 10-K", enabled, llm=None)}
    assert "sec_filings" in chosen


# ---------------------------------------------------------------------------
# Plan 3: LLM-chosen routing — select_sources honors a planner-provided source tag.
# ---------------------------------------------------------------------------


def test_preferred_source_honored_over_keywords():
    """A valid planner tag overrides keyword routing (+ keeps the RAG floor)."""
    enabled = [RagSource(), MarketDataSource(), SecFilingsSource()]
    # Query keywords would match nothing special, but planner picked sec_filings.
    chosen = {s.name for s in select_sources("tell me about the company", enabled, preferred="sec_filings")}
    assert "sec_filings" in chosen and "rag" in chosen
    assert "market_data" not in chosen


def test_preferred_auto_falls_back_to_keywords():
    """preferred='auto' defers to keyword routing."""
    enabled = [RagSource(), MarketDataSource()]
    chosen = {s.name for s in select_sources("the stock price and trading volume", enabled, preferred="auto")}
    assert "market_data" in chosen and "rag" in chosen


def test_preferred_unknown_source_falls_back_to_keywords():
    """An unknown/not-enabled planner tag is ignored; keyword routing applies."""
    enabled = [RagSource(), MarketDataSource()]
    chosen = {s.name for s in select_sources("the stock price and trading volume", enabled, preferred="fundamentals")}
    assert "market_data" in chosen and "rag" in chosen


def test_preferred_empty_string_falls_back_to_keywords():
    enabled = [RagSource(), MacroEconomicSource()]
    chosen = {s.name for s in select_sources("what is the latest US inflation rate", enabled, preferred="")}
    assert "macro_economic" in chosen


# ---------------------------------------------------------------------------
# Plan 1+2: planner is source-aware — describe_for_planner lists selected+available sources.
# ---------------------------------------------------------------------------

from kxta.source_agents.registry import SourceRegistry


class _AvailableStub:
    """A keyless, always-available source (no requires_* -> available via is_available)."""

    def __init__(self, name):
        self.name = name
        self.label = name.title()
        self.description = f"{name} description"
        self.keywords = [name]

    def is_available(self):
        return True


class _NeedsKeyStub:
    name = "needs_key_src"
    label = "Needs Key"
    description = "requires a key"
    keywords = []
    requires_env = ["SOME_MISSING_KEY"]


def test_describe_for_planner_lists_selected_available_source_ids():
    """Selected + available sources appear with their canonical `source` id; off ones don't."""
    reg = SourceRegistry([_AvailableStub("alpha"), _AvailableStub("beta")])
    section = reg.describe_for_planner({"use_alpha": True, "use_beta": False})
    assert "`alpha`" in section
    assert "`beta`" not in section
    assert "Source-Routing Guidance" in section


def test_describe_for_planner_omits_selected_but_unavailable_source():
    """A source the user selected but can't run (missing key) is not advertised to the planner."""
    reg = SourceRegistry([_NeedsKeyStub()])
    section = reg.describe_for_planner({"use_needs_key_src": True})
    assert "No specialized data source" in section


def test_describe_for_planner_empty_when_nothing_selected():
    reg = SourceRegistry([_AvailableStub("alpha")])
    section = reg.describe_for_planner({"use_alpha": False})
    assert "No specialized data source" in section


# ---------------------------------------------------------------------------
# Plan 3: GeneratedQuery.source normalization.
# ---------------------------------------------------------------------------

from kxta.schema import GeneratedQuery


def test_generated_query_source_defaults_to_auto():
    q = GeneratedQuery(query="q", report_section="s", rationale="r")
    assert q.source == "auto"


def test_generated_query_source_normalized_lowercase():
    q = GeneratedQuery(query="q", report_section="s", rationale="r", source="  SEC_Filings ")
    assert q.source == "sec_filings"


def test_generated_query_blank_source_becomes_auto():
    q = GeneratedQuery(query="q", report_section="s", rationale="r", source="")
    assert q.source == "auto"


# ---------------------------------------------------------------------------
# Failure-aware rerouting (fallback chains)
# ---------------------------------------------------------------------------
from kxta.source_agents.routing import fallback_sources


class _Src:

    def __init__(self, name):
        self.name = name
        self.keywords = ["x"]


def test_fallback_sources_walks_chain_in_order():
    enabled = [_Src("kdb"), _Src("market_data"), _Src("web_search")]
    out = fallback_sources(["kdb"], enabled, tried={"kdb"})
    assert [s.name for s in out] == ["market_data", "web_search"]


def test_fallback_sources_skips_tried_and_disabled():
    enabled = [_Src("fundamentals"), _Src("web_search")]  # market_data/sec_filings not enabled
    out = fallback_sources(["fundamentals"], enabled, tried={"fundamentals"})
    assert [s.name for s in out] == ["web_search"]


def test_fallback_sources_dedupes_across_failures():
    enabled = [_Src("kdb"), _Src("market_data"), _Src("web_search")]
    out = fallback_sources(["kdb", "market_data"], enabled, tried={"kdb", "market_data"})
    assert [s.name for s in out] == ["web_search"]


def test_fallback_sources_empty_for_floor_sources():
    enabled = [_Src("rag"), _Src("web_search")]
    assert fallback_sources(["rag"], enabled, tried={"rag"}) == []


# ---------------------------------------------------------------------------
# Cross-agent findings digest
# ---------------------------------------------------------------------------
from kxta.search_utils import build_findings_digest


def test_build_findings_digest_parses_sources_xml():
    blob = ("<sources><source><query>TSLA fundamentals</query>"
            "<answer>Revenue 96B, margin -2%   extra   whitespace</answer></source>"
            "<source><query>RIVN news</query><answer>Robotaxi delay headlines</answer></source></sources>")
    d = build_findings_digest([blob])
    assert "TSLA fundamentals" in d and "Revenue 96B" in d
    assert "RIVN news" in d
    assert "extra whitespace" in d  # whitespace collapsed


def test_build_findings_digest_caps_length_and_skips_garbage():
    blob = "<sources><source><query>q</query><answer>" + ("x" * 5000) + "</answer></source></sources>"
    d = build_findings_digest([blob, "not-xml-at-all"], max_chars=300)
    assert len(d) <= 300
    assert build_findings_digest([]) == ""
