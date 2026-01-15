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
import { Settings, Database, ArrowLeft, MessageSquare } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card } from '../components/common';
import { KDBDataLoader } from '../components/settings/KDBDataLoader';
import { KDBChatPanel } from '../components/kdb';

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<'data' | 'chat' | 'general'>('chat');
  const [dataLoaderEnabled, setDataLoaderEnabled] = useState<boolean | null>(null);

  // Check if data loader is enabled by fetching KDB status
  useEffect(() => {
    const checkDataLoaderStatus = async () => {
      try {
        const response = await fetch('/kdb/status');
        if (response.ok) {
          const data = await response.json();
          setDataLoaderEnabled(data.data_loader_enabled ?? false);
          // If data loader is enabled, default to data tab
          if (data.data_loader_enabled) {
            setActiveTab('data');
          }
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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="p-2 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-nvidia-gray-800 rounded-lg flex items-center justify-center">
              <Settings className="w-5 h-5 text-nvidia-green" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Settings</h1>
              <p className="text-sm text-nvidia-gray-400">Configure your research assistant</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-nvidia-gray-700 pb-2">
        {/* Data tab - only shown when data loader is enabled (internal MCP) */}
        {dataLoaderEnabled && (
          <button
            onClick={() => setActiveTab('data')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              activeTab === 'data'
                ? 'bg-nvidia-green/10 text-nvidia-green'
                : 'text-nvidia-gray-400 hover:text-white hover:bg-nvidia-gray-800'
            }`}
          >
            <Database className="w-4 h-4" />
            KDB-X Data
          </button>
        )}
        <button
          onClick={() => setActiveTab('chat')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            activeTab === 'chat'
              ? 'bg-nvidia-green/10 text-nvidia-green'
              : 'text-nvidia-gray-400 hover:text-white hover:bg-nvidia-gray-800'
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          KDB Chat
        </button>
        <button
          onClick={() => setActiveTab('general')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            activeTab === 'general'
              ? 'bg-nvidia-green/10 text-nvidia-green'
              : 'text-nvidia-gray-400 hover:text-white hover:bg-nvidia-gray-800'
          }`}
        >
          <Settings className="w-4 h-4" />
          General
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'data' && dataLoaderEnabled && <KDBDataLoader />}

      {activeTab === 'chat' && <KDBChatPanel />}

      {activeTab === 'general' && (
        <Card>
          <h2 className="text-lg font-semibold text-white mb-4">General Settings</h2>
          <p className="text-nvidia-gray-400">General settings coming soon...</p>
        </Card>
      )}
    </div>
  );
}
