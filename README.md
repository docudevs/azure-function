# DocuDevs Serverless Function

Azure Function app that reacts to Event Grid blob notifications, maintains DocuDevs configuration cache, and processes incoming documents with the DocuDevs SDK.

## Structure

- `function_app.py` – Azure Functions entrypoints (`handle_config_update`, `handle_document_ingest`).
- `docudevs_function/` – Shared implementation (configuration resolution, storage adapter, DocuDevs processing, bootstrap helpers).
- `tests/` – Pytest suite covering configuration resolution and processing pipeline logic.
- `azuredeploy.json` / `azuredeploy.parameters.json` – ARM template supporting the Deploy to Azure button workflow.
- `samples/` – Example configuration payloads for local development.

## Local development

1. Install [uv](https://github.com/astral-sh/uv) if you have not already.
2. Create a virtual environment and install dependencies:

   ```bash
   uv sync --project .
   ```

3. Start the Azure Functions host (requires the Azure Functions Core Tools):

   ```bash
   func start
   ```

   The default settings in `local.settings.json` are configured for the Azurite emulator (`UseDevelopmentStorage=true`).

4. Run tests:

   ```bash
   uv run --project . pytest
   ```

   Before publishing to Azure, export a deployment-ready `requirements.txt`:

   ```bash
   uv export --project . --no-hashes > requirements.txt
   ```

## Configuration

Environment variables (or app settings in Azure Functions) drive runtime behavior:

| Setting | Description | Default |
| --- | --- | --- |
| `STORAGE_CONNECTION_STRING` | Optional connection string for development (overrides managed identity). | – |
| `STORAGE_ACCOUNT_URL` | Blob account URL used with managed identity. | – |
| `IN_CONTAINER_NAME` | Container monitored for incoming documents and configuration. | `in` |
| `OUT_CONTAINER_NAME` | Container that receives DocuDevs responses. | `out` |
| `DEFAULT_CONFIG_FOLDER` | Fallback folder for configuration inheritance. | `__default__` |
| `DOCUDEVS_BASE_URL` | DocuDevs API endpoint. | `https://api.docudevs.ai` |
| `DOCUDEVS_API_KEY` | DocuDevs API key (can be a Key Vault reference). | – |

## Event filtering

- Configuration events (`handle_config_update`) respond to `params.json`, `schema.json`, or `metadata.json` changes.
- Document events (`handle_document_ingest`) skip JSON artifacts and rely on the configuration hierarchy to resolve DocuDevs parameters.

## Azure deployment

Deploy the full function app and supporting resources directly from GitHub:

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fpiizei%2Fdocudevs%2Fmain%2Ffunction%2Fazuredeploy.json)

Use the provided `azuredeploy.json` template to provision:

- Flex Consumption Function App with system-assigned managed identity.
- Application Insights instance.
- Optional storage account creation, or bind to an existing account.
- Event Grid subscriptions for configuration and document events.
- Managed identity role assignments (Blob Data Contributor + Queue Data Contributor).

When deploying via the **Deploy to Azure** button, specify the DocuDevs API key or a Key Vault secret URI. The template configures `WEBSITE_RUN_FROM_PACKAGE` for package-based deployment.

## Samples

`./samples` contains starter `params.json` and `schema.json` files that can be uploaded to the `in/` container for local testing.
