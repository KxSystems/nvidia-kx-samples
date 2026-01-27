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

import { useEffect, useState, useCallback } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/layout';
import { HomePage } from './pages/HomePage';
import { ResearchPage } from './pages/ResearchPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoadingSpinner } from './components/common';
import { getAllCollections } from './api/collections';
import type { Collection } from './types/api';

function App() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCollections = useCallback(async () => {
    try {
      const data = await getAllCollections();
      setCollections(data);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch collections:', err);
      setError('Failed to connect to the server. Please ensure the backend is running.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCollections();
  }, [fetchCollections]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-nvidia-gray-900 flex items-center justify-center">
        <LoadingSpinner size="lg" message="Connecting to server..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-nvidia-gray-900 flex items-center justify-center p-4">
        <div className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 p-8 max-w-md text-center">
          <h1 className="text-xl font-semibold text-white mb-2">Connection Error</h1>
          <p className="text-nvidia-gray-400 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="btn-primary"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage collections={collections} onCollectionsChange={fetchCollections} />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

export default App;
