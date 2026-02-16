# Dataset Federation Readiness

## Ziel
Vorbereitung der lokalen Projekt-/Global-Datenbanken auf ein spaeteres Server-Feature, das Datensaetze mehrerer Nutzer zu einem Gesamtdatensatz zusammenfuehrt.

## Was bisher gefehlt hat
Vor diesem Pass fehlten vor allem diese Eintraege/Strukturen:

1. Installation-/Mandanten-Provenienz
- Kein stabiler `installation_id` / `anonymous_user_id` / Namespace in der DB.
- Folge: Kollisionen und unklare Herkunft bei serverseitiger Zusammenfuehrung.

2. Consent-/Upload-Status
- Kein persistenter Upload-Freigabezustand inkl. Versionierung der Zustimmung.

3. Incremental Sync Cursor
- Keine Watermarks/Cursor pro Datenstrom fuer delta-basierte Uebertragung.

4. Export-Job-Telemetrie
- Kein Job-Log fuer Upload-Batches (Status, Hash, Bytes, Fehler).

5. Delete-Replikation
- Loeschungen (z. B. Run-Cleanup) wurden nicht als Tombstones persistiert.
- Folge: Server koennte geloeschte Datensaetze nicht sauber nachvollziehen.

## In diesem Pass additiv eingefuehrt
In `app/sql_dataset_store.py` (Schema `2.4`):

1. `federation_profile`
- `installation_id` (PK)
- `anonymous_user_id`
- `dataset_namespace`
- `allow_upload`
- `consent_scope`, `consent_version`, `consent_updated_at`
- `created_at`, `updated_at`
- Bootstrap erfolgt automatisch bei DB-Init.

2. `federation_sync_state`
- `stream_name` (PK)
- `last_cursor`, `last_synced_at`, `updated_at`

3. `federation_export_jobs`
- `export_id` (PK)
- `installation_id`, `status`, `schema_version`
- `item_counts_json`, `payload_sha256`, `payload_bytes`
- `error_summary`, `created_at`, `finished_at`

4. `federation_tombstones`
- `tombstone_id` (PK)
- `entity_type`, `entity_id`, `reason`, `deleted_at`, `uploaded_at`
- Bei Run-Loeschung (`cleanup_unpinned_runs`) werden nun Tombstones geschrieben.

## Neue API-Methoden (Store)
- `load_federation_profile()`
- `update_federation_profile(...)`
- `update_federation_sync_state(...)`
- `record_federation_export_job(...)`

## Was weiterhin spaeter folgt (bewusst noch nicht implementiert)
1. Transport-/Server-Client (Auth, Retry, Backoff, Conflict-Handling).
2. Serverseitiges Mapping/ETL auf Global-Schema.
3. Datenminimierung/PII-Policy und Opt-in UX in GUI.
4. Feld-level Schema-Contracts fuer versionierte API-Uploads.

## Empfehlung fuer naechste Version
- Upload nur aus explizit gepinnten Runs oder freigegebenen Batches.
- Delta-Upload ueber `federation_sync_state` mit idempotenten `export_id` Jobs.
- Tombstone-Replay zwingend aktivieren, bevor Server-Merge produktiv geht.
