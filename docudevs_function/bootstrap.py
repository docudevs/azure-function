from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from docudevs_client import DocuDevsClient

from .azure_storage import AzureBlobStorage
from .configuration import ConfigurationStore
from .processor import DocumentProcessor


@dataclass(frozen=True)
class Settings:
    storage_account_url: str | None
    storage_connection_string: str | None
    input_container: str
    output_container: str
    default_config_folder: str
    docudevs_base_url: str
    docudevs_api_key: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            storage_account_url=os.getenv("STORAGE_ACCOUNT_URL"),
            storage_connection_string=os.getenv("STORAGE_CONNECTION_STRING"),
            input_container=os.getenv("IN_CONTAINER_NAME", "in"),
            output_container=os.getenv("OUT_CONTAINER_NAME", "out"),
            default_config_folder=os.getenv("DEFAULT_CONFIG_FOLDER", "__default__"),
            docudevs_base_url=os.getenv("DOCUDEVS_BASE_URL", "https://api.docudevs.ai"),
            docudevs_api_key=os.getenv("DOCUDEVS_API_KEY"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()


@lru_cache(maxsize=1)
def get_blob_service_client() -> BlobServiceClient:
    settings = get_settings()
    if settings.storage_connection_string:
        return BlobServiceClient.from_connection_string(settings.storage_connection_string)
    if not settings.storage_account_url:
        raise RuntimeError("STORAGE_ACCOUNT_URL is not configured")
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return BlobServiceClient(account_url=settings.storage_account_url, credential=credential)


@lru_cache(maxsize=1)
def get_storage_adapter() -> AzureBlobStorage:
    return AzureBlobStorage(get_blob_service_client())


@lru_cache(maxsize=1)
def get_configuration_store() -> ConfigurationStore:
    settings = get_settings()
    return ConfigurationStore(
        storage=get_storage_adapter(),
        container_name=settings.input_container,
        default_folder=settings.default_config_folder,
    )


@lru_cache(maxsize=1)
def get_doc_client() -> DocuDevsClient:
    settings = get_settings()
    if not settings.docudevs_api_key:
        raise RuntimeError("DOCUDEVS_API_KEY is not configured")
    return DocuDevsClient(api_url=settings.docudevs_base_url, token=settings.docudevs_api_key)


@lru_cache(maxsize=1)
def get_document_processor() -> DocumentProcessor:
    settings = get_settings()
    return DocumentProcessor(
        doc_client=get_doc_client(),
        storage=get_storage_adapter(),
        config_store=get_configuration_store(),
        input_container=settings.input_container,
        output_container=settings.output_container,
    )
