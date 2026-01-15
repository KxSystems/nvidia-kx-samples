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

import { FileText, ArrowLeft, MessageSquare } from 'lucide-react';
import { Button, Card } from '../common';
import { ReportViewer } from './ReportViewer';
import { ReportProgress } from './ReportProgress';
import { CitationList } from './CitationList';
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
    citations,
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
          />
          <div className="mt-6 flex justify-end">
            <Button variant="secondary" onClick={cancel}>
              Cancel Generation
            </Button>
          </div>
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
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
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
          <ReportViewer content={report} />
        </Card>

        {citations && <CitationList citations={citations} />}
      </div>
    );
  }

  // Initial state - prompt to generate
  return (
    <Card className="text-center py-12">
      <FileText className="w-16 h-16 text-nvidia-gray-600 mx-auto mb-4" />
      <h2 className="text-xl font-semibold text-white mb-2">
        Ready to Generate Report
      </h2>
      <p className="text-nvidia-gray-400 mb-6 max-w-md mx-auto">
        Your queries are ready. Click below to start generating your comprehensive research report.
      </p>
      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 max-w-md mx-auto">
          {error}
        </div>
      )}
      <div className="flex justify-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          Edit Queries
        </Button>
        <Button onClick={handleStartGeneration}>
          Generate Report
        </Button>
      </div>
    </Card>
  );
}
