"""重測系統格式（如 KC2327，DBF-based）讀取。

用途分兩種：
  1. 控制點來源（D13 + D14 的 COT_REF=='0' 界址點）：這是「已確定新圖」，範圍雖小，
     座標已正確，用來跟未定位資料夾的 BNP/COA 比對出套合轉換參數。
  2. 直接輸出、不需轉換的資料（因為本來就已經是正確座標）：
     - 參考點：D14 的 COT_REF != '0'（key 用「母點號.子序號」小數編碼，例如 '1.11'）
     - 參考線：D29（端點可能指向參考點的小數編碼、補點的 Q 開頭名稱，極少數情況指向
       D14 的界址點整數點號——沿用 QGZ 工具 survey.py 的 _lookup_ref_point 邏輯，找不到
       就整條線跳過，不猜測連錯的點）
     - 補點：D20（CTL_NAME 為文字點名，無地號歸屬）

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


def _path(folder, base_name, ext):
    return os.path.join(folder, f'{base_name}.{ext}')


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


def load_ref_points(folder, base_name):
    """D14 內 COT_REF != '0' 的參考點：{'母點號.子序號': (Y,X)}。已是正確座標，不需轉換。"""
    recs = _read_opt(folder, base_name, 'D14')
    pts = {}
    for r in recs:
        ref = (r.get('COT_REF') or '0').strip()
        if ref in ('0', ''):
            continue
        num = _to_int(r.get('COT_NUMBER'))
        sub = _to_int(ref)
        y, x = _to_float(r.get('COT_Y')), _to_float(r.get('COT_X'))
        if num is None or not sub or y is None or x is None:
            continue
        pts[f'{num}.{sub}'] = (y, x)
    return pts


def load_ref_lines(folder, base_name):
    """D29 參考線：[(top_key, mid_key_or_None, bot_key), ...]。key 沿用原始字串，不轉型，
    因為端點可能是參考點的小數編碼、補點的 Q 開頭名稱、或極少數 D14 界址點整數點號，
    由呼叫端統一解析。"""
    recs = _read_opt(folder, base_name, 'D29')
    lines = []
    for r in recs:
        top = (r.get('LIN_TOP') or '').strip()
        bot = (r.get('LIN_BOT') or '').strip()
        mid = (r.get('LIN_MID') or '').strip()
        if not top or not bot or top == '0' or bot == '0':
            continue
        lines.append((top, mid if mid and mid != '0' else None, bot))
    return lines


def load_supplements(folder, base_name):
    """D20 補點：[{'name','y','x','level'}, ...]。已是正確座標，不需轉換。"""
    recs = _read_opt(folder, base_name, 'D20')
    out = []
    for r in recs:
        name = (r.get('CTL_NAME') or '').strip()
        y, x = _to_float(r.get('CTL_Y')), _to_float(r.get('CTL_X'))
        if not name or y is None or x is None:
            continue
        out.append({'name': name, 'y': y, 'x': x, 'level': (r.get('CTL_LEVEL') or '').strip()})
    return out
