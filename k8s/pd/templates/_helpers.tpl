{{- define "pd.settingsName" -}}
pd-settings-{{ toJson .Values.settings | sha256sum | trunc 10 }}
{{- end -}}
