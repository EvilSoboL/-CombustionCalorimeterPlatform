from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from calorimeter.readers import read_gas_xlsx, read_oscilloscope_txt


class ReaderTests(unittest.TestCase):
    def test_cp1251_oscilloscope_file(self) -> None:
        content = """Oscilloscope Data File
Experiment Time :   22-06-2026 12:50:24
Number Of Channels : 2
Data Format: Volts
Time markers scale: секунды
Data as Time Sequence:
                    Ch  1      Ch  2
                 Канал 1    Канал 2

     0.000000 \t  1.000000\t  2.000000
     0.500000 \t  1.500000\t  2.500000
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temperature.txt"
            path.write_bytes(content.encode("cp1251"))
            data = read_oscilloscope_txt(path, expected_channels=2)
        self.assertEqual(2, len(data.timestamps))
        self.assertEqual([1.0, 1.5], data.channels[0])
        self.assertEqual(0.5, (data.end - data.start).total_seconds())

    def test_xlsx_shared_strings_and_excel_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gas.xlsx"
            self._write_minimal_xlsx(path)
            data = read_gas_xlsx(path)
        self.assertEqual("testo", data.sheet_name)
        self.assertEqual([20.0, 19.0], data.columns["% O2"])
        self.assertNotIn("сек", data.columns)
        self.assertEqual("2026-06-22 13:24:00", str(data.start))

    @staticmethod
    def _write_minimal_xlsx(path: Path) -> None:
        workbook = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="testo" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
        relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Target="worksheets/sheet1.xml"
  Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
</Relationships>"""
        shared = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <si><t>Дата / время</t></si><si><t>сек</t></si><si><t>% O2</t></si>
</sst>"""
        sheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>
 <row r="2"><c r="A2"><v>46195.5583333333</v></c><c r="B2"><v>0</v></c><c r="C2"><v>20</v></c></row>
 <row r="3"><c r="A3"><v>46195.5583449074</v></c><c r="B3"><v>1</v></c><c r="C3"><v>19</v></c></row>
</sheetData></worksheet>"""
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/sharedStrings.xml", shared)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)


if __name__ == "__main__":
    unittest.main()
