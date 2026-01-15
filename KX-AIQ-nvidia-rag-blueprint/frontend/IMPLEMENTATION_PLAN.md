# Custom AIRA Frontend - Implementation Plan

## Overview
Build a React + TypeScript frontend that replicates the AIRA (AI Research Assistant) UI, communicating with the existing backend via REST API + Server-Sent Events (SSE).

## Project Location
`/frontend/` (new directory in project root)

## Technology Stack
- **React 18** with TypeScript
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **Zustand** - State management
- **React Query** - Server state/caching
- **React Markdown** - Report rendering

---

## Project Structure

```
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts           # Axios/fetch setup
│   │   ├── sse.ts              # SSE streaming utilities
│   │   ├── queries.ts          # /generate_query/stream
│   │   ├── summary.ts          # /generate_summary/stream
│   │   ├── artifactQa.ts       # /artifact_qa
│   │   └── collections.ts      # /default_collections, /v1/collections
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── Layout.tsx
│   │   ├── collections/
│   │   │   ├── CollectionSelector.tsx
│   │   │   └── CollectionCard.tsx
│   │   ├── queries/
│   │   │   ├── QueryGenerator.tsx
│   │   │   ├── QueryList.tsx
│   │   │   ├── QueryCard.tsx
│   │   │   └── QueryEditor.tsx
│   │   ├── report/
│   │   │   ├── ReportGenerator.tsx
│   │   │   ├── ReportViewer.tsx
│   │   │   ├── ReportProgress.tsx
│   │   │   └── CitationList.tsx
│   │   ├── qa/
│   │   │   ├── QAPanel.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   └── RewriteDialog.tsx
│   │   └── common/
│   │       ├── Button.tsx
│   │       ├── Input.tsx
│   │       ├── Card.tsx
│   │       ├── LoadingSpinner.tsx
│   │       └── StreamingText.tsx
│   ├── hooks/
│   │   ├── useSSE.ts           # SSE streaming hook
│   │   ├── useQueryGeneration.ts
│   │   ├── useReportGeneration.ts
│   │   └── useArtifactQA.ts
│   ├── store/
│   │   ├── workflowStore.ts    # Main workflow state
│   │   └── uiStore.ts          # UI state (modals, etc.)
│   ├── types/
│   │   └── api.ts              # TypeScript interfaces
│   ├── pages/
│   │   ├── HomePage.tsx
│   │   └── ResearchPage.tsx
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── public/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
└── Dockerfile
```

---

## TypeScript Types (from schema.py)

```typescript
// types/api.ts

interface GeneratedQuery {
  query: string;
  report_section: string;
  rationale: string;
}

interface GenerateQueryInput {
  topic: string;
  report_organization: string;
  num_queries?: number;
  llm_name: string;
}

interface GenerateSummaryInput {
  topic: string;
  report_organization: string;
  queries: GeneratedQuery[];
  search_web: boolean;
  rag_collection: string;
  reflection_count?: number;
  llm_name: string;
}

interface ArtifactQAInput {
  artifact: string;
  question: string;
  chat_history?: string[];
  use_internet?: boolean;
  rewrite_mode?: 'entire' | null;
  additional_context?: string;
  rag_collection: string;
}

interface ArtifactQAOutput {
  assistant_reply: string;
  updated_artifact?: string;
}

// SSE intermediate step format
interface IntermediateStep {
  step: string;  // 'generating_questions' | 'running_summary' | 'reflect_on_summary' | 'final_report'
  content?: string;
  queries?: GeneratedQuery[];
}
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate_query/stream` | POST | Generate queries (SSE) |
| `/generate_summary/stream` | POST | Generate report (SSE) |
| `/artifact_qa` | POST | Q&A / rewrite artifact |
| `/default_collections` | GET | Get demo collections |
| `/v1/collections` | GET | List RAG collections |

---

## Implementation Steps

### Phase 1: Project Setup
1. Create Vite + React + TypeScript project
2. Configure Tailwind CSS
3. Set up folder structure
4. Add dependencies (zustand, react-markdown, etc.)
5. Create Dockerfile

### Phase 2: Core Infrastructure
1. **API Client** (`api/client.ts`)
   - Axios instance with base URL config
   - Error handling interceptors

2. **SSE Utilities** (`api/sse.ts`)
   - `createSSEStream()` function
   - Parse `intermediate_step` JSON from stream
   - Handle connection errors/reconnect

3. **Types** (`types/api.ts`)
   - All TypeScript interfaces from schema.py

### Phase 3: State Management
1. **Workflow Store** (`store/workflowStore.ts`)
   ```typescript
   interface WorkflowState {
     stage: 'idle' | 'queries' | 'report' | 'qa';
     topic: string;
     reportOrganization: string;
     collection: string;
     queries: GeneratedQuery[];
     report: string;
     citations: string;
     isStreaming: boolean;
     streamingContent: string;
   }
   ```

### Phase 4: Components

**Stage 1 - Query Generation:**
- `QueryGenerator.tsx` - Form for topic + report structure
- `QueryList.tsx` - Display/edit generated queries
- `QueryCard.tsx` - Individual query with edit capability

**Stage 2 - Report Generation:**
- `ReportGenerator.tsx` - Start report generation
- `ReportProgress.tsx` - Show streaming progress (web_research, summarize, reflect)
- `ReportViewer.tsx` - Render markdown report
- `CitationList.tsx` - Display citations

**Stage 3 - Q&A:**
- `QAPanel.tsx` - Chat interface
- `ChatMessage.tsx` - Message bubble
- `RewriteDialog.tsx` - Rewrite instructions modal

### Phase 5: Pages & Workflow
1. `HomePage.tsx` - Collection selection
2. `ResearchPage.tsx` - Multi-stage workflow with:
   - Step indicator (1: Queries → 2: Report → 3: Q&A)
   - Conditional rendering based on stage
   - Navigation between stages

### Phase 6: Styling & Polish
1. Responsive design
2. Loading states
3. Error handling UI
4. Animations/transitions

---

## Key SSE Streaming Pattern

```typescript
// hooks/useSSE.ts
export function useSSEStream<T>(url: string, body: object) {
  const [data, setData] = useState<T | null>(null);
  const [streaming, setStreaming] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const start = async () => {
    setIsLoading(true);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;

      const text = decoder.decode(value);
      // Parse SSE format: data: {...}\n\n
      const lines = text.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const json = JSON.parse(line.slice(6));
          if (json.intermediate_step) {
            setStreaming(json.intermediate_step);
          }
          if (json.queries || json.final_report) {
            setData(json as T);
          }
        }
      }
    }
    setIsLoading(false);
  };

  return { data, streaming, isLoading, start };
}
```

---

## Environment Variables

```env
VITE_API_URL=http://localhost:3838
```

---

## Dockerfile

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

---

## Critical Backend Files (Reference)

- `aira/src/aiq_aira/schema.py` - Type definitions
- `aira/src/aiq_aira/functions/generate_queries.py` - Query SSE format
- `aira/src/aiq_aira/functions/generate_summary.py` - Report SSE format
- `docs/rest-api.md` - API documentation

---

## Estimated Files: ~35 files
## Estimated LOC: ~3,000-4,000 lines
