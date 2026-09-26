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
- name: CRB_SECRETS_DIR
  value: {{ include "crb.secretsStore.dir" . }}
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


{{/*
The secrets store (CRB_SECRETS_DIR). The api WRITES it (Settings → Claude Code login, the
tracker token) and checks it at submit; the worker READS it at build time. Both pods include
these helpers, so they mount ONE claim at one path: separate volumes let a token pass the
api's check and fail every build (docs/PREVENTION.md P-043, tests/test_deploy_secrets_store.py).
The store is a subdirectory of the mount: the volume root carries the fsGroup's group bits,
and the store refuses a group-accessible directory; the first write creates it 0700.
*/}}
{{- define "crb.secretsStore.dir" -}}
/srv/crb-secrets/store
{{- end -}}

{{- define "crb.secretsStore.claim" -}}
{{- default (printf "%s-secrets" (include "crb.fullname" .)) .Values.secretsStore.existingClaim -}}
{{- end -}}

{{- define "crb.secretsStore.mount" -}}
- name: secrets-store
  mountPath: /srv/crb-secrets
{{- end -}}

{{- define "crb.secretsStore.volume" -}}
{{- if not (has .Values.secretsStore.accessMode (list "ReadWriteOnce" "ReadWriteMany")) }}
{{- fail (printf "secretsStore.accessMode must be ReadWriteOnce | ReadWriteMany (got %q): the api and the worker both mount the store" .Values.secretsStore.accessMode) }}
{{- end -}}
- name: secrets-store
  persistentVolumeClaim:
    claimName: {{ include "crb.secretsStore.claim" . }}
{{- end -}}

{{/* The pod label the node pin selects: every pod that mounts the store carries it. */}}
{{- define "crb.secretsStore.podLabel" -}}
crb.dev/secrets-store: shared
{{- end -}}

{{/*
A pod's affinity: the operator's (api.affinity / worker.affinity), plus — for a
ReadWriteOnce store, which attaches to one node — a required pod affinity that puts every
pod carrying the store label on the node of the first one scheduled. Call with
(dict "root" $ "affinity" .Values.<component>.affinity).
*/}}
{{- define "crb.secretsStore.affinity" -}}
{{- $root := .root -}}
{{- $aff := deepCopy (.affinity | default dict) -}}
{{- if eq $root.Values.secretsStore.accessMode "ReadWriteOnce" -}}
{{- $match := merge (include "crb.selectorLabels" $root | fromYaml) (include "crb.secretsStore.podLabel" $root | fromYaml) -}}
{{- $term := dict "labelSelector" (dict "matchLabels" $match) "topologyKey" "kubernetes.io/hostname" -}}
{{- $pa := deepCopy (get $aff "podAffinity" | default dict) -}}
{{- $req := get $pa "requiredDuringSchedulingIgnoredDuringExecution" | default list -}}
{{- $_ := set $pa "requiredDuringSchedulingIgnoredDuringExecution" (append $req $term) -}}
{{- $_ := set $aff "podAffinity" $pa -}}
{{- end -}}
{{- if $aff -}}
affinity:
  {{- toYaml $aff | nindent 2 }}
{{- end -}}
{{- end -}}
