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

import { useState, useEffect } from 'react';
import { Settings, ArrowLeft, CheckCircle, AlertCircle, XCircle, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card } from '../components/common';
import { getSourceAgents } from '../api/sourceAgents';
import type { SourceAgentInfo } from '../types/api';
import { KdbDocsSettings } from '../components/settings/KdbDocsSettings';

interface KdbStatus {
  connected: boolean;
  message?: string;
  data_loader_enabled?: boolean;
  mcp_endpoint?: string;
}

function StateIcon({ state }: { state: SourceAgentInfo['state'] }) {
  if (state === 'available') return <CheckCircle className="w-4 h-4 text-green-600" />;
  if (state === 'needs_key') return <AlertCircle className="w-4 h-4 text-amber-500" />;
  return <XCircle className="w-4 h-4 text-nvidia-gray-500" />;
}

/**
 * Settings → System Status: a read-only diagnostics view of what's wired up —
 * the research agents and their availability, plus the KDB-X connection — so an
 * operator can confirm configuration (keys, NIMs, services) without leaving the app.
 */
export function SettingsPage() {
  const [agents, setAgents] = useState<SourceAgentInfo[] | null>(null);
  const [kdb, setKdb] = useState<KdbStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const [a, k] = await Promise.all([
        getSourceAgents().catch(() => null),
        fetch('/api/kdb/status').then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      setAgents(a);
      setKdb(k);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const availableCount = agents?.filter((a) => a.state === 'available').length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="p-2 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-nvidia-gray-50 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-nvidia-gray-800 rounded-lg flex items-center justify-center">
              <Settings className="w-5 h-5 text-nvidia-green" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-nvidia-gray-50">Settings &amp; Status</h1>
              <p className="text-sm text-nvidia-gray-400">What's configured and connected in this workspace</p>
            </div>
          </div>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-nvidia-gray-600 text-nvidia-gray-300 hover:text-nvidia-gray-50 hover:border-nvidia-gray-400 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Research agents */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-nvidia-gray-50">Research Agents</h2>
          {agents && (
            <span className="text-sm text-nvidia-gray-400">
              <span className="text-nvidia-green font-medium">{availableCount}</span> / {agents.length} available
            </span>
          )}
        </div>
        {!agents ? (
          <p className="text-sm text-nvidia-gray-500">{loading ? 'Loading…' : 'Could not load agent status.'}</p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-2">
            {agents.map((a) => (
              <div
                key={a.name}
                className="flex items-start gap-2.5 p-2.5 rounded-lg border border-nvidia-gray-700 bg-nvidia-gray-800/50"
              >
                <StateIcon state={a.state} />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-nvidia-gray-100">{a.label}</p>
                  <p className="text-xs text-nvidia-gray-500 truncate">
                    {a.state === 'available'
                      ? (a.description || 'Ready')
                      : a.state === 'needs_key'
                        ? `Needs API key${a.missing_key ? ` (${a.missing_key})` : ''}`
                        : (a.reason || 'Unavailable')}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* KDB-X connection */}
      <Card>
        <h2 className="text-lg font-semibold text-nvidia-gray-50 mb-4">KDB-X Connection</h2>
        {!kdb ? (
          <p className="text-sm text-nvidia-gray-500">{loading ? 'Loading…' : 'KDB-X status unavailable.'}</p>
        ) : (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              {kdb.connected ? (
                <CheckCircle className="w-4 h-4 text-green-600" />
              ) : (
                <XCircle className="w-4 h-4 text-red-500" />
              )}
              <span className="text-nvidia-gray-200">{kdb.connected ? 'Connected' : 'Not connected'}</span>
              {kdb.message && <span className="text-nvidia-gray-500">— {kdb.message}</span>}
            </div>
            <div className="text-nvidia-gray-400">
              Data loader:{' '}
              <span className="text-nvidia-gray-200">{kdb.data_loader_enabled ? 'enabled' : 'disabled'}</span>
              {kdb.data_loader_enabled && (
                <> — <Link to="/kdb" className="text-blue-600 underline hover:no-underline">open the KDB-X workspace</Link></>
              )}
            </div>
          </div>
        )}
      </Card>

      {/* KDB-X Document Collection */}
      <Card>
        <KdbDocsSettings onSaved={refresh} />
      </Card>

      {/* About */}
      <Card>
        <h2 className="text-lg font-semibold text-nvidia-gray-50 mb-2">About</h2>
        <p className="text-sm text-nvidia-gray-400">
          AI Trading Agents Blueprint — a multi-agent financial research system built on the NVIDIA
          NeMo Agent Toolkit and NIM (LLMs, NeMo Retriever reranking/embedding/extraction, NemoGuard safety),
          with KDB-X for market data. Decision support, not personalized investment advice.
        </p>
      </Card>
    </div>
  );
}
