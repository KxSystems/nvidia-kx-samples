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

import { Settings, Menu, Database } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Button } from '../common';
import { useUIStore } from '../../store/uiStore';

// KX Logo component - official brand colors (white text on dark)
function KXLogo({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <rect width="48" height="24" rx="4" fill="#1a1d22" />
      <text
        x="24"
        y="17"
        textAnchor="middle"
        fill="#ffffff"
        fontFamily="Arial, sans-serif"
        fontWeight="bold"
        fontSize="14"
      >
        KX
      </text>
    </svg>
  );
}

export function Header() {
  const { toggleSidebar } = useUIStore();
  const location = useLocation();
  // Surface the KDB-X workspace in primary nav only when KDB is actually wired
  // up (connected or its data loader enabled) — hidden in KDB-disabled deployments.
  const [kdbAvailable, setKdbAvailable] = useState(false);
  useEffect(() => {
    fetch('/api/kdb/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setKdbAvailable(!!d && (d.connected || d.data_loader_enabled)))
      .catch(() => setKdbAvailable(false));
  }, []);
  const onKdb = location.pathname === '/kdb';

  return (
    <header className="h-16 bg-nvidia-gray-800 border-b border-nvidia-gray-700 px-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <button
          onClick={toggleSidebar}
          aria-label="Toggle sidebar"
          className="p-2 text-nvidia-gray-400 hover:text-nvidia-gray-50 transition-colors lg:hidden"
        >
          <Menu className="w-5 h-5" />
        </button>
        <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
          <div className="w-8 h-8 bg-nvidia-green rounded flex items-center justify-center">
            <span className="text-white font-bold text-sm">TA</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold text-nvidia-gray-50">AI Trading Agents</h1>
            <p className="text-xs text-nvidia-gray-400">Financial Research &amp; Decision Support</p>
          </div>
        </Link>
      </div>

      <div className="flex items-center gap-4">
        {/* KDB-X workspace — primary nav (replaces the buried Settings tabs) */}
        {kdbAvailable && (
          <Link
            to="/kdb"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              onKdb
                ? 'bg-nvidia-green/10 text-nvidia-green'
                : 'text-nvidia-gray-300 hover:text-nvidia-gray-50 hover:bg-nvidia-gray-900/50'
            }`}
          >
            <Database className="w-4 h-4" />
            KDB-X
          </Link>
        )}
        {/* KX Branding */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-nvidia-gray-900/50 rounded-lg border border-nvidia-gray-700">
          <span className="text-xs text-nvidia-gray-400">Powered by</span>
          <KXLogo className="h-5 w-auto" />
        </div>
        <Link to="/settings" aria-label="Settings">
          <Button variant="ghost" size="sm">
            <Settings className="w-4 h-4" />
          </Button>
        </Link>
      </div>
    </header>
  );
}
