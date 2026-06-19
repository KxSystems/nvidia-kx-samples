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

import logging
import asyncio
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.utils.json import parse_json_markdown
from langchain_core.stores import InMemoryByteStore
from langgraph.types import StreamWriter
from kxta.schema import GeneratedQuery

from kxta.schema import KXTAState
from kxta.prompts import (
    finalize_report,
    query_writer_instructions,
    reflection_instructions,
    deepen_plan_instructions,
    supervisor_instructions,
    build_data_sources_section,
)

from kxta.utils import async_gen, format_sources, update_system_prompt, no_think_prefix, current_date_str, tickers_display
from kxta.constants import ASYNC_TIMEOUT

from kxta.search_utils import build_findings_digest
from kxta.search_utils import process_single_query, deduplicate_and_format_sources, is_query_novel, query_is_novel
from kxta.report_gen_utils import summarize_report
from kxta.scratchpad import Scratchpad

logger = logging.getLogger(__name__)
store = InMemoryByteStore()


async def generate_query(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """
    Node for generating a research plan as a list of queries. 
    Takes in a topic and desired report organization. 
    Returns the list of query objects. 
    """
    logger.info("GENERATE QUERY")
    writer({"generating_questions": "\n Generating queries \n"
            })  # send something to initialize the UI so the timeout shows

    # Generate a query
    llm = config["configurable"].get("llm")
    number_of_queries = config["configurable"].get("number_of_queries")
    report_organization = config["configurable"].get("report_organization")
    topic = config["configurable"].get("topic")

    # Build the data-sources section from the full source registry so the planner is aware of
    # every selected + currently-usable source (not just rag/kdb/web) and can route each query
    # to the best-fit source. Falls back to the legacy 3-source builder if the registry yields
    # nothing usable (e.g. registry import unavailable in a stripped-down test env).
    try:
        from kxta.source_agents.registry import get_registry
        available_data_sources = get_registry().describe_for_planner(config["configurable"])
    except Exception as e:
        logger.warning(f"Falling back to legacy data-sources section: {e}")
        available_data_sources = build_data_sources_section(
            use_kdb=config["configurable"].get("use_kdb", False),
            use_rag=config["configurable"].get("use_rag", True),
            use_web=config["configurable"].get("use_web", False),
        )

    system_prompt = ""
    system_prompt = update_system_prompt(system_prompt, llm)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])
    chain = prompt | llm

    input = {
        "topic":
            topic,
        "report_organization":
            report_organization,
        "number_of_queries":
            number_of_queries,
        "input":
            query_writer_instructions.format(topic=topic,
                                             report_organization=report_organization,
                                             number_of_queries=number_of_queries,
                                             available_data_sources=available_data_sources,
                                             today=current_date_str(),
                                             tickers=tickers_display(config))
    }

    answer_agg = ""
    stop = False
    saw_reasoning = False

    try:
        async with asyncio.timeout(ASYNC_TIMEOUT):
            async for chunk in chain.astream(input, stream_usage=True):
                # Hosted reasoning models (e.g. nemotron v1.5 on NGC) stream the thinking in
                # additional_kwargs['reasoning_content'], separate from the answer content.
                # Self-hosted NIMs instead inline it in content up to </think>.
                ak = getattr(chunk, "additional_kwargs", None) or {}
                reasoning = ak.get("reasoning_content") or "" if isinstance(ak, dict) else ""
                if reasoning:
                    saw_reasoning = True
                    writer({"generating_questions": reasoning})

                answer_agg += chunk.content
                if "</think>" in chunk.content:
                    stop = True
                # When the model streams reasoning separately, content is just the JSON plan —
                # don't echo it as "thinking". Otherwise stream content until </think>.
                if not stop and not saw_reasoning:
                    writer({"generating_questions": chunk.content})
    except asyncio.TimeoutError as e:
        writer({
            "generating_questions": " \n \n ---------------- \n \n Timeout error from reasoning LLM, please try again"
        })
        queries = []
        return {"queries": queries}

    # Reasoning models emit thinking before </think>, with the JSON plan after it. Hosted NIM
    # endpoints may not emit </think> at all — in that case the whole response is the plan.
    splitted = answer_agg.split("</think>")
    json_str = (splitted[-1] if len(splitted) >= 2 else answer_agg).strip()
    if not json_str:
        writer(
            {"generating_questions": " \n \n ---------------- \n \n No response from reasoning LLM, please try again"})
        logger.info(f"Empty query response. Raw: {answer_agg[:500]}")
        return {"queries": []}
    try:
        queries_raw = parse_json_markdown(json_str)
        # Convert raw dictionaries to GeneratedQuery objects so validators run
        queries = [GeneratedQuery(**q_dict) for q_dict in queries_raw]
    except Exception as e:
        logger.error(f"Error parsing or validating queries: {e}")
        queries = []

    return {"queries": queries}


async def web_research(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """
    Node for performing research based on the queries returned by generate_query.
    Research is performed deterministically by running RAG (and optionally a web search) on each query.
    The function extracts the queries from the state, processes each one via process_single_query,
    and finally formats the sources into an aggregated XML structure.
    A separate list of source citations is also maintained, tracking the query, answer, and sources for each query.
    """

    logger.info("STARTING WEB RESEARCH")
    llm = config["configurable"].get("llm")
    search_web = config["configurable"].get("search_web")
    collection = config["configurable"].get("collection")
    # Get use_kdb flag - None means legacy auto-detect behavior
    use_kdb = config["configurable"].get("use_kdb", None)

    logger.info(f"Web research config: search_web={search_web}, use_kdb={use_kdb}, collection={collection}")

    # Initialize scratchpad for audit trail
    scratchpad = Scratchpad()
    scratchpad.log("init", {"topic": config["configurable"].get("topic"), "use_kdb": use_kdb, "search_web": search_web})

    # Determine the queries and state queries based on the type of state.
    # If the state is a list of queries, use them directly.
    queries = [q.query for q in state.queries]
    state_queries = state.queries
    total = len(queries)

    writer({"search_progress": f"Starting research: {total} queries to process"})
    for idx, q in enumerate(queries):
        writer({"search_progress": f"Queuing query {idx + 1}/{total}: {q[:50]}..."})

    # Process each query concurrently. Pass the planner-chosen source tag (q.source) through so
    # routing honors the LLM's per-query source decision, falling back to keywords when "auto".
    results = await asyncio.gather(*[
        process_single_query(q.query,
                             config,
                             writer,
                             collection,
                             llm,
                             search_web,
                             use_kdb=use_kdb,
                             scratchpad=scratchpad,
                             preferred_source=getattr(q, "source", None)) for q in state_queries
    ])

    writer({"search_progress": f"All {total} queries complete. Formatting sources..."})

    search_str, citation_str = _format_research(results, state_queries)
    return {"citations": citation_str, "web_research_results": [search_str]}


def _format_research(results, state_queries):
    """Unpack process_single_query results into a formatted <sources> blob + citation string."""
    generated_answers = [result[0] for result in results]
    citations = [result[1] if result[1] is not None else "" for result in results]
    relevancy_list = [result[2] for result in results]
    web_results = [result[3] for result in results]
    citations_web = [result[4] if result[4] is not None else "" for result in results]

    search_str = deduplicate_and_format_sources(citations,
                                                generated_answers,
                                                relevancy_list,
                                                web_results,
                                                state_queries)

    all_citations = []
    for idx, citation in enumerate(citations):
        if relevancy_list[idx]["score"] == "yes":
            all_citations.append(citation)
        if relevancy_list[idx]["score"] != "yes" and citations_web[idx] not in ["N/A", ""]:
            all_citations.append(citations_web[idx])
    return search_str, "\n".join(set(all_citations))


async def _research_queries(state_queries, config, writer, scratchpad=None, prior_results=None):
    """Run a batch of queries through the source agents in parallel; return (search_str, citation_str).

    Shared by web_research (scout hop) and deepen_research (follow-up hops).
    `prior_results` (earlier rounds' <sources> blobs) becomes a compact cross-agent
    findings digest injected into each agent's query, so follow-up invocations
    build on — rather than repeat — what other agents already found.
    """
    digest = build_findings_digest(prior_results) if prior_results else ""
    if digest:
        config = {**config, "configurable": {**config["configurable"], "findings_digest": digest}}
    llm = config["configurable"].get("llm")
    search_web = config["configurable"].get("search_web")
    collection = config["configurable"].get("collection")
    use_kdb = config["configurable"].get("use_kdb", None)
    results = await asyncio.gather(*[
        process_single_query(q.query,
                             config,
                             writer,
                             collection,
                             llm,
                             search_web,
                             use_kdb=use_kdb,
                             scratchpad=scratchpad,
                             preferred_source=getattr(q, "source", None)) for q in state_queries
    ])
    return _format_research(results, state_queries)


async def _deepen_plan(config, writer, findings, previous_queries):
    """Plan the next research hop: read the findings so far, emit follow-up GeneratedQuery objects.

    Returns [] on timeout / parse failure / explicit empty plan.
    """
    llm = config["configurable"].get("llm")
    try:
        from kxta.source_agents.registry import get_registry
        available_data_sources = get_registry().describe_for_planner(config["configurable"])
    except Exception:
        available_data_sources = ""

    system_prompt = update_system_prompt("", llm)
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
    chain = prompt | llm
    user_input = deepen_plan_instructions.format(
        topic=config["configurable"].get("topic"),
        report_organization=config["configurable"].get("report_organization"),
        available_data_sources=available_data_sources,
        findings=(findings or "")[:12000],
        previous_queries="\n".join(f"- {q}" for q in previous_queries),
        number_of_queries=config["configurable"].get("deepen_queries", 2),
        today=current_date_str(),
        tickers=tickers_display(config),
    )
    agg = ""
    try:
        async with asyncio.timeout(ASYNC_TIMEOUT):
            async for chunk in chain.astream({"input": user_input}, stream_usage=True):
                ak = getattr(chunk, "additional_kwargs", None) or {}
                reasoning = ak.get("reasoning_content") or "" if isinstance(ak, dict) else ""
                if reasoning:
                    writer({"generating_questions": reasoning})
                agg += chunk.content
    except asyncio.TimeoutError:
        return []
    splitted = agg.split("</think>")
    json_str = (splitted[-1] if len(splitted) >= 2 else agg).strip()
    try:
        raw = parse_json_markdown(json_str)
        if not isinstance(raw, list):
            return []
        return [GeneratedQuery(**q) for q in raw]
    except Exception as e:
        logger.warning(f"deepen plan parse failed: {e}")
        return []


async def _supervise_plan(config, writer, findings, previous_queries, step, max_steps):
    """Supervisor-lite coordinator: judge coverage, return (decision, dispatch[GeneratedQuery]).

    decision is "continue" or "done"; dispatch is the agents/queries to run next ([] when done).
    Returns ("done", []) on timeout / parse failure.
    """
    llm = config["configurable"].get("llm")
    try:
        from kxta.source_agents.registry import get_registry
        available_data_sources = get_registry().describe_for_planner(config["configurable"])
    except Exception:
        available_data_sources = ""

    system_prompt = update_system_prompt("", llm)
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
    chain = prompt | llm
    user_input = supervisor_instructions.format(
        topic=config["configurable"].get("topic"),
        report_organization=config["configurable"].get("report_organization"),
        available_data_sources=available_data_sources,
        findings=(findings or "")[:12000],
        previous_queries="\n".join(f"- {q}" for q in previous_queries),
        step=step,
        max_steps=max_steps,
        today=current_date_str(),
        tickers=tickers_display(config),
    )
    agg = ""
    try:
        async with asyncio.timeout(ASYNC_TIMEOUT):
            async for chunk in chain.astream({"input": user_input}, stream_usage=True):
                ak = getattr(chunk, "additional_kwargs", None) or {}
                reasoning = ak.get("reasoning_content") or "" if isinstance(ak, dict) else ""
                if reasoning:
                    writer({"search_progress": reasoning})
                agg += chunk.content
    except asyncio.TimeoutError:
        return "done", []
    splitted = agg.split("</think>")
    json_str = (splitted[-1] if len(splitted) >= 2 else agg).strip()
    try:
        obj = parse_json_markdown(json_str)
        if not isinstance(obj, dict):
            return "done", []
        decision = str(obj.get("decision", "done")).strip().lower()
        dispatch = []
        for d in obj.get("dispatch", []) or []:
            if not isinstance(d, dict) or not d.get("query"):
                continue
            dispatch.append(
                GeneratedQuery(
                    query=d["query"],
                    report_section=d.get("report_section", "Supervisor follow-up"),
                    rationale=d.get("rationale", ""),
                    source=d.get("source", "auto"),
                ))
        return decision, dispatch
    except Exception as e:
        logger.warning(f"supervisor plan parse failed: {e}")
        return "done", []


async def _supervise_research(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """Bounded supervisor-lite loop: a coordinator decides, up to max_supervisor_steps times,
    whether to dispatch more agents to close coverage gaps, and stops when the report can be
    written. More agent-selection-aware than fixed-hop deepen, with an explicit stop condition.
    """
    max_steps = int(config["configurable"].get("max_supervisor_steps", 3) or 3)
    max_steps = max(1, min(max_steps, 5))  # hard bound
    logger.info(f"SUPERVISOR RESEARCH (max_steps={max_steps})")

    results = list(state.web_research_results or [])
    cites = [state.citations] if state.citations else []
    previous_queries = [q.query for q in (state.queries or [])]

    for step in range(max_steps):
        writer({"search_progress": f"Supervisor: assessing coverage (step {step + 1}/{max_steps})..."})
        findings = "\n\n".join(r for r in results if r)
        decision, dispatch = await _supervise_plan(config, writer, findings, previous_queries, step + 1, max_steps)
        dispatch = [q for q in dispatch if await query_is_novel(q.query, previous_queries)]
        if decision == "done" or not dispatch:
            writer({"search_progress": "Supervisor: evidence sufficient — proceeding to synthesis."})
            break
        for q in dispatch:
            writer({"search_progress": f"Supervisor dispatch → {q.source}: {q.query[:50]}..."})
        previous_queries += [q.query for q in dispatch]
        search_str, citation_str = await _research_queries(dispatch, config, writer, prior_results=results)
        results.append(search_str)
        if citation_str:
            cites.append(citation_str)

    return {"web_research_results": results, "citations": "\n".join(c for c in cites if c)}


async def deepen_research(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """Pre-synthesis research expansion. Three modes (all bounded, default = off):

    - supervisor_mode: a coordinator LLM decides which agents to dispatch and when to stop
      (bounded by max_supervisor_steps) — supervisor-lite orchestration.
    - research_hops > 1: fixed 'scout -> deepen' multi-hop (follow-up queries from findings).
    - else: no-op (single scout round), preserving the original behavior.
    """
    if bool(config["configurable"].get("supervisor_mode", False)):
        return await _supervise_research(state, config, writer)

    research_hops = int(config["configurable"].get("research_hops", 1) or 1)
    if research_hops <= 1:
        return {}

    logger.info(f"DEEPEN RESEARCH (research_hops={research_hops})")
    results = list(state.web_research_results or [])
    cites = [state.citations] if state.citations else []
    previous_queries = [q.query for q in (state.queries or [])]

    for hop in range(research_hops - 1):
        writer({"search_progress": f"Deepening research (hop {hop + 2}/{research_hops})..."})
        findings = "\n\n".join(r for r in results if r)
        new_queries = await _deepen_plan(config, writer, findings, previous_queries)
        new_queries = [q for q in new_queries if await query_is_novel(q.query, previous_queries)]
        if not new_queries:
            writer({"search_progress": "No new angles found; proceeding to synthesis."})
            break
        for q in new_queries:
            writer({"search_progress": f"Follow-up: {q.query[:60]}..."})
        previous_queries += [q.query for q in new_queries]
        search_str, citation_str = await _research_queries(new_queries, config, writer, prior_results=results)
        results.append(search_str)
        if citation_str:
            cites.append(citation_str)

    return {"web_research_results": results, "citations": "\n".join(c for c in cites if c)}


async def summarize_sources(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """
    Node for summarizing or extending an existing summary. Takes the web research report and writes a report draft.
    """
    logger.info("SUMMARIZE")
    llm = config["configurable"].get("llm")
    report_organization = config["configurable"].get("report_organization")

    # All research gathered before drafting (scout + any deepen hops), joined.
    most_recent_web_research = "\n\n".join(r for r in (state.web_research_results or []) if r)
    existing_summary = state.running_summary

    # -- Call the helper function here --
    updated_report = await summarize_report(existing_summary=existing_summary,
                                            new_source=most_recent_web_research,
                                            report_organization=report_organization,
                                            llm=llm,
                                            writer=writer,
                                            today=current_date_str(),
                                            tickers=tickers_display(config))

    state.running_summary = updated_report

    writer({"running_summary": updated_report})
    return {"running_summary": updated_report}


async def reflect_on_summary(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """
    Node for reflecting on the summary to find knowledge gaps. 
    Identified gaps are added as new queries.
    Number of new queries is determined by the num_reflections parameter.
    For each new query, the node performs web research and report extension.
    The extended report and additional citations are added to the state.
    """
    logger.info("REFLECTING")
    llm = config["configurable"].get("llm")
    num_reflections = config["configurable"].get("num_reflections")
    report_organization = config["configurable"].get("report_organization")
    search_web = config["configurable"].get("search_web")
    collection = config["configurable"].get("collection")
    # Get use_kdb flag - None means legacy auto-detect behavior
    use_kdb = config["configurable"].get("use_kdb", None)

    logger.info(f"REFLECTING {num_reflections} TIMES (use_kdb={use_kdb})")

    # Track all queries searched so far to detect duplicates
    all_previous_queries = [q.query for q in state.queries] if state.queries else []

    for reflection_idx in range(num_reflections):
        writer({"search_progress": f"Reflection {reflection_idx + 1}/{num_reflections}: Identifying gaps..."})
        input = {
            "input":
                reflection_instructions.format(
                    report_organization=report_organization,
                    topic=config["configurable"].get("topic"),
                    report=state.running_summary,
                    previous_queries="\n".join(f"- {q}" for q in all_previous_queries),
                    today=current_date_str(),
                    tickers=tickers_display(config),
                )
        }
        system_prompt = ""
        system_prompt = update_system_prompt(system_prompt, llm)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human",
             "Using report organization as a guide identify a knowledge gap and generate a follow-up web search query based on our existing knowledge. \n \n {input}"
             ),
        ])
        chain = prompt | llm

        writer({"reflect_on_summary": "\n Starting reflection \n"})
        async for _i in async_gen(1):
            result = ""
            stop = False
            saw_reasoning = False
            async for chunk in chain.astream(input, stream_usage=True):
                # Hosted reasoning models stream thinking in reasoning_content; self-hosted
                # NIMs inline it in content up to </think>. Show thinking either way.
                ak = getattr(chunk, "additional_kwargs", None) or {}
                reasoning = ak.get("reasoning_content") or "" if isinstance(ak, dict) else ""
                if reasoning:
                    saw_reasoning = True
                    writer({"reflect_on_summary": reasoning})
                result = result + chunk.content
                if "</think>" in chunk.content:
                    stop = True
                if not stop and not saw_reasoning:
                    writer({"reflect_on_summary": chunk.content})

        # Reasoning may be inline (<think>..</think>JSON) or separate (content is just JSON).
        splitted = result.split("</think>")
        reflection_json = (splitted[-1] if len(splitted) >= 2 else result).strip()
        if not reflection_json:
            running_summary = state.running_summary
            writer({"running_summary": running_summary})
            return {"running_summary": running_summary}

        try:
            reflection_obj = parse_json_markdown(reflection_json)
            gen_query = GeneratedQuery(query=reflection_obj["query"] if isinstance(reflection_obj, dict)
                                       and "query" in reflection_obj else str(reflection_obj),
                                       report_section="All",
                                       rationale="Reflection-based query")
        except Exception as e:
            # Couldn't parse a follow-up query from this round — skip it gracefully.
            logger.warning(f"Error parsing reflection JSON, skipping this reflection: {e}")
            continue

        writer({"search_progress": f"Reflection {reflection_idx + 1}: Searching '{gen_query.query[:50]}...'"})

        # Check if the generated query is novel compared to all previous queries
        if not is_query_novel(gen_query.query, all_previous_queries):
            logger.info(f"Skipping similar reflection query: {gen_query.query[:50]}...")
            writer({"reflect_on_summary": "\n Skipping similar query, trying next reflection \n"})
            continue
        all_previous_queries.append(gen_query.query)

        rag_answer, rag_citation, relevancy, web_answer, web_citation = await process_single_query(
            query=gen_query.query,
            config=config,
            writer=writer,
            collection=collection,
            llm=llm,
            search_web=search_web,
            use_kdb=use_kdb
        )

        search_str = deduplicate_and_format_sources([rag_citation], [rag_answer], [relevancy], [web_answer],
                                                    [gen_query])

        state.web_research_results.append(search_str)

        if relevancy['score'] == "yes" and rag_citation is not None:
            state.citations = "\n".join([state.citations, rag_citation])

        if relevancy['score'] != "yes" and web_citation not in ["N/A", ""] and web_citation is not None:
            state.citations = "\n".join([state.citations, web_citation])

        # Most recent web research
        existing_summary = state.running_summary
        most_recent_web_research = state.web_research_results[-1]

        updated_report = await summarize_report(existing_summary=existing_summary,
                                                new_source=most_recent_web_research,
                                                report_organization=report_organization,
                                                llm=llm,
                                                writer=writer)

        # Check report growth for early termination
        report_delta = len(updated_report) - len(existing_summary) if existing_summary else len(updated_report)
        min_growth = max(100, int(len(existing_summary) * 0.05)) if existing_summary else 100
        if report_delta < min_growth:
            logger.info(f"Report grew by only {report_delta} chars, stopping reflection early")
            writer({"reflect_on_summary": f"\n Early stop: minimal new information found \n"})
            state.running_summary = updated_report
            writer({"running_summary": updated_report})
            break

        state.running_summary = updated_report

        writer({"running_summary": updated_report})

    running_summary = state.running_summary
    writer({"running_summary": running_summary})
    return {"running_summary": running_summary, "citations": state.citations}


async def finalize_summary(state: KXTAState, config: RunnableConfig, writer: StreamWriter):
    """
    Node for double checking the final summary is valid markdown
    and manually adding the sources list to the end of the report.
    """
    logger.info("FINALZING REPORT")
    llm = config["configurable"].get("llm")
    report_organization = config["configurable"].get("report_organization")

    writer({"final_report": "\n Starting finalization \n"})

    sources_formatted = format_sources(state.citations)

    # Final report creation, used to remove any remaing model commentary from the report draft.
    # Reasoning OFF for Nemotron-family writers (no-op otherwise) — see no_think_prefix.
    finalizer = ChatPromptTemplate.from_messages([
        ("system", no_think_prefix(llm)),
        ("human", finalize_report),
    ]) | llm
    final_buf = ""
    try:
        async with asyncio.timeout(ASYNC_TIMEOUT * 3):
            async for chunk in finalizer.astream(
                {
                    "report": state.running_summary,
                    "report_organization": report_organization,
                    "today": current_date_str(),
                    "tickers": tickers_display(config),
                },
                    stream_usage=True):
                final_buf += chunk.content
                writer({"final_report": chunk.content})
    except asyncio.TimeoutError as e:
        writer({
            "final_report":
                " \n \n --------------- \n Timeout error from reasoning LLM during final report creation. Consider restarting report generation. \n \n "
        })
        state.running_summary = f"{state.running_summary} \n\n ---- \n\n {sources_formatted}"
        writer({"finalized_summary": state.running_summary})
        return {"final_report": state.running_summary, "citations": sources_formatted}

    # Strip out <think> sections
    while "<think>" in final_buf and "</think>" in final_buf:
        start = final_buf.find("<think>")
        end = final_buf.find("</think>") + len("</think>")
        final_buf = final_buf[:start] + final_buf[end:]

    # Handle case where opening <think> tag might be missing
    while "</think>" in final_buf:
        end = final_buf.find("</think>") + len("</think>")
        final_buf = final_buf[end:]

    state.running_summary = f"{final_buf} \n\n ## Sources \n\n{sources_formatted}"
    writer({"finalized_summary": state.running_summary})
    return {"final_report": state.running_summary, "citations": sources_formatted}
