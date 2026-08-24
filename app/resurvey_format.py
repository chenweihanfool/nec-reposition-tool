"""重測系統格式（如 KC2327，DBF-based）讀取。

用途分兩種：
  1. 控制點來源（D13 + D14 的 COT_REF=='0' 界址點）：這是「已確定新圖」，範圍雖小，
     座標已正確，用來跟未定位資料夾的 BNP/COA 比對出套合轉換參數。
  2. 直接輸出、不需轉換的資料（因為本來就已經是正確座標）：參考點（D14 的
     COT_REF != '0'）、參考線（D29）、補點（D20）。這些不透過本模組解析成 Python
     結構再另外寫出——地籍測量軟體（如 WNECCAD）本來就認得 D14/D29/D20 這個 DBF
     格式，所以 pipeline.py 直接用 dbf_reader 讀出欄位結構＋記錄、篩選後照原格式寫回
     輸出資料夾，讓輸出可以被同一套軟體直接開啟（而非發明新的純文字副檔名）。

欄位對應已用 D:\\ClaudeCode\\QGZ專案檔寫入複丈歷史資料\\app\\survey.py 的既有邏輯與實測資料驗證。
"""
import os
import re

from dbf_reader import read_dbf_records


class CaseNotFoundError(Exception):
    pass


def detect_case(folder):
    """在資料夾中尋找 XX####.D14 檔案，回傳 (prefix, base_name)。"""
    pat = re.compile(r'^([A-Za-z]+)(\d+)\.D14$', re.IGNORECASE)
    for entry in os.listdir(folder):
        m = pat.match(entry)
        if m:
            return m.group(1).upper(), m.group(1).upper() + m.group(2)
    raise CaseNotFoundError(
        f'資料夾「{folder}」內找不到 .D14 檔案，請確認選擇的是重測系統格式的參考資料夾'
        f'（例如 KC2327，內含 .D13/.D14/.D29）'
    )


def case_path(folder, base_name, ext):
    return os.path.join(folder, f'{base_name}.{ext}')


_path = case_path  # 內部沿用舊名稱


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_opt(folder, base_name, ext):
    p = _path(folder, base_name, ext)
    if not os.path.exists(p):
        return []
    try:
        return read_dbf_records(p)
    except Exception:
        return []


def load_confirmed_points(folder, base_name):
    """D14 內 COT_REF=='0' 的界址點：{點號: (Y,X)}。已是正確座標，供控制點比對與
    參考線端點極少數情況下的整數點號查找使用。"""
    recs = _read_opt(folder, base_name, 'D14')
    pts = {}
    for r in recs:
        ref = (r.get('COT_REF') or '0').strip()
        if ref not in ('0', ''):
            continue
        num = _to_int(r.get('COT_NUMBER'))
        y, x = _to_float(r.get('COT_Y')), _to_float(r.get('COT_X'))
        if num is None or y is None or x is None:
            continue
        pts[num] = (y, x)
    return pts


def load_confirmed_rings(folder, base_name):
    """D13：{(母號,子號): [D14點號,...]}（依 COORD_1..8 依序累加，同宗地可能跨多筆記錄）。"""
    recs = _read_opt(folder, base_name, 'D13')
    rings = {}
    for r in recs:
        m, c = _to_int(r.get('O_PARCEL')), _to_int(r.get('O_PARCEL_E')) or 0
        if m is None:
            continue
        key = (m, c)
        seq = rings.setdefault(key, [])
        for i in range(1, 9):
            pid = _to_int(r.get(f'COORD_{i}'))
            if pid:
                seq.append(pid)
    return rings


def is_ref_point_record(record):
    """D14 一筆記錄是否為「參考點」（COT_REF != '0'，非界址點）。"""
    ref = (record.get('COT_REF') or '0').strip()
    return ref not in ('0', '')
