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

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.utils.json import parse_json_markdown

from kxta.artifact_prompts import (UPDATE_ENTIRE_ARTIFACT_PROMPT, RELEVANCY_CHECK)

from kxta.schema import ArtifactQAInput, ArtifactQAOutput, ArtifactRewriteMode
from kxta.utils import no_think_prefix

logger = logging.getLogger(__name__)

##############################
# Helper functions for rewriting
##############################


def remove_think_tags(text: str) -> str:
    """
    Remove any text in a string that is wrapped in <think> tags.
    """
    # IF think tags are in there
    if "<think>" not in text or "</think>" not in text:
        return text

    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>") + len("</think>")
        text = text[:start] + text[end:]

    return text


async def check_relevant(llm, artifact, question, chat_history: list[str]):

    try:
        prompt = PromptTemplate.from_template(RELEVANCY_CHECK)
        relevancy_checker = prompt | llm
        result = await relevancy_checker.ainvoke({"artifact": artifact, "prompt": question})

        response = parse_json_markdown(result.content)
        if 'relevant' not in response:
            return 'no'

    except Exception as e:
        logger.info(f"Failed to apply guardrails with {question} and {result}")
        return 'no'

    return response['relevant']


async def do_entire_artifact_rewrite(llm, artifact_content: str, user_message: str):
    """
    Rewrites the entire artifact using the prompt: UPDATE_ENTIRE_ARTIFACT_PROMPT
    If the user wants a new artifact type or title, we can also incorporate GET_TITLE_TYPE_REWRITE_ARTIFACT or similar.
    """
    updateMetaPrompt = ""  # Optionally insert dynamic meta prompt
    rewrite_prompt = UPDATE_ENTIRE_ARTIFACT_PROMPT.format(
        artifactContent=artifact_content,
        reflections="N/A",  # or user-specific reflections
        updateMetaPrompt=updateMetaPrompt)
    # The user request is appended to the end.
    user_facing_prompt = rewrite_prompt + f"\n\nUser request:\n{user_message}"

    final_text = ""
    # We'll just read the entire stream from the LLM
    async for chunk in llm.astream(user_facing_prompt):
        final_text += chunk.content

    # strip out <think> if present
    final_text = remove_think_tags(final_text)

    return final_text.strip()


##############################
# The main chat function
##############################


async def artifact_chat_handler(llm, input_data: ArtifactQAInput) -> ArtifactQAOutput:
    """
    1) If user asked for a rewrite (rewrite_mode is set), call the correct rewriting routine.
    2) Else do normal Q&A with the artifact as context.
    3) Return updated artifact + assistant message.
    """

    current_artifact = input_data.artifact
    user_message = input_data.question
    chat_history = input_data.chat_history or []
    rewrite_mode: ArtifactRewriteMode = input_data.rewrite_mode
    additional_context = input_data.additional_context

    def add_context_to_user_message(msg):
        context = additional_context
        if not context:
            return msg

        return f"{msg}\n\nAdditional context:\n{context}"

    # 1) If user specifically wants a rewrite:
    if input_data.rewrite_mode:
        if rewrite_mode == ArtifactRewriteMode.ENTIRE:
            updated = await do_entire_artifact_rewrite(llm, current_artifact, add_context_to_user_message(user_message))
            # add sources to the updated report if they exist
            if hasattr(input_data, 'sources') and input_data.sources:
                updated = updated + "\n\n" + input_data.sources

            return ArtifactQAOutput(updated_artifact=updated,
                                    assistant_reply="Here is the updated artifact (entire rewrite).")
        else:
            # Unrecognized rewrite mode
            return ArtifactQAOutput(updated_artifact=current_artifact,
                                    assistant_reply=(f"I do not recognize rewrite_mode={rewrite_mode}. "
                                                     f"No changes made. Q/A session is available if needed."))

    # 2) Otherwise, do normal Q&A with the artifact
    # We build a system + conversation + user approach
    # We'll stuff the artifact in a system message for context
    system_context = ("<app-context>\n"
                      "You are a helpful AI assistant. The user has an artifact (text, doc, or code) in front of them. "
                      "You can refer to it as needed to answer questions or provide clarifications. "
                      "When writing code, do not wrap with triple backticks, as the UI doesn't want them. "
                      "Follow the user requests carefully.\n"
                      "</app-context>\n\n"
                      f"<artifact>\n{current_artifact}\n</artifact>")

    # Convert chat_history to a list of Human/AI messages.
    # We'll just do a naive approach: even indices are user, odd indices are assistant.
    conversation_messages = []
    _nt = no_think_prefix(llm)
    if _nt:
        # Reasoning OFF for Nemotron-family Q&A (no-op otherwise) — answers don't
        # benefit from chain-of-thought and it multiplies latency.
        from langchain_core.messages import SystemMessage
        conversation_messages.append(SystemMessage(content=_nt))
    conversation_messages.append(HumanMessage(content=system_context))
    for i, text in enumerate(chat_history):
        if i % 2 == 0:
            conversation_messages.append(HumanMessage(content=text))
        else:
            conversation_messages.append(AIMessage(content=text))

    # Add the new user message
    conversation_messages.append(HumanMessage(content=user_message))

    # Build a ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages(conversation_messages).format_messages()

    # Call the LLM
    answer_buf = ""
    async for chunk in llm.astream(prompt):
        answer_buf += chunk.content

    # Remove <think> if present
    answer_buf = remove_think_tags(answer_buf)

    assistant_reply = answer_buf.strip()

    # Add sources if they exist
    final_artifact = current_artifact
    if hasattr(input_data, 'sources') and input_data.sources:
        final_artifact = current_artifact + "\n\n" + input_data.sources

    return ArtifactQAOutput(updated_artifact=final_artifact, assistant_reply=assistant_reply)


async def artifact_chat_handler_streaming(llm, input_data: ArtifactQAInput):
    """
    Streaming variant of artifact_chat_handler: yields ArtifactQAOutput chunks.

    Intermediate chunks carry delta=True with assistant_reply holding just the new
    tokens; the final message has delta=False with the complete cleaned reply (and
    the artifact, unchanged for Q&A). Rewrite mode is inherently a single result,
    so it yields once.
    """
    # Rewrites produce one final artifact — no token stream to forward.
    if input_data.rewrite_mode:
        yield await artifact_chat_handler(llm, input_data)
        return

    current_artifact = input_data.artifact
    user_message = input_data.question
    chat_history = input_data.chat_history or []
    additional_context = input_data.additional_context

    if additional_context:
        user_message = f"{user_message}\n\nAdditional context:\n{additional_context}"

    system_context = ("<app-context>\n"
                      "You are a helpful AI assistant. The user has an artifact (text, doc, or code) in front of them. "
                      "You can refer to it as needed to answer questions or provide clarifications. "
                      "When writing code, do not wrap with triple backticks, as the UI doesn't want them. "
                      "Follow the user requests carefully.\n"
                      "</app-context>\n\n"
                      f"<artifact>\n{current_artifact}\n</artifact>")

    conversation_messages = []
    _nt = no_think_prefix(llm)
    if _nt:
        # Reasoning OFF for Nemotron-family Q&A (no-op otherwise) — answers don't
        # benefit from chain-of-thought and it multiplies latency.
        from langchain_core.messages import SystemMessage
        conversation_messages.append(SystemMessage(content=_nt))
    conversation_messages.append(HumanMessage(content=system_context))
    for i, text in enumerate(chat_history):
        if i % 2 == 0:
            conversation_messages.append(HumanMessage(content=text))
        else:
            conversation_messages.append(AIMessage(content=text))
    conversation_messages.append(HumanMessage(content=user_message))

    prompt = ChatPromptTemplate.from_messages(conversation_messages).format_messages()

    # Stream tokens as deltas; suppress <think>...</think> spans if the model emits them.
    answer_buf = ""
    in_think = False
    async for chunk in llm.astream(prompt):
        piece = chunk.content or ""
        answer_buf += piece
        if in_think:
            if "</think>" in answer_buf:
                in_think = False
            continue
        if "<think>" in piece:
            in_think = "</think>" not in piece
            continue
        if piece:
            yield ArtifactQAOutput(updated_artifact="", assistant_reply=piece, delta=True)

    assistant_reply = remove_think_tags(answer_buf).strip()

    final_artifact = current_artifact
    if hasattr(input_data, 'sources') and input_data.sources:
        final_artifact = current_artifact + "\n\n" + input_data.sources

    yield ArtifactQAOutput(updated_artifact=final_artifact, assistant_reply=assistant_reply, delta=False)
