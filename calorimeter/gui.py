from __future__ import annotations

import re
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import GasData, OscilloscopeData, ProcessingSettings, Regime
from .processing import common_time_range, export_csv, gas_contains_minute, process_experiment
from .readers import read_gas_xlsx, read_oscilloscope_txt


def parse_user_time(value: str, reference_date: date) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Выберите время в формате ЧЧ:ММ") from exc
    return datetime.combine(reference_date, parsed)


def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


class CalorimeterApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master = master
        self.gas_data: GasData | None = None
        self.temperature_data: OscilloscopeData | None = None
        self.flow_data: OscilloscopeData | None = None
        self.regimes: list[Regime] = []

        self.gas_path = tk.StringVar()
        self.temperature_path = tk.StringVar()
        self.flow_path = tk.StringVar()
        self.experiment_name = tk.StringVar()
        self.temp_coefficient = tk.StringVar()
        self.temp_offset = tk.StringVar(value="0")
        self.flow_coefficient = tk.StringVar()
        self.flow_zero = tk.StringVar(value="0")
        self.density = tk.StringVar(value="1000")
        self.heat_capacity = tk.StringVar(value="4184")
        self.regime_name = tk.StringVar()
        self.regime_start = tk.StringVar()
        self.regime_end = tk.StringVar()
        self.source_summary = tk.StringVar(value="Файлы еще не загружены")
        self.status = tk.StringVar(value="Выберите три файла и нажмите «Загрузить и проверить»")

        self._build_ui()

    def _build_ui(self) -> None:
        self.grid(sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        sources = ttk.LabelFrame(self, text="1. Исходные данные", padding=10)
        sources.grid(row=0, column=0, sticky="ew")
        sources.columnconfigure(1, weight=1)
        self._file_row(sources, 0, "Газоанализатор XLSX", self.gas_path, (("Excel XLSX", "*.xlsx"),))
        self._file_row(sources, 1, "Температура TXT (2 канала)", self.temperature_path, (("TXT", "*.txt"),))
        self._file_row(sources, 2, "Расход TXT (1 канал)", self.flow_path, (("TXT", "*.txt"),))
        ttk.Button(sources, text="Загрузить и проверить", command=self._load_sources).grid(
            row=3, column=2, sticky="e", pady=(8, 0)
        )
        ttk.Label(sources, textvariable=self.source_summary, foreground="#284f73").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        settings = ttk.LabelFrame(self, text="2. Калибровка и свойства теплоносителя", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=10)
        for column in (1, 3, 5):
            settings.columnconfigure(column, weight=1)
        self._entry(settings, 0, 0, "Название эксперимента", self.experiment_name, width=24)
        self._entry(settings, 0, 2, "Температура, °C/В", self.temp_coefficient)
        self._entry(settings, 0, 4, "Смещение температуры, °C", self.temp_offset)
        self._entry(settings, 1, 0, "Расход, л/(мин·В)", self.flow_coefficient)
        self._entry(settings, 1, 2, "Нулевой сигнал расхода, В", self.flow_zero)
        self._entry(settings, 1, 4, "Плотность, кг/м³", self.density)
        self._entry(settings, 2, 0, "Теплоемкость, Дж/(кг·°C)", self.heat_capacity)
        ttk.Label(
            settings,
            text="T = U·kT + bT;  расход = max(0, (U − U0)·kV). Коэффициенты берутся из калибровки датчиков.",
            foreground="#555555",
        ).grid(row=2, column=2, columnspan=4, sticky="w", padx=(8, 0), pady=(7, 0))

        regimes_frame = ttk.LabelFrame(self, text="3. Стационарные режимы", padding=10)
        regimes_frame.grid(row=2, column=0, sticky="nsew")
        regimes_frame.columnconfigure(0, weight=1)
        regimes_frame.rowconfigure(1, weight=1)

        editor = ttk.Frame(regimes_frame)
        editor.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        editor.columnconfigure(1, weight=1)
        editor.columnconfigure(3, weight=1)
        editor.columnconfigure(5, weight=1)
        self._entry(editor, 0, 0, "Название режима", self.regime_name, width=18)
        ttk.Label(editor, text="Начало").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=3)
        self.start_time_combo = ttk.Combobox(
            editor, textvariable=self.regime_start, width=8, state="readonly"
        )
        self.start_time_combo.grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=3)
        ttk.Label(editor, text="Конец").grid(row=0, column=4, sticky="w", padx=(0, 6), pady=3)
        self.end_time_combo = ttk.Combobox(
            editor, textvariable=self.regime_end, width=8, state="readonly"
        )
        self.end_time_combo.grid(row=0, column=5, sticky="ew", padx=(0, 8), pady=3)
        ttk.Button(editor, text="Добавить", command=self._add_regime).grid(row=0, column=6, padx=(8, 3))
        ttk.Button(editor, text="Изменить", command=self._update_regime).grid(row=0, column=7, padx=3)
        ttk.Button(editor, text="Удалить", command=self._delete_regime).grid(row=0, column=8, padx=(3, 0))
        ttk.Label(
            editor,
            text="Выберите начало и конец в формате ЧЧ:ММ из времени, найденного в XLSX.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=9, sticky="w", pady=(7, 0))

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

        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Рассчитать и сохранить CSV", command=self._process).grid(
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

    def _load_sources(self) -> None:
        paths = (self.gas_path.get().strip(), self.temperature_path.get().strip(), self.flow_path.get().strip())
        if not all(paths):
            messagebox.showerror("Не выбраны файлы", "Укажите XLSX, TXT температуры и TXT расхода")
            return
        self.status.set("Чтение файлов…")
        self.master.update_idletasks()
        try:
            gas = read_gas_xlsx(paths[0])
            temperature = read_oscilloscope_txt(paths[1], expected_channels=2)
            flow = read_oscilloscope_txt(paths[2], expected_channels=1)
            start, end = common_time_range(gas, temperature, flow)
            if start >= end:
                raise ValueError("У трех файлов нет общего временного диапазона")
        except Exception as exc:
            self.status.set("Ошибка загрузки")
            messagebox.showerror("Ошибка исходных данных", str(exc))
            return
        self.gas_data = gas
        self.temperature_data = temperature
        self.flow_data = flow
        available_minutes = sorted({timestamp.strftime("%H:%M") for timestamp in gas.timestamps})
        self.start_time_combo.configure(values=available_minutes)
        self.end_time_combo.configure(values=available_minutes)
        self.regime_start.set("")
        self.regime_end.set("")
        self.source_summary.set(
            f"Общий диапазон: {_format_time(start)} — {_format_time(end)}; "
            f"газовых колонок: {len(gas.columns)}"
        )
        self.status.set(
            f"Загружено: XLSX {len(gas.timestamps)} строк, температура {len(temperature.timestamps)}, "
            f"расход {len(flow.timestamps)}"
        )
        if not self.experiment_name.get().strip():
            self.experiment_name.set(Path(paths[0]).stem)

    def _reference_date(self) -> date:
        if self.gas_data is None:
            raise ValueError("Сначала загрузите исходные файлы")
        return self.gas_data.start.date()

    def _read_regime_editor(self) -> Regime:
        reference = self._reference_date()
        if self.gas_data is None:
            raise ValueError("Сначала загрузите XLSX")
        start = parse_user_time(self.regime_start.get(), reference)
        end = parse_user_time(self.regime_end.get(), reference)
        for label, value in (("начала", start), ("конца", end)):
            if not gas_contains_minute(self.gas_data, value):
                raise ValueError(
                    f"Время {label} {value:%H:%M} отсутствует в первой колонке XLSX"
                )
        return Regime(
            self.regime_name.get().strip(),
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
        self._clear_regime_editor()

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
        self.regime_name.set(regime.name)
        self.regime_start.set(regime.start.strftime("%H:%M"))
        self.regime_end.set(regime.end.strftime("%H:%M"))

    def _clear_regime_editor(self) -> None:
        self.regime_name.set("")
        self.regime_start.set("")
        self.regime_end.set("")

    @staticmethod
    def _number(value: str, name: str) -> float:
        try:
            return float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"Поле «{name}» должно содержать число") from exc

    def _settings(self) -> ProcessingSettings:
        return ProcessingSettings(
            experiment_name=self.experiment_name.get().strip(),
            temperature_coefficient_c_per_v=self._number(
                self.temp_coefficient.get(), "Температура, °C/В"
            ),
            temperature_offset_c=self._number(self.temp_offset.get(), "Смещение температуры"),
            flow_coefficient_l_min_per_v=self._number(
                self.flow_coefficient.get(), "Расход, л/(мин·В)"
            ),
            flow_zero_v=self._number(self.flow_zero.get(), "Нулевой сигнал расхода"),
            density_kg_m3=self._number(self.density.get(), "Плотность"),
            heat_capacity_j_kg_c=self._number(self.heat_capacity.get(), "Теплоемкость"),
        )

    def _process(self) -> None:
        if self.gas_data is None or self.temperature_data is None or self.flow_data is None:
            messagebox.showerror("Нет данных", "Сначала загрузите и проверьте три исходных файла")
            return
        try:
            settings = self._settings()
            results = process_experiment(
                self.gas_data,
                self.temperature_data,
                self.flow_data,
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
