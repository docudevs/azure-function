from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any, Tuple
from urllib.parse import unquote

import azure.functions as func

from docudevs_function.bootstrap import (
    get_configuration_store,
    get_document_processor,
    get_settings,
    get_storage_adapter,
)

LOGGER = logging.getLogger(__name__)

app = func.FunctionApp()

CONFIG_FILES = {"params.json", "schema.json", "metadata.json"}


@app.function_name(name="handle_config_update")
@app.event_grid_trigger(arg_name="event")
async def handle_config_update(event: func.EventGridEvent) -> None:
    subject = event.subject or ""
    parsed = _parse_subject(subject)
    if not parsed:
        LOGGER.warning("Ignoring event with unexpected subject: %s", subject)
        return
    container, blob_name = parsed
    settings = get_settings()
    if container != settings.input_container:
        return
    file_name = PurePosixPath(blob_name).name
    if file_name not in CONFIG_FILES:
        return

    store = get_configuration_store()
    folder = PurePosixPath(blob_name).parent
    store.invalidate(folder)
    if event.event_type.endswith("BlobDeleted"):
        _delete_consolidated_config(folder)
        LOGGER.info("Config deleted for %s", folder)
        return

    try:
        config = store.build(folder)
    except FileNotFoundError:
        LOGGER.warning("Config update event but params.json missing for %s", folder)
        return
    store.write_consolidated_config(config)
    LOGGER.info("Config rebuilt for %s", folder)


@app.function_name(name="handle_document_ingest")
@app.event_grid_trigger(arg_name="event")
async def handle_document_ingest(event: func.EventGridEvent) -> str:
    subject = event.subject or ""
    parsed = _parse_subject(subject)
    if not parsed:
        LOGGER.warning("Ignoring ingest event with unexpected subject: %s", subject)
        return "ignored"
    container, blob_name = parsed
    settings = get_settings()
    if container != settings.input_container:
        return "ignored"
    file_name = PurePosixPath(blob_name).name
    if file_name in CONFIG_FILES or file_name.endswith(".json"):
        return "skipped"

    processor = get_document_processor()
    outcome = await processor.process_blob(blob_name)
    LOGGER.info("Processed blob %s with outcome %s", blob_name, outcome.value)
    return outcome.value


def _parse_subject(subject: str) -> Tuple[str, str] | None:
    prefix = "/blobServices/default/containers/"
    if not subject.startswith(prefix):
        return None
    remainder = subject[len(prefix) :]
    if "/blobs/" not in remainder:
        return None
    container, blob_part = remainder.split("/blobs/", 1)
    if not container or not blob_part:
        return None
    return container, unquote(blob_part)


def _delete_consolidated_config(folder: PurePosixPath) -> None:
    storage = get_storage_adapter()
    settings = get_settings()
    blob_name = f"{folder.as_posix().lstrip('/')}/config.json" if str(folder) not in {"", "."} else "config.json"
    blob_client = storage.service_client.get_blob_client(container=settings.input_container, blob=blob_name)
    try:
        blob_client.delete_blob(delete_snapshots="include")
    except Exception as exc:  # pragma: no cover - best effort cleanup
        LOGGER.debug("Unable to delete consolidated config %s: %s", blob_name, exc)


def _coalesce_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


def _json_response(payload: dict[str, Any], *, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
    )
