from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Regime:
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Название режима не может быть пустым")
        if self.end <= self.start:
            raise ValueError("Конец режима должен быть позже начала")


@dataclass(frozen=True)
class ProcessingSettings:
    experiment_name: str
    water_liters_per_pulse: float | None = None
    fuel_flow_coefficient_l_min_per_v: float | None = None
    fuel_flow_zero_v: float = 0.0
    density_kg_m3: float = 1000.0
    heat_capacity_j_kg_c: float = 4184.0

    def __post_init__(self) -> None:
        if not self.experiment_name.strip():
            raise ValueError("Название эксперимента не может быть пустым")
        if self.water_liters_per_pulse is not None and self.water_liters_per_pulse <= 0:
            raise ValueError("Объем воды на импульс должен быть больше нуля")
        if (
            self.fuel_flow_coefficient_l_min_per_v is not None
            and self.fuel_flow_coefficient_l_min_per_v == 0
        ):
            raise ValueError("Коэффициент расхода топлива не может быть равен нулю")
        if self.density_kg_m3 <= 0:
            raise ValueError("Плотность должна быть больше нуля")
        if self.heat_capacity_j_kg_c <= 0:
            raise ValueError("Теплоемкость должна быть больше нуля")


@dataclass
class GasData:
    timestamps: list[datetime]
    columns: dict[str, list[float | None]]
    sheet_name: str

    @property
    def start(self) -> datetime:
        return self.timestamps[0]

    @property
    def end(self) -> datetime:
        return self.timestamps[-1]


@dataclass
class OscilloscopeData:
    timestamps: list[datetime]
    elapsed_seconds: list[float]
    channels: list[list[float]]
    experiment_start: datetime
    source_name: str

    @property
    def start(self) -> datetime:
        return self.timestamps[0]

    @property
    def end(self) -> datetime:
        return self.timestamps[-1]


@dataclass
class RegimeResult:
    base: dict[str, object]
    gas_statistics: dict[str, tuple[float, float, int]]
