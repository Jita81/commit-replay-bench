{{/*
Chart name / fullname / labels (standard helm conventions).
*/}}
{{- define "crb.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "crb.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "crb.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "crb.labels" -}}
helm.sh/chart: {{ include "crb.chart" . }}
app.kubernetes.io/name: {{ include "crb.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: crb
{{- end -}}

{{/* Selector labels shared by every crb pod (api, worker, migrate, postgres). */}}
{{- define "crb.selectorLabels" -}}
app.kubernetes.io/name: {{ include "crb.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "crb.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "crb.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Image reference: digest wins over tag; tag defaults to appVersion. */}}
{{- define "crb.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}
{{- end -}}

{{- define "crb.postgresHost" -}}
{{- printf "%s-postgres" (include "crb.fullname" .) -}}
{{- end -}}

{{/*
Environment shared by api / worker / migrate: ConfigMap + the operator's Secret, plus the
fixed container paths. Secrets are referenced, never rendered.
*/}}
{{- define "crb.envFrom" -}}
- configMapRef:
    name: {{ include "crb.fullname" . }}
- secretRef:
    name: {{ required "existingSecret (with CRB_SECRET_KEY and CRB_DATABASE_URL) is required" .Values.existingSecret }}
{{- end -}}

{{- define "crb.commonEnv" -}}
- name: CRB_HOME
  value: /srv/crb
- name: CRB_BIND_HOST
  value: "0.0.0.0"
- name: CRB_BIND_PORT
  value: "8000"
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Writable scratch volumes required by readOnlyRootFilesystem. */}}
{{- define "crb.scratchVolumes" -}}
- name: tmp
  emptyDir:
    sizeLimit: {{ .Values.tmp.sizeLimit }}
- name: home
  emptyDir:
    sizeLimit: {{ .Values.home.sizeLimit }}
{{- end -}}

{{- define "crb.scratchMounts" -}}
- name: tmp
  mountPath: /tmp
- name: home
  mountPath: /home/crb
{{- end -}}
