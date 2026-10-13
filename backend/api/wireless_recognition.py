from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ..memory.hooks import track_skill_run
from ..skills.wireless_recognition.service import (
    AnalysisBusy, CaptureChanged, UploadTooLarge, WirelessService, encode, get_wireless_service,
)

router = APIRouter(prefix="/api/wireless-recognition", tags=["wireless-recognition"])


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_sample: int = Field(0, ge=0)
    stop_sample: int | None = Field(None, gt=0)
    frequency_start_hz: float | None = Field(None, gt=0)
    frequency_stop_hz: float | None = Field(None, gt=0)
    sample_rate_hz: float | None = Field(None, gt=0, le=1e10)


def perform(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except UploadTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except AnalysisBusy as exc:
        raise HTTPException(429, str(exc)) from exc
    except CaptureChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OverflowError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/status")
def status(service: WirelessService = Depends(get_wireless_service)):
    return service.status()


@router.post("/scan")
def scan(service: WirelessService = Depends(get_wireless_service)):
    return perform(service.scan)


@router.get("/sessions")
def sessions(service: WirelessService = Depends(get_wireless_service)):
    return service.list_sessions()


@router.get("/records")
def records(limit: int = Query(500, ge=1, le=2000), session: str | None = None,
            offset: int = Query(0, ge=0), service: WirelessService = Depends(get_wireless_service)):
    return service.list_records(limit, session, offset)


@router.post("/upload")
def upload(file: UploadFile = File(...), sample_rate_hz: float | None = Form(None),
           service: WirelessService = Depends(get_wireless_service)):
    return perform(service.upload, file.file, file.filename or "capture.spec", sample_rate_hz)


@router.get("/waterfall")
def waterfall(session: str | None = None, limit: int = Query(128, ge=1, le=128),
              mode: int = Query(0, ge=0, le=1),
              sample_rate_hz: float | None = Query(None, gt=0, le=1e10),
              service: WirelessService = Depends(get_wireless_service)):
    return perform(service.waterfall, session, limit, mode, sample_rate_hz)


@router.get("/records/{record_id}/preview")
def preview(record_id: str, sample_rate_hz: float | None = Query(None, gt=0, le=1e10),
            service: WirelessService = Depends(get_wireless_service)):
    return perform(service.preview, record_id, sample_rate_hz)


@router.post("/records/{record_id}/analyze")
def analyze(record_id: str, request: AnalyzeRequest, service: WirelessService = Depends(get_wireless_service)):
    with track_skill_run("wireless_recognition", input_data={"record_id": record_id, **request.model_dump()}) as audit:
        result = perform(service.analyze, record_id, **request.model_dump())
        audit["output_summary"] = encode({"id": result["id"], "protocol": result["protocol"]["status"],
                                           "measurements": result["measurements"]})[:200]
        return result


@router.get("/analyses")
def analyses(service: WirelessService = Depends(get_wireless_service)):
    return service.list_analyses()


@router.get("/analyses/{analysis_id}")
def analysis(analysis_id: str, service: WirelessService = Depends(get_wireless_service)):
    return perform(service.get_analysis, analysis_id)


@router.get("/analyses/{analysis_id}/export")
def export(analysis_id: str, service: WirelessService = Depends(get_wireless_service)):
    result = perform(service.get_analysis, analysis_id)
    return Response(encode(result), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="wireless-{result["id"]}.json"'})
