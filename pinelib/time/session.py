from __future__ import annotations

import re
from dataclasses import dataclass

from pinelib.errors import PL_SESSION_INVALID, PineRuntimeError
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.time.calendar import from_unix_ms

_SEGMENT_RE = re.compile(
    r"^(?P<start>[0-2][0-9][0-5][0-9])-(?P<end>[0-2][0-9][0-5][0-9])$"
)


@dataclass(frozen=True, slots=True)
class SessionSegment:
    start_minute: int
    end_minute: int

    @property
    def overnight(self) -> bool:
        return self.end_minute <= self.start_minute


@dataclass(frozen=True, slots=True)
class SessionSpec:
    raw: str
    segments: tuple[SessionSegment, ...]
    days: frozenset[int]

    def contains(self, timestamp_ms: int, timezone_name: str) -> bool:
        local = from_unix_ms(timestamp_ms, timezone_name)
        pine_day = ((local.weekday() + 1) % 7) + 1
        minute_of_day = local.hour * 60 + local.minute
        previous_day = ((pine_day + 5) % 7) + 1
        for segment in self.segments:
            if segment.start_minute == segment.end_minute:
                if pine_day in self.days:
                    return True
            elif not segment.overnight:
                if (
                    pine_day in self.days
                    and segment.start_minute <= minute_of_day < segment.end_minute
                ):
                    return True
            else:
                if minute_of_day >= segment.start_minute and pine_day in self.days:
                    return True
                if minute_of_day < segment.end_minute and previous_day in self.days:
                    return True
        return False


def parse_session(raw: str, language: RuntimeLanguageContext) -> SessionSpec:
    text = raw.strip()
    if text.lower() == "24x7":
        return SessionSpec(raw, (SessionSegment(0, 0),), frozenset(range(1, 8)))
    if not text:
        raise PineRuntimeError("session string is empty", code=PL_SESSION_INVALID)
    if ":" in text:
        times, day_text = text.rsplit(":", 1)
        if not day_text or any(character not in "1234567" for character in day_text):
            raise PineRuntimeError("invalid session day set", code=PL_SESSION_INVALID)
        days = frozenset(int(character) for character in day_text)
    else:
        times = text
        days = frozenset({2, 3, 4, 5, 6} if language.pine_version <= 4 else range(1, 8))
    segments: list[SessionSegment] = []
    for item in times.split(","):
        match = _SEGMENT_RE.fullmatch(item)
        if not match:
            raise PineRuntimeError(
                f"invalid session segment: {item}", code=PL_SESSION_INVALID
            )
        start_text = match.group("start")
        end_text = match.group("end")
        start_hour = int(start_text[:2])
        end_hour = int(end_text[:2])
        if start_hour > 23 or end_hour > 23:
            raise PineRuntimeError("session hour exceeds 23", code=PL_SESSION_INVALID)
        segments.append(
            SessionSegment(
                start_hour * 60 + int(start_text[2:]),
                end_hour * 60 + int(end_text[2:]),
            )
        )
    return SessionSpec(raw, tuple(segments), days)
