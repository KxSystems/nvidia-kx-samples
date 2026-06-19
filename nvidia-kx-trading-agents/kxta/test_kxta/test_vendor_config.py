import pytest
from kxta.source_agents._vendor import config as vcfg


def test_llm_getters_return_injected_blueprint_llm():
    sentinel = object()
    with vcfg.use_blueprint_llm(sentinel):
        assert vcfg.get_research_llm() is sentinel
        assert vcfg.get_summarization_llm() is sentinel
        assert vcfg.get_query_summary_llm() is sentinel


def test_llm_getters_raise_when_no_llm_injected():
    with pytest.raises(RuntimeError):
        vcfg.get_research_llm()


def test_load_prompt_template_reads_vendor_prompts():
    text = vcfg.load_prompt_template("web_search.txt", iteration=0)
    assert isinstance(text, str)
