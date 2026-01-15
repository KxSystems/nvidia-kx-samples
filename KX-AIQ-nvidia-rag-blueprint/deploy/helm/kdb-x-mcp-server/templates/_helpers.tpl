{{/*
Expand the name of the chart.
*/}}
{{- define "kdb-x-mcp-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "kdb-x-mcp-server.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "kdb-x-mcp-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kdb-x-mcp-server.labels" -}}
helm.sh/chart: {{ include "kdb-x-mcp-server.chart" . }}
{{ include "kdb-x-mcp-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kdb-x-mcp-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kdb-x-mcp-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "kdb-x-mcp-server.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "kdb-x-mcp-server.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the database secret name
*/}}
{{- define "kdb-x-mcp-server.dbSecretName" -}}
{{- if .Values.dbSecret.existingSecret }}
{{- .Values.dbSecret.existingSecret }}
{{- else }}
{{- .Values.dbSecret.name }}
{{- end }}
{{- end }}

{{/*
Get the TLS secret name
*/}}
{{- define "kdb-x-mcp-server.tlsSecretName" -}}
{{- .Values.tlsSecret.name }}
{{- end }}

{{/*
Get the OpenAI secret name
*/}}
{{- define "kdb-x-mcp-server.openaiSecretName" -}}
{{- .Values.openaiSecret.name }}
{{- end }}

{{/*
Get the MCP endpoint URL based on mode
*/}}
{{- define "kdb-x-mcp-server.mcpEndpoint" -}}
{{- if eq .Values.mode "internal" }}
{{- printf "http://%s.%s.svc.cluster.local:%v/mcp" (include "kdb-x-mcp-server.fullname" .) .Release.Namespace .Values.service.port }}
{{- else }}
{{- .Values.external.endpoint }}
{{- end }}
{{- end }}

{{/*
Get the external API secret name
*/}}
{{- define "kdb-x-mcp-server.externalApiSecretName" -}}
{{- printf "%s-external-api" (include "kdb-x-mcp-server.fullname" .) }}
{{- end }}
