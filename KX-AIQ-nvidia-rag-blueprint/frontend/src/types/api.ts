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

// Generated query from the backend
export interface GeneratedQuery {
  query: string;
  report_section: string;
  rationale: string;
}

// Input for generating queries
export interface GenerateQueryInput {
  topic: string;
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
}

// Input for generating summary/report
export interface GenerateSummaryInput {
  topic: string;
  report_organization: string;
  queries: GeneratedQuery[];
  search_web: boolean;
  rag_collection: string;
  reflection_count?: number;
  llm_name: string;
  /**
   * KDB+ data source control:
   * - undefined/null: Legacy auto-detect behavior (routes based on query content)
   * - true: Force KDB search for all queries
   * - false: Disable KDB search entirely
   */
  use_kdb?: boolean | null;
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
