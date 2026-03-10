from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from .logging_config import get_logger
from .models import DocumentTag, PaperlessDocument, UploadResult

logger = get_logger(__name__)


class PaperlessClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        token: str,
        task_poll_seconds: float,
        task_timeout_seconds: float,
    ) -> None:
        self._http_client = http_client
        self._token = token
        self._task_poll_seconds = task_poll_seconds
        self._task_timeout_seconds = task_timeout_seconds

    async def fetch_document(self, base_url: str, document_id: int) -> PaperlessDocument:
        logger.info("fetching paperless document", document_id=document_id, base_url=base_url)
        details = await self._request_json("GET", base_url, f"/api/documents/{document_id}/")
        mime_type = details.get("mime_type")
        if not mime_type:
            metadata = await self._request_json("GET", base_url, f"/api/documents/{document_id}/metadata/")
            mime_type = metadata.get("original_mime_type")
        if not mime_type:
            raise RuntimeError(f"Paperless did not return a MIME type for document {document_id}")

        tags = await self._resolve_tags(base_url, details.get("tags", []))
        custom_fields = _normalize_custom_fields(details.get("custom_fields", []))
        document = PaperlessDocument(
            id=document_id,
            title=details.get("title") or details.get("original_file_name") or f"Document {document_id}",
            original_filename=details.get("original_file_name") or f"document-{document_id}",
            mime_type=mime_type,
            tags=tags,
            custom_fields=custom_fields,
            correspondent=details.get("correspondent"),
            document_type=details.get("document_type"),
            created=details.get("created"),
        )
        logger.info(
            "fetched paperless document",
            document_id=document_id,
            mime_type=document.mime_type,
            tag_count=len(document.tags),
            custom_field_count=len(document.custom_fields),
        )
        return document

    async def download_document(self, base_url: str, document_id: int) -> bytes:
        logger.info("downloading paperless document", document_id=document_id, base_url=base_url)
        response = await self._request(
            "GET",
            base_url,
            f"/api/documents/{document_id}/download/",
            headers={"Accept": "application/pdf, application/octet-stream;q=0.9, */*;q=0.8"},
        )
        logger.info(
            "downloaded paperless document",
            document_id=document_id,
            content_type=response.headers.get("content-type"),
            size_bytes=len(response.content),
        )
        return response.content

    async def find_tag_id(self, base_url: str, tag_name: str) -> int:
        response = await self._request_json(
            "GET",
            base_url,
            "/api/tags/",
            params={"name__iexact": tag_name, "page_size": "1"},
        )
        results = response.get("results", [])
        if not results:
            raise RuntimeError(f"Paperless tag not found: {tag_name}")
        return int(results[0]["id"])

    async def find_custom_field_id(self, base_url: str, field_name: str) -> int:
        next_url = "/api/custom_fields/"
        while next_url:
            payload = await self._request_json("GET", base_url, next_url)
            for field in payload.get("results", []):
                if str(field.get("name", "")).strip().lower() == field_name.lower():
                    return int(field["id"])
            next_url = payload.get("next")
        raise RuntimeError(f"Paperless custom field not found: {field_name}")

    async def upload_document(
        self,
        base_url: str,
        *,
        artifact_name: str,
        artifact_bytes: bytes,
        artifact_mime_type: str,
        title: str,
        tags: list[int],
        custom_fields: dict[str, Any],
        correspondent: int | None,
        document_type: int | None,
        created: str | None,
    ) -> UploadResult:
        logger.info(
            "uploading translated document",
            filename=artifact_name,
            mime_type=artifact_mime_type,
            title=title,
            tag_count=len(tags),
        )
        data: dict[str, str | list[str]] = {
            "title": title,
            "custom_fields": json.dumps(custom_fields, ensure_ascii=False),
        }
        if correspondent is not None:
            data["correspondent"] = str(correspondent)
        if document_type is not None:
            data["document_type"] = str(document_type)
        if created:
            data["created"] = created
        if tags:
            data["tags"] = [str(tag_id) for tag_id in tags]

        logger.info("Document data", data=data)

        files = {"document": (artifact_name, artifact_bytes, artifact_mime_type)}
        response = await self._request(
            "POST",
            base_url,
            "/api/documents/post_document/",
            data=data,
            files=files,
        )
        task_id = _extract_task_id(response)
        logger.info("uploaded translated document", task_id=task_id, filename=artifact_name)
        return UploadResult(task_id=task_id, raw_response=_decode_json_or_text(response))

    async def wait_for_task(self, base_url: str, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._task_timeout_seconds
        while time.monotonic() < deadline:
            payload = await self._request_json(
                "GET",
                base_url,
                "/api/tasks/",
                params={"task_id": task_id},
            )
            task = _extract_task(payload)
            status = str(task.get("status") or "").upper()
            if status in {"SUCCESS", "SUCCEEDED", "COMPLETED"}:
                logger.info("paperless task completed", task_id=task_id, status=status)
                return task
            if status in {"FAILURE", "FAILED", "REVOKED"}:
                raise RuntimeError(f"Paperless task {task_id} failed with status {status}: {task}")
            await asyncio.sleep(self._task_poll_seconds)
        raise TimeoutError(f"Timed out waiting for Paperless task {task_id}")

    async def update_document_tags(self, base_url: str, document_id: int, tag_ids: list[int]) -> None:
        logger.info("updating original document tags", document_id=document_id, tag_ids=tag_ids)
        await self._request(
            "PATCH",
            base_url,
            f"/api/documents/{document_id}/",
            json={"tags": tag_ids},
        )

    async def _resolve_tags(self, base_url: str, raw_tags: list[Any]) -> list[DocumentTag]:
        resolved: list[DocumentTag] = []
        tags_to_fetch: list[int] = []
        for raw_tag in raw_tags:
            if isinstance(raw_tag, dict):
                if "name" in raw_tag and "id" in raw_tag:
                    resolved.append(DocumentTag(id=int(raw_tag["id"]), name=str(raw_tag["name"])))
                elif "id" in raw_tag:
                    tags_to_fetch.append(int(raw_tag["id"]))
            else:
                tags_to_fetch.append(int(raw_tag))

        if tags_to_fetch:
            fetched_tags = await asyncio.gather(
                *(self._request_json("GET", base_url, f"/api/tags/{tag_id}/") for tag_id in tags_to_fetch)
            )
            resolved.extend(
                DocumentTag(id=int(tag_payload["id"]), name=str(tag_payload["name"]))
                for tag_payload in fetched_tags
            )
        return resolved

    async def _request_json(
        self,
        method: str,
        base_url: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self._request(method, base_url, path, **kwargs)
        return response.json()

    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        url = _build_url(base_url, path)
        started = time.monotonic()
        extra_headers = kwargs.pop("headers", {})
        headers = {
            "Authorization": f"Token {self._token}",
            "Accept": "application/json",
            **extra_headers,
        }
        response = await self._http_client.request(
            method,
            url,
            headers=headers,
            **kwargs,
        )
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        logger.info(
            "paperless request",
            method=method,
            url=url,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.raise_for_status()
        return response


def _build_url(base_url: str, path: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _normalize_custom_fields(raw_custom_fields: Any) -> list[dict[str, Any]]:
    if isinstance(raw_custom_fields, dict):
        return [{"field": int(key), "value": value} for key, value in raw_custom_fields.items()]
    if isinstance(raw_custom_fields, list):
        return [field for field in raw_custom_fields if isinstance(field, dict)]
    return []


def _extract_task_id(response: httpx.Response) -> str:
    payload = _decode_json_or_text(response)
    if isinstance(payload, dict):
        for key in ("task_id", "task", "id"):
            value = payload.get(key)
            if value:
                return str(value)
    if isinstance(payload, str) and payload.strip():
        return payload.strip().strip('"')
    raise RuntimeError(f"Paperless upload response did not contain a task id: {payload}")


def _decode_json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _extract_task(payload: list[dict[str, Any]]) -> dict[str, Any]:
    if payload and isinstance(payload[0].get("results"), list):
        return payload[0]["results"][0]
    if payload and isinstance(payload[0].get("task"), dict):
        return payload[0]["task"]
    return payload[0]
