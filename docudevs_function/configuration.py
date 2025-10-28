from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, Optional, Protocol


@dataclass
class StorageObject:
    """Lightweight representation of a blob object."""

    data: bytes
    content_type: str
    etag: str


class StorageClient(Protocol):  # pragma: no cover - protocol only
    def get_object(self, container: str, name: str) -> Optional[StorageObject]:
        ...

    def put_object(self, container: str, name: str, data: bytes, content_type: str, etag: str) -> None:
        ...


@dataclass
class FolderConfiguration:
    params: Dict
    source_folder: PurePosixPath
    schema: Optional[Dict]
    metadata: Optional[Dict]
    etags: Dict[str, str]


class ConfigurationStore:

    def __init__(
        self,
        *,
        storage: StorageClient,
        container_name: str,
        default_folder: str = "__default__",
    ) -> None:
        self._storage = storage
        self._container = container_name
        self._default_folder = PurePosixPath(default_folder)
        self._cache: dict[str, FolderConfiguration] = {}

    def build(self, folder: str | PurePosixPath) -> FolderConfiguration:
        folder_path = self._normalize_folder(folder)
        key = str(folder_path)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        consolidated = self._read_json(folder_path, "config.json")
        if consolidated:
            payload, etag = consolidated
            params = payload.get("params")
            if params is None:
                raise ValueError(f"config.json for {folder_path} missing 'params'")
            schema = payload.get("schema")
            metadata = payload.get("metadata")
            config = FolderConfiguration(
                params=params,
                schema=schema,
                metadata=metadata,
                source_folder=folder_path,
                etags={"config.json": etag},
            )
            self._cache[key] = config
            return config

        params = self._require_json(folder_path, "params.json")
        schema = self._read_json(folder_path, "schema.json")
        metadata = self._read_json(folder_path, "metadata.json")

        etags: dict[str, str] = {"params.json": params[1]}
        schema_payload = schema[0] if schema else None
        metadata_payload = metadata[0] if metadata else None
        if schema:
            etags["schema.json"] = schema[1]
        if metadata:
            etags["metadata.json"] = metadata[1]

        config = FolderConfiguration(
            params=params[0],
            schema=schema_payload,
            metadata=metadata_payload,
            source_folder=folder_path,
            etags=etags,
        )
        self._cache[key] = config
        return config

    def resolve(self, folder: str | PurePosixPath) -> FolderConfiguration:
        folder_path = self._normalize_folder(folder)
        for candidate in self._candidate_folders(folder_path):
            try:
                return self.build(candidate)
            except FileNotFoundError:
                continue
        raise FileNotFoundError(f"No configuration found for folder '{folder_path}'")

    def invalidate(self, folder: str | PurePosixPath) -> None:
        folder_path = self._normalize_folder(folder)
        self._cache.pop(str(folder_path), None)

    def write_consolidated_config(self, config: FolderConfiguration) -> None:
        payload = {
            "params": config.params,
            "schema": config.schema,
            "metadata": config.metadata,
            "source": str(config.source_folder),
        }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        etag = config.etags.get("config.json", config.etags.get("params.json", ""))
        folder_key = str(config.source_folder)
        target_name = f"{folder_key}/config.json" if folder_key else "config.json"
        self._storage.put_object(
            self._container,
            target_name,
            data=data,
            content_type="application/json",
            etag=etag,
        )
        self._cache[str(config.source_folder)] = config

    def _require_json(self, folder: PurePosixPath, file_name: str) -> tuple[Dict, str]:
        resource = self._read_json(folder, file_name)
        if resource is None:
            raise FileNotFoundError(f"Missing {file_name} under {folder}")
        return resource

    def _read_json(self, folder: PurePosixPath, file_name: str) -> tuple[Dict, str] | None:
        blob_name = self._join(folder, file_name)
        obj = self._storage.get_object(self._container, blob_name)
        if obj is None:
            return None
        payload = json.loads(obj.data.decode("utf-8"))
        return payload, obj.etag

    def _candidate_folders(self, folder: PurePosixPath) -> Iterable[PurePosixPath]:
        seen: set[str] = set()
        current = folder
        while True:
            key = str(current)
            if key not in seen:
                seen.add(key)
                yield current
            if current == current.parent:
                break
            if key == "" or key == ".":
                break
            current = current.parent
        yield self._default_folder

    def _join(self, folder: PurePosixPath, file_name: str) -> str:
        if str(folder) in ("", "."):
            return file_name
        return f"{folder.as_posix().lstrip('/')}/{file_name}"

    def _normalize_folder(self, folder: str | PurePosixPath) -> PurePosixPath:
        path = folder if isinstance(folder, PurePosixPath) else PurePosixPath(folder)
        if str(path) in ("", "."):
            return PurePosixPath("")
        return path
