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
import { Database, ArrowLeft, MessageSquare } from 'lucide-react';
import { Link } from 'react-router-dom';
import { KDBDataLoader } from '../components/settings/KDBDataLoader';
import { KDBChatPanel } from '../components/kdb';

/**
 * First-class KDB-X workspace (promoted out of Settings): natural-language Chat
 * and the historical-data Loader. The Loader tab is shown only when the data
 * loader is enabled (internal MCP, KDB_MCP_INTERNAL=true) — same condition as
 * before, just surfaced in primary navigation instead of buried in Settings.
 */
export function KDBPage() {
  const [activeTab, setActiveTab] = useState<'data' | 'chat'>('chat');
  const [dataLoaderEnabled, setDataLoaderEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    const checkDataLoaderStatus = async () => {
      try {
        const response = await fetch('/api/kdb/status');
        if (response.ok) {
          const data = await response.json();
          setDataLoaderEnabled(data.data_loader_enabled ?? false);
          // Chat stays the default tab; Load Data is opt-in even when enabled.
        } else {
          setDataLoaderEnabled(false);
        }
      } catch {
        setDataLoaderEnabled(false);
      }
    };
    checkDataLoaderStatus();
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          to="/"
          className="p-2 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-nvidia-gray-50 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#1a1d22] rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">KX</span>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-nvidia-gray-50">KDB-X</h1>
            <p className="text-sm text-nvidia-gray-400">Query and load market data in the time-series database</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-nvidia-gray-700 pb-2">
        <button
          onClick={() => setActiveTab('chat')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            activeTab === 'chat'
              ? 'bg-nvidia-green/10 text-nvidia-green'
              : 'text-nvidia-gray-400 hover:text-nvidia-gray-50 hover:bg-nvidia-gray-800'
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          Chat
        </button>
        {/* Loader tab — only when the internal MCP enables write/load operations */}
        {dataLoaderEnabled && (
          <button
            onClick={() => setActiveTab('data')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              activeTab === 'data'
                ? 'bg-nvidia-green/10 text-nvidia-green'
                : 'text-nvidia-gray-400 hover:text-nvidia-gray-50 hover:bg-nvidia-gray-800'
            }`}
          >
            <Database className="w-4 h-4" />
            Load Data
          </button>
        )}
      </div>

      {/* Tab Content */}
      {activeTab === 'chat' && <KDBChatPanel />}
      {activeTab === 'data' && dataLoaderEnabled && <KDBDataLoader />}
    </div>
  );
}
