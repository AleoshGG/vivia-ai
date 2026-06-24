import os
from pathlib import Path
from typing import BinaryIO, List
from .repository import StorageRepository

class LocalRepository(StorageRepository):
    """
    Implementación de StorageRepository para el sistema de archivos local.
    Útil para desarrollo sin depender de un entorno Cloud.
    """
    def __init__(self, base_path: str = "./local_data_lake"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_full_path(self, key: str) -> Path:
        return self.base_path / key

    def upload(self, key: str, data: BinaryIO) -> str:
        full_path = self._get_full_path(key)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data.read())
        return f"file://{full_path.absolute()}"

    def download(self, key: str) -> bytes:
        full_path = self._get_full_path(key)
        with open(full_path, "rb") as f:
            return f.read()

    def list_objects(self, prefix: str) -> List[str]:
        # Implementación simple de listado
        result = []
        for root, _, files in os.walk(self.base_path):
            for file in files:
                rel_path = Path(root) / file
                key = str(rel_path.relative_to(self.base_path))
                if key.startswith(prefix):
                    result.append(key)
        return result

    def delete(self, key: str) -> None:
        full_path = self._get_full_path(key)
        if full_path.exists():
            full_path.unlink()

    def exists(self, key: str) -> bool:
        return self._get_full_path(key).exists()
