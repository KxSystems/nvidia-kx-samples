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

import {
  CandlestickChart,
  Globe,
  Globe2,
  Database,
  Server,
  Check,
  Plus,
  Upload,
  TrendingUp,
  Building2,
  Newspaper,
  FileText,
  Landmark,
  Lock,
  X,
  Settings2,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { useWorkflowStore } from '../../store/workflowStore';
import { Button } from '../common';
import { Tooltip } from '../common/Tooltip';
import { NewCollectionDialog, FileUploadDialog } from '../collections';
import { getSourceAgents } from '../../api/sourceAgents';
import { getKdbDocsSettings, setKdbDocsSettings } from '../../api/kdbDocs';
import { getKdbTablesSettings, setKdbTablesSettings } from '../../api/kdbTables';
import type { Collection, SourceAgentInfo } from '../../types/api';

// The six research source agents surfaced as dynamic toggles. The backend
// also reports 'rag' and 'kdb', but those map to dedicated store keys.
const DYNAMIC_SOURCE_NAMES = [
  // KDB-X-backed agents first, so they sit next to the fixed KDB-X tile.
  'kdb_docs',
  'kdb_pit',
  'onetick',
  'web_search',
  'market_data',
  'news_headlines',
  'fundamentals',
  'sec_filings',
  'macro_economic',
];

// Icon map for each backend source name.
const SOURCE_ICONS: Record<string, React.ReactNode> = {
  web: <Globe className="w-5 h-5" />,
  rag: <Database className="w-5 h-5" />,
  kdb: <Server className="w-5 h-5" />,
  onetick: <CandlestickChart className="w-5 h-5" />,
  web_search: <Globe2 className="w-5 h-5" />,
  market_data: <TrendingUp className="w-5 h-5" />,
  news_headlines: <Newspaper className="w-5 h-5" />,
  fundamentals: <Building2 className="w-5 h-5" />,
  sec_filings: <FileText className="w-5 h-5" />,
  macro_economic: <Landmark className="w-5 h-5" />,
  kdb_docs: <FileText className="w-5 h-5" />,
  kdb_pit: <CandlestickChart className="w-5 h-5" />,
};

// Short display labels for the compact grid tiles.
const SHORT_LABELS: Record<string, string> = {
  web: 'Web Search',
  rag: 'Documents (RAG)',
  kdb: 'Time-Series (KDB-X)',
  onetick: 'OneTick',
  web_search: 'Deep Web',
  market_data: 'Market Data',
  news_headlines: 'News',
  fundamentals: 'Fundamentals',
  sec_filings: 'SEC Filings',
  macro_economic: 'Macro',
  kdb_docs: 'Documents (KDB-X)',
  kdb_pit: 'Point-in-Time (KDB-X)',
};

// A few words describing what each source does (shown under the label).
const SHORT_DESC: Record<string, string> = {
  web: 'Quick Tavily web search',
  rag: 'Search your documents',
  kdb: 'Financial time-series',
  onetick: 'OneTick Cloud tick data',
  web_search: 'Multi-step web research',
  market_data: 'Quotes & indicators',
  news_headlines: 'Recent headlines',
  fundamentals: 'Financials & valuation',
  sec_filings: 'SEC 10-K / 10-Q / 8-K',
  macro_economic: 'FRED macro indicators',
  kdb_docs: 'Filings via KDB-X vectors',
  kdb_pit: 'Trade vs prevailing quote',
};

// Agents that fetch data over the public internet — selecting them adds
// round-trip latency, so we surface a small warning on their tiles.
const NETWORK_LATENCY_AGENTS = new Set([
  'web_search', 'market_data', 'news_headlines', 'fundamentals',
  'sec_filings', 'macro_economic', 'onetick', 'web',
]);

// Turn raw backend availability reasons into friendly, non-technical captions.
function friendlyReason(agent?: SourceAgentInfo): string | undefined {
  if (!agent) return undefined;
  if (agent.state === 'needs_key') {
    return `Needs API key${agent.missing_key ? ` (${agent.missing_key})` : ''}`;
  }
  if (agent.state === 'unavailable') {
    const r = (agent.reason || '').toLowerCase();
    if (r.includes('not installed')) return 'Optional add-on — not installed';
    if (r.includes('not deployed') || r.includes('unreachable')) return 'Service not deployed';
    return 'Unavailable';
  }
  return undefined;
}

interface SourceSelectorProps {
  collections: Collection[];
  onCollectionsChange?: () => void;
}

// ----------------------------------------------------------------------------
// Compact icon tile
// ----------------------------------------------------------------------------
interface SourceTileProps {
  name: string;
  label: string;
  isSelected: boolean;
  isAvailable: boolean;
  /** Short inline status label shown on the disabled tile (e.g. "Unavailable"). */
  disabledReason?: string;
  /** Full reason shown on hover (Tooltip); falls back to disabledReason. */
  disabledTooltip?: string;
  onToggle: () => void;
  /** Small count badge appended to the label (e.g. selected collection count). */
  countBadge?: number;
}

function SourceTile({ name, label, isSelected, isAvailable, disabledReason, disabledTooltip, onToggle, countBadge }: SourceTileProps) {
  const icon = SOURCE_ICONS[name] ?? <Globe className="w-5 h-5" />;
  const shortLabel = SHORT_LABELS[name] ?? label;

  const tile = (
    <button
      type="button"
      disabled={!isAvailable}
      onClick={onToggle}
      title={isAvailable ? label : undefined}
      className={clsx(
        'relative w-full flex flex-col items-center gap-2 p-3 rounded-xl border-2 transition-all duration-150 select-none',
        isAvailable
          ? clsx(
            isSelected
              ? 'border-nvidia-green bg-nvidia-green/10 text-nvidia-gray-50'
              : 'border-nvidia-gray-700 bg-nvidia-gray-800 text-nvidia-gray-400 hover:border-nvidia-gray-500 hover:text-nvidia-gray-200'
          )
          : 'border-nvidia-gray-700 bg-nvidia-gray-800/40 text-nvidia-gray-300 cursor-not-allowed'
      )}
    >
      {/* Selected check badge */}
      {isSelected && isAvailable && (
        <span className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-nvidia-green flex items-center justify-center">
          <Check className="w-2.5 h-2.5 text-white" />
        </span>
      )}

      {/* Disabled lock badge */}
      {!isAvailable && (
        <span className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-nvidia-gray-700 flex items-center justify-center">
          <Lock className="w-2.5 h-2.5 text-nvidia-gray-500" />
        </span>
      )}

      {/* Icon */}
      <span
        className={clsx(
          'flex items-center justify-center w-9 h-9 rounded-lg transition-colors',
          isAvailable
            ? isSelected
              ? 'bg-nvidia-green text-white'
              : 'bg-nvidia-gray-700 text-nvidia-gray-400'
            : 'bg-nvidia-gray-700/70 text-nvidia-gray-300'
        )}
      >
        {icon}
      </span>

      {/* Label */}
      <span
        className={clsx(
          'text-xs font-medium leading-tight text-center max-w-full truncate px-0.5',
          !isAvailable && 'text-nvidia-gray-200'
        )}
      >
        {shortLabel}
        {typeof countBadge === 'number' && countBadge > 0 && (
          <span className="ml-1 inline-block px-1.5 rounded-full bg-nvidia-green/15 text-nvidia-green text-[10px] font-semibold align-middle">
            {countBadge}
          </span>
        )}
      </span>

      {/* Short description (available) or short unavailability label (disabled);
          the FULL reason shows on hover via the Tooltip wrapper. */}
      {isAvailable ? (
        SHORT_DESC[name] && (
          <span
            className={clsx(
              'text-[10px] leading-tight text-center max-w-full truncate px-0.5 -mt-1',
              isSelected ? 'text-nvidia-green/90' : 'text-nvidia-gray-500'
            )}
          >
            {SHORT_DESC[name]}
          </span>
        )
      ) : (
        <span className="text-[10px] leading-tight text-amber-600/80 text-center max-w-full truncate px-0.5 -mt-1">
          {disabledReason ?? 'Unavailable'}
        </span>
      )}

      {/* Latency warning for agents that fetch over the public internet */}
      {isAvailable && NETWORK_LATENCY_AGENTS.has(name) && (
        <span className="mt-0.5 flex items-center gap-1 text-[10px] leading-tight text-amber-400 text-center max-w-full truncate px-0.5">
          <span aria-hidden>⚠</span> External — adds latency
        </span>
      )}
    </button>
  );

  return !isAvailable && (disabledTooltip || disabledReason)
    ? <Tooltip content={disabledTooltip ?? disabledReason} className="w-full">{tile}</Tooltip>
    : tile;
}

// ----------------------------------------------------------------------------
// Picker modal — overlay + centered card, mirroring FileUploadDialog's pattern.
// ----------------------------------------------------------------------------
interface PickerModalProps {
  isOpen: boolean;
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
}

function PickerModal({ isOpen, title, subtitle, icon, onClose, children }: PickerModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 w-full max-w-lg shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between p-4 border-b border-nvidia-gray-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-nvidia-green/20 flex items-center justify-center">
              {icon}
            </div>
            <div>
              <h3 className="text-lg font-semibold text-nvidia-gray-50">{title}</h3>
              {subtitle && <p className="text-sm text-nvidia-gray-400">{subtitle}</p>}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-nvidia-gray-400 hover:text-nvidia-gray-50 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {children}
          <div className="flex justify-end gap-2 pt-2">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Main component
// ----------------------------------------------------------------------------
export function SourceSelector({ collections, onCollectionsChange }: SourceSelectorProps) {
  const {
    sources,
    dynamicSources,
    selectedCollections,
    sourcesInitialized,
    toggleSource,
    toggleDynamicSource,
    toggleCollection,
    initializeSources,
    selectedKdbDocsCollection,
    setKdbDocsCollection,
    selectedKdbTables,
    setSelectedKdbTables,
  } = useWorkflowStore();

  const [sourceAgents, setSourceAgents] = useState<SourceAgentInfo[]>([]);

  // Fetch /source_agents and auto-select all available ones (once).
  useEffect(() => {
    let cancelled = false;
    getSourceAgents()
      .then((agents) => {
        if (cancelled) return;
        setSourceAgents(agents);

        // Only auto-initialize once; after that, preserve user opt-outs.
        if (!sourcesInitialized) {
          // Default to NOTHING selected — the user must explicitly choose agents.
          // (Availability still comes from agent.state for the tiles; this only sets
          // the initial selection. The Home page disables "Continue to Research" and
          // shows a "select at least one agent" prompt until something is picked.)
          const dynamic: Record<string, boolean> = {};
          for (const agent of agents.filter((a) => DYNAMIC_SOURCE_NAMES.includes(a.name))) {
            dynamic[agent.name] = false;
          }
          initializeSources({ webSearch: false, kdbx: false, rag: false, dynamic });
        }
      })
      .catch(() => {
        // Fail gracefully — keep whatever was in store, just mark initialized.
        if (!cancelled && !sourcesInitialized) {
          initializeSources({
            webSearch: sources.webSearch,
            kdbx: sources.kdbx,
            rag: sources.rag,
            dynamic: dynamicSources,
          });
        }
        if (!cancelled) setSourceAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps — intentionally run once

  // --- Build tile descriptors ---
  const webAgent = sourceAgents.find((a) => a.name === 'web');
  const ragAgent = sourceAgents.find((a) => a.name === 'rag');
  const kdbAgent = sourceAgents.find((a) => a.name === 'kdb');
  const dynamicAgentMap = Object.fromEntries(
    sourceAgents.filter((a) => DYNAMIC_SOURCE_NAMES.includes(a.name)).map((a) => [a.name, a])
  );

  const webAvailable = sourceAgents.length === 0 || webAgent?.state === 'available';
  const ragAvailable = sourceAgents.length === 0 || ragAgent?.state === 'available';
  const kdbAvailable = sourceAgents.length === 0 || kdbAgent?.state === 'available';

  const webDisabledReason = friendlyReason(webAgent);
  const ragDisabledReason = friendlyReason(ragAgent);
  const kdbDisabledReason = friendlyReason(kdbAgent);

  const [isNewCollectionOpen, setIsNewCollectionOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadCollectionName, setUploadCollectionName] = useState('');

  // RAG collection picker modal state
  const [ragModalOpen, setRagModalOpen] = useState(false);

  // KDB-docs collection picker state
  const [kdbDocsAvailableCollections, setKdbDocsAvailableCollections] = useState<string[]>([]);
  const [kdbDocsLoaded, setKdbDocsLoaded] = useState(false);
  const [kdbDocsModalOpen, setKdbDocsModalOpen] = useState(false);

  // KDB time-series table picker state
  const [kdbAvailableTables, setKdbAvailableTables] = useState<string[]>([]);
  const [kdbTableRows, setKdbTableRows] = useState<Record<string, number | null>>({});
  const [kdbTablesLoaded, setKdbTablesLoaded] = useState(false);
  const [kdbTablesModalOpen, setKdbTablesModalOpen] = useState(false);

  // Track previous enabled-state so we can auto-open the modal on the OFF->ON edge.
  const kdbDocsEnabled = !!dynamicSources['kdb_docs'];
  const kdbxEnabled = sources.kdbx;
  const ragEnabled = ragAvailable && sources.rag;
  const prevKdbDocsEnabled = useRef(kdbDocsEnabled);
  const prevKdbxEnabled = useRef(kdbxEnabled);
  const prevRagEnabled = useRef(ragEnabled);

  // RAG: open modal on enable (and refresh collections), close on disable.
  useEffect(() => {
    if (ragEnabled && !prevRagEnabled.current) {
      setRagModalOpen(true);
      onCollectionsChange?.();
    } else if (!ragEnabled && prevRagEnabled.current) {
      setRagModalOpen(false);
    }
    prevRagEnabled.current = ragEnabled;
  }, [ragEnabled]); // eslint-disable-line react-hooks/exhaustive-deps

  // kdb_docs: open modal on enable, close + reset lazy-load on disable.
  useEffect(() => {
    if (kdbDocsEnabled && !prevKdbDocsEnabled.current) {
      setKdbDocsModalOpen(true);
    } else if (!kdbDocsEnabled && prevKdbDocsEnabled.current) {
      setKdbDocsModalOpen(false);
      setKdbDocsLoaded(false);
    }
    prevKdbDocsEnabled.current = kdbDocsEnabled;
  }, [kdbDocsEnabled]);

  // KDB-X tables: open modal on enable, close + reset lazy-load on disable.
  useEffect(() => {
    if (kdbxEnabled && !prevKdbxEnabled.current) {
      setKdbTablesModalOpen(true);
    } else if (!kdbxEnabled && prevKdbxEnabled.current) {
      setKdbTablesModalOpen(false);
      setKdbTablesLoaded(false);
    }
    prevKdbxEnabled.current = kdbxEnabled;
  }, [kdbxEnabled]);

  // Fetch kdb_docs settings the first time its modal opens (pre-fill).
  useEffect(() => {
    if (!kdbDocsModalOpen || kdbDocsLoaded) return;
    getKdbDocsSettings()
      .then((settings) => {
        setKdbDocsAvailableCollections(settings.available_collections);
        if (settings.collection !== null) {
          setKdbDocsCollection(settings.collection);
        }
        setKdbDocsLoaded(true);
      })
      .catch(() => setKdbDocsLoaded(true));
  }, [kdbDocsModalOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch kdb table settings the first time its modal opens (pre-fill).
  useEffect(() => {
    if (!kdbTablesModalOpen || kdbTablesLoaded) return;
    getKdbTablesSettings()
      .then((settings) => {
        setKdbAvailableTables(settings.available_tables);
        setSelectedKdbTables(settings.selected_tables);
        setKdbTableRows(settings.table_rows ?? {});
        setKdbTablesLoaded(true);
      })
      .catch(() => setKdbTablesLoaded(true));
  }, [kdbTablesModalOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenUpload = (collectionName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setUploadCollectionName(collectionName);
    setIsUploadOpen(true);
  };

  const handleCollectionCreated = () => {
    onCollectionsChange?.();
  };

  const handleFilesUploaded = () => {
    onCollectionsChange?.();
  };

  return (
    <>
      {/* Compact icon grid — one unified panel for all sources */}
      <div className="rounded-xl border border-nvidia-gray-700 bg-nvidia-gray-800 p-4 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-nvidia-gray-400">
          Agents
        </p>

        <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
          {/* 1. Tavily web search — mapped from /source_agents 'web' */}
          <SourceTile
            name="web"
            label={webAgent?.label ?? 'Web Search (Tavily)'}
            isSelected={sources.webSearch}
            isAvailable={webAvailable}
            disabledReason={webDisabledReason}
            disabledTooltip={webAgent?.reason}
            onToggle={() => { if (webAvailable) toggleSource('webSearch'); }}
          />

          {/* 2. RAG — mapped from /source_agents 'rag' */}
          <SourceTile
            name="rag"
            label="Documents (RAG)"
            isSelected={sources.rag}
            isAvailable={ragAvailable}
            disabledReason={ragDisabledReason}
            disabledTooltip={ragAgent?.reason}
            onToggle={() => { if (ragAvailable) toggleSource('rag'); }}
            countBadge={sources.rag ? selectedCollections.length : undefined}
          />

          {/* 3. KDB-X — mapped from /source_agents 'kdb' */}
          <SourceTile
            name="kdb"
            label={kdbAgent?.label ?? 'KDB-X Database'}
            isSelected={sources.kdbx}
            isAvailable={kdbAvailable}
            disabledReason={kdbDisabledReason}
            disabledTooltip={kdbAgent?.reason}
            onToggle={() => { if (kdbAvailable) toggleSource('kdbx'); }}
          />

          {/* 4-9. Dynamic source agents */}
          {DYNAMIC_SOURCE_NAMES.map((name) => {
            const agent = dynamicAgentMap[name];
            const available = sourceAgents.length === 0 || agent?.state === 'available';
            const disabledReason = friendlyReason(agent);

            return (
              <SourceTile
                key={name}
                name={name}
                label={agent?.label ?? name}
                isSelected={!!dynamicSources[name]}
                isAvailable={available}
                disabledReason={disabledReason}
                disabledTooltip={agent?.reason}
                onToggle={() => { if (available) toggleDynamicSource(name); }}
              />
            );
          })}
        </div>

        {/* Reopen links for agents whose data selection lives in a modal popup. */}
        {(ragEnabled || kdbDocsEnabled || (kdbAvailable && sources.kdbx)) && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1">
            {ragEnabled && (
              <button
                type="button"
                onClick={() => setRagModalOpen(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-nvidia-green hover:text-nvidia-green/80 transition-colors"
              >
                <Settings2 className="w-3.5 h-3.5" />
                {SHORT_LABELS['rag']}: {selectedCollections.length > 0
                  ? `${selectedCollections.length} collection${selectedCollections.length === 1 ? '' : 's'}`
                  : 'choose collections'}
              </button>
            )}
            {kdbDocsEnabled && (
              <button
                type="button"
                onClick={() => setKdbDocsModalOpen(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-nvidia-green hover:text-nvidia-green/80 transition-colors"
              >
                <Settings2 className="w-3.5 h-3.5" />
                {SHORT_LABELS['kdb_docs']}: {selectedKdbDocsCollection ?? 'choose a collection'}
              </button>
            )}
            {kdbAvailable && sources.kdbx && (
              <button
                type="button"
                onClick={() => setKdbTablesModalOpen(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-nvidia-green hover:text-nvidia-green/80 transition-colors"
              >
                <Settings2 className="w-3.5 h-3.5" />
                {SHORT_LABELS['kdb']}: {selectedKdbTables.length > 0
                  ? `${selectedKdbTables.length} table${selectedKdbTables.length === 1 ? '' : 's'}`
                  : 'choose tables'}
              </button>
            )}
          </div>
        )}
      </div>

      {/* RAG collection picker — modal popup, opens when Documents (RAG) is selected */}
      <PickerModal
        isOpen={ragModalOpen}
        title="Documents (RAG) — choose collections"
        subtitle="Pick what the agent searches"
        icon={<Database className="w-5 h-5 text-nvidia-green" />}
        onClose={() => setRagModalOpen(false)}
      >
        <div className="flex justify-end">
          <button
            onClick={() => setIsNewCollectionOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-nvidia-green bg-nvidia-green/10 border border-nvidia-green/30 rounded-lg hover:bg-nvidia-green/20 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            New
          </button>
        </div>

        {collections.length === 0 ? (
          <p className="text-sm text-nvidia-gray-500">No collections available</p>
        ) : (
          <div className="grid gap-2 max-h-72 overflow-y-auto scrollbar-thin pr-1">
            {collections.map((collection) => (
              <div
                key={collection.name}
                className={clsx(
                  'flex items-center justify-between p-3 rounded-lg border transition-all',
                  selectedCollections.includes(collection.name)
                    ? 'border-nvidia-green bg-nvidia-green/10'
                    : 'border-nvidia-gray-600 bg-nvidia-gray-700/50'
                )}
              >
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleCollection(collection.name);
                  }}
                  className="flex items-center gap-3 flex-1 text-left"
                >
                  <div
                    className={clsx(
                      'w-5 h-5 rounded border-2 flex items-center justify-center transition-all flex-shrink-0',
                      selectedCollections.includes(collection.name)
                        ? 'border-nvidia-green bg-nvidia-green'
                        : 'border-nvidia-gray-500'
                    )}
                  >
                    {selectedCollections.includes(collection.name) && (
                      <Check className="w-3 h-3 text-white" />
                    )}
                  </div>
                  <div>
                    <span
                      className={clsx(
                        'font-medium',
                        selectedCollections.includes(collection.name) ? 'text-nvidia-gray-50' : 'text-nvidia-gray-300'
                      )}
                    >
                      {collection.name}
                    </span>
                    {collection.document_count !== undefined && (
                      <span className="text-xs text-nvidia-gray-500 ml-2">
                        ({collection.document_count} docs)
                      </span>
                    )}
                  </div>
                </button>
                <button
                  onClick={(e) => handleOpenUpload(collection.name, e)}
                  className="p-2 text-nvidia-gray-400 hover:text-nvidia-green hover:bg-nvidia-gray-700 rounded-lg transition-colors"
                  title="Upload files to this collection"
                >
                  <Upload className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </PickerModal>

      {/* kdb_docs collection picker — modal popup, opens when the agent is selected */}
      <PickerModal
        isOpen={kdbDocsModalOpen}
        title="Documents (KDB-X) — choose a collection"
        subtitle="Pick what the agent searches"
        icon={<FileText className="w-5 h-5 text-nvidia-green" />}
        onClose={() => setKdbDocsModalOpen(false)}
      >
        {kdbDocsAvailableCollections.length === 0 ? (
          <p className="text-sm text-nvidia-gray-500">
            No collections available — load data into KDB-X first.
          </p>
        ) : (
          <div className="grid gap-2 max-h-72 overflow-y-auto scrollbar-thin pr-1">
            {kdbDocsAvailableCollections.map((col) => (
              <div
                key={col}
                className={clsx(
                  'flex items-center p-3 rounded-lg border transition-all cursor-pointer',
                  selectedKdbDocsCollection === col
                    ? 'border-nvidia-green bg-nvidia-green/10'
                    : 'border-nvidia-gray-600 bg-nvidia-gray-700/50'
                )}
                onClick={() => {
                  setKdbDocsCollection(col);
                  setKdbDocsSettings(col).catch(() => undefined);
                }}
              >
                {/* Radio indicator */}
                <div
                  className={clsx(
                    'w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 mr-3 transition-all',
                    selectedKdbDocsCollection === col
                      ? 'border-nvidia-green bg-nvidia-green'
                      : 'border-nvidia-gray-500'
                  )}
                >
                  {selectedKdbDocsCollection === col && (
                    <div className="w-1.5 h-1.5 rounded-full bg-white" />
                  )}
                </div>
                <span
                  className={clsx(
                    'text-sm font-medium',
                    selectedKdbDocsCollection === col ? 'text-nvidia-gray-50' : 'text-nvidia-gray-300'
                  )}
                >
                  {col}
                </span>
              </div>
            ))}
          </div>
        )}

        {selectedKdbDocsCollection === null && kdbDocsAvailableCollections.length > 0 && (
          <p className="text-xs text-amber-500/80">
            Pick a collection — the agent stays unavailable until you do.
          </p>
        )}
      </PickerModal>

      {/* KDB time-series table picker — modal popup, opens when KDB-X is selected */}
      <PickerModal
        isOpen={kdbTablesModalOpen}
        title="KDB-X — choose tables"
        subtitle="Select tables to query"
        icon={<Server className="w-5 h-5 text-nvidia-green" />}
        onClose={() => setKdbTablesModalOpen(false)}
      >
        {kdbAvailableTables.length === 0 ? (
          <p className="text-sm text-nvidia-gray-500">
            No tables configured / scoped — set KDB_VISIBLE_TABLES or load data.
          </p>
        ) : (
          <div className="grid gap-2 max-h-72 overflow-y-auto scrollbar-thin pr-1">
            {kdbAvailableTables.map((table) => (
              <div
                key={table}
                className={clsx(
                  'flex items-center p-3 rounded-lg border transition-all cursor-pointer',
                  selectedKdbTables.includes(table)
                    ? 'border-nvidia-green bg-nvidia-green/10'
                    : 'border-nvidia-gray-600 bg-nvidia-gray-700/50'
                )}
                onClick={() => {
                  const next = selectedKdbTables.includes(table)
                    ? selectedKdbTables.filter((t) => t !== table)
                    : [...selectedKdbTables, table];
                  setSelectedKdbTables(next);
                  setKdbTablesSettings(next).catch(() => undefined);
                }}
              >
                <div
                  className={clsx(
                    'w-5 h-5 rounded border-2 flex items-center justify-center transition-all flex-shrink-0 mr-3',
                    selectedKdbTables.includes(table)
                      ? 'border-nvidia-green bg-nvidia-green'
                      : 'border-nvidia-gray-500'
                  )}
                >
                  {selectedKdbTables.includes(table) && (
                    <Check className="w-3 h-3 text-white" />
                  )}
                </div>
                <span
                  className={clsx(
                    'text-sm font-medium',
                    selectedKdbTables.includes(table) ? 'text-nvidia-gray-50' : 'text-nvidia-gray-300'
                  )}
                >
                  {table}
                </span>
                {/* Row-count status: populated vs empty/not-loaded */}
                {(() => {
                  const rows = kdbTableRows[table];
                  if (rows === undefined || rows === null) {
                    return <span className="ml-auto text-xs text-amber-400/80">not loaded</span>;
                  }
                  if (rows === 0) {
                    return <span className="ml-auto text-xs text-amber-400">empty</span>;
                  }
                  return (
                    <span className="ml-auto text-xs text-nvidia-gray-400">
                      {rows.toLocaleString()} rows
                    </span>
                  );
                })()}
              </div>
            ))}
          </div>
        )}

        {kdbAvailableTables.length > 0 && (
          <p className="text-xs text-nvidia-gray-500">
            Empty / not-loaded tables return no data — load via KDB-X → Load Data.
          </p>
        )}
      </PickerModal>

      <NewCollectionDialog
        isOpen={isNewCollectionOpen}
        onClose={() => setIsNewCollectionOpen(false)}
        onCreated={handleCollectionCreated}
      />

      <FileUploadDialog
        isOpen={isUploadOpen}
        collectionName={uploadCollectionName}
        onClose={() => setIsUploadOpen(false)}
        onUploaded={handleFilesUploaded}
      />
    </>
  );
}
