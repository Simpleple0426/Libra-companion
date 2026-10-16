"""Canonical application-tool contracts; authorization remains in domain adapters."""
from dataclasses import dataclass
from datetime import datetime
from inspect import Parameter, Signature
import math
import re


@dataclass(frozen=True)
class Field:
    types: tuple
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    nonempty: bool = False
    choices: tuple | None = None
    pattern: str | None = None
    max_length: int | None = None

    def validate(self, value):
        if not isinstance(value, self.types):
            return False
        if isinstance(value, bool) and bool not in self.types:
            return False
        if self.choices is not None and value not in self.choices:
            return False
        if self.pattern is not None and (not isinstance(value, str) or not re.fullmatch(self.pattern, value)):
            return False
        if self.max_length is not None and len(value) > self.max_length:
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                return False
            if self.minimum is not None and value < self.minimum:
                return False
            if self.maximum is not None and value > self.maximum:
                return False
        return not self.nonempty or bool(value.strip())


def field(*types, required=False, minimum=None, maximum=None, nonempty=False, choices=None, pattern=None, max_length=None):
    return Field(types, required, minimum, maximum, nonempty, choices, pattern, max_length)


TEXT = field(str)
QUERY = field(str, required=True, nonempty=True)
BOOL = field(bool)
COUNT = field(int, minimum=1, maximum=100000)
OPTIONAL_TEXT = field(str, type(None))
OPTIONAL_MAP = field(dict, type(None))
OPTIONAL_LIST = field(list, tuple, type(None))
ID = field(int, type(None), minimum=1)


@dataclass(frozen=True)
class ToolSpec:
    adapter: str
    fields: dict
    result_types: tuple
    timeout_seconds: float = 30
    write: bool = False
    inline: bool = False

    def bind(self, args, kwargs):
        signature = Signature([
            Parameter(name, Parameter.POSITIONAL_OR_KEYWORD,
                      default=Parameter.empty if rule.required else None)
            for name, rule in self.fields.items()
        ])
        try:
            arguments = signature.bind(*args, **kwargs).arguments
        except TypeError:
            raise ValueError('invalid_tool_arguments') from None
        for name, value in arguments.items():
            if not self.fields[name].validate(value):
                raise ValueError('invalid_tool_argument:' + name)
        return dict(arguments)


RECALL = dict(thread_id=OPTIONAL_TEXT, recent_messages=field(list, tuple),
              budget=COUNT, query_plan=OPTIONAL_LIST)

TOOL_SPECS = {
    'diet.preferences': ToolSpec('read_diet_preferences', {}, (dict,), 10),
    'outing.prepare': ToolSpec('prepare_outing', {}, (dict,), 10, write=True),
    'rest.prepare': ToolSpec('prepare_rest', {}, (dict,), 10, write=True),
    'work.prepare': ToolSpec('prepare_work', {}, (dict,), 10, write=True),
    'television.prepare': ToolSpec('prepare_television', {}, (dict,), 10, write=True),
    'exercise.prepare': ToolSpec('prepare_exercise', {}, (dict,), 10, write=True),
    'housework.prepare': ToolSpec('prepare_housework', {}, (dict,), 10, write=True),
    'care.prepare': ToolSpec('prepare_personal_care', {}, (dict,), 10, write=True),
    'meals.prepare': ToolSpec('prepare_meal', {}, (dict,), 180, write=True),
    'movies.search': ToolSpec('search_movies', dict(query=field(str,required=True,nonempty=True,max_length=120), count=field(int,required=True,minimum=1,maximum=8)), (list,), 30),
    'movies.detail': ToolSpec('movie_detail', dict(douban_id=field(str,required=True,pattern=r'\d{1,16}')), (dict,), 30),
    'movies.reviews': ToolSpec('movie_reviews', dict(douban_id=field(str,required=True,pattern=r'\d{1,16}'),count=field(int,required=True,minimum=1,maximum=8)), (list,), 30),
    'movies.chart': ToolSpec('movie_chart', dict(kind=field(str,required=True,choices=('top250','weekly','new')),count=field(int,required=True,minimum=1,maximum=8)), (list,), 30),
    'movies.add': ToolSpec('add_movie_candidate', dict(douban_id=field(str,required=True,pattern=r'\d{1,16}'),runtime_index=field(int,required=True,minimum=0)), (dict,), 35, write=True),
    'books.search': ToolSpec('search_books', dict(query=field(str,required=True,nonempty=True,max_length=200),count=field(int,required=True,minimum=1,maximum=8)), (list,), 30),
    'weread.search': ToolSpec('search_weread_books', dict(query=field(str,required=True,nonempty=True,max_length=200),count=field(int,required=True,minimum=1,maximum=8)), (list,), 30),
    'weread.info': ToolSpec('weread_book_info', dict(book_id=field(str,required=True,pattern=r'[A-Za-z0-9_-]{1,100}')), (dict,), 30),
    'weread.chapters': ToolSpec('weread_book_chapters', dict(book_id=field(str,required=True,pattern=r'[A-Za-z0-9_-]{1,100}')), (dict,), 30),
    'books.detail': ToolSpec('book_detail', dict(douban_id=field(str,required=True,pattern=r'\d{1,16}')), (dict,), 30),
    'quotes.fetch': ToolSpec('fetch_quote_page', dict(url=QUERY), (str,), 15),
    'quotes.book': ToolSpec('book_quotes', dict(work=field(dict,required=True)), (list,), 85),
    'quotes.wiki': ToolSpec('wiki_quotes', dict(work=field(dict,required=True),language=field(str,required=True,choices=('zh','en'))), (list,), 40),
    'quotes.collect': ToolSpec('collect_quotes', dict(work=field(dict,required=True)), (list,), 120),
    'emotion.await': ToolSpec('await_emotion', {}, (dict,), 300, inline=True),
    'memory.search': ToolSpec('search_personal_memory', dict(
        query=QUERY, **RECALL, limit=COUNT, graph_hops=field(int, minimum=0, maximum=10),
        query_expansion=BOOL, emotion_resonance=BOOL, literal_raw=BOOL,
        adaptive_search=BOOL, query_weights=OPTIONAL_MAP, channel_weights=OPTIONAL_MAP), (dict,), 60),
    'shared_history.search': ToolSpec('search_shared_history', dict(query=QUERY, **RECALL), (str,), 60),
    'shared_history.read': ToolSpec('read_shared_history', dict(chunk_id=QUERY), (dict,)),
    'character.search': ToolSpec('search_character', dict(query=QUERY, limit=COUNT,
        domains=OPTIONAL_LIST, relationship_stage=OPTIONAL_TEXT, intent=OPTIONAL_TEXT,
        appraisal=OPTIONAL_MAP), (list,), 60),
    'weather.fetch': ToolSpec('get_weather', dict(
        latitude=field(int, float, required=True, minimum=-90, maximum=90),
        longitude=field(int, float, required=True, minimum=-180, maximum=180),
        force_refresh=BOOL, include_reminder=BOOL), (dict,), 60),
    'weather.current': ToolSpec('_query_weather_agent', {}, (tuple,), 65),
    'libra.state': ToolSpec('get_libra_state_at', dict(at=field(datetime, type(None))), (dict, type(None))),
    'xiaohongshu.search': ToolSpec('search_xhs', dict(query=QUERY, source=TEXT,
        num_notes=field(int, minimum=1, maximum=50)), (dict,), 180),
    'xiaohongshu.read': ToolSpec('read_xhs_links', dict(text=QUERY, use_cache=BOOL, ocr=BOOL), (dict,), 300),
    'album.save': ToolSpec('_save_latest_user_photo_to_album', {}, (dict, type(None)), 30, True),
    'letter.request': ToolSpec('_write_requested_letter', dict(user_message=QUERY,
        source_message_id=field(int, required=True, minimum=1)), (type(None),), 300, True),
    'letter.write': ToolSpec('create_letter', dict(sender=QUERY, content=QUERY, subject=TEXT,
        reply_to_id=ID, letter_type=OPTIONAL_TEXT, trigger_reason=TEXT, trigger_key=TEXT,
        event_date=OPTIONAL_TEXT, memory_candidates=OPTIONAL_LIST, generation_source=TEXT,
        connection=field(object)), (dict,), 30, True),
    'device.context': ToolSpec('_device_status_summary', dict(include_private_device=BOOL,
        include_calendar=BOOL, calendar_days_before=field(int, minimum=0, maximum=366),
        calendar_days_ahead=field(int, minimum=0, maximum=366)), (str, type(None))),
    'world.followup_detail': ToolSpec('resolve_followup_detail', dict(
        connection=field(object, required=True), question=QUERY,
        state=field(dict, type(None), required=True), now=field(datetime, type(None))), (dict, type(None)), 30, True),
    'arrival.register': ToolSpec('arrival_register', dict(text=QUERY,
        message_id=field(int, type(None), required=True, minimum=1),
        trip=field(dict, type(None), required=True)), (str, bool, dict, type(None)), 30, True),
    'local.actions': ToolSpec('execute_local_actions', dict(context=field(dict, required=True)), (list,), 30, True),
}

RETRIEVAL_OPERATIONS = {name: TOOL_SPECS[name].adapter for name in (
    'memory.search', 'shared_history.search', 'shared_history.read', 'character.search')}
OPERATIONS = {name: spec.adapter for name, spec in TOOL_SPECS.items()}
