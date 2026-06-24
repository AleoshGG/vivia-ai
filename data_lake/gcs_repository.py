from typing import BinaryIO, List, Optional
from google.cloud import storage
from .repository import StorageRepository
import logging

logger = logging.getLogger(__name__)

class GCSRepository(StorageRepository):
    """
    Implementación de StorageRepository para Google Cloud Storage.
    """
    def __init__(self, bucket_name: str, credentials_path: Optional[str] = None):
        self.bucket_name = bucket_name
        try:
            if credentials_path:
                self.client = storage.Client.from_service_account_json(credentials_path)
            else:
                self.client = storage.Client()
            self.bucket = self.client.bucket(bucket_name)
        except Exception as e:
            logger.error(f"Error inicializando GCS client: {e}")
            raise

    def upload(self, key: str, data: BinaryIO) -> str:
        blob = self.bucket.blob(key)
        blob.upload_from_file(data)
        return f"gs://{self.bucket_name}/{key}"

    def download(self, key: str) -> bytes:
        blob = self.bucket.blob(key)
        return blob.download_as_bytes()

    def list_objects(self, prefix: str) -> List[str]:
        blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)
        return [blob.name for blob in blobs]

    def delete(self, key: str) -> None:
        blob = self.bucket.blob(key)
        blob.delete()

    def exists(self, key: str) -> bool:
        blob = self.bucket.blob(key)
        return blob.exists()
