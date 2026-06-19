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

import { FileText, ArrowLeft, MessageSquare, AlertCircle, RefreshCw } from 'lucide-react';
import { Button, Card } from '../common';
import { ReportViewer } from './ReportViewer';
import { ReportProgress } from './ReportProgress';
import { AgentActivity } from './AgentActivity';
import { useWorkflowStore } from '../../store/workflowStore';
import { useReportGeneration } from '../../hooks/useReportGeneration';

interface ReportGeneratorProps {
  onBack: () => void;
  onStartQA: () => void;
}

export function ReportGenerator({ onBack, onStartQA }: ReportGeneratorProps) {
  const {
    report,
    isStreaming,
    currentStep,
    streamingContent,
    error,
    agentEvents,
  } = useWorkflowStore();

  const { generate, cancel } = useReportGeneration();

  const handleStartGeneration = () => {
    generate({ reflectionCount: 1 });
  };

  // Show progress while generating
  if (isStreaming) {
    return (
      <div className="space-y-6">
        <Card>
          <ReportProgress
            currentStep={currentStep}
            streamingContent={streamingContent}
            onCancel={cancel}
          />
        </Card>

        {/* Agent Activity Panel */}
        <AgentActivity events={agentEvents} isStreaming={isStreaming} />
      </div>
    );
  }

  // Show report if complete
  if (report) {
    return (
      <div className="space-y-6">
        {/* Show completed progress steps - clickable to see details */}
        <Card>
          <ReportProgress
            currentStep=""
            streamingContent=""
          />
        </Card>

        {/* Agent Activity Panel - collapsed by default after completion */}
        {agentEvents.length > 0 && (
          <AgentActivity events={agentEvents} isStreaming={false} />
        )}

        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-nvidia-gray-50 flex items-center gap-2">
            <FileText className="w-5 h-5 text-nvidia-green" />
            Research Report
          </h2>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onBack} leftIcon={<ArrowLeft className="w-4 h-4" />}>
              Back to Queries
            </Button>
            <Button onClick={onStartQA} leftIcon={<MessageSquare className="w-4 h-4" />}>
              Ask Questions
            </Button>
          </div>
        </div>

        <Card>
          {/* ReportViewer renders the sources table inline from the report's own
              tail, so no separate citations card is needed. */}
          <ReportViewer content={report} />
        </Card>
      </div>
    );
  }

  // Initial state — prompt to generate; doubles as the failed state with retry.
  return (
    <Card className="text-center py-12">
      {error ? (
        <AlertCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
      ) : (
        <FileText className="w-16 h-16 text-nvidia-gray-500 mx-auto mb-4" />
      )}
      <h2 className="text-xl font-semibold text-nvidia-gray-50 mb-2">
        {error ? 'Report Generation Failed' : 'Ready to Generate Report'}
      </h2>
      <p className="text-nvidia-gray-400 mb-6 max-w-md mx-auto">
        {error
          ? 'Something went wrong while generating the report. Your research plan is unchanged — you can retry, or go back and adjust the queries.'
          : 'Your queries are ready. Click below to start generating your comprehensive research report.'}
      </p>
      {error && (
        <div
          className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-600 max-w-md mx-auto text-left"
          role="alert"
        >
          {error}
        </div>
      )}
      <div className="flex justify-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          Edit Queries
        </Button>
        <Button
          onClick={handleStartGeneration}
          leftIcon={error ? <RefreshCw className="w-4 h-4" /> : undefined}
        >
          {error ? 'Retry Report' : 'Generate Report'}
        </Button>
      </div>
    </Card>
  );
}
