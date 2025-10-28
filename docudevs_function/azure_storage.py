from __future__ import annotations

import logging
from typing import Optional

from azure.core.exceptions import ResourceNotFoundError, ResourceModifiedError
from azure.storage.blob import BlobServiceClient, ContentSettings

from .configuration import StorageClient, StorageObject

LOGGER = logging.getLogger(__name__)


class AzureBlobStorage(StorageClient):

    def __init__(self, service_client: BlobServiceClient) -> None:
        self._service_client = service_client

    @property
    def service_client(self) -> BlobServiceClient:
        return self._service_client

    def get_object(self, container: str, name: str) -> Optional[StorageObject]:
        blob_client = self._service_client.get_blob_client(container=container, blob=name)
        try:
            downloader = blob_client.download_blob()
        except ResourceNotFoundError:
            return None
        data = downloader.readall()
        properties = downloader.properties
        content_type = ""
        if properties.content_settings and properties.content_settings.content_type:
            content_type = properties.content_settings.content_type
        elif properties.content_type:
            content_type = properties.content_type
        etag = properties.etag or ""
        return StorageObject(data=data, content_type=content_type, etag=etag)

    def put_object(self, container: str, name: str, data: bytes, content_type: str, etag: str) -> None:
        blob_client = self._service_client.get_blob_client(container=container, blob=name)
        content_settings = ContentSettings(content_type=content_type)
        try:
            kwargs = {"overwrite": True, "content_settings": content_settings}
            if etag:
                kwargs["if_match"] = etag
            blob_client.upload_blob(data, **kwargs)
        except ResourceModifiedError:
            LOGGER.warning("Concurrency conflict while uploading %s/%s; retrying without ETag", container, name)
            blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
        except ResourceNotFoundError:
            LOGGER.info("Container %s missing; creating before upload", container)
            self._service_client.get_container_client(container).create_container()
            blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
