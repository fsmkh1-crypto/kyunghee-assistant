"""Fetch model-based weather separately from the assistant's language model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
import json
import math
import re
import unicodedata
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlencode

DEFAULT_WEATHER_REGION = "세종시"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
SOURCE_NAME = "Open-Meteo"
SOURCE_URL = "https://open-meteo.com/en/docs"
KST = timezone(timedelta(hours=9))

_CURRENT_FIELDS = {
    "temperature_2m": "°C",
    "apparent_temperature": "°C",
    "relative_humidity_2m": "%",
    "precipitation": "mm",
    "weather_code": "wmo code",
    "wind_speed_10m": "km/h",
}
_DAILY_FIELDS = {
    "weather_code": "wmo code",
    "temperature_2m_min": "°C",
    "temperature_2m_max": "°C",
    "precipitation_probability_max": "%",
}
_CONDITIONS = {
    0: "맑음", 1: "대체로 맑음", 2: "부분적으로 흐림", 3: "흐림",
    45: "안개", 48: "착빙 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    56: "약한 어는 이슬비", 57: "강한 어는 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비", 66: "약한 어는 비", 67: "강한 어는 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈",
    80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    85: "약한 눈 소나기", 86: "강한 눈 소나기",
    95: "뇌우", 96: "약한 우박을 동반한 뇌우", 99: "강한 우박을 동반한 뇌우",
}


class WeatherError(RuntimeError):
    """A user-facing failure with no inferred or cached conditions."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class _Location:
    name: str
    latitude: float
    longitude: float


# Representative center points for the Korean metro areas. A Korean GeoNames
# text search for 대전 can otherwise match multiple unrelated rural settlements.
_METROS = (
    (_Location("세종시", 36.48, 127.28889), ("세종", "세종시", "세종특별자치시", "Sejong", "Sejong City")),
    (_Location("대전광역시", 36.34389, 127.39889), ("대전", "대전시", "대전광역시", "Daejeon", "Daejeon City")),
    (_Location("서울특별시", 37.55167, 126.99028), ("서울", "서울시", "서울특별시", "Seoul", "Seoul City")),
    (_Location("부산광역시", 35.16444, 129.06556), ("부산", "부산시", "부산광역시", "Busan", "Busan City")),
    (_Location("대구광역시", 35.85417, 128.57417), ("대구", "대구시", "대구광역시", "Daegu", "Daegu City")),
    (_Location("인천광역시", 37.49194, 126.69111), ("인천", "인천시", "인천광역시", "Incheon", "Incheon City")),
    (_Location("울산광역시", 35.54722, 129.34167), ("울산", "울산시", "울산광역시", "Ulsan", "Ulsan City")),
    (_Location("광주광역시", 35.15194, 126.86861), ("광주광역시", "Gwangju Metropolitan City")),
)


@dataclass(frozen=True)
class CurrentWeather:
    time: str
    temperature_c: float | None
    feels_like_c: float | None
    humidity_percent: float | None
    precipitation_mm: float | None
    interval_seconds: int | None
    condition: str | None
    wind_kmh: float | None


@dataclass(frozen=True)
class DailyWeather:
    date: str
    condition: str | None
    low_c: float | None
    high_c: float | None
    precipitation_chance_percent: float | None


@dataclass(frozen=True)
class WeatherReport:
    region: str
    queried_at: str
    current: CurrentWeather
    daily: tuple[DailyWeather, ...]
    source_name: str = SOURCE_NAME
    source_url: str = SOURCE_URL

    def format_text(self) -> str:
        current = self.current
        values = [current.condition] if current.condition else []
        if current.temperature_c is not None:
            values.append(f"기온 {current.temperature_c:g}°C")
        if current.feels_like_c is not None:
            values.append(f"체감 {current.feels_like_c:g}°C")
        if current.humidity_percent is not None:
            values.append(f"습도 {current.humidity_percent:g}%")
        if current.precipitation_mm is not None:
            period = ""
            if current.interval_seconds and current.interval_seconds % 60 == 0:
                period = f"{current.interval_seconds // 60}분 "
            values.append(f"{period}강수량 {current.precipitation_mm:g}mm")
        if current.wind_kmh is not None:
            values.append(f"풍속 {current.wind_kmh:g}km/h")
        observed = datetime.fromisoformat(current.time).isoformat(sep=" ", timespec="minutes")
        lines = [
            f"{self.region} 날씨",
            "현재 " + ", ".join(values),
            f"자료 기준 {observed} (기상 모델)",
        ]
        for day in self.daily:
            values = [day.condition] if day.condition else []
            if day.low_c is not None:
                values.append(f"최저 {day.low_c:g}°C")
            if day.high_c is not None:
                values.append(f"최고 {day.high_c:g}°C")
            if day.precipitation_chance_percent is not None:
                values.append(f"최대 강수확률 {day.precipitation_chance_percent:g}%")
            lines.append(f"{day.date} 예보 " + (", ".join(values) if values else "자료 없음"))
        if not self.daily:
            lines.append("일별 예보 자료를 받지 못했어요.")
        queried = datetime.fromisoformat(self.queried_at).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        lines.extend((f"조회 시각 {queried}", f"출처 {self.source_name} {self.source_url}"))
        return "\n".join(lines)

    @property
    def summary(self) -> str:
        return self.format_text()

    def to_tool_result(self) -> dict:
        return {
            "ok": True,
            "region": self.region,
            "queried_at": self.queried_at,
            "source": {"name": self.source_name, "url": self.source_url},
            "current": asdict(self.current),
            "daily": [asdict(day) for day in self.daily],
            "summary": self.format_text(),
        }


def _normal(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _location_name(value: str) -> str:
    return re.sub(r"(?<=[가-힣]{2})(?:특별자치시|특별시|광역시|시)$", "", _normal(value))


_METRO_ALIASES = {_normal(alias): location for location, aliases in _METROS for alias in aliases}
_US_STATES = dict(zip(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split(),
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia".split("|"),
))


def _safe_label(value: object) -> str:
    if not isinstance(value, str) or any(unicodedata.category(ch)[0] == "C" for ch in value):
        return ""
    return " ".join(value.split())[:80]


def _place_from_result(row: dict) -> _Location | None:
    latitude = _number(row.get("latitude"), -90, 90)
    longitude = _number(row.get("longitude"), -180, 180)
    name = _safe_label(row.get("name"))
    if latitude is None or longitude is None or not name:
        return None
    parts = [name]
    for field in ("admin2", "admin1", "country"):
        label = _safe_label(row.get(field))
        if label and _location_name(label) not in {_location_name(part) for part in parts}:
            parts.append(label)
    return _Location(", ".join(parts), latitude, longitude)


def _number(value, minimum, maximum) -> float | None:
    if type(value) not in (int, float) or not minimum <= value <= maximum or not math.isfinite(value):
        return None
    return float(value)


def _measure(values, units, expected, field, minimum, maximum):
    unit = units.get(field)
    if not isinstance(unit, str) or unit.casefold() != expected[field].casefold():
        return None
    return _number(values.get(field), minimum, maximum)


def _condition(values, units, expected) -> str | None:
    code = _measure(values, units, expected, "weather_code", 0, 99)
    return _CONDITIONS.get(code)


def _object(value):
    return value if isinstance(value, dict) else {}


def _entries(value):
    return value if isinstance(value, list) else []


class WeatherService:
    """Use Open-Meteo's no-key, non-commercial API and disclose its source."""

    def __init__(self, *, transport=None, clock=None, timeout=8.0):
        self._open = transport if transport is not None else build_opener(_NoRedirect()).open
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._timeout = timeout

    def _fetch(self, base: str, params: dict) -> dict:
        request = Request(base + "?" + urlencode(params), headers={"Accept": "application/json"})
        try:
            with self._open(request, timeout=self._timeout) as response:
                raw = response.read(1_048_577)
        except (OSError, HTTPException) as exc:
            raise WeatherError("기상정보 서버에 연결하지 못했어요. 잠시 뒤 다시 조회해 주세요.") from exc
        try:
            payload = json.loads(raw) if len(raw) <= 1_048_576 else None
        except (ValueError, RecursionError):
            payload = None
        if not isinstance(payload, dict) or payload.get("error"):
            raise WeatherError("기상정보 서버의 응답을 확인할 수 없어요.")
        return payload

    def _locate(self, region: str) -> _Location:
        parts = [part.strip() for part in region.split(",")]
        primary = parts[0]
        qualifier = parts[1] if len(parts) > 1 else ""
        country = parts[2] if len(parts) == 3 else ""
        separator = len(parts) > 1
        metro = _METRO_ALIASES.get(_normal(primary))
        if (metro and (not separator or _normal(qualifier) in {"kr", "south korea", "대한민국", "한국"})
                and (not country or _normal(country) in {"kr", "south korea", "대한민국", "한국"})):
            return metro
        if len(primary) < 2 or len(parts) > 3 or separator and not qualifier or len(parts) == 3 and not country:
            raise WeatherError("도시 이름을 두 글자 이상 적어 주세요. 지역을 좁히려면 ‘도시, 시·도 또는 국가’로 적어 주세요.")
        language = "ko" if re.search(r"[가-힣]", region) else "en"
        query = {"name": primary, "count": 100 if qualifier else 16, "language": language, "format": "json"}
        state = _US_STATES.get(qualifier.upper())
        if state is None:
            state = next((name for name in _US_STATES.values() if _normal(name) == _normal(qualifier)), None)
        if state and country and _normal(country) in {"us", "usa", "united states", "미국"}:
            query["countryCode"] = "US"
        elif not state and re.fullmatch(r"[A-Za-z]{2}", country or qualifier):
            query["countryCode"] = (country or qualifier).upper()
        payload = self._fetch(GEOCODING_URL, query)
        exact = []
        for row in _entries(payload.get("results")):
            if not isinstance(row, dict):
                continue
            if _location_name(_safe_label(row.get("name"))) != _location_name(primary):
                continue
            labels = {_normal(_safe_label(row.get(key))) for key in ("admin1", "admin2", "country", "country_code")}
            if qualifier:
                requested = {_normal(qualifier)}
                if state:
                    requested.add(_normal(state))
                # Country codes and US state codes can overlap (CA/California).
                # Match actual provider geography and ask if both are present.
                if qualifier.upper() == "CA":
                    requested.add("canada")
                if not requested.intersection(labels):
                    continue
            if country:
                requested_country = {_normal(country)}
                if _normal(country) in {"us", "usa", "united states", "미국"}:
                    requested_country.update(("us", "united states"))
                if country.upper() == "CA":
                    requested_country.add("canada")
                if not requested_country.intersection(labels):
                    continue
            place = _place_from_result(row)
            if place is not None and place not in exact:
                exact.append(place)
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            names = "\n".join(dict.fromkeys(place.name for place in exact[:3]))
            raise WeatherError(f"같은 이름의 지역이 여러 곳이에요. ‘도시, 시·도 또는 국가’로 좁혀 주세요.\n{names}")
        raise WeatherError("지역을 정확히 찾지 못했어요. 도시 이름과 시·도 또는 국가를 확인해 주세요.")

    def lookup(self, region: str | None = None, *, days: int = 3) -> WeatherReport:
        if region is None:
            region = DEFAULT_WEATHER_REGION
        if not isinstance(region, str) or not 2 <= len(region.strip()) <= 80 or not _safe_label(region):
            raise WeatherError("조회할 도시 이름을 2~80자로 입력해 주세요.")
        if type(days) is not int or not 1 <= days <= 7:
            raise WeatherError("1일부터 7일까지의 날씨를 조회할 수 있어요.")
        place = self._locate(unicodedata.normalize("NFKC", _safe_label(region)))
        params = {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "timezone": "auto",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "current": ",".join(_CURRENT_FIELDS),
            "daily": ",".join(_DAILY_FIELDS),
            "forecast_days": days,
        }
        payload = self._fetch(FORECAST_URL, params)
        queried = self._clock().astimezone(KST)
        current, observed = self._parse_current(payload, queried)
        daily = self._parse_daily(payload, observed.date(), days)
        source_url = SOURCE_URL + "?" + urlencode({"latitude": place.latitude, "longitude": place.longitude})
        return WeatherReport(place.name, queried.isoformat(timespec="seconds"), current, daily, source_url=source_url)

    @staticmethod
    def _parse_current(payload: dict, queried: datetime) -> tuple[CurrentWeather, datetime]:
        data = _object(payload.get("current"))
        units = _object(payload.get("current_units"))
        try:
            observed = datetime.fromisoformat(data.get("time", ""))
            if observed.utcoffset() is None:
                seconds = payload.get("utc_offset_seconds")
                if type(seconds) is not int or not -86_400 < seconds < 86_400:
                    raise ValueError
                observed = observed.replace(tzinfo=timezone(timedelta(seconds=seconds)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise WeatherError("현재 날씨의 자료 기준 시각을 확인할 수 없어요.") from exc
        if not -timedelta(minutes=30) <= queried - observed <= timedelta(hours=3):
            raise WeatherError("최신 날씨 자료를 받지 못했어요. 잠시 뒤 다시 조회해 주세요.")
        measure = lambda field, low, high: _measure(data, units, _CURRENT_FIELDS, field, low, high)
        interval = data.get("interval")
        if type(interval) is not int or not 0 < interval <= 3600:
            interval = None
        current = CurrentWeather(
            observed.isoformat(timespec="minutes"),
            measure("temperature_2m", -100, 100),
            measure("apparent_temperature", -120, 120),
            measure("relative_humidity_2m", 0, 100),
            measure("precipitation", 0, 5000),
            interval,
            _condition(data, units, _CURRENT_FIELDS),
            measure("wind_speed_10m", 0, 500),
        )
        if current.temperature_c is None and current.condition is None:
            raise WeatherError("현재 날씨 자료를 받지 못했어요. 잠시 뒤 다시 조회해 주세요.")
        return current, observed

    @staticmethod
    def _parse_daily(payload: dict, today: date, days: int) -> tuple[DailyWeather, ...]:
        data = _object(payload.get("daily"))
        units = _object(payload.get("daily_units"))
        series = {field: _entries(data.get(field)) for field in _DAILY_FIELDS}
        forecasts = []
        seen = set()
        for index, value in enumerate(_entries(data.get("time"))[:days]):
            try:
                day = date.fromisoformat(value)
            except (TypeError, ValueError):
                continue
            if day in seen or not 0 <= (day - today).days < days:
                continue
            seen.add(day)
            row = {field: values[index] for field, values in series.items() if index < len(values)}
            low = _measure(row, units, _DAILY_FIELDS, "temperature_2m_min", -100, 100)
            high = _measure(row, units, _DAILY_FIELDS, "temperature_2m_max", -100, 100)
            if low is not None and high is not None and low > high:
                low = high = None
            forecasts.append(DailyWeather(
                day.isoformat(), _condition(row, units, _DAILY_FIELDS), low, high,
                _measure(row, units, _DAILY_FIELDS, "precipitation_probability_max", 0, 100),
            ))
        return tuple(forecasts)
