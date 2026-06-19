from kxta.source_agents.base import SourceResult, merge_source_results


def _r(source, content, citation="", relevant=True):
    return SourceResult(source=source, content=content, citation=citation, is_relevant=relevant)


def test_merge_single_relevant_source_returns_its_content():
    results = [_r("rag", "RAG answer", "rag-cite")]
    content, citation = merge_source_results(results, "q")
    assert "RAG answer" in content
    assert "rag-cite" in citation


def test_merge_single_source_has_no_attribution_header():
    content, citation = merge_source_results([_r("rag", "bare body", "rag-cite")], "q")
    assert content == "bare body"
    assert "**" not in content
    assert citation == "rag-cite"


def test_merge_two_relevant_sources_attributes_both():
    results = [_r("kdb", "KDB nums", "kdb-cite"), _r("rag", "RAG text", "rag-cite")]
    content, citation = merge_source_results(results, "q")
    assert "KDB nums" in content and "RAG text" in content
    assert "kdb-cite" in citation and "rag-cite" in citation
    assert "kdb" in content.lower() and "rag" in content.lower()


def test_merge_skips_irrelevant_when_a_relevant_exists():
    results = [_r("kdb", "irrelevant", relevant=False), _r("rag", "good", "rag-cite")]
    content, citation = merge_source_results(results, "q")
    assert "good" in content
    assert "irrelevant" not in content


def test_merge_no_relevant_returns_fallback_message():
    results = [_r("kdb", "", relevant=False)]
    content, citation = merge_source_results(results, "q")
    assert content
    assert citation == ""


def test_merge_all_irrelevant_with_content_returns_first_raw():
    results = [_r("kdb", "partial kdb data", "kdb-cite", relevant=False),
               _r("rag", "partial rag data", "rag-cite", relevant=False)]
    content, citation = merge_source_results(results, "q")
    assert content == "partial kdb data"  # first, raw, no attribution header
    assert citation == "kdb-cite"
