import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from insurance_email_intake.client import HTTPUnderwritingClient
from insurance_email_intake.errors import NotCompletableError, RecordNotFoundError
from insurance_email_intake.intake import EmailIntakeService
from insurance_email_intake.models import IntakeRecord, IntakeResult, IntakeStatus
from insurance_email_intake.parser import build_eml
from insurance_email_intake.settings import Settings, get_settings
from insurance_email_intake.store import SOURCE_ID_PATTERN, RecordStore

logger = logging.getLogger(__name__)

SourceIdParam = Annotated[str, PathParam(pattern=SOURCE_ID_PATTERN.pattern)]

_STATUS_CODES = {
    IntakeStatus.PROCESSED: 200,
    IntakeStatus.DUPLICATE: 200,
    IntakeStatus.UNAVAILABLE: 502,
    IntakeStatus.REJECTED: 422,
}


class TextEmailRequest(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    sender: str = "broker@example-brokerage.test"
    message_id: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class CompleteRequest(BaseModel):
    overrides: dict[str, Any] = Field(min_length=1)


def build_service(settings: Settings) -> EmailIntakeService:
    return EmailIntakeService(
        client=HTTPUnderwritingClient(
            settings.underwriting_base_url,
            settings.underwriting_timeout_seconds,
        ),
        store=RecordStore(settings.state_dir),
        persist=settings.persist_decisions,
        default_language=settings.default_language,
    )


def _respond(result: IntakeResult) -> JSONResponse:
    return JSONResponse(
        status_code=_STATUS_CODES[result.status],
        content=result.model_dump(mode="json"),
    )


def _watch_loop(
    service: EmailIntakeService,
    inbox_dir: Path,
    interval_seconds: float,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            for result in service.scan_inbox(inbox_dir):
                if result.status is not IntakeStatus.DUPLICATE:
                    logger.info(
                        "Inbox: %s %s -> %s",
                        result.status,
                        result.source_id,
                        result.workflow_status or result.message,
                    )
        except Exception:
            logger.exception("Inbox scan failed.")
        stop.wait(interval_seconds)


def create_app(
    service: EmailIntakeService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    resolved_settings = settings or get_settings()
    resolved_service = service or build_service(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        thread: threading.Thread | None = None
        if resolved_settings.watch_enabled:
            thread = threading.Thread(
                target=_watch_loop,
                args=(
                    resolved_service,
                    resolved_settings.inbox_dir,
                    resolved_settings.watch_interval_seconds,
                    stop,
                ),
                daemon=True,
            )
            thread.start()
        yield
        stop.set()
        if thread is not None:
            thread.join(timeout=5)

    app = FastAPI(
        title="Insurance Email Intake API",
        version="0.1.0",
        description="Captures broker emails and forwards them to underwriting.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/emails/eml", summary="Submit a raw RFC 822 email")
    async def receive_eml(
        request: Request,
        x_document_name: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty request body.")
        result = await run_in_threadpool(
            resolved_service.ingest_bytes, raw, None, x_document_name
        )
        return _respond(result)

    @app.post("/v1/emails/text", summary="Submit an email as JSON text")
    async def receive_text(payload: TextEmailRequest) -> JSONResponse:
        raw = build_eml(
            sender=payload.sender,
            subject=payload.subject,
            body=payload.body,
            message_id=payload.message_id,
        )
        result = await run_in_threadpool(
            resolved_service.ingest_bytes, raw, payload.overrides, None
        )
        return _respond(result)

    @app.post(
        "/v1/emails/{source_id}/complete",
        summary="Add missing fields to an email pending information",
    )
    async def complete_email(
        source_id: SourceIdParam,
        payload: CompleteRequest,
    ) -> JSONResponse:
        try:
            result = await run_in_threadpool(
                resolved_service.complete, source_id, payload.overrides
            )
        except RecordNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotCompletableError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _respond(result)

    @app.get("/v1/emails", summary="List processed emails")
    def list_emails() -> list[IntakeRecord]:
        return resolved_service.store.list_records()

    @app.get("/v1/emails/{source_id}", summary="Get one processed email")
    def get_email(source_id: SourceIdParam) -> IntakeRecord:
        record = resolved_service.store.get(source_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Email '{source_id}' was not found.",
            )
        return record

    @app.post("/v1/inbox/scan", summary="Process the inbox folder once")
    def scan_inbox() -> list[IntakeResult]:
        return resolved_service.scan_inbox(resolved_settings.inbox_dir)

    return app
