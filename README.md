# DocuDevs Azure Function Integration Guide

Welcome! This Azure Functions app lets you connect the DocuDevs document intelligence platform to your own Azure Storage account. Drop a file in storage, and the function will fetch the relevant configuration, call DocuDevs, and write the structured JSON output back to storage so the rest of your workflow can continue automatically.

If you are looking for contributor or maintenance notes, see `DEVELOPMENT.md`.

## What you get

- Event Grid–driven automation that reacts as soon as a new document lands in your input container.
- Folder-based configuration so each business unit can provide its own `params.json`, `schema.json`, or `metadata.json` without changing code.
- Automatic routing of DocuDevs responses (success or failure) to an output container for downstream systems.

## Prerequisites

- Azure subscription with permission to deploy Azure Functions, Storage, and Event Grid resources.
- DocuDevs account and API key.
- Incoming blob events routed through Event Grid (the deployment template supplied in this repository sets this up for you).

## Deploy in minutes

1. Click the **Deploy to Azure** button below and follow the portal prompts.
2. Provide your DocuDevs API key (or a Key Vault reference) and choose the storage account you want the function to monitor.
3. Complete the deployment to create the Function App, identity, Event Grid subscriptions, and supporting resources.

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fdocudevs%2Fazure-function%2Fmain%2Fazuredeploy.json)

Prefer infrastructure-as-code? Use the included `azuredeploy.json` ARM template with your own parameters. The function can also be packaged and published through your existing CI/CD pipeline.

## Configure your storage layout

The function watches one input container (default `in`) and one output container (default `out`). Within the input container:

- Store documents anywhere; nested folders are allowed.
- Provide configuration by uploading the following optional files alongside, or in a parent folder:
  - `params.json` (required for DocuDevs commands)
  - `schema.json`
  - `metadata.json`
- A generated `config.json` is written by the app to cache the consolidated view—do not edit it manually.

Configuration inheritance: if a folder does not include its own configuration file, the function looks upward through parent folders until it finds one, then merges the results. This makes it easy to set account-wide defaults in a shared folder and override only what you need per customer or project.

## Runtime settings

Configure these Application Settings in Azure (or environment variables locally). Defaults shown where applicable.

| Setting | Purpose | Default |
| --- | --- | --- |
| `DOCUDEVS_API_KEY` | Authenticates calls to DocuDevs. | – |
| `DOCUDEVS_BASE_URL` | Override the DocuDevs endpoint if needed. | `https://api.docudevs.ai` |
| `IN_CONTAINER_NAME` | Container monitored for input documents and configuration. | `in` |
| `OUT_CONTAINER_NAME` | Container receiving processed DocuDevs responses. | `out` |
| `DEFAULT_CONFIG_FOLDER` | Folder used when no configuration exists alongside a file. | `__default__` |
| `STORAGE_CONNECTION_STRING` | Local development helper; production typically relies on managed identity. | – |
| `STORAGE_ACCOUNT_URL` | Required when using managed identity. | – |

## Processing flow

1. Event Grid notifies the function when a new blob is created or updated in the input container.
2. The function resolves the applicable configuration, honoring inheritance and cached snapshots.
3. The document is uploaded to DocuDevs and processed using the merged configuration command.
4. Results are written as JSON to the output container using the source blob name with a `.json` extension.
5. If DocuDevs returns an error, the function writes `<blob-name>.error.json` with diagnostic details so you can retry after fixing the configuration or source document.


## Monitoring and troubleshooting

- **Storage outputs**: Inspect the output container for `.json` or `.error.json` files to verify processing.
- **Application Insights**: The deployment template enables logging so you can search for function traces, failures, and latency metrics.
- **Configuration cache**: Deleting a configuration file automatically removes the cached `config.json`. Upload the corrected file and the next run rebuilds the cache.
- **Access control**: The function uses its managed identity to reach Blob Storage. Ensure it has Blob Data Contributor role assignments on the target storage account.

## Need developer details?

Everything related to local development, testing, and repository structure lives in `DEVELOPMENT.md` so this page can stay focused on your deployment experience.
