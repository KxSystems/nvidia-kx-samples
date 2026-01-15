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
import { X } from 'lucide-react';
import { Button, Textarea } from '../common';
import { useArtifactQA } from '../../hooks/useArtifactQA';

interface RewriteDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function RewriteDialog({ isOpen, onClose }: RewriteDialogProps) {
  const [instructions, setInstructions] = useState('');
  const { rewrite, isLoading } = useArtifactQA();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!instructions.trim()) return;

    await rewrite(instructions);
    setInstructions('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 w-full max-w-lg shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between p-4 border-b border-nvidia-gray-700">
          <h3 className="text-lg font-semibold text-white">Rewrite Report</h3>
          <button
            onClick={onClose}
            className="p-1 text-nvidia-gray-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <Textarea
            label="Rewrite Instructions"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Describe how you want the report to be rewritten. For example: 'Make it more concise' or 'Add a section about market trends'"
            rows={5}
            disabled={isLoading}
          />

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!instructions.trim() || isLoading}
              isLoading={isLoading}
            >
              Rewrite
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
