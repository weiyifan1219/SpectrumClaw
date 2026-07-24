"""HTTP API for the low-altitude spectrum simulator control surface."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse

from ..skills.uav_spectrum_sim.runtime import (
    GAZEBO_GUI_VNC_PORT,
    camera_frame_path,
    execute_vehicle_command,
    disable_manual_control,
    get_live_snapshot,
    get_runtime_status,
    issue_manual_control_session,
    manual_control_session_valid,
    set_manual_control,
    write_manual_control_intent,
    start_gui_session,
    start_simulation,
    stop_gui_session,
    stop_simulation,
)


router = APIRouter(prefix="/api/uav-spectrum-sim")


class VehicleCommandRequest(BaseModel):
    altitude_m: float | None = Field(default=None, ge=1.0, le=20.0)


class ManualControlRequest(BaseModel):
    session_token: str | None = Field(default=None, min_length=16, max_length=128)
    forward: float = Field(default=0.0, ge=-1.0, le=1.0)
    right: float = Field(default=0.0, ge=-1.0, le=1.0)
    up: float = Field(default=0.0, ge=-1.0, le=1.0)
    yaw: float = Field(default=0.0, ge=-1.0, le=1.0)


@router.get("/status")
def status():
    return get_runtime_status()


@router.post("/start")
def start():
    try:
        return start_simulation()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop")
def stop():
    return stop_simulation()


@router.post("/gui/start")
def start_gui():
    try:
        return start_gui_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/gui/stop")
def stop_gui():
    return stop_gui_session()


@router.post("/control/{action}")
def control_vehicle(action: str, request: VehicleCommandRequest | None = None):
    if action not in {"status", "arm", "takeoff", "hover", "land", "return_to_launch"}:
        raise HTTPException(status_code=404, detail="未知的无人机仿真控制指令")
    try:
        return execute_vehicle_command(action, request.altitude_m if request else None)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/manual/enable")
def enable_manual_control():
    try:
        session_token = issue_manual_control_session()
        result = set_manual_control(True)
        return {**result, "session_token": session_token}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/manual/input")
def update_manual_control(request: ManualControlRequest):
    if not manual_control_session_valid(request.session_token):
        raise HTTPException(status_code=409, detail="遥控会话已失效，请重新启用 WASD 遥控")
    try:
        return set_manual_control(True, request.forward, request.right, request.up, request.yaw)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/manual/release")
def release_manual_control():
    try:
        return set_manual_control(True)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/manual/disable")
def stop_manual_control():
    try:
        return disable_manual_control()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.websocket("/live")
async def live_simulation_state(websocket: WebSocket):
    """Push compact simulator state to the locally rendered WebGL view."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(get_live_snapshot())
            # MJPEG owns visual smoothness.  Telemetry is metadata only, so
            # 5 Hz avoids forcing a full React operations page render for
            # every pose tick while retaining responsive state transitions.
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, RuntimeError):
        return


@router.websocket("/manual/live")
async def live_manual_control(websocket: WebSocket):
    """Receive low-latency browser control intents over one persistent socket.

    The WebSocket is deliberately limited to the same bounded velocity fields
    accepted by the HTTP fallback.  The sidecar remains the sole MAVLink owner.
    """
    runtime = get_runtime_status()["runtime"]
    if runtime["state"] != "running" or not runtime["manual"]["bridge_running"]:
        await websocket.close(code=1013, reason="PX4 manual control bridge is not ready")
        return
    if not manual_control_session_valid(websocket.query_params.get("token")):
        await websocket.close(code=1008, reason="manual control session is invalid")
        return
    await websocket.accept()
    try:
        while True:
            try:
                request = ManualControlRequest(**await websocket.receive_json())
            except (TypeError, ValueError):
                await websocket.send_json({"ok": False, "error": "遥控输入格式无效"})
                continue
            write_manual_control_intent(True, request.forward, request.right, request.up, request.yaw)
    except WebSocketDisconnect:
        return


@router.websocket("/gui/rfb")
async def relay_rfb(websocket: WebSocket):
    """Relay browser RFB traffic to loopback-only x11vnc on the simulator host."""
    gui = get_runtime_status()["runtime"]["gui"]
    if gui["state"] != "online":
        await websocket.close(code=1013, reason="Gazebo GUI is not ready")
        return
    # noVNC explicitly requests the ``binary`` WebSocket subprotocol.  The
    # browser rejects an upgrade response that omits it, even though the TCP
    # RFB relay itself is healthy.
    await websocket.accept(subprotocol="binary")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", GAZEBO_GUI_VNC_PORT)
    except OSError:
        await websocket.close(code=1013, reason="Gazebo GUI transport is unavailable")
        return

    async def browser_to_vnc():
        try:
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    return
                payload = event.get("bytes")
                if payload:
                    writer.write(payload)
                    await writer.drain()
        except WebSocketDisconnect:
            return

    async def vnc_to_browser():
        while payload := await reader.read(65536):
            await websocket.send_bytes(payload)

    tasks = [asyncio.create_task(browser_to_vnc()), asyncio.create_task(vnc_to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        writer.close()
        await writer.wait_closed()


@router.get("/camera/{direction}")
def camera_frame(direction: str):
    """Serve the latest JPEG emitted by the Gazebo sensor bridge."""
    if direction not in {"front", "rear", "left", "right", "down", "chase"}:
        raise HTTPException(status_code=404, detail="未知相机方向")
    path = camera_frame_path(direction)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Gazebo 相机尚未生成画面")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/camera/{direction}/stream")
async def camera_stream(direction: str):
    """Serve a persistent MJPEG stream so the main observer avoids polling."""
    if direction not in {"front", "rear", "left", "right", "down", "chase"}:
        raise HTTPException(status_code=404, detail="未知相机方向")
    path = camera_frame_path(direction)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Gazebo 相机尚未生成画面")

    async def frames():
        last_mtime_ns = 0
        while True:
            try:
                stat = path.stat()
                if stat.st_mtime_ns != last_mtime_ns:
                    payload = path.read_bytes()
                    if payload:
                        last_mtime_ns = stat.st_mtime_ns
                        header = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                        )
                        yield header + payload + b"\r\n"
            except FileNotFoundError:
                return
            await asyncio.sleep(0.02)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, max-age=0", "X-Accel-Buffering": "no"},
    )
