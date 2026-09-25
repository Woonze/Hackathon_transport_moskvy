from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from . import config


class Granularity(str, Enum):
    day = "day"
    hour = "hour"
    month = "month"


class Kind(str, Enum):
    forecast = "forecast"
    history = "history"


class ExportFormat(str, Enum):
    csv = "csv"
    xlsx = "xlsx"


class HourPoint(BaseModel):
    route: int
    date: str
    hour: int
    passengers: int


class DayPoint(BaseModel):
    route: int
    date: str
    passengers: int


class MonthPoint(BaseModel):
    route: int
    month: str
    passengers: int


class RouteInfo(BaseModel):
    id: int
    name: str
    historical_total: int
    forecast_total: int


class WeekdayAverage(BaseModel):
    route: int
    weekday: int
    passengers: float


class ErrorBody(BaseModel):
    detail: str
    code: str


SERIES_DOC = {
    200: {"model": list[HourPoint | DayPoint | MonthPoint], "description": "Точки ряда; поля зависят от granularity"},
    404: {"model": ErrorBody, "description": "Маршрут не найден"},
    422: {"model": ErrorBody, "description": "Некорректные параметры"},
}


class Factors(BaseModel):
    """Глобальные множители: итоговый = weather × event × season."""

    weather: float = Field(1.0, ge=0.5, le=1.5, description="Погода")
    event: float = Field(1.0, ge=0.5, le=1.5, description="Событие")
    season: float = Field(1.0, ge=0.5, le=1.5, description="Сезон")


class Rule(BaseModel):
    """Точечная поправка: период, часы и (необязательно) маршруты."""

    start: date
    end: date
    factor: float = Field(ge=0.1, le=3.0)
    hour_from: int = Field(0, ge=0, le=23)
    hour_to: int = Field(23, ge=0, le=23)
    routes: list[int] | None = None
    label: str | None = Field(None, max_length=80)

    @model_validator(mode="after")
    def _order(self):
        if self.start > self.end:
            raise ValueError("дата начала правила позже даты окончания")
        if self.hour_from > self.hour_to:
            raise ValueError("час начала правила позже часа окончания")
        return self


class AdjustRequest(BaseModel):
    start: date = config.FORECAST_START
    end: date = config.FORECAST_END
    route: int | None = None
    granularity: Granularity = Granularity.day
    factors: Factors = Factors()
    rules: list[Rule] = Field(default_factory=list, max_length=20)
    calendar: bool = Field(False, description="Производственный календарь РФ уже учтён в обученной ML-модели; дополнительный множитель к таким прогнозам не применяется")
    regime: bool = Field(False, description="Учесть структурные сдвиги режима «маршрут × день недели» (например, отмена выходных рейсов)")
    weather_auto: bool = Field(False, description="Учесть погоду по архиву Open-Meteo: осадки и снегопад умножаются на измеренные коэффициенты")


class IngestRequest(BaseModel):
    """Пакет сырых валидаций. Обязательные поля записи: tran_date_time, validation_result, ngpt_route."""

    records: list[dict] = Field(min_length=1, max_length=config.INGEST_MAX_RECORDS)
    batch_id: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[\w.\-]+$", description="Ключ идемпотентности; по умолчанию — хеш содержимого")
    complete: bool = Field(False, description="Записи завершают все даты пакета: остальные часы этих дат считаются нулевыми при обучении ML")
