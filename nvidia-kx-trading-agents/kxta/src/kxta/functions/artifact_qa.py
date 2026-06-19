# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import logging
from typing import AsyncGenerator
from nat.data_models.function import FunctionBaseConfig
from nat.builder.builder import Builder
from nat.cli.register_workflow import register_function
from nat.builder.function_info import FunctionInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.data_models.component_ref import FunctionRef, LLMRef
import os

from kxta.schema import (ArtifactQAInput, ArtifactQAOutput, GeneratedQuery)

from kxta.artifact_utils import artifact_chat_handler, artifact_chat_handler_streaming, check_relevant
from kxta.guardrails import check_content_safety
from kxta.nodes import process_single_query, deduplicate_and_format_sources

logger = logging.getLogger(__name__)

_GUARDRAIL_REFUSAL = "Sorry, I am not able to help answer that question. Please try again."


async def _question_blocked_by_guardrail(llm, query_message) -> bool:
    """Apply the input guardrail selected by KXTA_APPLY_GUARDRAIL.

    - "true":      today's LLM relevancy gate (check_relevant)
    - "nemoguard": NemoGuard content-safety NIM (enhance-when-present; if the
                   NIM is not configured/unavailable the check returns None and
                   we proceed, matching today's behavior)
    - anything else: no guardrail
    """
    apply_guardrail = os.getenv("KXTA_APPLY_GUARDRAIL", "false").lower()

    if apply_guardrail == "nemoguard":
        safety = await check_content_safety(query_message.question)
        if safety is not None and not safety["safe"]:
            logger.warning(f"NemoGuard blocked artifact QA question (categories: {safety['categories']})")
            return True
        return False

    if apply_guardrail == "true":
        relevancy_check = await check_relevant(llm=llm,
                                               artifact=query_message.artifact,
                                               question=query_message.question,
                                               chat_history=query_message.chat_history)
        return relevancy_check == 'no'

    return False


def _is_artifact_only_question(question: str) -> bool:
    """
    Check if the question can be answered from the artifact alone,
    without needing additional search.

    Returns True for questions like:
    - "summarize the report"
    - "what are the key findings"
    - "explain the conclusion"
    """
    question_lower = question.lower().strip()

    # Keywords that indicate the question is about the existing artifact
    artifact_keywords = [
        "summarize",
        "summary",
        "key findings",
        "key points",
        "main points",
        "conclusion",
        "conclusions",
        "what does the report say",
        "what did you find",
        "explain the",
        "tell me about the report",
        "recap",
        "overview",
        "highlights",
        "takeaways"
    ]

    # If the question contains these keywords and is short (not a complex query)
    if len(question_lower) < 100:
        for keyword in artifact_keywords:
            if keyword in question_lower:
                return True

    return False


class ArtifactQAConfig(FunctionBaseConfig, name="artifact_qa"):
    """
    Configuration for an artifact Q&A function/endpoint.
    """
    llm_name: LLMRef = "instruct_llm"
    rag_url: str = ""


@register_function(config_type=ArtifactQAConfig)
async def artifact_qa_fn(config: ArtifactQAConfig, aiq_builder: Builder):
    """
    Registers a single-node graph to handle Q&A about a previously generated artifact.
    Exposed as 'artifact_qa' in config.yml
    The endpoint handles both report edits and general Q&A.
    Report edits are indicated by the 'rewrite_mode' parameter, set by the UI.
    For each case, the single query search endpoint is called with the user query and added as additional context.
    The search result, current report, and user query are then processed.
    The search is done to enable questions or edit requests that go beyond the 
    scope of the original report contents.
    """

    # Acquire the LLM from the builder
    llm = await aiq_builder.get_llm(llm_name=config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    async def _artifact_qa(query_message: ArtifactQAInput) -> ArtifactQAOutput:
        """
        Run the Q&A logic for a single user question about an artifact.
        """

        if await _question_blocked_by_guardrail(llm, query_message):
            return ArtifactQAOutput(updated_artifact=query_message.artifact, assistant_reply=_GUARDRAIL_REFUSAL)

        # Check if the question can be answered from the artifact alone
        # Skip additional search for simple questions like "summarize the report"
        if _is_artifact_only_question(query_message.question):
            logger.info(f"Artifact-only question detected, skipping search: {query_message.question[:50]}...")
            return await artifact_chat_handler(llm, query_message)

        # Only enabled when not rewrite mode or rewrite mode is "entire"
        graph_config = {"configurable": {"rag_url": config.rag_url, }}

        def writer(message):
            """
            The RAG search expects a stream writer function.
            This is a temporary placeholder to satisfy the type checker.
            """
            logger.debug(f"Writing message: {message}")

        rag_answer, rag_citation, relevancy, web_answer, web_citation = await process_single_query(
            query=query_message.question,
            config=graph_config,
            writer=writer,
            collection=query_message.rag_collection,
            llm=llm,
            search_web=query_message.use_internet
        )

        gen_query = GeneratedQuery(query=query_message.question, report_section=query_message.artifact, rationale="Q/A")

        query_message.question += "\n\n --- ADDITIONAL CONTEXT --- \n" + deduplicate_and_format_sources(
            [rag_citation], [rag_answer], [relevancy], [web_answer], [gen_query])

        return await artifact_chat_handler(llm, query_message)

    async def _artifact_qa_streaming(query_message: ArtifactQAInput) -> AsyncGenerator[ArtifactQAOutput, None]:
        """
        Run the Q&A logic for a single user question about an artifact, streaming the response.
        """

        if await _question_blocked_by_guardrail(llm, query_message):
            yield ArtifactQAOutput(updated_artifact=query_message.artifact, assistant_reply=_GUARDRAIL_REFUSAL)
            return

        # Check if the question can be answered from the artifact alone
        # Skip additional search for simple questions like "summarize the report"
        if _is_artifact_only_question(query_message.question):
            logger.info(f"Artifact-only question detected, skipping search: {query_message.question[:50]}...")
            async for out in artifact_chat_handler_streaming(llm, query_message):
                yield out
            return

        # Only enabled when not rewrite mode or rewrite mode is "entire"
        graph_config = {"configurable": {"rag_url": config.rag_url, }}

        def writer(message):
            """
            The RAG search expects a stream writer function.
            This is a temporary placeholder to satisfy the type checker.
            """
            logger.debug(f"Writing message: {message}")

        rag_answer, rag_citation, relevancy, web_answer, web_citation = await process_single_query(
            query=query_message.question,
            config=graph_config,
            writer=writer,
            collection=query_message.rag_collection,
            llm=llm,
            search_web=query_message.use_internet
        )

        gen_query = GeneratedQuery(query=query_message.question, report_section=query_message.artifact, rationale="Q/A")

        query_message.question += "\n\n --- ADDITIONAL CONTEXT --- \n" + deduplicate_and_format_sources(
            [rag_citation], [rag_answer], [relevancy], [web_answer], [gen_query])

        async for out in artifact_chat_handler_streaming(llm, query_message):
            yield out

    yield FunctionInfo.create(
        single_fn=_artifact_qa,
        stream_fn=_artifact_qa_streaming,
        description="Chat-based Q&A about a previously generated artifact, optionally doing additional RAG lookups.")
