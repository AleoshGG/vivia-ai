# data_lake/__init__.py
from .repository import StorageRepository
from .gcs_repository import GCSRepository
from .local_repository import LocalRepository

__all__ = ["StorageRepository", "GCSRepository", "LocalRepository"]
