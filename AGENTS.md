# DocuDevs Azure Function – AI Assistant Guide

This is a serverless function that uses DocuDevs api SaaS product to transform documents (unstructured data, pdf / word etc) from azure-storage-account into structured json data.
It uses DocuDevs python sdk client to perform the transformation. 
The system is fully configurable by adding certain config files into the azure-storage-account, from where also the documents are picked for transformation.

## Core Architecture
- Event Grid–driven Azure Functions live in `function_app.py`; `handle_config_update` rebuilds cached configuration and `handle_document_ingest` orchestrates DocuDevs processing.
- Entrypoints rely on bootstrap singletons (`docudevs_function/bootstrap.py`) that cache settings, blob clients, and service objects via `functools.lru_cache`—reuse helpers instead of rehydrating dependencies.
- Configuration derives from environment variables (see `Settings.from_environment`) with `IN_CONTAINER_NAME`/`OUT_CONTAINER_NAME` defaults of `in`/`out` and requires `DOCUDEVS_API_KEY` when invoking DocuDevs.

## Storage & Configuration Conventions
- Config files are folder-scoped blobs under the input container: `params.json` (required), optional `schema.json`/`metadata.json`, and generated `config.json` containing a consolidated snapshot.
- `ConfigurationStore` (in `docudevs_function/configuration.py`) normalizes folders using POSIX paths, walks parent folders for fallback inheritance, and caches `FolderConfiguration` objects—call `invalidate` before relying on fresh data.
- Deleting any config asset triggers `_delete_consolidated_config`, which removes the synthesized `config.json`; writes honor blob ETags to avoid overwriting concurrent updates.

## Document Processing Flow
- `DocumentProcessor.process_blob` fetches the source blob, resolves configuration, uploads the document via `DocuDevsClient.upload_document`, then issues `process_document` using a command built from merged params/schema metadata.
- MIME type precedence: explicit `mimeType` in params, then blob content type, finally `application/octet-stream`.
- Success responses are written back to the output container as `<blob>.json`; failures serialize `{status:"error", message}` to `<blob>.error.json` to aid replay diagnostics.

## External Integrations
- Blob access uses `azure.storage.blob.BlobServiceClient`; prefer providing `STORAGE_CONNECTION_STRING` locally, otherwise supply `STORAGE_ACCOUNT_URL` and rely on `DefaultAzureCredential` (no interactive prompt available in production).
- DocuDevs SDK types (`UploadDocumentBody`, `UploadCommand`, `File`, `UNSET`) are lazily imported via `_import_doc_sdk()` to simplify monkeypatching in tests.

## Testing & Tooling
- Pytest suite lives under `tests/`; async tests use `pytest.mark.asyncio` and monkeypatch `_import_doc_sdk` to avoid real DocuDevs calls.
- Local commands (assume `uv`): `uv sync --project .` to install, `func start` to run the host, `uv run --project . pytest` for tests, and `uv export --project . --no-hashes > requirements.txt` before packaging.
- Fake storage/doc clients in tests mimic blob behaviors; when adding new behaviors, extend these doubles to keep coverage fast.

## Implementation Tips
- Reuse `get_configuration_store()` and `get_document_processor()` instead of instantiating directly; they encapsulate caching and dependency wiring.
- Respect the `CONFIG_FILES` guard in `function_app.py` when introducing new blob-triggered behavior to avoid processing configuration artifacts as documents.
- When persisting outputs, pass stable ETags or empty strings—`AzureBlobStorage.put_object` falls back to unconditional upload on conflict and auto-creates missing containers.
- Loggers are already defined (`LOGGER = logging.getLogger(__name__)`); prefer `LOGGER` over `print` for operational visibility.
