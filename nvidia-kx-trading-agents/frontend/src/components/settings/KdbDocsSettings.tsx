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

import { useEffect, useState } from 'react';
import { getKdbDocsSettings, setKdbDocsSettings } from '../../api/kdbDocs';
import { Button } from '../common/Button';

interface KdbDocsSettingsProps {
  onSaved?: () => void;
}

export function KdbDocsSettings({ onSaved }: KdbDocsSettingsProps) {
  const [collection, setCollection] = useState<string>('');
  const [available, setAvailable] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getKdbDocsSettings();
      setCollection(s.collection ?? '');
      setAvailable(s.available_collections ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const s = await setKdbDocsSettings(collection || null);
      setCollection(s.collection ?? '');
      setAvailable(s.available_collections ?? []);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-nvidia-gray-50">KDB-X Document Search</h3>
        <p className="text-sm text-nvidia-gray-400 mt-1">
          Pick a RAG collection for the in-engine (GPU) document agent. Upload documents in the
          Collections tab; they become searchable here once ingested.
        </p>
      </div>
      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-900/20 border border-red-800/50 rounded-lg">
          <span className="text-red-400 text-sm">{error}</span>
        </div>
      )}
      <div className="flex items-center gap-3">
        <select
          aria-label="RAG collection for document search"
          value={collection}
          disabled={loading || saving}
          onChange={(e) => setCollection(e.target.value)}
          className="input flex-1"
        >
          <option value="">— none (agent disabled) —</option>
          {available.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
          {collection && !available.includes(collection) && (
            <option value={collection}>{collection}</option>
          )}
        </select>
        <Button onClick={save} disabled={loading || saving} isLoading={saving}>
          Save
        </Button>
      </div>
    </div>
  );
}
