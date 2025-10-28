from __future__ import annotations

import io
import json
import logging
from enum import Enum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Optional, Protocol
from uuid import uuid4

from .configuration import ConfigurationStore, FolderConfiguration, StorageClient, StorageObject

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from docudevs.models.upload_command import UploadCommand
    from docudevs.models.upload_document_body import UploadDocumentBody


def _import_doc_sdk():  # pragma: no cover - import wrapper to ease monkeypatching
    from docudevs.models.upload_document_body import UploadDocumentBody
    from docudevs.models.upload_command import UploadCommand
    from docudevs.types import File, UNSET

    return UploadDocumentBody, UploadCommand, File, UNSET

LOGGER = logging.getLogger(__name__)


class DocuDevsClient(Protocol):  # pragma: no cover - protocol only
    async def upload_document(self, body: "UploadDocumentBody") -> Any:
        ...

    async def process_document(self, guid: str, body: "UploadCommand") -> Any:
        ...

    async def wait_until_ready(
        self,
        guid: str,
        timeout: int = 180,
        poll_interval: float = 5.0,
        result_format: Optional[str] = None,
        excel_save_to: Optional[str] = None,
    ) -> Any:
        ...


class ProcessingOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class DocumentProcessor:

    def __init__(
        self,
        *,
        doc_client: DocuDevsClient,
        storage: StorageClient,
        config_store: ConfigurationStore,
        input_container: str,
        output_container: str,
    ) -> None:
        self._doc_client = doc_client
        self._storage = storage
        self._config_store = config_store
        self._input_container = input_container
        self._output_container = output_container
        self._doc_sdk: tuple[Any, Any, Any, Any] | None = None

    async def process_blob(self, blob_name: str) -> ProcessingOutcome:
        blob_path = PurePosixPath(blob_name)
        try:
            document = self._storage.get_object(self._input_container, blob_path.as_posix())
            if document is None:
                raise FileNotFoundError(f"Blob '{blob_name}' not found in container '{self._input_container}'")
            folder = blob_path.parent
            config = self._config_store.resolve(folder)
            payload, extension, content_type = await self._upload_and_process(blob_path, document, config)
            self._write_success(blob_name, payload, extension, content_type)
            return ProcessingOutcome.SUCCESS
        except Exception as exc:
            LOGGER.exception("Failed to process blob %s", blob_name, exc_info=exc)
            self._write_failure(blob_name, exc)
            return ProcessingOutcome.FAILURE

    async def _upload_and_process(
        self,
        blob_path: PurePosixPath,
        document: StorageObject,
        config: FolderConfiguration,
    ) -> bytes:
        mime_type = self._resolve_mime_type(config, document)
        upload_document_body, _, file_cls, _ = self._get_doc_sdk()
        upload_body = upload_document_body(
            document=file_cls(payload=io.BytesIO(document.data), file_name=blob_path.name, mime_type=mime_type),
        )
        upload_response = await self._doc_client.upload_document(body=upload_body)
        guid = self._extract_guid(upload_response)
        upload_command = self._build_command(config, mime_type)
        process_response = await self._doc_client.process_document(guid=guid, body=upload_command)
        status_code = getattr(process_response, "status_code", None)
        if status_code is not None and status_code >= 400:
            payload = self._serialize_response(process_response).decode("utf-8", errors="replace")
            raise RuntimeError(f"DocuDevs process_document failed ({status_code}): {payload}")

        wait_format, wait_kwargs = self._resolve_wait_parameters(config.params)
        result = await self._wait_for_completion(guid, wait_format, wait_kwargs)
        payload = self._serialize_result(result, wait_format)
        extension, content_type = self._resolve_output_descriptor(wait_format)
        return payload, extension, content_type

    def _resolve_mime_type(self, config: FolderConfiguration, document: StorageObject) -> str:
        params_mime = self._lookup_param(config.params, "mimeType") or self._lookup_param(config.params, "mime_type")
        if isinstance(params_mime, str) and params_mime:
            return params_mime
        if document.content_type:
            return document.content_type
        return "application/octet-stream"

    def _lookup_param(self, params: dict, key: str) -> Optional[Any]:
        value = params.get(key)
        if value is not None:
            return value
        return params.get(key[0].lower() + key[1:]) if key and key[0].isupper() else None

    def _build_command(self, config: FolderConfiguration, mime_type: str) -> "UploadCommand":
        _, upload_command_cls, _, unset = self._get_doc_sdk()
        params = dict(config.params)
        params.setdefault("mimeType", mime_type)
        command = upload_command_cls.from_dict(params)
        if (command.schema is unset or command.schema is None) and config.schema is not None:
            command.schema = (
                json.dumps(config.schema, separators=(",", ":"))
                if isinstance(config.schema, (dict, list))
                else str(config.schema)
            )
        if config.metadata is not None:
            command.additional_properties.setdefault("metadata", config.metadata)
        return command

    def _resolve_wait_parameters(self, params: dict) -> tuple[Optional[str], dict[str, Any]]:
        result_format = self._lookup_param(params, "resultFormat")
        normalized_format: Optional[str] = None
        if isinstance(result_format, str):
            candidate = result_format.strip().lower()
            if candidate in {"json", "csv", "excel"}:
                normalized_format = candidate
            else:
                LOGGER.warning("Ignoring unsupported result format '%s'", result_format)

        timeout_raw = (
            self._lookup_param(params, "resultTimeoutSeconds")
            or self._lookup_param(params, "resultTimeout")
        )
        timeout = self._coerce_positive_int(timeout_raw)

        poll_raw = (
            self._lookup_param(params, "resultPollIntervalSeconds")
            or self._lookup_param(params, "resultPollInterval")
        )
        poll_interval = self._coerce_positive_float(poll_raw)

        wait_kwargs: dict[str, Any] = {}
        if timeout is not None:
            wait_kwargs["timeout"] = timeout
        if poll_interval is not None:
            wait_kwargs["poll_interval"] = poll_interval
        if normalized_format is not None:
            wait_kwargs["result_format"] = normalized_format
        return normalized_format, wait_kwargs

    def _extract_guid(self, response: Any) -> str:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            guid = parsed.get("guid") or parsed.get("jobGuid")
            if guid:
                return guid
        if parsed is not None and hasattr(parsed, "guid"):
            guid = getattr(parsed, "guid")
            if guid:
                return guid
        guid_attr = getattr(response, "guid", None)
        if isinstance(guid_attr, str) and guid_attr:
            return guid_attr
        content = getattr(response, "content", b"")
        if content:
            try:
                payload = json.loads(content.decode("utf-8"))
                guid = payload.get("guid") or payload.get("jobGuid")
                if guid:
                    return guid
            except json.JSONDecodeError:
                pass
        raise RuntimeError("Upload response missing guid")

    def _serialize_response(self, response: Any) -> bytes:
        parsed = getattr(response, "parsed", None)
        if parsed is None:
            content = getattr(response, "content", None)
            if isinstance(content, bytes) and content:
                return content
            return json.dumps({"status": getattr(response, "status_code", "unknown")}).encode("utf-8")
        if isinstance(parsed, (bytes, bytearray)):
            return bytes(parsed)
        if hasattr(parsed, "to_dict"):
            return json.dumps(parsed.to_dict()).encode("utf-8")
        if isinstance(parsed, dict):
            return json.dumps(parsed).encode("utf-8")
        return json.dumps({k: v for k, v in vars(parsed).items() if not k.startswith("_")}).encode("utf-8")

    async def _wait_for_completion(self, guid: str, result_format: Optional[str], wait_kwargs: dict[str, Any]) -> Any:
        # `result_format` already propagated into wait_kwargs (when supported), but we retain it to simplify testing hooks
        return await self._doc_client.wait_until_ready(guid=guid, **wait_kwargs)

    def _serialize_result(self, result: Any, result_format: Optional[str]) -> bytes:
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        if isinstance(result, str):
            return result.encode("utf-8")
        if hasattr(result, "to_dict"):
            return json.dumps(result.to_dict()).encode("utf-8")
        if isinstance(result, (dict, list)):
            return json.dumps(result).encode("utf-8")
        if hasattr(result, "__dict__"):
            return json.dumps({k: v for k, v in vars(result).items() if not k.startswith("_")}).encode("utf-8")
        return json.dumps(result, default=str).encode("utf-8")

    def _resolve_output_descriptor(self, result_format: Optional[str]) -> tuple[str, str]:
        if result_format == "csv":
            return "csv", "text/csv"
        if result_format == "excel":
            return "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "json", "application/json"

    def _write_success(self, blob_name: str, payload: bytes, extension: str, content_type: str) -> None:
        target_name = f"{blob_name}.{extension}"
        self._storage.put_object(
            self._output_container,
            target_name,
            data=payload,
            content_type=content_type,
            etag=self._generate_etag(),
        )

    def _write_failure(self, blob_name: str, exc: Exception) -> None:
        payload = json.dumps({"status": "error", "message": str(exc)}).encode("utf-8")
        target_name = f"{blob_name}.error.json"
        self._storage.put_object(
            self._output_container,
            target_name,
            data=payload,
            content_type="application/json",
            etag=self._generate_etag(),
        )

    def _generate_etag(self) -> str:
        return f"{uuid4()}"

    def _get_doc_sdk(self) -> tuple[Any, Any, Any, Any]:
        if self._doc_sdk is None:
            self._doc_sdk = _import_doc_sdk()
        return self._doc_sdk

    def _coerce_positive_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            LOGGER.warning("Unable to coerce timeout value '%s' to int", value)
            return None
        return coerced if coerced > 0 else None

    def _coerce_positive_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            LOGGER.warning("Unable to coerce poll interval value '%s' to float", value)
            return None
        return coerced if coerced > 0 else None
