from __future__ import annotations

import csv
import tempfile
from pathlib import Path


def is_ole_container(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(8) == bytes.fromhex("D0CF11E0A1B11AE1")


def export_sheets_with_excel(path: Path, sheet_names: list[str]) -> dict[str, list[list[str]]]:
    if not is_ole_container(path):
        raise ValueError(f"{path} is not an OLE-based workbook")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "This workbook is an encrypted/OLE Excel container. Install pywin32 and "
            "run on Windows with Microsoft Excel available."
        ) from exc

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    workbook = None
    result: dict[str, list[list[str]]] = {}
    try:
        workbook = excel.Workbooks.Open(str(path), 0, True)
        with tempfile.TemporaryDirectory(prefix="data-room-intel-") as temp:
            temp_path = Path(temp)
            for sheet_name in sheet_names:
                worksheet = workbook.Worksheets(sheet_name)
                worksheet.Copy()
                single = excel.ActiveWorkbook
                csv_path = temp_path / f"{sheet_name}.csv"
                single.SaveAs(str(csv_path), 62)
                single.Close(False)
                with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    result[sheet_name] = list(csv.reader(stream))
    finally:
        if workbook is not None:
            workbook.Close(False)
        excel.Quit()
        pythoncom.CoUninitialize()
    return result

