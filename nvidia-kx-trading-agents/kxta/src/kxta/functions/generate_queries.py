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

from typing import AsyncGenerator
import typing
from nat.data_models.api_server import AIQChatResponseChunk
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig
from nat.builder.builder import Builder
from nat.cli.register_workflow import register_function
from nat.builder.function_info import FunctionInfo
from nat.builder.framework_enum import LLMFrameworkEnum
import asyncio
import json

import os

from kxta.guardrails import check_content_safety
from kxta.nodes import generate_query
from kxta.schema import KXTAState
from kxta.schema import ConfigSchema
from kxta.schema import GenerateQueryStateInput
from kxta.schema import GenerateQueryStateOutput
from langchain_core.runnables import RunnableConfig
from langgraph.graph import START, END, StateGraph
import logging

logger = logging.getLogger(__name__)


class KXTAGenerateQueriesConfig(FunctionBaseConfig, name="generate_queries"):
    """
    Configuration for the generate_queries function/endpoint
    """


async def _topic_blocked_by_guardrail(topic: str) -> str | None:
    """NemoGuard content-safety input rail on the research topic.

    Active only when KXTA_APPLY_GUARDRAIL=nemoguard (the "true" value keeps its
    existing meaning: the LLM relevancy gate used in artifact_qa). Returns a
    user-facing error message when the topic is unsafe, None to proceed.
    Enhance-when-present: if the NemoGuard NIM is not configured or
    unavailable, check_content_safety returns None and generation proceeds.
    """
    if os.getenv("KXTA_APPLY_GUARDRAIL", "false").lower() != "nemoguard":
        return None
    safety = await check_content_safety(topic)
    if safety is not None and not safety["safe"]:
        logger.warning(f"NemoGuard blocked research topic (categories: {safety['categories']})")
        msg = "The research topic was blocked by the content safety guardrail."
        if safety["categories"]:
            msg += f" Flagged categories: {safety['categories']}."
        return msg + " Please rephrase your topic."
    return None


@register_function(config_type=KXTAGenerateQueriesConfig)
async def generate_queries_fn(config: KXTAGenerateQueriesConfig, aiq_builder: Builder):
    """
    The main function for report planning, representing /generate_queries in config.yml
    """
    # Build a simple graph from START -> generate_query -> END
    builder = StateGraph(KXTAState, config_schema=ConfigSchema)

    builder.add_node("generate_query", generate_query)
    builder.add_edge(START, "generate_query")
    builder.add_edge("generate_query", END)

    graph = builder.compile()

    async def _generate_queries_single(message: GenerateQueryStateInput) -> GenerateQueryStateOutput:
        """
        This function runs the graph to generate queries for a given topic/report structure
        """
        blocked_msg = await _topic_blocked_by_guardrail(message.topic)
        if blocked_msg:
            raise ValueError(blocked_msg)

        # Acquire the LLM from the builder
        llm = await aiq_builder.get_llm(llm_name=message.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

        response = await graph.ainvoke(
            input={
                "queries": [], "web_research_results": [], "running_summary": ""
            },
            config={
                "llm": llm,
                "number_of_queries": message.num_queries,
                "report_organization": message.report_organization,
                "topic": message.topic,
                "tickers": message.tickers,  # Source selection for dynamic prompt
                "use_kdb": message.use_kdb,
                "use_rag": message.use_rag,
                "use_web": message.use_web,
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
        return GenerateQueryStateOutput.model_validate(response)

    # ------------------------------------------------------------------
    # STREAMING VERSION
    # ------------------------------------------------------------------
    async def _generate_queries_stream(
            message: GenerateQueryStateInput) -> AsyncGenerator[GenerateQueryStateOutput, None]:
        """
        This function runs the graph to generate queries for a given topic/report structure, streaming the response
        """
        blocked_msg = await _topic_blocked_by_guardrail(message.topic)
        if blocked_msg:
            # Errors surface in the stream the same way intermediate progress
            # does: as a JSON intermediate_step payload.
            yield GenerateQueryStateOutput(intermediate_step=json.dumps({"error": blocked_msg}))
            return

        # Acquire the LLM from the builder
        llm = await aiq_builder.get_llm(llm_name=message.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

        stream = graph.astream(
            input={
                "queries": [], "web_research_results": [], "running_summary": ""
            },
            stream_mode=['custom', 'values'],
            config={
                "llm": llm,
                "number_of_queries": message.num_queries,
                "report_organization": message.report_organization,
                "topic": message.topic,
                "tickers": message.tickers,  # Source selection for dynamic prompt
                "use_kdb": message.use_kdb,
                "use_rag": message.use_rag,
                "use_web": message.use_web,
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
        # HARD-CANCEL on client disconnect — aclose() the langgraph stream so the
        # in-flight planning step is torn down instead of running on in the background.
        try:
            async for _t, val in stream:
                if _t == "values":
                    if "queries" not in val:
                        yield GenerateQueryStateOutput(intermediate_step=json.dumps(val))
                    else:
                        yield GenerateQueryStateOutput(queries=val['queries'])
                else:
                    yield GenerateQueryStateOutput(intermediate_step=json.dumps(val))
        except (GeneratorExit, asyncio.CancelledError):
            logger.info("generate_query stream cancelled (client disconnect)")
            await stream.aclose()
            raise
        finally:
            await stream.aclose()

    yield FunctionInfo.create(
        single_fn=_generate_queries_single,
        stream_fn=_generate_queries_stream,
        description=
        "Generate multiple web-search queries (Stage 1) given a topic and a desired report organization (supports streaming)."
    )
