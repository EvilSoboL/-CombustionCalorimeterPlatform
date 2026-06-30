from __future__ import annotations

import re


ATOMIZER_KIND_TO_CODE = {
    "Пар (V)": "V",
    "Воздух (A)": "A",
}
ATOMIZER_CODE_TO_KIND = {value: key for key, value in ATOMIZER_KIND_TO_CODE.items()}


def format_flow_value(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def build_regime_name(
    fuel_flow_kg_h: float,
    atomizer_code: str,
    atomizer_flow_kg_h: float,
    air_flow_kg_h: float | None = None,
) -> str:
    if fuel_flow_kg_h <= 0:
        raise ValueError("Расход топлива должен быть больше нуля")
    if atomizer_flow_kg_h <= 0:
        raise ValueError("Расход распылителя должен быть больше нуля")
    if air_flow_kg_h is not None and air_flow_kg_h <= 0:
        raise ValueError("Расход воздуха должен быть больше нуля")
    if atomizer_code not in ATOMIZER_CODE_TO_KIND:
        raise ValueError("Выберите тип распылителя")
    name = (
        f"F{format_flow_value(fuel_flow_kg_h)}"
        f"{atomizer_code}{format_flow_value(atomizer_flow_kg_h)}"
    )
    if air_flow_kg_h is not None:
        name += f"A{format_flow_value(air_flow_kg_h)}"
    return name


def parse_regime_name(value: str) -> tuple[float, str, float, float | None] | None:
    match = re.fullmatch(
        r"F(?P<fuel>\d+(?:\.\d+)?)(?P<atomizer>[VA])"
        r"(?P<atomizer_flow>\d+(?:\.\d+)?)(?:A(?P<air>\d+(?:\.\d+)?))?",
        value.strip(),
    )
    if match is None:
        return None
    air = match.group("air")
    return (
        float(match.group("fuel")),
        match.group("atomizer"),
        float(match.group("atomizer_flow")),
        float(air) if air is not None else None,
    )
