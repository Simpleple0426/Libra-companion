"""Authenticated co-viewing API. No CORS or raw user-message ingestion."""
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field


class Start(BaseModel):
    title: str = Field(default="", max_length=200)
    frequency: Literal['quiet', 'normal', 'chatty'] = 'normal'


class Control(BaseModel):
    session_id: str = Field(max_length=100)
    action: Literal['heartbeat', 'pause', 'resume', 'stop', 'resync']


class SubtitleCue(BaseModel):
    start: float = Field(ge=0, le=360000, allow_inf_nan=False)
    end: float = Field(ge=0, le=360000, allow_inf_nan=False)
    text: str = Field(max_length=2000)


class Observation(BaseModel):
    session_id: str = Field(max_length=100)
    sequence: int = Field(ge=0)
    frame: str = Field(max_length=2_000_000)
    position: float | None = Field(default=None, ge=0, le=360000, allow_inf_nan=False)
    subtitles: list[SubtitleCue] = Field(default_factory=list, max_length=500)
    timeline_revision: int | None = Field(default=None, ge=0)


def build_watch_router(service, token_path):
    def authorize(authorization: str = Header(default="")):
        try:
            token = token_path.read_text(encoding='utf-8').strip()
        except OSError:
            token = ''
        if not token or not secrets.compare_digest(authorization, 'Bearer ' + token):
            raise HTTPException(401, "陪看连接码不正确或尚未配置")

    router = APIRouter(prefix='/watch-together', dependencies=[Depends(authorize)])

    @router.get('/status')
    def status():
        return {'ready': True}

    @router.post('/start')
    def start(body: Start):
        return service.start(body.title, body.frequency)

    @router.post('/control')
    def control(body: Control):
        try:
            return service.control(body.session_id, body.action)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.post('/observe')
    def observe(body: Observation):
        try:
            return service.observe(body.session_id, body.sequence, body.frame,
                body.position, [cue.model_dump() for cue in body.subtitles], body.timeline_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    return router
