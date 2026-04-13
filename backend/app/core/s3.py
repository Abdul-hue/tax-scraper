import asyncio
import logging
import os
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "scraper-api-assets-2026")


def _build_s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


def _upload_screenshot_sync(screenshot_bytes: bytes, filename: str) -> str:
    if not screenshot_bytes:
        raise ValueError("Screenshot bytes cannot be empty.")
    if not filename:
        raise ValueError("Filename is required for S3 upload.")
    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME]):
        raise ValueError(
            "Missing AWS configuration. Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and S3_BUCKET_NAME."
        )

    s3_key = f"screenshots/{filename}"
    client = _build_s3_client()

    try:
        client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=screenshot_bytes,
            ContentType="image/png",
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Failed to upload screenshot to S3: %s", exc)
        raise RuntimeError("S3 upload failed.") from exc

    encoded_key = quote(s3_key, safe="/")
    return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{encoded_key}"


def upload_screenshot_to_s3_sync(screenshot_bytes: bytes, filename: str) -> str:
    """Synchronous uploader for sync scraper contexts."""
    return _upload_screenshot_sync(screenshot_bytes, filename)


async def upload_screenshot_to_s3(screenshot_bytes: bytes, filename: str) -> str:
    """
    Upload screenshot bytes directly to S3 and return a public URL.
    This function is async-friendly and performs the boto3 upload in a worker thread.
    """
    return await asyncio.to_thread(_upload_screenshot_sync, screenshot_bytes, filename)
