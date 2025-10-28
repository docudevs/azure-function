# DocuDevs Azure Function – Developer Guide

This document is for contributors who maintain or extend the Azure Function integration for DocuDevs. It captures repository structure, local tooling, and release tasks so external-facing docs can stay focused on adopters.

## Repository layout

- `function_app.py` – Azure Functions entrypoints (`handle_config_update`, `handle_document_ingest`, `handle_manual_request`).
- `docudevs_function/` – Shared implementation: configuration resolution, storage adapters, DocuDevs processor workflows, and bootstrap helpers.
- `tests/` – Pytest suite covering configuration inheritance and processing pipeline logic.
- `samples/` – Example configuration payloads for exercising the function locally.
- `azuredeploy.json` / `azuredeploy.parameters.json` – ARM template used by the Deploy to Azure button and CI/CD pipelines.
- `AGENTS.md` – Deep-dive architecture notes gathered for AI assistant usage.

## Architecture highlights

The function app is event-driven: Event Grid blob notifications trigger the functions defined in `function_app.py`. Helper modules in `docudevs_function/` are instantiated via cached bootstrap factories (`docudevs_function/bootstrap.py`) to avoid recreating service clients. Configuration is folder-scoped in Blob Storage and resolved via `ConfigurationStore`, which merges `params.json`, `schema.json`, and `metadata.json` across the folder hierarchy.

Refer to `AGENTS.md` for end-to-end processing flow, storage conventions, and testing doubles that the suite relies on.

## Local development workflow

1. Install [uv](https://github.com/astral-sh/uv) if it is not already available.
2. Install dependencies into the managed virtual environment:

   ```bash
   uv sync --project .
   ```

3. Launch the Azure Functions host (requires Azure Functions Core Tools):

   ```bash
   func start
   ```

   `local.settings.json` ships configured for the Azurite emulator via `UseDevelopmentStorage=true`.

4. Run the test suite:

   ```bash
   uv run --project . pytest
   ```

## Packaging and publishing

- Generate a deployment-ready `requirements.txt` when packaging for Azure:

  ```bash
  uv export --project . --no-hashes > requirements.txt
  ```

- The provided ARM template deploys a Flex Consumption Function App with system-assigned managed identity, wiring up Event Grid subscriptions and storage permissions. Update `azuredeploy.parameters.json` or supply custom parameters through your pipeline as needed.

## Coding standards and notes

- Prefer the cached factories (`get_configuration_store`, `get_document_processor`) over manual instantiation to retain reuse.
- Tests monkeypatch `_import_doc_sdk()` to avoid real DocuDevs calls; add behaviors to the fakes in `tests/` when introducing new functionality.
- Use the provided loggers instead of `print` for operational visibility.

Before merging changes, ensure tests pass and review storage permission implications for any new features.
