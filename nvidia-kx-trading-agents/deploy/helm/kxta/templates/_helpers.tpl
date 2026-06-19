{{/*
Expand the name of the chart.
*/}}
{{- define "kxta.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "kxta.fullname" -}}
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
{{- define "kxta.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Generate DockerConfigJson for image pull secrets
*/}}
{{- define "createImagePullSecret" }}
{{- printf "{\"auths\":{\"%s\":{\"auth\":\"%s\"}}}" .Values.imagePullSecret.registry (printf "%s:%s" .Values.imagePullSecret.username .Values.imagePullSecret.password | b64enc) | b64enc }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kxta.labels" -}}
helm.sh/chart: {{ include "kxta.chart" . }}
{{ include "kxta.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kxta.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kxta.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "kxta.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "kxta.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create secret to access NGC Api
*/}}
{{- define "ngcApiSecret" }}
{{- printf "%s" .Values.ngcApiSecret.password | b64enc }}
{{- end }}

{{- define "tavilyApiSecret" }}
{{- printf "%s" .Values.tavilyApiSecret.password | b64enc }}
{{- end }}

{{/*
Create secret for KDB+ API Key
*/}}
{{- define "kdbApiSecret" }}
{{- printf "%s" .Values.kdbApiSecret.password | b64enc }}
{{- end }}

{{/*
Source agent API key helpers
*/}}
{{- define "firecrawlApiSecret" }}
{{- printf "%s" .Values.firecrawlApiSecret.password | b64enc }}
{{- end }}

{{- define "alphavantageApiSecret" }}
{{- printf "%s" .Values.alphavantageApiSecret.password | b64enc }}
{{- end }}

{{- define "fredApiSecret" }}
{{- printf "%s" .Values.fredApiSecret.password | b64enc }}
{{- end }}

{{/*
Generate DockerConfigJson for image pull secrets (KX Portal)
*/}}
{{- define "imagePullSecret" }}
{{- printf "{\"auths\":{\"%s\":{\"auth\":\"%s\"}}}" .Values.imagePullSecret.registry (printf "%s:%s" .Values.imagePullSecret.username .Values.imagePullSecret.password | b64enc) | b64enc }}
{{- end }}

{{/*
Generate DockerConfigJson for NGC image pull secrets
*/}}
{{- define "ngcImagePullSecret" }}
{{- printf "{\"auths\":{\"%s\":{\"auth\":\"%s\"}}}" .Values.ngcImagePullSecret.registry (printf "%s:%s" .Values.ngcImagePullSecret.username .Values.ngcImagePullSecret.password | b64enc) | b64enc }}
{{- end }}
