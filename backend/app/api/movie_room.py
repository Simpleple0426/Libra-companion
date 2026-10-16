import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class RoomChat(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    viewing_id: str | None = Field(default=None, max_length=100)


def build_movie_router(records, watch, solo, chat, review):
    router = APIRouter(prefix='/movie-room')

    @router.get('/messages')
    def messages(date: str | None = None, request_id: str | None = None, before: int | None = None, limit: int = Query(default=100, ge=1, le=200)):
        try:
            rows = records.messages(date, before, limit)
            receipt = records.chat_receipt(request_id) if request_id else None
            state = None
            if receipt:
                state = {'request_id': request_id, 'completed': receipt['replies'] is not None,
                         'messages': ([dict(id=receipt['message_id'], role='user', content=receipt['content'],
                                            request_id=request_id, viewing_id=receipt['viewing_id'], created_at=receipt['created_at'])]
                                      + (json.loads(receipt['replies']) if receipt['replies'] is not None else []))}
            return {'messages': rows, 'request_state': state, 'current': watch.current(),
                    'next_before': rows[0]['id'] if len(rows) == limit else None}
        except ValueError as error:
            raise HTTPException(400, '日期格式应为 YYYY-MM-DD') from error

    @router.post('/chat')
    def converse(body: RoomChat):
        if not body.message.strip():
            raise HTTPException(400, '消息不能为空')
        if body.viewing_id and not records.get(body.viewing_id):
            raise HTTPException(404, '未找到这次观影')
        try:
            return chat(body)
        except ValueError as error:
            raise HTTPException(409, '这条发送请求已经使用，请重新发送') from error

    @router.get('/library')
    def library():
        try:
            own = solo()
            available = True
        except Exception:
            own, available = [], False
        return {'solo': own, 'shared': records.viewings(), 'solo_available': available}

    @router.post('/viewings/{ident}/finish')
    def finish(ident: str):
        if not records.get(ident):
            raise HTTPException(404, '未找到这次观影')
        watch.finish(ident)
        review(ident)
        return {'success': True, 'viewing': records.get(ident)}

    return router
