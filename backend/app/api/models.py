"""Pydantic request contracts shared by the HTTP API modules."""
from pydantic import BaseModel, Field


class XhsAttachmentRequest(BaseModel):
    url: str
    comment: str = ""


class ChatRequest(BaseModel):
    message: str
    request_id: str | None = None
    device_context_enabled: bool = False
    reply_mode: str = "auto"
    music_context: str = ""
    xhs_attachment: XhsAttachmentRequest | None = None


class MusicPlaylistAddRequest(BaseModel):
    song_id: int
    name: str
    artist: str = ""
    cover_url: str = ""


class MusicNowRequest(BaseModel):
    song_id: int
    name: str
    artist: str = ""
    position: float = 0
    duration: float = 0
    playing: bool = False


class XhsReadRequest(BaseModel):
    text: str
    use_cache: bool = True


class XhsSearchRequest(BaseModel):
    query: str
    num_notes: int = 6


class WeatherRequest(BaseModel):
    latitude: float
    longitude: float


class PushTokenRequest(BaseModel):
    token: str
    platform: str = "android"


class CalendarEventRequest(BaseModel):
    event_id: str
    title: str
    start: str
    end: str
    all_day: bool = False
    location: str = ""
    source: str = "system"


class CalendarEventsRequest(BaseModel):
    events: list[CalendarEventRequest]
    sync_start: str | None = None
    sync_end: str | None = None
    reconcile_system: bool = False


class TodoRequest(BaseModel):
    local_id: str
    title: str
    due_date: str
    done: bool = False
    remind_at: str | None = None
    repeat_rule: str | None = None


class TodosSyncRequest(BaseModel):
    todos: list[TodoRequest]


class HabitRequest(BaseModel):
    local_id: str
    title: str
    active_from: str = "1900-01-01"
    active_until: str | None = None
    completed_dates: list[str] = Field(default_factory=list)


class HabitsSyncRequest(BaseModel):
    habits: list[HabitRequest]


class HabitCheckinRequest(BaseModel):
    checked_date: str
    done: bool = True


class MobileStateRequest(BaseModel):
    value: object


class FocusSessionRequest(BaseModel):
    session_key: str
    started_at: str
    duration_seconds: int
    content: str = ""
    timer_mode: str = "countdown"


class FocusSessionsRequest(BaseModel):
    sessions: list[FocusSessionRequest]


class ProactiveSettingRequest(BaseModel):
    enabled: bool


class DietPreferencesRequest(BaseModel):
    likes: str = Field(default='', max_length=500)
    avoid: str = Field(default='', max_length=500)
    taste: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=500)


class PersonalizationSettingRequest(BaseModel):
    libra_name: str
    user_name: str
    libra_nickname: str
    user_nickname: str
    user_address: str
    met_at: str
    checkin_min_minutes: int
    checkin_max_minutes: int
    weather_reminder_enabled: bool
    state_update_enabled: bool
    user_diet_preferences: DietPreferencesRequest | None = None


class AppPresenceRequest(BaseModel):
    active: bool


class UserStatusUpdateRequest(BaseModel):
    status: str


class UserTimelineEventRequest(BaseModel):
    occurred_at: str
    description: str
    event_type: str = 'legacy'


class UserTimelineSyncRequest(BaseModel):
    events: list[UserTimelineEventRequest]


class ChunkSettingRequest(BaseModel):
    min_chars: int


class CallRequest(BaseModel):
    call_id: str


class CallInterruptRequest(BaseModel):
    call_id: str
    generation_id: str


class SharedMemoryPhotoRequest(BaseModel):
    message_id: int


class SharedMemoryLocationRequest(BaseModel):
    location_text: str = ""


class MomentRequest(BaseModel):
    content: str


class MemoryCommentRequest(BaseModel):
    content: str


class LetterRequest(BaseModel):
    content: str
    reply_to_id: int | None = None


class LetterFavoriteRequest(BaseModel):
    favorite: bool


class ReadingDiscussionRequest(BaseModel):
    message: str = ""
    advance: bool = False
    chunk_id: str = ""
    section_index: int | None = None
