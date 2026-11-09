import copy
from datetime import datetime, timezone
import io
import json
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from assistant_ai.weather import (
    DEFAULT_WEATHER_REGION, FORECAST_URL, GEOCODING_URL, WeatherError, WeatherService,
)


NOW = datetime(2026, 11, 9, 3, 34, 56, tzinfo=timezone.utc)
FORECAST = {
    "utc_offset_seconds": 32400,
    "current_units": {
        "time": "iso8601", "interval": "seconds", "temperature_2m": "°C",
        "apparent_temperature": "°C", "relative_humidity_2m": "%", "precipitation": "mm",
        "weather_code": "wmo code", "wind_speed_10m": "km/h",
    },
    "current": {
        "time": "2026-11-09T12:30", "interval": 900, "temperature_2m": 11.4,
        "apparent_temperature": 8, "relative_humidity_2m": 65, "precipitation": 0,
        "weather_code": 1, "wind_speed_10m": 7.2,
    },
    "daily_units": {
        "time": "iso8601", "weather_code": "wmo code", "temperature_2m_min": "°C",
        "temperature_2m_max": "°C", "precipitation_probability_max": "%",
    },
    "daily": {
        "time": ["2026-11-09", "2026-11-10", "2026-11-11"],
        "weather_code": [1, 61, 3], "temperature_2m_min": [6.1, 7, 4.5],
        "temperature_2m_max": [13, 12.5, 14], "precipitation_probability_max": [0, 89, 10],
    },
}


def location(name, latitude, longitude, *, country, area):
    return {"name": name, "latitude": latitude, "longitude": longitude, "country": country, "admin1": area}


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.forecast = copy.deepcopy(FORECAST)
        self.geo = {"results": []}

        def fetch(request, *, timeout):
            split = urlsplit(request.full_url)
            endpoint = f"{split.scheme}://{split.netloc}{split.path}"
            self.requests.append((endpoint, parse_qs(split.query), request.headers, timeout))
            payload = self.forecast if endpoint == FORECAST_URL else self.geo
            if isinstance(payload, Exception):
                raise payload
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        self.service = WeatherService(transport=fetch, clock=lambda: NOW)

    def test_default_sejong_fetches_forecast_without_geocoding(self):
        self.assertEqual(self.requests, [])
        report = self.service.lookup()
        self.assertEqual(report.region, DEFAULT_WEATHER_REGION)
        self.assertEqual(report.queried_at, "2026-11-09T12:34:56+09:00")
        self.assertEqual(report.current.time, "2026-11-09T12:30+09:00")
        self.assertEqual(report.daily[1].condition, "약한 비")
        self.assertEqual(report.daily[1].precipitation_chance_percent, 89)
        self.assertEqual(report.current.precipitation_mm, 0)
        self.assertIn("15분 강수량 0mm", report.format_text())
        self.assertIn("조회 시각 2026-11-09 12:34:56 KST", report.format_text())
        self.assertIn("출처 Open-Meteo https://open-meteo.com/", report.format_text())
        data = report.to_tool_result()
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"]["url"], report.source_url)
        self.assertEqual(data["daily"][1]["low_c"], 7)
        self.assertEqual(len(self.requests), 1)
        endpoint, query, headers, timeout = self.requests[0]
        self.assertEqual(endpoint, FORECAST_URL)
        self.assertEqual(query["latitude"], ["36.48"])
        self.assertEqual(query["longitude"], ["127.28889"])
        self.assertEqual(query["forecast_days"], ["3"])
        self.assertEqual(headers, {"Accept": "application/json"})
        self.assertEqual(timeout, 8.0)

    def test_daejeon_is_resolved_to_metro_not_rural_namesake(self):
        report = self.service.lookup("대전", days=1)
        self.assertEqual(report.region, "대전광역시")
        self.assertEqual(self.requests[0][1]["latitude"], ["36.34389"])
        self.assertEqual(len(report.daily), 1)

    def test_ambiguous_location_requests_country_without_forecast(self):
        self.geo["results"] = [
            location("London", 51.5, -0.12, country="United Kingdom", area="England"),
            location("London", 42.98, -81.24, country="Canada", area="Ontario"),
        ]
        with self.assertRaisesRegex(WeatherError, "여러 곳") as raised:
            self.service.lookup("London")
        self.assertIn("Ontario", str(raised.exception))
        self.assertEqual([req[0] for req in self.requests], [GEOCODING_URL])

    def test_foreign_country_qualifier_uses_provider_country_filter(self):
        self.geo["results"] = [location("London", 42.98, -81.24, country="Canada", area="Ontario")]
        self.forecast["utc_offset_seconds"] = -18000
        self.forecast["current"]["time"] = "2026-11-08T22:30"
        self.forecast["daily"]["time"] = ["2026-11-08", "2026-11-09", "2026-11-10"]
        result = self.service.lookup("London, CA")
        self.assertEqual(result.current.time, "2026-11-08T22:30-05:00")
        self.assertEqual(result.daily[0].date, "2026-11-08")
        self.assertEqual(self.requests[0][1]["countryCode"], ["CA"])
        self.assertEqual(self.requests[0][1]["name"], ["London"])
        self.assertEqual(self.requests[1][1]["longitude"], ["-81.24"])

    def test_fuzzy_city_is_never_silently_substituted(self):
        self.geo["results"] = [location("Seoul", 37.55, 127.0, country="South Korea", area="Seoul")]
        with self.assertRaisesRegex(WeatherError, "정확히 찾지 못했어요"):
            self.service.lookup("Seouls")
        self.assertEqual(len(self.requests), 1)

    def test_network_error_never_returns_a_synthetic_report(self):
        self.forecast = URLError("internal trace with credential")
        with self.assertRaises(WeatherError) as raised:
            self.service.lookup()
        self.assertIn("연결하지 못했어요", str(raised.exception))
        self.assertNotIn("credential", str(raised.exception))

    def test_stale_response_rejected(self):
        self.forecast["current"]["time"] = "2026-11-09T01:00"
        with self.assertRaisesRegex(WeatherError, "최신 날씨 자료"):
            self.service.lookup()

    def test_missing_and_mislabeled_measurements_are_not_invented(self):
        self.forecast["current_units"]["wind_speed_10m"] = "mph"
        self.forecast["current"]["apparent_temperature"] = None
        self.forecast["daily"]["precipitation_probability_max"] = [None, 101, -1]
        report = self.service.lookup()
        self.assertIsNone(report.current.wind_kmh)
        self.assertIsNone(report.current.feels_like_c)
        self.assertTrue(all(day.precipitation_chance_percent is None for day in report.daily))
        self.assertNotIn("체감", report.summary)
        self.assertNotIn("강수확률", report.summary)

    def test_malformed_response_and_invalid_region_raise_safe_error(self):
        for region in ("", "가", "서울\n부산", "a" * 81, 10):
            with self.subTest(region=region), self.assertRaises(WeatherError):
                self.service.lookup(region)
        self.assertEqual(self.requests, [])
        self.forecast = {"current": {"time": "not a date"}, "current_units": {}}
        with self.assertRaisesRegex(WeatherError, "자료 기준 시각"):
            self.service.lookup()


if __name__ == "__main__":
    unittest.main()
