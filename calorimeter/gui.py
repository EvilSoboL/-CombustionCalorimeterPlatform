from __future__ import annotations

import math
import re
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import GasData, OscilloscopeData, PlcData, ProcessingSettings, Regime
from .processing import common_time_range, export_csv, gas_contains_minute, process_experiment
from .readers import read_gas_xlsx, read_oscilloscope_txt, read_plc_csv
from .regime_names import (
    ATOMIZER_CODE_TO_KIND,
    ATOMIZER_KIND_TO_CODE,
    build_regime_name,
    format_flow_value,
    parse_regime_name,
)
from .result_analysis import RegimeAnalysis, analyze_result_csv, export_analysis_csv


def parse_user_time(value: str, reference_date: date) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Выберите время в формате ЧЧ:ММ") from exc
    return datetime.combine(reference_date, parsed)


def _format_editor_time(value: datetime) -> str:
    if value.second or value.microsecond:
        return value.strftime("%H:%M:%S")
    return value.strftime("%H:%M")


def end_time_options_after_start(available_times: list[str], start_value: str) -> list[str]:
    try:
        start_time = datetime.strptime(start_value.strip(), "%H:%M").time()
    except ValueError:
        return list(available_times)
    result: list[str] = []
    for value in available_times:
        try:
            end_time = datetime.strptime(value, "%H:%M").time()
        except ValueError:
            continue
        if end_time > start_time:
            result.append(value)
    return result


def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _format_analysis_number(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        return ""
    return f"{value:.6g}"


class CalorimeterApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master = master
        self.gas_data: GasData | None = None
        self.temperature_data: OscilloscopeData | None = None
        self.water_flow_data: OscilloscopeData | None = None
        self.plc_data: PlcData | None = None
        self.regimes: list[Regime] = []
        self.available_minutes: list[str] = []

        self.gas_path = tk.StringVar()
        self.temperature_path = tk.StringVar()
        self.water_flow_path = tk.StringVar()
        self.plc_path = tk.StringVar()
        self.experiment_name = tk.StringVar()
        self.water_liters_per_pulse = tk.StringVar()
        self.cold_junction_temperature = tk.StringVar(value="25")
        self.density = tk.StringVar(value="1000")
        self.heat_capacity = tk.StringVar(value="4184")
        self.fuel_flow_kg_h = tk.StringVar()
        self.atomizer_kind = tk.StringVar(value="Пар (V)")
        self.atomizer_flow_kg_h = tk.StringVar()
        self.air_flow_kg_h = tk.StringVar()
        self.regime_name = tk.StringVar()
        self.regime_start = tk.StringVar()
        self.regime_end = tk.StringVar()
        self.source_summary = tk.StringVar(value="Файлы еще не загружены")
        self.status = tk.StringVar(
            value="Выберите XLSX газоанализатора. TXT датчиков можно добавить при необходимости."
        )
        self.analysis_csv_path = tk.StringVar()
        self.steam_inlet_temperature_c = tk.StringVar()
        self.steam_outlet_temperature_c = tk.StringVar()
        self.analysis_status = tk.StringVar(
            value="Выберите CSV, полученный на первой вкладке, и запустите анализ."
        )
        self.analysis_results: list[RegimeAnalysis] = []
        self._suspend_regime_name_update = False

        for variable in (
            self.fuel_flow_kg_h,
            self.atomizer_kind,
            self.atomizer_flow_kg_h,
            self.air_flow_kg_h,
        ):
            variable.trace_add("write", self._on_regime_flow_changed)

        self._build_ui()

    def _build_ui(self) -> None:
        self.grid(sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")
        processing_tab = ttk.Frame(notebook)
        analysis_tab = ttk.Frame(notebook)
        notebook.add(processing_tab, text="Обработка данных")
        notebook.add(analysis_tab, text="Анализ результата")

        self._build_processing_tab(processing_tab)
        self._build_analysis_tab(analysis_tab)

    def _build_processing_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        sources = ttk.LabelFrame(parent, text="1. Исходные данные", padding=10)
        sources.grid(row=0, column=0, sticky="ew")
        sources.columnconfigure(1, weight=1)
        self._file_row(
            sources,
            0,
            "Газоанализатор XLSX (обязательно)",
            self.gas_path,
            (("Excel XLSX", "*.xlsx"),),
        )
        self._file_row(
            sources,
            1,
            "Температура TXT (опционально, 2 канала)",
            self.temperature_path,
            (("TXT", "*.txt"),),
        )
        self._file_row(
            sources,
            2,
            "Расход воды TXT (опционально, 1 канал)",
            self.water_flow_path,
            (("TXT", "*.txt"),),
        )
        self._file_row(
            sources,
            3,
            "ПЛК CSV (опционально)",
            self.plc_path,
            (("CSV", "*.csv"),),
        )
        ttk.Button(sources, text="Загрузить и проверить", command=self._load_sources).grid(
            row=4, column=2, sticky="e", pady=(8, 0)
        )
        ttk.Label(sources, textvariable=self.source_summary, foreground="#284f73").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        settings = ttk.LabelFrame(parent, text="2. Калибровка и свойства теплоносителя", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=10)
        for column in (1, 3, 5):
            settings.columnconfigure(column, weight=1)
        self._entry(settings, 0, 0, "Название эксперимента", self.experiment_name, width=24)
        self._entry(settings, 0, 2, "Вода, л/импульс", self.water_liters_per_pulse)
        self._entry(settings, 0, 4, "Свободные концы термопары, °C", self.cold_junction_temperature)
        self._entry(settings, 1, 0, "Плотность воды, кг/м³", self.density)
        self._entry(settings, 1, 2, "Теплоемкость воды, Дж/(кг·°C)", self.heat_capacity)
        ttk.Label(
            settings,
            text=(
                "Дополнительные TXT/CSV-файлы необязательны: без них CSV будет содержать только XLSX. "
                "CSV ПЛК усредняется по тем же режимам, что и газоанализатор. "
                "Температура ТХА(K) считается по ГОСТ Р 8.585-2001; свободные концы — температура клемм/холодного спая. "
                "Если модуль уже скомпенсировал холодный спай к 0 °C, поставьте 0. "
                "Вода, л/импульс — паспортный объем за один импульс расходомера; если указан K в имп/л, введите 1/K. "
                "Плотность и теплоемкость нужны только для расчета тепла."
            ),
            foreground="#555555",
            wraplength=1040,
            justify="left",
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(7, 0))

        regimes_frame = ttk.LabelFrame(parent, text="3. Стационарные режимы", padding=10)
        regimes_frame.grid(row=2, column=0, sticky="nsew")
        regimes_frame.columnconfigure(0, weight=1)
        regimes_frame.rowconfigure(1, weight=1)

        editor = ttk.Frame(regimes_frame)
        editor.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5, 7):
            editor.columnconfigure(column, weight=1)
        self._entry(editor, 0, 0, "Топливо F, кг/ч", self.fuel_flow_kg_h, width=8)
        ttk.Label(editor, text="Распылитель").grid(
            row=0, column=2, sticky="w", padx=(0, 6), pady=3
        )
        self.atomizer_combo = ttk.Combobox(
            editor,
            textvariable=self.atomizer_kind,
            values=tuple(ATOMIZER_KIND_TO_CODE),
            width=12,
            state="readonly",
        )
        self.atomizer_combo.grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=3)
        self._entry(editor, 0, 4, "Расход расп., кг/ч", self.atomizer_flow_kg_h, width=8)
        self._entry(editor, 0, 6, "Воздух A, кг/ч (опц.)", self.air_flow_kg_h, width=8)

        ttk.Label(editor, text="Название режима").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=3
        )
        ttk.Entry(editor, textvariable=self.regime_name, width=18, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=3
        )
        ttk.Label(editor, text="Начало").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=3)
        self.start_time_combo = ttk.Combobox(
            editor, textvariable=self.regime_start, width=8, state="readonly"
        )
        self.start_time_combo.grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=3)
        self.start_time_combo.bind("<<ComboboxSelected>>", self._on_start_time_selected)
        ttk.Label(editor, text="Конец").grid(row=1, column=4, sticky="w", padx=(0, 6), pady=3)
        self.end_time_combo = ttk.Combobox(
            editor, textvariable=self.regime_end, width=8, state="readonly"
        )
        self.end_time_combo.grid(row=1, column=5, sticky="ew", padx=(0, 8), pady=3)
        ttk.Button(editor, text="Добавить", command=self._add_regime).grid(row=1, column=6, padx=(8, 3))
        ttk.Button(editor, text="Изменить", command=self._update_regime).grid(row=1, column=7, padx=3)
        ttk.Button(editor, text="Удалить", command=self._delete_regime).grid(row=1, column=8, padx=(3, 0))
        ttk.Label(
            editor,
            text=(
                "Название режима формируется из расходов: F — топливо, V — пар распылителя, "
                "A — воздух. Например: F1V0.8A7.5. Начало выбирается из XLSX; конец "
                "автоматически ставится через 2 минуты."
            ),
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=9, sticky="w", pady=(7, 0))

        table_frame = ttk.Frame(regimes_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.regime_table = ttk.Treeview(
            table_frame,
            columns=("name", "start", "end", "duration"),
            show="headings",
            height=8,
            selectmode="browse",
        )
        for column, label, width in (
            ("name", "Режим", 210),
            ("start", "Начало", 190),
            ("end", "Конец", 190),
            ("duration", "Длительность, с", 130),
        ):
            self.regime_table.heading(column, text=label)
            self.regime_table.column(column, width=width, minwidth=100)
        self.regime_table.grid(row=0, column=0, sticky="nsew")
        self.regime_table.bind("<<TreeviewSelect>>", self._on_regime_select)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.regime_table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.regime_table.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Рассчитать и сохранить CSV", command=self._process).grid(
            row=0, column=1, sticky="e"
        )

    def _build_analysis_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        source = ttk.LabelFrame(parent, text="1. CSV результата первой вкладки", padding=10)
        source.grid(row=0, column=0, sticky="ew")
        source.columnconfigure(1, weight=1)
        source.columnconfigure(3, weight=1)
        self._file_row(
            source,
            0,
            "Итоговый CSV",
            self.analysis_csv_path,
            (("CSV", "*.csv"),),
        )
        self._entry(source, 1, 0, "T вход парогенератора, °C", self.steam_inlet_temperature_c)
        self._entry(source, 1, 2, "T выход парогенератора, °C", self.steam_outlet_temperature_c)
        ttk.Button(
            source,
            text="Загрузить и проанализировать",
            command=self._analyze_result_csv,
        ).grid(row=1, column=4, sticky="e", pady=(8, 0))
        ttk.Label(
            source,
            text=(
                "Анализ оставляет каждый режим отдельной строкой и пересчитывает "
                "CO, NO, NO2 из ppm в мг/кВт·ч. Тепло пара считается по разности "
                "энтальпии между водой на входе и паром на выходе парогенератора."
            ),
            foreground="#555555",
            wraplength=1040,
            justify="left",
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        table_frame = ttk.LabelFrame(parent, text="2. Сводка по режимам", padding=10)
        table_frame.grid(row=1, column=0, sticky="nsew", pady=10)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.analysis_table = ttk.Treeview(
            table_frame,
            columns=(
                "experiment",
                "regime",
                "heat_kj",
                "heat_kwh",
                "steam_heat",
                "fuel_heat",
                "fuel_mass",
                "fuel_lhv",
                "o2",
                "co_ppm",
                "co_mg",
                "no_ppm",
                "no_mg",
                "no2_ppm",
                "no2_mg",
            ),
            show="headings",
            height=12,
        )
        for column, label, width in (
            ("experiment", "Эксперимент", 180),
            ("regime", "Режим", 140),
            ("heat_kj", "Тепло, кДж", 110),
            ("heat_kwh", "Тепло, кВт·ч", 120),
            ("steam_heat", "Тепло пара, кДж", 125),
            ("fuel_heat", "Тепло топлива, кДж", 135),
            ("fuel_mass", "Масса топлива, кг", 130),
            ("fuel_lhv", "Уд. теплота, МДж/кг", 145),
            ("o2", "O2, %", 85),
            ("co_ppm", "CO, ppm", 90),
            ("co_mg", "CO, мг/кВт·ч", 125),
            ("no_ppm", "NO, ppm", 90),
            ("no_mg", "NO, мг/кВт·ч", 125),
            ("no2_ppm", "NO2, ppm", 90),
            ("no2_mg", "NO2, мг/кВт·ч", 130),
        ):
            self.analysis_table.heading(column, text=label)
            self.analysis_table.column(column, width=width, minwidth=70)
        self.analysis_table.grid(row=0, column=0, sticky="nsew")
        y_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.analysis_table.yview)
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        x_scrollbar = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.analysis_table.xview
        )
        x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.analysis_table.configure(
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set,
        )

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.analysis_status).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Сохранить анализ CSV", command=self._save_analysis_csv).grid(
            row=0, column=1, sticky="e"
        )

    def _file_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        filetypes: tuple[tuple[str, str], ...],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(
            parent,
            text="Обзор…",
            command=lambda: self._browse_file(variable, filetypes),
        ).grid(row=row, column=2, pady=3)

    @staticmethod
    def _entry(
        parent: ttk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        width: int = 12,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(parent, textvariable=variable, width=width).grid(
            row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=3
        )

    def _browse_file(
        self, variable: tk.StringVar, filetypes: tuple[tuple[str, str], ...]
    ) -> None:
        selected = filedialog.askopenfilename(filetypes=filetypes + (("Все файлы", "*.*"),))
        if selected:
            variable.set(selected)

    @staticmethod
    def _silent_number(value: str) -> float | None:
        text = value.strip()
        if not text:
            return None
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None

    def _atomizer_code(self) -> str:
        code = ATOMIZER_KIND_TO_CODE.get(self.atomizer_kind.get())
        if code is None:
            raise ValueError("Выберите тип распылителя")
        return code

    def _on_regime_flow_changed(self, *_args: object) -> None:
        if self._suspend_regime_name_update:
            return
        self._update_regime_name_from_flows()

    def _update_regime_name_from_flows(self) -> None:
        fuel = self._silent_number(self.fuel_flow_kg_h.get())
        atomizer_flow = self._silent_number(self.atomizer_flow_kg_h.get())
        air_text = self.air_flow_kg_h.get().strip()
        air = self._silent_number(air_text) if air_text else None
        atomizer_code = ATOMIZER_KIND_TO_CODE.get(self.atomizer_kind.get())
        if (
            fuel is None
            or atomizer_flow is None
            or atomizer_code is None
            or fuel <= 0
            or atomizer_flow <= 0
            or (air_text and (air is None or air <= 0))
        ):
            self.regime_name.set("")
            return
        self.regime_name.set(build_regime_name(fuel, atomizer_code, atomizer_flow, air))

    def _set_flow_fields_from_regime_name(self, name: str) -> None:
        parsed = parse_regime_name(name)
        self._suspend_regime_name_update = True
        try:
            if parsed is None:
                self.fuel_flow_kg_h.set("")
                self.atomizer_kind.set("Пар (V)")
                self.atomizer_flow_kg_h.set("")
                self.air_flow_kg_h.set("")
                self.regime_name.set(name)
                return
            fuel, atomizer_code, atomizer_flow, air = parsed
            self.fuel_flow_kg_h.set(format_flow_value(fuel))
            self.atomizer_kind.set(ATOMIZER_CODE_TO_KIND[atomizer_code])
            self.atomizer_flow_kg_h.set(format_flow_value(atomizer_flow))
            self.air_flow_kg_h.set("" if air is None else format_flow_value(air))
        finally:
            self._suspend_regime_name_update = False
        self._update_regime_name_from_flows()

    def _analyze_result_csv(self) -> None:
        path = self.analysis_csv_path.get().strip()
        if not path:
            messagebox.showerror("Не выбран CSV", "Укажите CSV, полученный на первой вкладке.")
            return
        self.analysis_status.set("Чтение и анализ CSV…")
        self.master.update_idletasks()
        try:
            steam_inlet = self._number(
                self.steam_inlet_temperature_c.get(),
                "T вход парогенератора",
            )
            steam_outlet = self._number(
                self.steam_outlet_temperature_c.get(),
                "T выход парогенератора",
            )
            self.analysis_results = analyze_result_csv(path, steam_inlet, steam_outlet)
        except ValueError as exc:
            self.analysis_results = []
            self._refresh_analysis_table()
            self.analysis_status.set("Ошибка анализа")
            messagebox.showerror("Ошибка анализа CSV", str(exc))
            return
        self._refresh_analysis_table()
        self.analysis_status.set(
            f"Готово: проанализировано режимов {len(self.analysis_results)}"
        )

    def _refresh_analysis_table(self) -> None:
        for item in self.analysis_table.get_children():
            self.analysis_table.delete(item)
        for index, result in enumerate(self.analysis_results):
            self.analysis_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    result.experiment_name,
                    result.regime_name,
                    _format_analysis_number(result.heat_kj),
                    _format_analysis_number(result.heat_kwh),
                    _format_analysis_number(result.steam_heat_kj),
                    _format_analysis_number(result.fuel_heat_kj),
                    _format_analysis_number(result.fuel_mass_kg),
                    _format_analysis_number(result.fuel_specific_heat_mj_kg),
                    _format_analysis_number(result.o2_percent),
                    _format_analysis_number(result.co_ppm),
                    _format_analysis_number(result.co_mg_kwh),
                    _format_analysis_number(result.no_ppm),
                    _format_analysis_number(result.no_mg_kwh),
                    _format_analysis_number(result.no2_ppm),
                    _format_analysis_number(result.no2_mg_kwh),
                ),
            )

    def _save_analysis_csv(self) -> None:
        if not self.analysis_results:
            messagebox.showinfo(
                "Нет результатов анализа",
                "Сначала загрузите и проанализируйте CSV результата.",
            )
            return
        source_name = Path(self.analysis_csv_path.get().strip()).stem or "result"
        destination = filedialog.asksaveasfilename(
            title="Сохранить CSV анализа",
            defaultextension=".csv",
            initialfile=f"{source_name}_analysis.csv",
            filetypes=(("CSV", "*.csv"), ("Все файлы", "*.*")),
        )
        if not destination:
            return
        try:
            export_analysis_csv(destination, self.analysis_results)
        except ValueError as exc:
            messagebox.showerror("Ошибка экспорта анализа", str(exc))
            return
        self.analysis_status.set(f"CSV анализа сохранен: {destination}")
        messagebox.showinfo("Анализ сохранен", f"CSV анализа сохранен:\n{destination}")

    def _load_sources(self) -> None:
        gas_path = self.gas_path.get().strip()
        temperature_path = self.temperature_path.get().strip()
        water_flow_path = self.water_flow_path.get().strip()
        plc_path = self.plc_path.get().strip()
        if not gas_path:
            messagebox.showerror(
                "Не выбран XLSX",
                "Укажите XLSX файл газоанализатора. Остальные файлы можно оставить пустыми.",
            )
            return
        self.status.set("Чтение файлов…")
        self.master.update_idletasks()
        try:
            gas = read_gas_xlsx(gas_path)
            temperature = (
                read_oscilloscope_txt(temperature_path, expected_channels=2)
                if temperature_path
                else None
            )
            water_flow = (
                read_oscilloscope_txt(water_flow_path, expected_channels=1)
                if water_flow_path
                else None
            )
            plc_data = read_plc_csv(plc_path) if plc_path else None
            start, end = common_time_range(gas, temperature, water_flow, plc_data)
            if start >= end:
                raise ValueError("У загруженных файлов нет общего временного диапазона")
        except Exception as exc:
            self.status.set("Ошибка загрузки")
            messagebox.showerror("Ошибка исходных данных", str(exc))
            return
        self.gas_data = gas
        self.temperature_data = temperature
        self.water_flow_data = water_flow
        self.plc_data = plc_data
        self.available_minutes = sorted({timestamp.strftime("%H:%M") for timestamp in gas.timestamps})
        self.start_time_combo.configure(values=self.available_minutes)
        self.end_time_combo.configure(values=self.available_minutes)
        self.regime_start.set("")
        self.regime_end.set("")
        range_label = "Общий диапазон загруженных файлов" if any(
            (temperature, water_flow, plc_data)
        ) else "Диапазон XLSX"
        self.source_summary.set(
            f"{range_label}: {_format_time(start)} — {_format_time(end)}; "
            f"газовых колонок: {len(gas.columns)}"
        )
        loaded = [f"XLSX {len(gas.timestamps)} строк"]
        if temperature is not None:
            loaded.append(f"температура {len(temperature.timestamps)}")
        if water_flow is not None:
            loaded.append(f"вода {len(water_flow.timestamps)}")
        if plc_data is not None:
            loaded.append(f"ПЛК {len(plc_data.timestamps)}")
        self.status.set("Загружено: " + ", ".join(loaded))
        if not self.experiment_name.get().strip():
            self.experiment_name.set(Path(gas_path).stem)

    def _reference_date(self) -> date:
        if self.gas_data is None:
            raise ValueError("Сначала загрузите XLSX")
        return self.gas_data.start.date()

    def _read_regime_editor(self) -> Regime:
        reference = self._reference_date()
        if self.gas_data is None:
            raise ValueError("Сначала загрузите XLSX")
        fuel = self._positive_number(self.fuel_flow_kg_h.get(), "Топливо F, кг/ч")
        atomizer_flow = self._positive_number(
            self.atomizer_flow_kg_h.get(), "Расход распылителя, кг/ч"
        )
        air = self._optional_number(self.air_flow_kg_h.get(), "Воздух A, кг/ч")
        if air is not None and air <= 0:
            raise ValueError("Поле «Воздух A, кг/ч» должно быть больше нуля")
        name = build_regime_name(fuel, self._atomizer_code(), atomizer_flow, air)
        self.regime_name.set(name)
        start = parse_user_time(self.regime_start.get(), reference)
        end = parse_user_time(self.regime_end.get(), reference)
        for label, value in (("начала", start), ("конца", end)):
            if not gas_contains_minute(self.gas_data, value):
                raise ValueError(
                    f"Время {label} {value:%H:%M} отсутствует в первой колонке XLSX"
                )
        return Regime(
            name,
            start,
            end,
        )

    def _add_regime(self) -> None:
        try:
            regime = self._read_regime_editor()
        except ValueError as exc:
            messagebox.showerror("Некорректный режим", str(exc))
            return
        self.regimes.append(regime)
        self.regimes.sort(key=lambda item: item.start)
        self._refresh_regimes()
        self._clear_regime_editor(keep_name=True)

    def _selected_index(self) -> int | None:
        selected = self.regime_table.selection()
        return int(selected[0]) if selected else None

    def _update_regime(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Режим не выбран", "Выберите строку режима для изменения")
            return
        try:
            regime = self._read_regime_editor()
        except ValueError as exc:
            messagebox.showerror("Некорректный режим", str(exc))
            return
        self.regimes[index] = regime
        self.regimes.sort(key=lambda item: item.start)
        self._refresh_regimes()
        self._clear_regime_editor()

    def _delete_regime(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Режим не выбран", "Выберите строку режима для удаления")
            return
        del self.regimes[index]
        self._refresh_regimes()
        self._clear_regime_editor()

    def _refresh_regimes(self) -> None:
        for item in self.regime_table.get_children():
            self.regime_table.delete(item)
        for index, regime in enumerate(self.regimes):
            duration = (regime.end - regime.start).total_seconds()
            self.regime_table.insert(
                "",
                "end",
                iid=str(index),
                values=(regime.name, _format_time(regime.start), _format_time(regime.end), f"{duration:g}"),
            )

    def _on_regime_select(self, _event: tk.Event[tk.Misc]) -> None:
        index = self._selected_index()
        if index is None:
            return
        regime = self.regimes[index]
        self._set_flow_fields_from_regime_name(regime.name)
        self.regime_start.set(_format_editor_time(regime.start))
        self._refresh_end_time_options(regime.start)
        self.regime_end.set(_format_editor_time(regime.end))

    def _on_start_time_selected(self, _event: tk.Event[tk.Misc]) -> None:
        if self.gas_data is None:
            return
        try:
            start = parse_user_time(self.regime_start.get(), self.gas_data.start.date())
        except ValueError:
            return
        options = self._refresh_end_time_options(start)
        auto_end = _format_editor_time(start + timedelta(minutes=2))
        self.regime_end.set(auto_end if auto_end in options else (options[0] if options else ""))

    def _refresh_end_time_options(self, start: datetime | None = None) -> list[str]:
        if start is None:
            options = list(self.available_minutes)
        else:
            options = end_time_options_after_start(self.available_minutes, start.strftime("%H:%M"))
        self.end_time_combo.configure(values=options)
        return options

    def _clear_regime_editor(self, keep_name: bool = False) -> None:
        if not keep_name:
            self._suspend_regime_name_update = True
            try:
                self.fuel_flow_kg_h.set("")
                self.atomizer_kind.set("Пар (V)")
                self.atomizer_flow_kg_h.set("")
                self.air_flow_kg_h.set("")
            finally:
                self._suspend_regime_name_update = False
            self.regime_name.set("")
        self._refresh_end_time_options()
        self.regime_start.set("")
        self.regime_end.set("")

    @staticmethod
    def _number(value: str, name: str) -> float:
        try:
            return float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"Поле «{name}» должно содержать число") from exc

    @staticmethod
    def _positive_number(value: str, name: str) -> float:
        number = CalorimeterApp._number(value, name)
        if number <= 0:
            raise ValueError(f"Поле «{name}» должно быть больше нуля")
        return number

    @staticmethod
    def _optional_number(value: str, name: str) -> float | None:
        if not value.strip():
            return None
        return CalorimeterApp._number(value, name)

    def _settings(self) -> ProcessingSettings:
        cold_junction = self._optional_number(
            self.cold_junction_temperature.get(), "Свободные концы термопары"
        )
        density = self._optional_number(self.density.get(), "Плотность")
        heat_capacity = self._optional_number(self.heat_capacity.get(), "Теплоемкость")
        return ProcessingSettings(
            experiment_name=self.experiment_name.get().strip(),
            water_liters_per_pulse=self._optional_number(
                self.water_liters_per_pulse.get(), "Вода, л/импульс"
            ),
            cold_junction_temperature_c=25.0 if cold_junction is None else cold_junction,
            density_kg_m3=1000.0 if density is None else density,
            heat_capacity_j_kg_c=4184.0 if heat_capacity is None else heat_capacity,
        )

    def _process(self) -> None:
        if self.gas_data is None:
            messagebox.showerror("Нет данных", "Сначала загрузите и проверьте XLSX газоанализатора")
            return
        try:
            settings = self._settings()
            results = process_experiment(
                self.gas_data,
                self.temperature_data,
                self.water_flow_data,
                self.plc_data,
                self.regimes,
                settings,
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка расчета", str(exc))
            return
        safe_name = re.sub(r"[^\w.-]+", "_", settings.experiment_name, flags=re.UNICODE).strip("_")
        destination = filedialog.asksaveasfilename(
            title="Сохранить сводный CSV",
            defaultextension=".csv",
            initialfile=f"{safe_name or 'experiment'}_result.csv",
            filetypes=(("CSV", "*.csv"), ("Все файлы", "*.*")),
        )
        if not destination:
            return
        try:
            export_csv(destination, results)
        except ValueError as exc:
            messagebox.showerror("Ошибка экспорта", str(exc))
            return
        self.status.set(f"Готово: рассчитано режимов {len(results)}, CSV сохранен: {destination}")
        messagebox.showinfo("Расчет завершен", f"Сводный CSV сохранен:\n{destination}")


def run() -> None:
    root = tk.Tk()
    root.title("Обработка данных калориметра")
    root.geometry("1120x760")
    root.minsize(940, 680)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    CalorimeterApp(root)
    root.mainloop()
