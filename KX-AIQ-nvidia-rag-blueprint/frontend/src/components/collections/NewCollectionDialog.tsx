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

import { useState } from 'react';
import { X, Database } from 'lucide-react';
import { Button, Input } from '../common';
import { createCollection } from '../../api/collections';

interface NewCollectionDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function NewCollectionDialog({ isOpen, onClose, onCreated }: NewCollectionDialogProps) {
  const [name, setName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      await createCollection(name.trim());
      setName('');
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create collection');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setName('');
      setError(null);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 w-full max-w-md shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between p-4 border-b border-nvidia-gray-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-nvidia-green/20 flex items-center justify-center">
              <Database className="w-5 h-5 text-nvidia-green" />
            </div>
            <h3 className="text-lg font-semibold text-white">New Collection</h3>
          </div>
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="p-1 text-nvidia-gray-400 hover:text-white transition-colors disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <Input
            label="Collection Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., Research_Papers"
            disabled={isLoading}
            helperText="Use alphanumeric characters and underscores only"
          />

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!name.trim() || isLoading}
              isLoading={isLoading}
            >
              Create Collection
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
