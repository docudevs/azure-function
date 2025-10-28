import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from docudevs_function.configuration import ConfigurationStore, FolderConfiguration, StorageObject


class FakeStorage:
    def __init__(self, objects: Dict[str, StorageObject]) -> None:
        self._objects = objects
        self.recorded_writes: Dict[str, StorageObject] = {}

    def get_object(self, container: str, name: str) -> Optional[StorageObject]:
        key = f"{container}/{name}"
        return self._objects.get(key)

    def put_object(self, container: str, name: str, data: bytes, content_type: str, etag: str) -> None:
        key = f"{container}/{name}"
        self.recorded_writes[key] = StorageObject(data=data, content_type=content_type, etag=etag)


@pytest.fixture
def storage() -> FakeStorage:
    objects = {
        "in/folder/params.json": StorageObject(
            data=json.dumps({"prompt": "hello"}).encode(),
            content_type="application/json",
            etag="etag-params",
        ),
        "in/folder/schema.json": StorageObject(
            data=json.dumps({"type": "object"}).encode(),
            content_type="application/json",
            etag="etag-schema",
        ),
        "in/__default__/params.json": StorageObject(
            data=json.dumps({"prompt": "fallback"}).encode(),
            content_type="application/json",
            etag="etag-default",
        ),
    }
    return FakeStorage(objects)


def test_build_config_combines_params_and_schema(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")

    config = store.build("folder")

    assert isinstance(config, FolderConfiguration)
    assert config.params == {"prompt": "hello"}
    assert config.schema == {"type": "object"}
    assert config.metadata is None
    assert config.source_folder == Path("folder")
    assert config.etags == {
        "params.json": "etag-params",
        "schema.json": "etag-schema",
    }


def test_resolve_config_falls_back_to_default(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")

    config = store.resolve("missing/subfolder")

    assert config.params == {"prompt": "fallback"}
    assert config.source_folder == Path("__default__")
    assert config.etags == {"params.json": "etag-default"}


def test_build_config_raises_when_params_missing(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")

    with pytest.raises(FileNotFoundError):
        store.build("missing/subfolder")


def test_write_consolidated_config(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")

    config = store.build("folder")
    store.write_consolidated_config(config)

    output_key = "in/folder/config.json"
    assert output_key in storage.recorded_writes
    written = storage.recorded_writes[output_key]
    assert written.content_type == "application/json"
    payload = json.loads(written.data)
    assert payload == {
        "params": {"prompt": "hello"},
        "schema": {"type": "object"},
        "metadata": None,
        "source": "folder",
    }
