from abc import ABC, abstractmethod
from typing import BinaryIO, List

class StorageRepository(ABC):
    """
    Interfaz abstracta para acceso al Data Lake.
    Cualquier proveedor (GCS, local, etc.) debe implementar esta interfaz.
    """

    @abstractmethod
    def upload(self, key: str, data: BinaryIO) -> str:
        """Sube un archivo al storage. Retorna la URI del objeto."""
        pass

    @abstractmethod
    def download(self, key: str) -> bytes:
        """Descarga un archivo del storage. Retorna los bytes del objeto."""
        pass

    @abstractmethod
    def list_objects(self, prefix: str) -> List[str]:
        """Lista las keys de objetos que coincidan con el prefijo."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Elimina un objeto del storage."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Verifica si un objeto existe en el storage."""
        pass
