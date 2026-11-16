{{/*
IncidentPilot chart helpers (O2).
*/}}
{{- define "incidentpilot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "incidentpilot.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "incidentpilot.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "incidentpilot.labels" -}}
app.kubernetes.io/name: {{ include "incidentpilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- range $k, $v := .Values.global.labels }}
{{ $k }}: {{ $v | quote }}
{{- end }}
incidentpilot.environment: {{ .Values.global.environment | quote }}
{{- end -}}

{{- define "incidentpilot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "incidentpilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
incidentpilot.io/privilege-class: {{ .component }}
{{- end -}}

{{- define "incidentpilot.image" -}}
{{- printf "%s/%s:%s" .root.Values.global.imageRegistry .image.repository .image.tag -}}
{{- end -}}

{{- define "incidentpilot.componentEnv" -}}
- name: INCIDENTPILOT_ENVIRONMENT
  value: {{ .root.Values.global.environment | quote }}
- name: LOG_LEVEL
  value: {{ .root.Values.config.logLevel | quote }}
- name: TEMPORAL_HOST
  value: {{ .root.Values.config.temporalHost | quote }}
- name: DATABASE_SECRET_NAME
  value: {{ .root.Values.config.databaseSecretName | quote }}
{{- if .root.Values.config.s3Endpoint }}
- name: S3_ENDPOINT
  value: {{ .root.Values.config.s3Endpoint | quote }}
{{- end }}
{{- range $k, $v := .extra }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
