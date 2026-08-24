"""極簡 dBase III/IV 讀取器（Big5 編碼），用於讀取地籍複丈案件的 D 系列檔案。"""
import struct


def read_dbf(path):
    """回傳 (fields, records)。fields 為 [(name, type, len, dec), ...]；
    records 為 [dict, ...]，值皆為去除頭尾空白的字串（依欄位型別未額外轉型）。"""
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 32:
        raise ValueError(f'{path}: 檔案過短，不是有效的 DBF 檔')

    num_records = struct.unpack_from('<I', data, 4)[0]
    header_size = struct.unpack_from('<H', data, 8)[0]
    record_size = struct.unpack_from('<H', data, 10)[0]

    fields = []
    pos = 32
    while pos < header_size - 1:
        chunk = data[pos:pos + 32]
        if not chunk or chunk[0] == 0x0D:
            break
        name = chunk[0:11].split(b'\x00')[0].decode('ascii', 'replace')
        ftype = chr(chunk[11])
        flen = chunk[16]
        fdec = chunk[17]
        fields.append((name, ftype, flen, fdec))
        pos += 32

    records = []
    rp = header_size
    for _ in range(num_records):
        rec = data[rp:rp + record_size]
        rp += record_size
        if not rec or rec[0:1] == b'*':
            continue  # 已刪除的紀錄
        off = 1
        row = {}
        for (name, ftype, flen, fdec) in fields:
            raw = rec[off:off + flen]
            try:
                val = raw.decode('big5', 'replace').strip()
            except Exception:
                val = raw.decode('latin-1', 'replace').strip()
            row[name] = val
            off += flen
        records.append(row)

    return fields, records


def read_dbf_records(path):
    """僅回傳 records（list[dict]）。"""
    _, records = read_dbf(path)
    return records


def write_dbf(path, fields, records):
    """寫出 dBase III 檔（無 memo），fields/records 格式與 read_dbf 回傳相同——用於
    把讀進來的參考點/參考線/補點（原封不動或篩選過的子集）依原始欄位結構寫回真正的
    DBF 檔，讓地籍測量軟體能直接讀取（而不是這個工具自己發明的文字格式）。

    'C' 欄位靠左、空白補右；'N'/'L' 欄位靠右、空白補左——皆為 dBase 慣例。
    """
    header_size = 32 + 32 * len(fields) + 1
    record_size = 1 + sum(f[2] for f in fields)

    with open(path, 'wb') as f:
        f.write(struct.pack('<B3B', 0x03, 0, 0, 0))
        f.write(struct.pack('<I', len(records)))
        f.write(struct.pack('<HH', header_size, record_size))
        f.write(b'\x00' * 20)
        for name, ftype, flen, fdec in fields:
            f.write(name.encode('ascii', 'replace')[:10].ljust(11, b'\x00'))
            f.write(ftype.encode('ascii'))
            f.write(b'\x00' * 4)
            f.write(struct.pack('<BB', flen, fdec))
            f.write(b'\x00' * 14)
        f.write(b'\x0d')

        for rec in records:
            f.write(b' ')
            for name, ftype, flen, fdec in fields:
                val = str(rec.get(name, '') or '')
                raw = val.encode('big5', 'replace')[:flen]
                if ftype == 'C':
                    f.write(raw.ljust(flen, b' '))
                else:
                    f.write(raw.rjust(flen, b' '))
        f.write(b'\x1a')
