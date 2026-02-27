"""MinIO (S3-compatible) document storage client."""

import io
import logging
from dataclasses import dataclass

from minio import Minio
from minio.error import S3Error

from exnot.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredObject:
    """Immutable reference to an object stored in MinIO."""

    bucket: str
    object_name: str
    size_bytes: int
    etag: str


class DocumentStorage:
    """Wraps the MinIO SDK for storing and retrieving scraped documents."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create the bucket if it doesn't already exist."""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info(f"Created MinIO bucket: {self._bucket}")
        except S3Error as e:
            logger.error(f"Failed to ensure MinIO bucket: {e}")
            raise

    @staticmethod
    def build_object_name(exchange_code: str, version: int, filename: str) -> str:
        """Build an object path: {exchange_code}/{version}/{filename}."""
        return f"{exchange_code}/{version}/{filename}"

    def store(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Upload bytes to MinIO and return a StoredObject reference."""
        result = self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info(f"Stored {object_name} ({len(data)} bytes) in MinIO")
        return StoredObject(
            bucket=self._bucket,
            object_name=result.object_name,
            size_bytes=len(data),
            etag=result.etag,
        )

    def retrieve(self, object_name: str) -> bytes:
        """Download an object's bytes from MinIO."""
        response = self._client.get_object(self._bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, object_name: str) -> bool:
        """Check whether an object exists in the bucket."""
        try:
            self._client.stat_object(self._bucket, object_name)
            return True
        except S3Error:
            return False

    def delete(self, object_name: str) -> None:
        """Remove an object from MinIO."""
        self._client.remove_object(self._bucket, object_name)
        logger.info(f"Deleted {object_name} from MinIO")
