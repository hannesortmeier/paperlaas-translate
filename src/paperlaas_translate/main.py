from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile

from .config import Settings, get_settings
from .llm import OpenAISegmentTranslator
from .logging_config import configure_logging, get_logger
from .paperless_client import PaperlessClient
from .service import TranslationService
from .translators import OfficeAndTextTranslator, PdfTranslator
from .utils import extract_document_id

logger = get_logger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    service: TranslationService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is not None:
            app.state.translation_service = service
            yield
            return

        app_settings = settings or get_settings()
        configure_logging(app_settings.log_level)
        timeout = httpx.Timeout(app_settings.paperless_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, verify=app_settings.paperless_verify_ssl) as http_client:
            paperless_client = PaperlessClient(
                http_client,
                token=app_settings.paperless_token,
                task_poll_seconds=app_settings.paperless_task_poll_seconds,
                task_timeout_seconds=app_settings.paperless_task_timeout_seconds,
            )
            segment_translator = OpenAISegmentTranslator(
                api_key=app_settings.openai_api_key,
                base_url=app_settings.openai_base_url,
                model=app_settings.openai_model,
            )
            office_translator = OfficeAndTextTranslator(
                segment_translator,
                batch_chars=app_settings.translation_batch_chars,
                batch_items=app_settings.translation_batch_items,
                temp_dir=app_settings.temp_dir,
            )
            pdf_translator = PdfTranslator(
                command=app_settings.pdf2zh_command,
                openai_api_key=app_settings.openai_api_key,
                openai_base_url=app_settings.openai_base_url,
                openai_model=app_settings.openai_model,
                temp_dir=app_settings.temp_dir,
                timeout_seconds=app_settings.pdf2zh_timeout_seconds,
                source_language=app_settings.pdf2zh_source_language,
                watermark_output_mode=app_settings.pdf2zh_watermark_output_mode,
            )
            app.state.translation_service = TranslationService(
                paperless_client,
                pdf_translator,
                office_translator,
            )
            yield

    app = FastAPI(title="paperlaas-translate", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/hooks/translate", status_code=202)
    async def translate_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        url: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        try:
            document_id = extract_document_id(url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info(
            "received translation webhook",
            request_id=request_id,
            document_id=document_id,
            content_type=request.headers.get("content-type"),
            source_url=url,
        )
        file_bytes = await file.read()
        background_tasks.add_task(
            request.app.state.translation_service.handle_webhook,
            url,
            request_id,
            file_bytes,
        )
        return {
            "status": "accepted",
            "request_id": request_id,
            "document_id": document_id,
        }

    return app


app = create_app()


def run() -> None:
    app_settings = get_settings()
    configure_logging(app_settings.log_level)
    uvicorn.run(
        "paperlaas_translate.main:app",
        host=app_settings.app_host,
        port=app_settings.app_port,
        reload=False,
    )
