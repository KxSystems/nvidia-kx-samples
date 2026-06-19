# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import json
import logging
import typing
from typing import AsyncGenerator

from nat.data_models.api_server import AIQChatResponseChunk
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig
from nat.builder.builder import Builder
from nat.cli.register_workflow import register_function
from nat.builder.function_info import FunctionInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from kxta.nodes import finalize_summary
from kxta.nodes import reflect_on_summary
from kxta.nodes import summarize_sources
from kxta.nodes import web_research
from kxta.nodes import deepen_research
from kxta.schema import KXTAState
from kxta.schema import ConfigSchema
from kxta.schema import GenerateSummaryStateInput
from kxta.schema import GenerateSummaryStateOutput
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def serialize_pydantic(obj):
    if isinstance(obj, list):
        return [serialize_pydantic(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_pydantic(value) for key, value in obj.items()}
    elif hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump()
    elif hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()
    else:
        return obj


class KXTAGenerateSummaryConfig(FunctionBaseConfig, name="generate_summaries"):
    """
    Configuration for the generate_summary function/endpoint
    """
    rag_url: str = ""


def serialize_pydantic(obj):
    if isinstance(obj, list):
        return [serialize_pydantic(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_pydantic(value) for key, value in obj.items()}
    elif hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump()
    elif hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()
    else:
        return obj


@register_function(config_type=KXTAGenerateSummaryConfig)
async def generate_summary_fn(config: KXTAGenerateSummaryConfig, aiq_builder: Builder):
    """
    The main function for research, report writing, and reflection to generate a report, representing /generate_summary in config.yml
    """

    # Build the Stage 2 pipeline
    builder = StateGraph(KXTAState, config_schema=ConfigSchema)
    builder.add_node("web_research", web_research)
    builder.add_node("deepen_research", deepen_research)
    builder.add_node("summarize_sources", summarize_sources)
    builder.add_node("finalize_summary", finalize_summary)
    builder.add_node("reflect_on_summary", reflect_on_summary)

    # The chain is: START -> web_research (scout) -> deepen_research (multi-hop, no-op when
    # research_hops<=1) -> summarize_sources -> reflect_on_summary -> finalize_summary -> END
    builder.add_edge(START, "web_research")
    builder.add_edge("web_research", "deepen_research")
    builder.add_edge("deepen_research", "summarize_sources")
    builder.add_edge("summarize_sources", "reflect_on_summary")
    builder.add_edge("reflect_on_summary", "finalize_summary")
    builder.add_edge("finalize_summary", END)

    graph = builder.compile()

    # ------------------------------------------------------------------
    # SINGLE-OUTPUT
    # ------------------------------------------------------------------
    async def _generate_summary_single(message: GenerateSummaryStateInput) -> GenerateSummaryStateOutput:
        """
        Runs the entire pipeline to produce a final summarized report
        """
        # Acquire the LLM from the builder
        llm = await aiq_builder.get_llm(llm_name=message.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

        response: KXTAState = await graph.ainvoke(
            input={
                "queries": message.queries, "web_research_results": [], "running_summary": ""
            },
            config={
                "llm": llm,
                "report_organization": message.report_organization,
                "rag_url": config.rag_url,
                "collection": message.rag_collection,
                "search_web": message.search_web,
                "num_reflections": message.reflection_count,
                "topic": message.topic,
                "tickers": message.tickers,
                "research_hops": message.research_hops,
                "supervisor_mode": message.supervisor_mode,
                "max_supervisor_steps": message.max_supervisor_steps,
                "use_kdb": message.use_kdb,  # None = legacy auto-detect
                "use_rag": getattr(message, "use_rag", True),
                "use_web_search": message.use_web_search,
                "use_market_data": message.use_market_data,
                "use_news_headlines": message.use_news_headlines,
                "use_fundamentals": message.use_fundamentals,
                "use_sec_filings": message.use_sec_filings,
                "use_macro_economic": message.use_macro_economic,
                "use_onetick": message.use_onetick,
                "use_kdb_docs": message.use_kdb_docs,
                "use_kdb_pit": message.use_kdb_pit,
            })
        return GenerateSummaryStateOutput(final_report=response["final_report"], citations=response["citations"])

    # ------------------------------------------------------------------
    # STREAMING VERSION
    # ------------------------------------------------------------------
    async def _generate_summary_stream(
            message: GenerateSummaryStateInput) -> AsyncGenerator[GenerateSummaryStateOutput, None]:
        """
        Runs the entire pipeline to produce a final summarized report, streaming the response
        """
        # Acquire the LLM from the builder
        llm = await aiq_builder.get_llm(llm_name=message.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

        stream = graph.astream(
            input={
                "queries": message.queries, "web_research_results": [], "running_summary": ""
            },
            stream_mode=['custom', 'values'],
            config={
                "llm": llm,
                "report_organization": message.report_organization,
                "rag_url": config.rag_url,
                "collection": message.rag_collection,
                "topic": message.topic,
                "tickers": message.tickers,
                "research_hops": message.research_hops,
                "supervisor_mode": message.supervisor_mode,
                "max_supervisor_steps": message.max_supervisor_steps,
                "search_web": message.search_web,
                "num_reflections": message.reflection_count,
                "use_kdb": message.use_kdb,  # None = legacy auto-detect
                "use_rag": getattr(message, "use_rag", True),
                "use_web_search": message.use_web_search,
                "use_market_data": message.use_market_data,
                "use_news_headlines": message.use_news_headlines,
                "use_fundamentals": message.use_fundamentals,
                "use_sec_filings": message.use_sec_filings,
                "use_macro_economic": message.use_macro_economic,
                "use_onetick": message.use_onetick,
                "use_kdb_docs": message.use_kdb_docs,
                "use_kdb_pit": message.use_kdb_pit,
            },
        )
        # HARD-CANCEL: if the client disconnects, the consumer stops pulling from this
        # generator and the surrounding task is cancelled. Explicitly aclose() the
        # langgraph stream so GeneratorExit propagates into the in-flight node ->
        # its asyncio.gather of source agents -> the agents themselves, instead of
        # letting that batch run to completion in the background.
        try:
            async for _t, val in stream:
                if _t == "values":
                    if "final_report" not in val:
                        yield GenerateSummaryStateOutput(intermediate_step=json.dumps(serialize_pydantic(val)))
                    else:
                        yield GenerateSummaryStateOutput(final_report=val["final_report"], citations=val["citations"])
                else:
                    yield GenerateSummaryStateOutput(intermediate_step=json.dumps(serialize_pydantic(val)))
        except (GeneratorExit, asyncio.CancelledError):
            logger.info("generate_summary stream cancelled (client disconnect) — aborting in-flight agents")
            await stream.aclose()
            raise
        finally:
            # Idempotent: ensures the graph's running step is torn down on any exit path.
            await stream.aclose()

    # Instead of from_fn(...), provide both single & stream versions:
    yield FunctionInfo.create(
        single_fn=_generate_summary_single,
        stream_fn=_generate_summary_stream,
        description=
        "Generates a full report (Stage 2) by doing web research, summarizing, reflecting, and finalizing the report (supports streaming)."
    )
