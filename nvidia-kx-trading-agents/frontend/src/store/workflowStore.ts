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

import { create } from 'zustand';
import type { GeneratedQuery, WorkflowStage, ChatMessage } from '../types/api';

// Step result from backend
export interface StepResult {
  stepId: string;
  stepName: string;
  status: 'pending' | 'active' | 'completed' | 'skipped';
  content?: string;
  details?: Record<string, unknown>;
  timestamp?: Date;
}

// Agent activity event. `type` is a source/activity id; known ids get bespoke styling in
// AgentActivity, any other id falls back to a generic look (so new sources stream as-is).
export interface AgentEvent {
  id: string;
  timestamp: Date;
  type: string;
  title: string;
  content?: string;
  status?: 'running' | 'complete' | 'error';
  duration?: string;      // e.g., "1.2s", "350ms"
  recordCount?: number;   // Number of records/docs processed
}

// Active sources for current report generation
export interface ActiveSources {
  rag: boolean;
  webSearch: boolean;
  kdb: boolean;
}

interface WorkflowState {
  // Current stage
  stage: WorkflowStage;

  // Source selection
  sources: {
    webSearch: boolean;
    kdbx: boolean;
    rag: boolean;
  };
  // Availability-driven research source agents, keyed by backend source name
  // (e.g. 'web_search', 'market_data'). Only available sources can be enabled.
  dynamicSources: Record<string, boolean>;
  selectedCollections: string[];

  // Guard: once sources have been auto-initialized from /source_agents, set
  // true so subsequent renders don't override the user's opt-outs.
  sourcesInitialized: boolean;

  // Topic and configuration
  topic: string;
  tickers: string;
  reportOrganization: string;
  /** Research depth: number of scout->deepen planning hops (1 = fast, 2 = deep). */
  researchDepth: number;
  collection: string;
  searchWeb: boolean;
  llmName: string;

  // Generated data
  queries: GeneratedQuery[];
  report: string;
  citations: string;

  // Streaming state
  isStreaming: boolean;
  streamingContent: string;
  currentStep: string;

  // Report generation progress
  reportSteps: StepResult[];
  activeSources: ActiveSources;
  agentEvents: AgentEvent[];

  // Thinking/Planning state
  thinkingContent: string;
  isThinking: boolean;
  planReady: boolean;

  // Q&A state
  chatHistory: ChatMessage[];

  // Error state
  error: string | null;

  // KDB-docs collection picker
  selectedKdbDocsCollection: string | null;
  setKdbDocsCollection: (collection: string | null) => void;

  // KDB time-series table picker
  selectedKdbTables: string[];
  setSelectedKdbTables: (tables: string[]) => void;
  toggleKdbTable: (table: string) => void;

  // Actions
  setStage: (stage: WorkflowStage) => void;
  toggleSource: (source: 'webSearch' | 'kdbx' | 'rag') => void;
  toggleDynamicSource: (name: string) => void;
  setSelectedCollections: (collections: string[]) => void;
  toggleCollection: (collection: string) => void;
  hasAnySourceSelected: () => boolean;
  initializeSources: (params: {
    webSearch: boolean;
    kdbx: boolean;
    rag: boolean;
    dynamic: Record<string, boolean>;
  }) => void;
  setTopic: (topic: string) => void;
  setTickers: (tickers: string) => void;
  setReportOrganization: (org: string) => void;
  setResearchDepth: (depth: number) => void;
  setCollection: (collection: string) => void;
  setSearchWeb: (searchWeb: boolean) => void;
  setLlmName: (name: string) => void;
  setQueries: (queries: GeneratedQuery[]) => void;
  updateQuery: (index: number, query: GeneratedQuery) => void;
  removeQuery: (index: number) => void;
  addQuery: (query: GeneratedQuery) => void;
  setReport: (report: string, citations?: string) => void;
  setStreaming: (isStreaming: boolean) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (content: string) => void;
  setCurrentStep: (step: string) => void;
  setThinkingContent: (content: string) => void;
  appendThinkingContent: (content: string) => void;
  setIsThinking: (isThinking: boolean) => void;
  setPlanReady: (ready: boolean) => void;
  addChatMessage: (message: ChatMessage) => void;
  appendToLastChatMessage: (text: string) => void;
  setLastChatMessage: (content: string) => void;
  clearChatHistory: () => void;
  setError: (error: string | null) => void;
  reset: () => void;
  resetToQueries: () => void;
  // Report step tracking actions
  setActiveSources: (sources: ActiveSources) => void;
  initializeReportSteps: (sources: ActiveSources) => void;
  updateStepStatus: (stepId: string, status: StepResult['status'], content?: string, details?: Record<string, unknown>) => void;
  setStepContent: (stepId: string, content: string, details?: Record<string, unknown>) => void;
  getStepResult: (stepId: string) => StepResult | undefined;
  clearReportSteps: () => void;
  // Agent activity actions
  addAgentEvent: (event: Omit<AgentEvent, 'id' | 'timestamp'>) => void;
  updateAgentEvent: (id: string, updates: Partial<AgentEvent>) => void;
  clearAgentEvents: () => void;
}

const initialState = {
  stage: 'idle' as WorkflowStage,
  sources: {
    webSearch: false,
    kdbx: false,
    rag: false,
  },
  dynamicSources: {} as Record<string, boolean>,
  selectedCollections: [] as string[],
  sourcesInitialized: false,
  selectedKdbDocsCollection: null as string | null,
  selectedKdbTables: [] as string[],
  topic: '',
  tickers: '',
  reportOrganization: '',
  researchDepth: 3,
  collection: '',
  searchWeb: true,
  llmName: 'nemotron',
  queries: [],
  report: '',
  citations: '',
  isStreaming: false,
  streamingContent: '',
  currentStep: '',
  reportSteps: [] as StepResult[],
  activeSources: { rag: false, webSearch: false, kdb: false } as ActiveSources,
  agentEvents: [] as AgentEvent[],
  thinkingContent: '',
  isThinking: false,
  planReady: false,
  chatHistory: [],
  error: null,
};

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  ...initialState,

  setStage: (stage) => set({ stage }),

  toggleSource: (source) =>
    set((state) => ({
      sources: {
        ...state.sources,
        [source]: !state.sources[source],
      },
      // Clear selected collections if RAG is disabled
      selectedCollections: source === 'rag' && state.sources.rag ? [] : state.selectedCollections,
    })),

  toggleDynamicSource: (name) =>
    set((state) => ({
      dynamicSources: {
        ...state.dynamicSources,
        [name]: !state.dynamicSources[name],
      },
    })),

  setSelectedCollections: (collections) => set({ selectedCollections: collections }),

  toggleCollection: (collection) =>
    set((state) => ({
      selectedCollections: state.selectedCollections.includes(collection)
        ? state.selectedCollections.filter((c) => c !== collection)
        : [...state.selectedCollections, collection],
    })),

  setKdbDocsCollection: (collection) => set({ selectedKdbDocsCollection: collection }),

  setSelectedKdbTables: (tables) => set({ selectedKdbTables: tables }),

  toggleKdbTable: (table) =>
    set((state) => ({
      selectedKdbTables: state.selectedKdbTables.includes(table)
        ? state.selectedKdbTables.filter((t) => t !== table)
        : [...state.selectedKdbTables, table],
    })),

  hasAnySourceSelected: () => {
    const state = get();
    const anyDynamic = Object.values(state.dynamicSources).some(Boolean);
    return (
      state.sources.webSearch ||
      state.sources.kdbx ||
      (state.sources.rag && state.selectedCollections.length > 0) ||
      anyDynamic
    );
  },

  initializeSources: ({ webSearch, kdbx, rag, dynamic }) => {
    set({
      sources: { webSearch, kdbx, rag },
      dynamicSources: dynamic,
      sourcesInitialized: true,
    });
  },

  setTopic: (topic) => set({ topic }),
  setTickers: (tickers) => set({ tickers }),
  setReportOrganization: (reportOrganization) => set({ reportOrganization }),
  setResearchDepth: (researchDepth) => set({ researchDepth }),
  setCollection: (collection) => set({ collection }),
  setSearchWeb: (searchWeb) => set({ searchWeb }),
  setLlmName: (llmName) => set({ llmName }),

  setQueries: (queries) => set({ queries }),
  updateQuery: (index, query) =>
    set((state) => ({
      queries: state.queries.map((q, i) => (i === index ? query : q)),
    })),
  removeQuery: (index) =>
    set((state) => ({
      queries: state.queries.filter((_, i) => i !== index),
    })),
  addQuery: (query) =>
    set((state) => ({
      queries: [...state.queries, query],
    })),

  setReport: (report, citations) =>
    set({ report, citations: citations || '' }),

  setStreaming: (isStreaming) => set({ isStreaming }),
  setStreamingContent: (streamingContent) => set({ streamingContent }),
  appendStreamingContent: (content) =>
    set((state) => ({
      streamingContent: state.streamingContent + content,
    })),
  setCurrentStep: (currentStep) => set({ currentStep }),
  setThinkingContent: (thinkingContent) => set({ thinkingContent }),
  appendThinkingContent: (content) =>
    set((state) => ({
      thinkingContent: state.thinkingContent + content,
    })),
  setIsThinking: (isThinking) => set({ isThinking }),
  setPlanReady: (planReady) => set({ planReady }),

  addChatMessage: (message) =>
    set((state) => ({
      chatHistory: [...state.chatHistory, message],
    })),
  appendToLastChatMessage: (text) =>
    set((state) => {
      if (state.chatHistory.length === 0) return {};
      const history = [...state.chatHistory];
      const last = history[history.length - 1];
      history[history.length - 1] = { ...last, content: last.content + text };
      return { chatHistory: history };
    }),
  setLastChatMessage: (content) =>
    set((state) => {
      if (state.chatHistory.length === 0) return {};
      const history = [...state.chatHistory];
      history[history.length - 1] = { ...history[history.length - 1], content };
      return { chatHistory: history };
    }),
  clearChatHistory: () => set({ chatHistory: [] }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),

  resetToQueries: () =>
    set((state) => ({
      stage: 'queries',
      report: '',
      citations: '',
      streamingContent: '',
      currentStep: '',
      chatHistory: [],
      error: null,
      reportSteps: [],
      activeSources: { rag: false, webSearch: false, kdb: false },
      agentEvents: [],
      topic: state.topic,
      reportOrganization: state.reportOrganization,
      collection: state.collection,
      queries: state.queries,
      sources: state.sources,
      dynamicSources: state.dynamicSources,
      selectedCollections: state.selectedCollections,
    })),

  // Report step tracking actions
  setActiveSources: (activeSources) => set({ activeSources }),

  initializeReportSteps: (sources) => {
    const steps: StepResult[] = [];

    // Phase label reflects the FULL agent fan-out (legacy trio + dynamic source
    // agents), not just Documents/KDB/Web — per-agent detail lives in Agent Activity.
    const dynamicCount = Object.values(get().dynamicSources).filter(Boolean).length;
    const agentCount = (sources.rag ? 1 : 0) + (sources.kdb ? 1 : 0) + (sources.webSearch ? 1 : 0) + dynamicCount;

    const searchLabel = agentCount > 0
      ? `Researching (${agentCount} agent${agentCount === 1 ? '' : 's'})`
      : 'Researching';

    // Single research step that covers all sources (RAG, KDB, Web)
    // Backend combines all results in web_research_results
    steps.push({
      stepId: 'rag_search',
      stepName: searchLabel,
      status: 'pending',
    });

    // Always add writing, reflection, and finalization steps
    steps.push({
      stepId: 'running_summary',
      stepName: 'Writing Report',
      status: 'pending',
    });
    steps.push({
      stepId: 'reflect_on_summary',
      stepName: 'Improving',
      status: 'pending',
    });
    steps.push({
      stepId: 'final_report',
      stepName: 'Finalizing',
      status: 'pending',
    });

    set({ reportSteps: steps, activeSources: sources });
  },

  updateStepStatus: (stepId, status, content, details) =>
    set((state) => ({
      reportSteps: state.reportSteps.map((step) =>
        step.stepId === stepId
          ? {
              ...step,
              status,
              content: content ?? step.content,
              details: details ?? step.details,
              timestamp: status === 'active' ? new Date() : step.timestamp,
            }
          : step
      ),
    })),

  setStepContent: (stepId, content, details) =>
    set((state) => ({
      reportSteps: state.reportSteps.map((step) =>
        step.stepId === stepId
          ? { ...step, content, details: details ?? step.details }
          : step
      ),
    })),

  getStepResult: (stepId) => {
    const state = get();
    return state.reportSteps.find((step) => step.stepId === stepId);
  },

  clearReportSteps: () => set({ reportSteps: [], activeSources: { rag: false, webSearch: false, kdb: false } }),

  // Agent activity actions
  addAgentEvent: (event) => {
    const newEvent: AgentEvent = {
      ...event,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
    };
    set((state) => ({
      agentEvents: [...state.agentEvents, newEvent],
    }));
  },

  updateAgentEvent: (id, updates) =>
    set((state) => ({
      agentEvents: state.agentEvents.map((event) =>
        event.id === id ? { ...event, ...updates } : event
      ),
    })),

  clearAgentEvents: () => set({ agentEvents: [] }),
}));
