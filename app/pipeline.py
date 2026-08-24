"""串接：讀未定位資料夾（NEC 原生格式）+ 參考資料夾（重測系統格式）
-> 用地號比對抓控制點 -> 求剛體轉換 -> 套用到 COA 界址點
-> 複製 BNP/PAR/CTL/DIS/MAP/RCO/UPN（拓樸/面積/局部繪圖座標，剛體轉換不影響）
-> 寫出參考點(RFP)/參考線(RFL)/補點(SUP)（直接採用參考資料夾裡已正確定位的座標，不轉換）
-> 輸出新資料夾。
"""
import os
import shutil

import fit
import nec_format
import resurvey_format

# 控制點數低於此值僅警告（不中止），因為地籍資料的可信度判斷應由使用者決定，見 README。
WARN_MIN_PAIRS = 6
WARN_MAX_RMSE = 0.3  # 公尺


class PipelineError(Exception):
    pass


def run(unpositioned_folder, reference_folder, output_folder, target_parcel=None, log=lambda m: None):
    """執行完整轉換流程，回傳診斷資訊 dict。
    target_parcel: 選填，(母號,子號) tuple。指定時套合會加權，讓結果在該地號附近盡可能貼合
    （代價是離該地號較遠處的整體精度可能變差），見 fit.fit_rigid_transform_targeted。
    """
    src_prefix, src_base = nec_format.detect_case(unpositioned_folder)
    ref_prefix, ref_base = resurvey_format.detect_case(reference_folder)
    log(f'未定位資料夾：{src_base}（NEC 原生格式）')
    log(f'參考資料夾：{ref_base}（重測系統格式）')

    coa_header, coa_points = nec_format.parse_coa(nec_format.case_path(unpositioned_folder, src_base, 'COA'))
    bnp_header, bnp_points = nec_format.parse_bnp(nec_format.case_path(unpositioned_folder, src_base, 'BNP'))
    log(f'COA 界址點 {len(coa_points)} 個，BNP 宗地 {len(bnp_points)} 筆')

    confirmed_points = resurvey_format.load_confirmed_points(reference_folder, ref_base)
    rings = resurvey_format.load_confirmed_rings(reference_folder, ref_base)
    log(f'參考資料夾已確定界址點 {len(confirmed_points)} 個，宗地 {len(rings)} 筆')

    pairs, match_diag = fit.match_control_points(bnp_points, coa_points, rings, confirmed_points)
    log(
        f"共同地號 {match_diag['total_common_parcels']} 筆，接受 {len(match_diag['accepted_parcels'])} 筆"
        f"（{match_diag['n_pairs']} 個控制點），點數不符 {len(match_diag['count_mismatch'])} 筆，"
        f"邊長比對不通過 {len(match_diag['rejected_parcels'])} 筆"
    )

    if len(pairs) < 2:
        raise PipelineError(
            f'可用控制點只有 {len(pairs)} 個，數學上至少需要 2 個點才能求解剛體轉換。'
            f'請確認兩個資料夾是否為同一測區、地號是否有重疊。'
        )

    if target_parcel is not None:
        try:
            result = fit.fit_rigid_transform_targeted(pairs, bnp_points, coa_points, target_parcel)
        except ValueError as e:
            raise PipelineError(str(e))
        log(
            f"已指定地號 {target_parcel[0]}-{target_parcel[1]} 加權套合（控制點離該地號越近權重越高）："
            f"該地號附近 RMSE {result['weighted_rmse'] * 100:.1f} cm（整體 RMSE {result['rmse'] * 100:.1f} cm）"
        )
    else:
        result = fit.fit_rigid_transform(pairs)
    log(
        f"套合結果：旋轉角 {result['theta_deg']:.4f}°，RMSE {result['rmse'] * 100:.1f} cm，"
        f"最大殘差 {result['max_residual'] * 100:.1f} cm（{result['n_points']} 個控制點）"
    )

    warnings = []
    if result['n_points'] < WARN_MIN_PAIRS:
        warnings.append(f"控制點只有 {result['n_points']} 個（建議 >= {WARN_MIN_PAIRS} 個），套合結果可信度較低，建議人工複核")
    check_rmse = result['weighted_rmse'] if target_parcel is not None else result['rmse']
    check_label = '指定地號附近加權 RMSE' if target_parcel is not None else '套合 RMSE'
    if check_rmse > WARN_MAX_RMSE:
        warnings.append(f"{check_label}（{check_rmse:.3f} m）超過建議門檻（{WARN_MAX_RMSE} m），建議人工複核比對結果再使用")
    for w in warnings:
        log(f'警告：{w}')

    transform = result['transform']
    new_coa_points = {pid: (*transform(y, x), flag) for pid, (y, x, flag) in coa_points.items()}

    os.makedirs(output_folder, exist_ok=True)
    nec_format.write_coa(nec_format.case_path(output_folder, src_base, 'COA'), coa_header, new_coa_points)
    log(f'已寫出套合後 COA：{len(new_coa_points)} 個界址點')

    shutil.copy2(nec_format.case_path(unpositioned_folder, src_base, 'BNP'),
                 nec_format.case_path(output_folder, src_base, 'BNP'))
    shutil.copy2(nec_format.case_path(unpositioned_folder, src_base, 'PAR'),
                 nec_format.case_path(output_folder, src_base, 'PAR'))
    copied = nec_format.copy_unchanged(unpositioned_folder, output_folder, src_base)
    log(f"已原樣複製：BNP, PAR, {', '.join(copied) if copied else '(無其餘檔案)'}")

    ref_points = resurvey_format.load_ref_points(reference_folder, ref_base)
    ref_lines_raw = resurvey_format.load_ref_lines(reference_folder, ref_base)
    supplements = resurvey_format.load_supplements(reference_folder, ref_base)
    supp_by_name = {s['name']: s for s in supplements}

    rfp_points = dict(ref_points)  # key(str, 'main.sub' 或極少數情況的整數點號) -> (y, x)
    resolved_lines = []
    skipped_lines = 0
    for top, mid, bot in ref_lines_raw:
        keys = [top] + ([mid] if mid else []) + [bot]
        ok = True
        for k in keys:
            if k in rfp_points or k in supp_by_name:
                continue
            pid = _safe_int(k)
            pt = confirmed_points.get(pid) if pid is not None else None
            if pt is not None:
                rfp_points[k] = pt
                continue
            ok = False
            break
        if not ok:
            skipped_lines += 1
            continue
        resolved_lines.append((top, mid, bot))

    if skipped_lines:
        log(f'{skipped_lines} 條參考線因端點座標查無資料而跳過（不猜測連錯的點）')

    _write_rfp(nec_format.case_path(output_folder, src_base, 'RFP'), src_base, rfp_points)
    _write_rfl(nec_format.case_path(output_folder, src_base, 'RFL'), src_base, resolved_lines)
    _write_sup(nec_format.case_path(output_folder, src_base, 'SUP'), src_base, supplements)
    log(f'已寫出參考點 {len(rfp_points)} 個、參考線 {len(resolved_lines)} 條、補點 {len(supplements)} 個')

    return {
        'fit_result': result,
        'match_diagnostics': match_diag,
        'warnings': warnings,
        'output_folder': output_folder,
        'n_coa': len(new_coa_points),
        'n_rfp': len(rfp_points),
        'n_rfl': len(resolved_lines),
        'n_sup': len(supplements),
    }


def _safe_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _sort_key(key):
    try:
        main, sub = key.split('.', 1)
        return (0, int(main), int(sub))
    except ValueError:
        return (1, key)


# ── 新增副檔名：比照 KC0327 原生格式（純文字、Big5、固定寬度）擴充 ──────────────
# .RFP 參考點：ID(左靠12)␣Y(16.8f)␣X(15.8f)，ID 為「母點號.子序號」小數編碼（少數情況為
#              找不到對應宗地的界址點整數點號，見上方端點解析邏輯）
# .RFL 參考線：TOP(左靠12)␣MID(左靠12，可空白)␣BOT(左靠12)，端點對應 .RFP 的 ID 或 .SUP 的點名
# .SUP 補點：  點名(左靠12)␣Y(16.8f)␣X(15.8f)␣等級(左靠4)

def _write_rfp(path, base_name, points):
    with open(path, 'w', encoding=nec_format.ENCODING, errors='replace', newline='') as f:
        f.write(f'{base_name} {len(points)}\n')
        for key in sorted(points, key=_sort_key):
            y, x = points[key]
            f.write(f'{key:<12s}{y:16.8f}{x:15.8f}\n')


def _write_rfl(path, base_name, lines):
    with open(path, 'w', encoding=nec_format.ENCODING, errors='replace', newline='') as f:
        f.write(f'{base_name} {len(lines)}\n')
        for top, mid, bot in lines:
            f.write(f'{top:<12s}{(mid or ""):<12s}{bot:<12s}\n')


def _write_sup(path, base_name, supplements):
    with open(path, 'w', encoding=nec_format.ENCODING, errors='replace', newline='') as f:
        f.write(f'{base_name} {len(supplements)}\n')
        for s in supplements:
            f.write(f"{s['name']:<12s}{s['y']:16.8f}{s['x']:15.8f}{s['level']:<4s}\n")
