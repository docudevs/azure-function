"""DocuDevs Azure Function application modules."""

from .configuration import ConfigurationStore, FolderConfiguration, StorageClient, StorageObject
from .processor import DocumentProcessor, ProcessingOutcome

__all__ = [
    "ConfigurationStore",
    "FolderConfiguration",
    "StorageClient",
    "StorageObject",
    "DocumentProcessor",
    "ProcessingOutcome",
]
