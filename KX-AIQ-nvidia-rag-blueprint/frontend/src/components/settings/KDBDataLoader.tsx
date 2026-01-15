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

import { useState, useCallback, useEffect, useRef } from 'react';
import { Download, Check, AlertCircle, Loader2, Calendar, TrendingUp, AlertTriangle, Wifi, WifiOff, RefreshCw, X, Newspaper, BarChart3, ThumbsUp } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../common/Card';
import { Button } from '../common/Button';
import { clsx } from 'clsx';

// Default stock symbols matching the KDB-X test data
const DEFAULT_SYMBOLS = [
  'AAPL', 'GOOG', 'MSFT', 'TSLA', 'AMZN',
  'NVDA', 'META', 'RIVN', 'BYD', 'BA'
];

const STORAGE_KEY = 'kdb-active-job-id';
const POLL_INTERVAL = 3000; // 3 seconds

interface LoadProgress {
  symbol: string;
  status: 'pending' | 'loading' | 'complete' | 'error';
  message?: string;
  rowsLoaded?: number;
}

interface LoadingState {
  isLoading: boolean;
  progress: LoadProgress[];
  overallProgress: number;
  currentPhase: string;
  error?: string;
  jobId?: string;
  connectionStatus: 'connected' | 'polling' | 'disconnected';
}

interface JobStatus {
  job_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  symbols: string[];
  completed_symbols: string[];
  current_symbol: string | null;
  phase: string;
  overall_progress: number;
  total_rows: number;
  rows_loaded: number;
  error: string | null;
  start_time: string;
  last_update: string;
}

interface JobSummary {
  job_id: string;
  status: string;
  symbols: string[];
  overall_progress: number;
  rows_loaded: number;
  start_time: string;
}

export function KDBDataLoader() {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [startDate, setStartDate] = useState(() => {
    // Default to 5 years ago
    const date = new Date();
    date.setFullYear(date.getFullYear() - 5);
    return date.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => {
    // Default to today
    return new Date().toISOString().split('T')[0];
  });

  const [loadingState, setLoadingState] = useState<LoadingState>({
    isLoading: false,
    progress: [],
    overallProgress: 0,
    currentPhase: '',
    connectionStatus: 'disconnected',
  });

  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Public data loading state
  const [publicDataTypes, setPublicDataTypes] = useState<Set<string>>(new Set(['fundamentals', 'news', 'recommendations']));
  const [publicDataLoading, setPublicDataLoading] = useState(false);
  const [publicDataProgress, setPublicDataProgress] = useState(0);
  const [publicDataPhase, setPublicDataPhase] = useState('');
  const [publicDataError, setPublicDataError] = useState<string | undefined>();
  const [publicDataComplete, setPublicDataComplete] = useState(false);

  // Helper to update state from job status
  const updateStateFromJob = useCallback((job: JobStatus) => {
    setLoadingState(prev => ({
      ...prev,
      isLoading: job.status === 'running',
      jobId: job.job_id,
      overallProgress: job.overall_progress,
      currentPhase: job.phase,
      error: job.error || undefined,
      progress: job.symbols.map(symbol => ({
        symbol,
        status: job.completed_symbols.includes(symbol)
          ? 'complete'
          : symbol === job.current_symbol
          ? 'loading'
          : 'pending',
        rowsLoaded: job.completed_symbols.includes(symbol) ? undefined : undefined,
      })),
    }));
  }, []);

  // Poll for job status
  const pollJobStatus = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(`/api/kdb/jobs/${jobId}`);
      if (!response.ok) {
        if (response.status === 404) {
          // Job not found, clear storage and stop polling
          localStorage.removeItem(STORAGE_KEY);
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setLoadingState(prev => ({
            ...prev,
            isLoading: false,
            connectionStatus: 'disconnected',
          }));
          return;
        }
        throw new Error(`Failed to fetch job status: ${response.statusText}`);
      }

      const job: JobStatus = await response.json();
      updateStateFromJob(job);
      setLoadingState(prev => ({
        ...prev,
        connectionStatus: 'polling',
      }));

      // Stop polling if job is done
      if (job.status !== 'running') {
        localStorage.removeItem(STORAGE_KEY);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        setLoadingState(prev => ({
          ...prev,
          connectionStatus: 'disconnected',
        }));
      }
    } catch (error) {
      console.error('Failed to poll job status:', error);
    }
  }, [updateStateFromJob]);

  // Start polling for a job
  const startPolling = useCallback((jobId: string) => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    pollJobStatus(jobId); // Immediate poll
    pollIntervalRef.current = setInterval(() => pollJobStatus(jobId), POLL_INTERVAL);
  }, [pollJobStatus]);

  // Check for active job on mount
  useEffect(() => {
    const checkActiveJob = async () => {
      // First check localStorage for a job we were tracking
      const storedJobId = localStorage.getItem(STORAGE_KEY);
      if (storedJobId) {
        startPolling(storedJobId);
        return;
      }

      // Otherwise check for any active job on the server
      try {
        const response = await fetch('/api/kdb/jobs/active');
        if (response.ok) {
          const data = await response.json();
          if (data.active_job) {
            localStorage.setItem(STORAGE_KEY, data.active_job.job_id);
            startPolling(data.active_job.job_id);
          }
        }
      } catch (error) {
        console.warn('Failed to check for active job:', error);
      }
    };

    checkActiveJob();
    fetchRecentJobs();

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [startPolling]);

  // Fetch recent jobs
  const fetchRecentJobs = async () => {
    try {
      const response = await fetch('/api/kdb/jobs?limit=5');
      if (response.ok) {
        const data = await response.json();
        setRecentJobs(data.jobs || []);
      }
    } catch (error) {
      console.warn('Failed to fetch recent jobs:', error);
    }
  };

  const toggleSymbol = useCallback((symbol: string) => {
    setSelectedSymbols(prev => {
      const next = new Set(prev);
      if (next.has(symbol)) {
        next.delete(symbol);
      } else {
        next.add(symbol);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedSymbols(new Set(DEFAULT_SYMBOLS));
  }, []);

  const clearAll = useCallback(() => {
    setSelectedSymbols(new Set());
  }, []);

  const loadData = useCallback(async () => {
    if (selectedSymbols.size === 0) {
      setLoadingState(prev => ({
        ...prev,
        error: 'Please select at least one symbol',
      }));
      return;
    }

    const symbols = Array.from(selectedSymbols);

    // Initialize progress for all symbols
    setLoadingState({
      isLoading: true,
      progress: symbols.map(symbol => ({
        symbol,
        status: 'pending',
      })),
      overallProgress: 0,
      currentPhase: 'Initializing...',
      error: undefined,
      connectionStatus: 'connected',
    });

    try {
      const response = await fetch('/api/kdb/load-historical', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          symbols,
          start_date: startDate,
          end_date: endDate,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to start data loading: ${response.statusText}`);
      }

      // Stream the progress
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));

              // Store job_id when we receive it
              if (data.job_id) {
                localStorage.setItem(STORAGE_KEY, data.job_id);
                setLoadingState(prev => ({
                  ...prev,
                  jobId: data.job_id,
                }));
              }

              if (data.type === 'progress') {
                setLoadingState(prev => ({
                  ...prev,
                  connectionStatus: 'connected',
                  progress: prev.progress.map(p =>
                    p.symbol === data.symbol
                      ? {
                          ...p,
                          status: data.status,
                          message: data.message,
                          rowsLoaded: data.rows_loaded,
                        }
                      : p
                  ),
                  overallProgress: data.overall_progress || prev.overallProgress,
                  currentPhase: data.phase || prev.currentPhase,
                }));
              } else if (data.type === 'complete') {
                localStorage.removeItem(STORAGE_KEY);
                setLoadingState(prev => ({
                  ...prev,
                  isLoading: false,
                  overallProgress: 100,
                  currentPhase: 'Complete!',
                  connectionStatus: 'disconnected',
                }));
                fetchRecentJobs(); // Refresh job list
              } else if (data.type === 'error') {
                localStorage.removeItem(STORAGE_KEY);
                setLoadingState(prev => ({
                  ...prev,
                  isLoading: false,
                  error: data.message,
                  connectionStatus: 'disconnected',
                }));
                fetchRecentJobs(); // Refresh job list
              }
            } catch (e) {
              console.warn('Failed to parse SSE data:', line, e);
            }
          }
        }
      }
    } catch (error) {
      // SSE connection lost - try to start polling if we have a job ID
      const storedJobId = localStorage.getItem(STORAGE_KEY);
      if (storedJobId) {
        setLoadingState(prev => ({
          ...prev,
          connectionStatus: 'polling',
        }));
        startPolling(storedJobId);
      } else {
        setLoadingState(prev => ({
          ...prev,
          isLoading: false,
          error: error instanceof Error ? error.message : 'Unknown error occurred',
          connectionStatus: 'disconnected',
        }));
      }
    }
  }, [selectedSymbols, startDate, endDate, startPolling]);

  // Cancel the current job
  const cancelJob = useCallback(async () => {
    if (!loadingState.jobId) return;

    try {
      const response = await fetch(`/api/kdb/jobs/${loadingState.jobId}/cancel`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to cancel job');
      }

      // Stop polling if active
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }

      localStorage.removeItem(STORAGE_KEY);
      setLoadingState(prev => ({
        ...prev,
        isLoading: false,
        error: 'Job cancelled',
        connectionStatus: 'disconnected',
      }));
      fetchRecentJobs();
    } catch (error) {
      console.error('Failed to cancel job:', error);
    }
  }, [loadingState.jobId]);

  // Retry a failed job
  const retryJob = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(`/api/kdb/jobs/${jobId}/retry`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to retry job');
      }

      // The response is an SSE stream - get the new job ID from headers
      const newJobId = response.headers.get('X-New-Job-Id');
      if (newJobId) {
        localStorage.setItem(STORAGE_KEY, newJobId);
      }

      // Handle SSE stream similar to loadData
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      setLoadingState(prev => ({
        ...prev,
        isLoading: true,
        error: undefined,
        connectionStatus: 'connected',
      }));

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.job_id) {
                localStorage.setItem(STORAGE_KEY, data.job_id);
                setLoadingState(prev => ({ ...prev, jobId: data.job_id }));
              }

              if (data.type === 'progress') {
                setLoadingState(prev => ({
                  ...prev,
                  connectionStatus: 'connected',
                  progress: prev.progress.map(p =>
                    p.symbol === data.symbol
                      ? { ...p, status: data.status, message: data.message, rowsLoaded: data.rows_loaded }
                      : p
                  ),
                  overallProgress: data.overall_progress || prev.overallProgress,
                  currentPhase: data.phase || prev.currentPhase,
                }));
              } else if (data.type === 'complete') {
                localStorage.removeItem(STORAGE_KEY);
                setLoadingState(prev => ({
                  ...prev,
                  isLoading: false,
                  overallProgress: 100,
                  currentPhase: 'Complete!',
                  connectionStatus: 'disconnected',
                }));
                fetchRecentJobs();
              } else if (data.type === 'error') {
                localStorage.removeItem(STORAGE_KEY);
                setLoadingState(prev => ({
                  ...prev,
                  isLoading: false,
                  error: data.message,
                  connectionStatus: 'disconnected',
                }));
                fetchRecentJobs();
              }
            } catch (e) {
              console.warn('Failed to parse SSE data:', line, e);
            }
          }
        }
      }
    } catch (error) {
      setLoadingState(prev => ({
        ...prev,
        error: error instanceof Error ? error.message : 'Failed to retry job',
      }));
    }
  }, []);

  // Load public data (fundamentals, news, recommendations)
  const loadPublicData = useCallback(async () => {
    if (selectedSymbols.size === 0) {
      setPublicDataError('Please select at least one symbol');
      return;
    }
    if (publicDataTypes.size === 0) {
      setPublicDataError('Please select at least one data type');
      return;
    }

    const symbols = Array.from(selectedSymbols);
    const dataTypes = Array.from(publicDataTypes);

    setPublicDataLoading(true);
    setPublicDataProgress(0);
    setPublicDataPhase('Starting...');
    setPublicDataError(undefined);
    setPublicDataComplete(false);

    try {
      const response = await fetch('/api/kdb/load-public', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          symbols,
          data_types: dataTypes,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to load public data: ${response.statusText}`);
      }

      // Stream the progress
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.type === 'progress') {
                setPublicDataProgress(data.overall_progress || 0);
                setPublicDataPhase(data.phase || '');
              } else if (data.type === 'complete') {
                setPublicDataLoading(false);
                setPublicDataProgress(100);
                setPublicDataPhase('Complete!');
                setPublicDataComplete(true);
              } else if (data.type === 'error') {
                setPublicDataLoading(false);
                setPublicDataError(data.message);
              }
            } catch (e) {
              console.warn('Failed to parse SSE data:', line, e);
            }
          }
        }
      }
    } catch (error) {
      setPublicDataLoading(false);
      setPublicDataError(error instanceof Error ? error.message : 'Unknown error occurred');
    }
  }, [selectedSymbols, publicDataTypes]);

  const togglePublicDataType = useCallback((dataType: string) => {
    setPublicDataTypes(prev => {
      const next = new Set(prev);
      if (next.has(dataType)) {
        next.delete(dataType);
      } else {
        next.add(dataType);
      }
      return next;
    });
  }, []);

  const getStatusIcon = (status: LoadProgress['status']) => {
    switch (status) {
      case 'loading':
        return <Loader2 className="w-4 h-4 animate-spin text-nvidia-green" />;
      case 'complete':
        return <Check className="w-4 h-4 text-green-400" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-400" />;
      default:
        return <div className="w-4 h-4 rounded-full border-2 border-nvidia-gray-600" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Testing-Only Warning Banner */}
      <div className="flex items-start gap-3 p-4 bg-red-900/20 border border-red-700/50 rounded-xl">
        <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
        <div>
          <h3 className="font-medium text-red-500">Testing & Development Only</h3>
          <p className="text-sm text-red-400/90 mt-1">
            This data loader is for <strong className="text-red-400">testing and demonstration purposes only</strong>.
            It is designed to work with the deployment configuration included in this repository and{' '}
            <strong className="text-red-400">should not be used in production environments</strong>.
          </p>
          <div className="text-xs text-red-600 mt-2 space-y-1">
            <p className="font-medium">Important notes:</p>
            <ul className="list-disc list-inside ml-2 space-y-0.5">
              <li>Loading data will <strong>clear all existing KDB-X tables</strong></li>
              <li>Security checks are relaxed to allow INSERT operations</li>
              <li>Data is sourced from Yahoo Finance (daily) + synthetic intraday generation</li>
              <li>For production, use proper ETL pipelines and data governance</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Data Tables Info */}
      <div className="flex items-start gap-3 p-4 bg-nvidia-gray-800/50 border border-nvidia-gray-700 rounded-xl">
        <TrendingUp className="w-5 h-5 text-nvidia-green flex-shrink-0 mt-0.5" />
        <div>
          <h3 className="font-medium text-nvidia-gray-200">Tables Created</h3>
          <div className="text-xs text-nvidia-gray-400 mt-2 space-y-1">
            <p className="font-medium text-nvidia-gray-300 mb-1">Historical Data (required):</p>
            <ul className="list-disc list-inside ml-2 space-y-0.5">
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">daily</code> — Real OHLCV data from Yahoo Finance</li>
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">trade</code> — Synthetic tick trades based on daily data</li>
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">quote</code> — Synthetic bid/ask quotes based on daily data</li>
            </ul>
            <p className="font-medium text-nvidia-gray-300 mt-2 mb-1">Public Data (optional):</p>
            <ul className="list-disc list-inside ml-2 space-y-0.5">
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">fundamentals</code> — PE ratio, market cap, EPS, beta, etc.</li>
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">news</code> — Recent news articles with title, publisher, link</li>
              <li><code className="bg-nvidia-gray-700 px-1.5 py-0.5 rounded">recommendations</code> — Analyst ratings (firm, grade, action)</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Symbol Selection */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-nvidia-gray-700 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-nvidia-green" />
              </div>
              <div>
                <CardTitle>Stock Symbols</CardTitle>
                <CardDescription>Select symbols to load historical data for</CardDescription>
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={selectAll}
                disabled={loadingState.isLoading}
              >
                Select All
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearAll}
                disabled={loadingState.isLoading}
              >
                Clear All
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-5 gap-3">
            {DEFAULT_SYMBOLS.map(symbol => (
              <button
                key={symbol}
                onClick={() => toggleSymbol(symbol)}
                disabled={loadingState.isLoading}
                className={clsx(
                  'px-4 py-3 rounded-lg border-2 transition-all font-medium text-sm',
                  selectedSymbols.has(symbol)
                    ? 'border-nvidia-green bg-nvidia-green/10 text-nvidia-green'
                    : 'border-nvidia-gray-700 bg-nvidia-gray-800 text-nvidia-gray-400 hover:border-nvidia-gray-600',
                  loadingState.isLoading && 'opacity-50 cursor-not-allowed'
                )}
              >
                {symbol}
              </button>
            ))}
          </div>
          <p className="mt-3 text-sm text-nvidia-gray-500">
            {selectedSymbols.size} symbol{selectedSymbols.size !== 1 ? 's' : ''} selected
          </p>
        </CardContent>
      </Card>

      {/* Date Range */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-nvidia-gray-700 rounded-lg flex items-center justify-center">
              <Calendar className="w-5 h-5 text-nvidia-green" />
            </div>
            <div>
              <CardTitle>Date Range</CardTitle>
              <CardDescription>Select the time period for historical data</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-sm font-medium text-nvidia-gray-200 mb-1.5">
                Start Date
              </label>
              <input
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                disabled={loadingState.isLoading}
                className="input w-full"
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-nvidia-gray-200 mb-1.5">
                End Date
              </label>
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                disabled={loadingState.isLoading}
                className="input w-full"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Load Button & Progress */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-nvidia-gray-700 rounded-lg flex items-center justify-center">
                <Download className="w-5 h-5 text-nvidia-green" />
              </div>
              <div>
                <CardTitle>Load Data</CardTitle>
                <CardDescription>
                  {loadingState.isLoading
                    ? loadingState.currentPhase
                    : 'Fetch historical data from Yahoo Finance and load into KDB-X'}
                </CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {/* Connection status indicator */}
              {loadingState.isLoading && (
                <div className={clsx(
                  'flex items-center gap-1.5 px-2 py-1 rounded text-xs',
                  loadingState.connectionStatus === 'connected' && 'bg-green-900/20 text-green-400',
                  loadingState.connectionStatus === 'polling' && 'bg-yellow-900/20 text-yellow-400',
                  loadingState.connectionStatus === 'disconnected' && 'bg-red-900/20 text-red-400'
                )}>
                  {loadingState.connectionStatus === 'connected' ? (
                    <><Wifi className="w-3 h-3" /> Streaming</>
                  ) : loadingState.connectionStatus === 'polling' ? (
                    <><WifiOff className="w-3 h-3" /> Polling</>
                  ) : (
                    <><WifiOff className="w-3 h-3" /> Disconnected</>
                  )}
                </div>
              )}

              {/* Cancel button */}
              {loadingState.isLoading && loadingState.jobId && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={cancelJob}
                  leftIcon={<X className="w-4 h-4" />}
                  className="text-red-400 hover:bg-red-900/20"
                >
                  Cancel
                </Button>
              )}

              {/* Load button */}
              {!loadingState.isLoading && (
                <Button
                  onClick={loadData}
                  disabled={selectedSymbols.size === 0}
                  leftIcon={<Download className="w-4 h-4" />}
                >
                  Load Historical Data
                </Button>
              )}
            </div>
          </div>
        </CardHeader>

        {/* Progress bar */}
        {loadingState.isLoading && (
          <CardContent>
            <div className="mb-4">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-nvidia-gray-400">Overall Progress</span>
                <span className="text-nvidia-green">{Math.round(loadingState.overallProgress)}%</span>
              </div>
              <div className="h-2 bg-nvidia-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-nvidia-green transition-all duration-300"
                  style={{ width: `${loadingState.overallProgress}%` }}
                />
              </div>
            </div>

            {/* Per-symbol progress */}
            <div className="space-y-2">
              {loadingState.progress.map(item => (
                <div
                  key={item.symbol}
                  className={clsx(
                    'flex items-center gap-3 p-2 rounded-lg',
                    item.status === 'loading' && 'bg-nvidia-green/5',
                    item.status === 'complete' && 'bg-green-900/10',
                    item.status === 'error' && 'bg-red-900/10'
                  )}
                >
                  {getStatusIcon(item.status)}
                  <span className="font-medium text-white w-16">{item.symbol}</span>
                  <span className="text-sm text-nvidia-gray-400 flex-1">
                    {item.message || (item.status === 'pending' ? 'Waiting...' : '')}
                  </span>
                  {item.rowsLoaded !== undefined && (
                    <span className="text-sm text-nvidia-gray-500">
                      {item.rowsLoaded.toLocaleString()} rows
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        )}

        {/* Error message */}
        {loadingState.error && (
          <CardContent>
            <div className="flex items-center gap-2 p-3 bg-red-900/20 border border-red-800/50 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
              <span className="text-red-400 text-sm">{loadingState.error}</span>
            </div>
          </CardContent>
        )}

        {/* Success message */}
        {!loadingState.isLoading && loadingState.overallProgress === 100 && !loadingState.error && (
          <CardContent>
            <div className="flex items-center gap-2 p-3 bg-green-900/20 border border-green-800/50 rounded-lg">
              <Check className="w-5 h-5 text-green-400 flex-shrink-0" />
              <span className="text-green-400 text-sm">
                Historical data loaded successfully! The data is now available in KDB-X for queries.
              </span>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Public Data Loading Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-nvidia-gray-700 rounded-lg flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-nvidia-green" />
            </div>
            <div>
              <CardTitle>Public Data (Optional)</CardTitle>
              <CardDescription>Load additional data from Yahoo Finance for richer analysis</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Data type selection */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-nvidia-gray-200 mb-2">
              Select data types to load
            </label>
            <div className="flex gap-3">
              <button
                onClick={() => togglePublicDataType('fundamentals')}
                disabled={publicDataLoading || loadingState.isLoading}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all text-sm',
                  publicDataTypes.has('fundamentals')
                    ? 'border-nvidia-green bg-nvidia-green/10 text-nvidia-green'
                    : 'border-nvidia-gray-700 bg-nvidia-gray-800 text-nvidia-gray-400 hover:border-nvidia-gray-600',
                  (publicDataLoading || loadingState.isLoading) && 'opacity-50 cursor-not-allowed'
                )}
              >
                <BarChart3 className="w-4 h-4" />
                Fundamentals
              </button>
              <button
                onClick={() => togglePublicDataType('news')}
                disabled={publicDataLoading || loadingState.isLoading}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all text-sm',
                  publicDataTypes.has('news')
                    ? 'border-nvidia-green bg-nvidia-green/10 text-nvidia-green'
                    : 'border-nvidia-gray-700 bg-nvidia-gray-800 text-nvidia-gray-400 hover:border-nvidia-gray-600',
                  (publicDataLoading || loadingState.isLoading) && 'opacity-50 cursor-not-allowed'
                )}
              >
                <Newspaper className="w-4 h-4" />
                News
              </button>
              <button
                onClick={() => togglePublicDataType('recommendations')}
                disabled={publicDataLoading || loadingState.isLoading}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all text-sm',
                  publicDataTypes.has('recommendations')
                    ? 'border-nvidia-green bg-nvidia-green/10 text-nvidia-green'
                    : 'border-nvidia-gray-700 bg-nvidia-gray-800 text-nvidia-gray-400 hover:border-nvidia-gray-600',
                  (publicDataLoading || loadingState.isLoading) && 'opacity-50 cursor-not-allowed'
                )}
              >
                <ThumbsUp className="w-4 h-4" />
                Analyst Ratings
              </button>
            </div>
            <p className="mt-2 text-xs text-nvidia-gray-500">
              Uses symbols selected above. Creates: <code className="bg-nvidia-gray-700 px-1 rounded">fundamentals</code>, <code className="bg-nvidia-gray-700 px-1 rounded">news</code>, <code className="bg-nvidia-gray-700 px-1 rounded">recommendations</code> tables
            </p>
          </div>

          {/* Load button */}
          <div className="flex items-center justify-between">
            <div className="text-sm text-nvidia-gray-400">
              {publicDataLoading ? publicDataPhase : `${publicDataTypes.size} data type(s) selected`}
            </div>
            <Button
              onClick={loadPublicData}
              disabled={selectedSymbols.size === 0 || publicDataTypes.size === 0 || publicDataLoading || loadingState.isLoading}
              leftIcon={publicDataLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            >
              {publicDataLoading ? 'Loading...' : 'Load Public Data'}
            </Button>
          </div>

          {/* Progress bar */}
          {publicDataLoading && (
            <div className="mt-4">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-nvidia-gray-400">Progress</span>
                <span className="text-nvidia-green">{Math.round(publicDataProgress)}%</span>
              </div>
              <div className="h-2 bg-nvidia-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-nvidia-green transition-all duration-300"
                  style={{ width: `${publicDataProgress}%` }}
                />
              </div>
            </div>
          )}

          {/* Error message */}
          {publicDataError && (
            <div className="mt-4 flex items-center gap-2 p-3 bg-red-900/20 border border-red-800/50 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
              <span className="text-red-400 text-sm">{publicDataError}</span>
            </div>
          )}

          {/* Success message */}
          {publicDataComplete && !publicDataLoading && !publicDataError && (
            <div className="mt-4 flex items-center gap-2 p-3 bg-green-900/20 border border-green-800/50 rounded-lg">
              <Check className="w-5 h-5 text-green-400 flex-shrink-0" />
              <span className="text-green-400 text-sm">
                Public data loaded! You can now ask about fundamentals, news, and analyst ratings in KDB Chat.
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Job History */}
      {recentJobs.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-nvidia-gray-700 rounded-lg flex items-center justify-center">
                  <RefreshCw className="w-5 h-5 text-nvidia-green" />
                </div>
                <div>
                  <CardTitle>Recent Jobs</CardTitle>
                  <CardDescription>History of data loading operations</CardDescription>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={fetchRecentJobs}
                leftIcon={<RefreshCw className="w-4 h-4" />}
              >
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recentJobs.map(job => (
                <div
                  key={job.job_id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-nvidia-gray-800/50"
                >
                  {/* Status badge */}
                  <div className={clsx(
                    'px-2 py-0.5 rounded text-xs font-medium',
                    job.status === 'completed' && 'bg-green-900/30 text-green-400',
                    job.status === 'running' && 'bg-nvidia-green/20 text-nvidia-green',
                    job.status === 'failed' && 'bg-red-900/30 text-red-400',
                    job.status === 'cancelled' && 'bg-yellow-900/30 text-yellow-400'
                  )}>
                    {job.status}
                  </div>

                  {/* Symbols */}
                  <span className="text-sm text-nvidia-gray-300 flex-1">
                    {job.symbols.slice(0, 3).join(', ')}
                    {job.symbols.length > 3 && ` +${job.symbols.length - 3} more`}
                  </span>

                  {/* Progress */}
                  <span className="text-sm text-nvidia-gray-500">
                    {job.overall_progress}%
                  </span>

                  {/* Rows loaded */}
                  <span className="text-sm text-nvidia-gray-500">
                    {job.rows_loaded.toLocaleString()} rows
                  </span>

                  {/* Time */}
                  <span className="text-xs text-nvidia-gray-600 w-24 text-right">
                    {new Date(job.start_time).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </span>

                  {/* Retry button for failed/cancelled jobs */}
                  {(job.status === 'failed' || job.status === 'cancelled') && !loadingState.isLoading && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => retryJob(job.job_id)}
                      leftIcon={<RefreshCw className="w-3 h-3" />}
                      className="text-nvidia-green"
                    >
                      Retry
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
