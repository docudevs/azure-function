import json
import io
from typing import Any, Dict, Optional

import pytest

from docudevs_function.configuration import ConfigurationStore, StorageObject
from docudevs_function import processor as processor_module
from docudevs_function.processor import DocumentProcessor, ProcessingOutcome


class FakeDocuDevsResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any], guid: Optional[str] = None) -> None:
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")
        self.parsed = payload
        self.guid = guid


class FakeDocuDevsClient:
    def __init__(self, wait_result: Any | None = None) -> None:
        self.upload_calls = []
        self.process_calls = []
        self.wait_calls = []
        self._wait_result = wait_result if wait_result is not None else {"result": "ok", "guid": "job-123"}

    async def upload_document(self, body: Any) -> FakeDocuDevsResponse:
        payload = body.document.payload  # type: ignore[attr-defined]
        guid = "job-123"
        self.upload_calls.append({"length": len(payload.getvalue())})
        return FakeDocuDevsResponse(status_code=200, payload={"guid": guid}, guid=guid)

    async def process_document(self, guid: str, body: Any) -> FakeDocuDevsResponse:
        self.process_calls.append({"guid": guid, "body": body.to_dict()})
        return FakeDocuDevsResponse(status_code=202, payload={"status": "accepted", "guid": guid})

    async def wait_until_ready(
        self,
        guid: str,
        timeout: int = 180,
        poll_interval: float = 5.0,
        result_format: str | None = None,
        excel_save_to: str | None = None,
    ) -> Any:
        self.wait_calls.append(
            {
                "guid": guid,
                "timeout": timeout,
                "poll_interval": poll_interval,
                "result_format": result_format,
                "excel_save_to": excel_save_to,
            }
        )
        return self._wait_result


class FakeStorage:
    def __init__(self, objects: Dict[str, StorageObject]) -> None:
        self._objects = objects
        self.recorded_writes: Dict[str, StorageObject] = {}

    def get_object(self, container: str, name: str) -> Optional[StorageObject]:
        return self._objects.get(f"{container}/{name}")

    def put_object(self, container: str, name: str, data: bytes, content_type: str, etag: str) -> None:
        self.recorded_writes[f"{container}/{name}"] = StorageObject(data=data, content_type=content_type, etag=etag)


@pytest.fixture
def storage() -> FakeStorage:
    objects = {
        "in/folder/params.json": StorageObject(
            data=json.dumps({"prompt": "hello", "mimeType": "application/pdf"}).encode(),
            content_type="application/json",
            etag="etag-params",
        ),
        "in/folder/schema.json": StorageObject(
            data=json.dumps({"type": "object"}).encode(),
            content_type="application/json",
            etag="etag-schema",
        ),
        "in/folder/document.pdf": StorageObject(
            data=b"%PDF-1.7",
            content_type="application/pdf",
            etag="etag-doc",
        ),
    }
    return FakeStorage(objects)


@pytest.fixture(autouse=True)
def patch_doc_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_unset = object()

    class DummyFile:
        def __init__(self, payload: io.BytesIO, file_name: Optional[str] = None, mime_type: Optional[str] = None) -> None:
            self.payload = payload
            self.file_name = file_name
            self.mime_type = mime_type

        def to_tuple(self) -> tuple[Optional[str], io.BytesIO, Optional[str]]:
            return self.file_name, self.payload, self.mime_type

    class DummyUploadDocumentBody:
        def __init__(self, document: DummyFile) -> None:
            self.document = document

    class DummyUploadCommand:
        def __init__(self, payload: Dict[str, Any]) -> None:
            self._payload = payload
            self.schema = payload.get("schema", dummy_unset)
            self.additional_properties: Dict[str, Any] = {}

        @classmethod
        def from_dict(cls, payload: Dict[str, Any]) -> "DummyUploadCommand":
            return cls(dict(payload))

        def to_dict(self) -> Dict[str, Any]:
            payload = dict(self._payload)
            if self.schema is not dummy_unset:
                payload["schema"] = self.schema
            if self.additional_properties:
                payload.update(self.additional_properties)
            return payload

    monkeypatch.setattr(
        processor_module,
        "_import_doc_sdk",
        lambda: (DummyUploadDocumentBody, DummyUploadCommand, DummyFile, dummy_unset),
        raising=False,
    )


@pytest.mark.asyncio
async def test_process_document_writes_result(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")
    client = FakeDocuDevsClient()
    processor = DocumentProcessor(
        doc_client=client,
        storage=storage,
        config_store=store,
        input_container="in",
        output_container="out",
    )

    outcome = await processor.process_blob("folder/document.pdf")

    assert outcome == ProcessingOutcome.SUCCESS
    assert client.upload_calls  # upload called
    assert client.process_calls[0]["guid"] == "job-123"
    assert client.wait_calls  # waited for result
    assert client.wait_calls[0]["result_format"] is None
    serialized_schema = client.process_calls[0]["body"]["schema"]
    assert isinstance(serialized_schema, str)
    assert json.loads(serialized_schema) == {"type": "object"}
    output_key = "out/folder/document.pdf.json"
    assert output_key in storage.recorded_writes
    written = storage.recorded_writes[output_key]
    assert json.loads(written.data) == {"result": "ok", "guid": "job-123"}
    assert written.content_type == "application/json"


@pytest.mark.asyncio
async def test_process_document_respects_result_format(storage: FakeStorage) -> None:
    storage._objects["in/folder/params.json"] = StorageObject(
        data=json.dumps(
            {
                "prompt": "hello",
                "mimeType": "application/pdf",
                "resultFormat": "csv",
                "resultTimeoutSeconds": 30,
                "resultPollIntervalSeconds": 2.5,
            }
        ).encode(),
        content_type="application/json",
        etag="etag-params",
    )
    store = ConfigurationStore(storage=storage, container_name="in")
    client = FakeDocuDevsClient(wait_result="column\nvalue\n")
    processor = DocumentProcessor(
        doc_client=client,
        storage=storage,
        config_store=store,
        input_container="in",
        output_container="out",
    )

    outcome = await processor.process_blob("folder/document.pdf")

    assert outcome == ProcessingOutcome.SUCCESS
    assert client.wait_calls
    wait_call = client.wait_calls[0]
    assert wait_call["result_format"] == "csv"
    assert wait_call["timeout"] == 30
    assert wait_call["poll_interval"] == pytest.approx(2.5)
    output_key = "out/folder/document.pdf.csv"
    assert output_key in storage.recorded_writes
    written = storage.recorded_writes[output_key]
    assert written.content_type == "text/csv"
    assert written.data.decode("utf-8") == "column\nvalue\n"


@pytest.mark.asyncio
async def test_process_document_handles_error(storage: FakeStorage) -> None:
    store = ConfigurationStore(storage=storage, container_name="in")

    class FailingClient(FakeDocuDevsClient):
        async def process_document(self, guid: str, body: Any) -> FakeDocuDevsResponse:  # type: ignore[override]
            raise RuntimeError("boom")

    processor = DocumentProcessor(
        doc_client=FailingClient(),
        storage=storage,
        config_store=store,
        input_container="in",
        output_container="out",
    )

    outcome = await processor.process_blob("folder/document.pdf")

    assert outcome == ProcessingOutcome.FAILURE
    output_key = "out/folder/document.pdf.error.json"
    assert output_key in storage.recorded_writes
    payload = json.loads(storage.recorded_writes[output_key].data)
    assert payload["status"] == "error"
    assert "boom" in payload["message"]
