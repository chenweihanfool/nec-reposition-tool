"""NEC 原生格式（如 KC0327）讀寫：BNP / COA / PAR 解析與寫出，其餘副檔名原樣複製。

純文字檔，Big5 編碼。COA / PAR 為固定寬度欄位；BNP 為空白分隔欄位（欄寬固定，但欄位間
一定有分隔空白，不會像 PAR 那樣在數字位數變多時黏在一起，故用 split() 即可）。

欄位配置經對照 KC0327.COA / KC0327.BNP / KC0327.PAR 實際檔案內容與
D:\\ClaudeCode\\.claude\\worktrees\\romantic-pare-017a3f\\adjust_cadastral.py 的既有解析邏輯驗證。
"""
import os
import re
import shutil
from collections import defaultdict

ENCODING = 'big5'
COPY_EXTS = ('CTL', 'DIS', 'MAP', 'RCO', 'UPN')


class CaseNotFoundError(Exception):
    pass


def detect_case(folder):
    """在資料夾中尋找 XX####.COA 檔案，回傳 (prefix, base_name)。"""
    pat = re.compile(r'^([A-Za-z]+)(\d+)\.COA$', re.IGNORECASE)
    for entry in os.listdir(folder):
        m = pat.match(entry)
        if m:
            return m.group(1).upper(), m.group(1).upper() + m.group(2)
    raise CaseNotFoundError(
        f'資料夾「{folder}」內找不到 .COA 檔案，請確認選擇的是 NEC 原生格式的未定位資料夾'
        f'（例如 KC0327，內含 .BNP/.COA/.PAR）'
    )


def case_path(folder, base_name, ext):
    return os.path.join(folder, f'{base_name}.{ext}')


# ── COA：界址點座標 ──────────────────────────────────────────────────────
# 每行：NNNNN␣YYYYYYYYYYYYYYYXXXXXXXXXXXXXXXXF
def parse_coa(path):
    """回傳 (header_line, {點號: (Y, X, flag)})。"""
    with open(path, encoding=ENCODING, errors='replace') as f:
        lines = f.readlines()
    header = lines[0]
    points = {}
    for line in lines[1:]:
        raw = line.rstrip('\n').rstrip('\r')
        if len(raw) < 6:
            continue
        try:
            pid = int(raw[:5])
        except ValueError:
            continue
        rest = raw[6:]
        if len(rest) < 31:
            continue
        try:
            y = float(rest[:16])
            x = float(rest[16:31])
        except ValueError:
            continue
        flag = rest[31] if len(rest) > 31 else ' '
        points[pid] = (y, x, flag)
    return header, points


def format_coa_line(pid, y, x, flag):
    return f'{pid:5d} {y:16.8f}{x:15.8f}{flag}\n'


def write_coa(path, header, points):
    """points: {點號: (Y, X, flag)}，依點號排序輸出。"""
    with open(path, 'w', encoding=ENCODING, errors='replace', newline='') as f:
        f.write(header if header.endswith('\n') else header + '\n')
        for pid in sorted(points):
            y, x, flag = points[pid]
            f.write(format_coa_line(pid, y, x, flag))


# ── BNP：宗地-界址點清單 ──────────────────────────────────────────────────
# 每行：母號␣子號␣段落序號␣總點數␣點號1␣點號2...（同宗地可能跨多行接續）
def parse_bnp(path):
    """回傳 (header_line, {(母號,子號): [點號,...]})。"""
    with open(path, encoding=ENCODING, errors='replace') as f:
        lines = f.readlines()
    header = lines[0]
    parcel_points = defaultdict(list)
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            main = int(parts[0])
            sub = int(parts[1])
            pts = [int(p) for p in parts[4:]]
        except ValueError:
            continue
        parcel_points[(main, sub)].extend(pts)
    return header, dict(parcel_points)


# ── PAR：宗地地目/面積 ────────────────────────────────────────────────────
# 固定寬度欄位（實測驗證，數字位數變多時欄位間空白會被擠掉，故不能用 split()/正規式空白分隔）：
#   [0:4)   母號        [4:8)   子號        [8:12)  段別
#   [12:22) 登記面積     [22:26) 母號(重複)   [26:30) 子號(重複)
#   [30:40) 數化面積     [40:41) 狀態代碼     [41:]   其餘（中心座標等，本工具不使用）
def parse_par(path):
    """回傳 (header_line, {(母號,子號): {'section','reg','dig','status'}})。"""
    with open(path, encoding=ENCODING, errors='replace') as f:
        lines = f.readlines()
    header = lines[0]
    info = {}
    for line in lines[1:]:
        raw = line.rstrip('\n').rstrip('\r')
        if len(raw) < 41:
            continue
        try:
            main = int(raw[0:4])
            sub = int(raw[4:8])
            section = int(raw[8:12])
            reg = float(raw[12:22])
            dig = float(raw[30:40])
            status = raw[40:41]
        except ValueError:
            continue
        info[(main, sub)] = {'section': section, 'reg': reg, 'dig': dig, 'status': status}
    return header, info


def copy_unchanged(src_folder, dst_folder, src_base, dst_base=None):
    """把拓樸/局部繪圖座標檔（CTL/DIS/MAP/RCO/UPN）原樣複製——剛體轉換不改變它們。
    dst_base 預設沿用 src_base；輸出檔名要跟輸出資料夾名稱一致時，呼叫端會傳入
    不同的 dst_base（見 pipeline.py）。"""
    dst_base = dst_base or src_base
    copied = []
    for ext in COPY_EXTS:
        src = case_path(src_folder, src_base, ext)
        if os.path.exists(src):
            shutil.copy2(src, case_path(dst_folder, dst_base, ext))
            copied.append(ext)
    return copied
