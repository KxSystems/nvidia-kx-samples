// SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Availability state for a research source agent
export type SourceState = 'available' | 'needs_key' | 'unavailable';

// Source agent info returned by GET /source_agents
export interface SourceAgentInfo {
  name: string;
  label: string;
  description?: string;
  state: SourceState;
  missing_key?: string | null;
  reason?: string;
}

// Generated query from the backend
export interface GeneratedQuery {
  query: string;
  report_section: string;
  rationale: string;
  /**
   * Planner-chosen data source id for this query (e.g. "fundamentals", "sec_filings",
   * "rag", or "auto"). Round-trips back into generate_summary so routing honors it.
   */
  source?: string;
}

// Input for generating queries
export interface GenerateQueryInput {
  topic: string;
  /** Optional ticker(s) / watchlist in focus; time-anchors and scopes the agents. */
  tickers?: string;
  report_organization: string;
  num_queries?: number;
  llm_name: string;
  /**
   * Source selection - tells query generator which data sources are available
   * so it can optimize queries accordingly
   */
  use_kdb?: boolean;
  use_rag?: boolean;
  use_web?: boolean;
  /**
   * Per-source enablement flags for the new research source agents, sent so the query
   * planner is aware of every selected source and can route queries to the best-fit one.
   */
  use_web_search?: boolean;
  use_market_data?: boolean;
  use_news_headlines?: boolean;
  use_fundamentals?: boolean;
  use_sec_filings?: boolean;
  use_macro_economic?: boolean;
  use_onetick?: boolean;
  use_kdb_docs?: boolean;
  use_kdb_pit?: boolean;
}

// Input for generating summary/report
export interface GenerateSummaryInput {
  topic: string;
  /** Optional ticker(s) / watchlist in focus; time-anchors and scopes the agents. */
  tickers?: string;
  report_organization: string;
  queries: GeneratedQuery[];
  search_web: boolean;
  rag_collection: string;
  reflection_count?: number;
  /** Research depth: number of scout->deepen planning hops (1 = fast, 2 = deep). */
  research_hops?: number;
  /** Bounded supervisor-lite mode: a coordinator LLM picks agents + decides when to stop. */
  supervisor_mode?: boolean;
  max_supervisor_steps?: number;
  llm_name: string;
  /**
   * KDB+ data source control:
   * - undefined/null: Legacy auto-detect behavior (routes based on query content)
   * - true: Force KDB search for all queries
   * - false: Disable KDB search entirely
   */
  use_kdb?: boolean | null;
  /**
   * Per-source enablement flags for the new research source agents.
   * Each flag is true iff the user enabled that source and it was available.
   */
  use_web_search?: boolean;
  use_market_data?: boolean;
  use_news_headlines?: boolean;
  use_fundamentals?: boolean;
  use_sec_filings?: boolean;
  use_macro_economic?: boolean;
  use_onetick?: boolean;
  use_kdb_docs?: boolean;
  use_kdb_pit?: boolean;
}

// Input for artifact Q&A
export interface ArtifactQAInput {
  artifact: string;
  question: string;
  chat_history?: string[];
  use_internet?: boolean;
  rewrite_mode?: 'entire' | null;
  additional_context?: string;
  rag_collection: string;
}

// Output from artifact Q&A
export interface ArtifactQAOutput {
  assistant_reply: string;
  updated_artifact?: string;
  /** True for streaming token chunks; the final message has delta=false with the full reply. */
  delta?: boolean;
}

// SSE intermediate step format
export interface IntermediateStep {
  step: 'generating_questions' | 'running_summary' | 'reflect_on_summary' | 'final_report' | 'web_research' | 'rag_search';
  content?: string;
  queries?: GeneratedQuery[];
}

// SSE event data
export interface SSEEventData {
  intermediate_step?: string;
  queries?: GeneratedQuery[];
  final_report?: string;
  citations?: string;
  error?: string;
}

// Collection info
export interface Collection {
  name: string;
  description?: string;
  document_count?: number;
}

// Chat message
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

// Workflow stages
export type WorkflowStage = 'idle' | 'queries' | 'report' | 'qa';

// Report generation progress
export interface ReportProgress {
  stage: string;
  message: string;
  progress?: number;
}
