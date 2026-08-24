"""串接：讀未定位資料夾（NEC 原生格式）+ 參考資料夾（重測系統格式）
-> 用地號比對抓控制點 -> 求剛體轉換 -> 套用到 COA 界址點
-> 複製 BNP/PAR/CTL/DIS/MAP/RCO/UPN（拓樸/面積/局部繪圖座標，剛體轉換不影響）
-> 寫出參考點/參考線/補點（D14/D29/D20，直接沿用參考資料夾原本的 DBF 格式與座標，
   不轉換、不另外發明格式，讓地籍測量軟體能直接開啟）
-> 輸出新資料夾。
"""
import os
import shutil

import dbf_reader
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
    out_base = os.path.basename(output_folder.rstrip('\\/')) or src_base
    log(f'未定位資料夾：{src_base}（NEC 原生格式）')
    log(f'參考資料夾：{ref_base}（重測系統格式）')
    log(f'輸出檔名將採用輸出資料夾名稱：{out_base}')

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
    nec_format.write_coa(nec_format.case_path(output_folder, out_base, 'COA'), coa_header, new_coa_points)
    log(f'已寫出套合後 COA：{len(new_coa_points)} 個界址點')

    shutil.copy2(nec_format.case_path(unpositioned_folder, src_base, 'BNP'),
                 nec_format.case_path(output_folder, out_base, 'BNP'))
    shutil.copy2(nec_format.case_path(unpositioned_folder, src_base, 'PAR'),
                 nec_format.case_path(output_folder, out_base, 'PAR'))
    copied = nec_format.copy_unchanged(unpositioned_folder, output_folder, src_base, out_base)
    log(f"已原樣複製：BNP, PAR, {', '.join(copied) if copied else '(無其餘檔案)'}")

    n_rfp = _copy_dbf_subset(reference_folder, ref_base, output_folder, out_base, 'D14',
                              keep=resurvey_format.is_ref_point_record)
    n_rfl = _copy_dbf_subset(reference_folder, ref_base, output_folder, out_base, 'D29')
    n_sup = _copy_dbf_subset(reference_folder, ref_base, output_folder, out_base, 'D20')
    log(f'已寫出參考點 {n_rfp} 個（D14）、參考線 {n_rfl} 條（D29）、補點 {n_sup} 個（D20）'
        f'——沿用參考資料夾原本的 DBF 格式，地籍測量軟體可直接開啟')

    return {
        'fit_result': result,
        'match_diagnostics': match_diag,
        'warnings': warnings,
        'output_folder': output_folder,
        'n_coa': len(new_coa_points),
        'n_rfp': n_rfp,
        'n_rfl': n_rfl,
        'n_sup': n_sup,
    }


def _copy_dbf_subset(src_folder, src_base, dst_folder, dst_base, ext, keep=None):
    """把參考資料夾的 D14/D29/D20（DBF 格式，已是正確座標、不需轉換）依原始欄位結構
    篩選（keep=None 表示全部保留）後寫到輸出資料夾，讓地籍測量軟體能直接開啟，
    而不是把資料轉成這個工具自己發明的文字格式。回傳寫出的記錄數（找不到來源檔則為 0）。
    """
    src_path = resurvey_format.case_path(src_folder, src_base, ext)
    if not os.path.exists(src_path):
        return 0
    fields, records = dbf_reader.read_dbf(src_path)
    if keep is not None:
        records = [r for r in records if keep(r)]
    dbf_reader.write_dbf(nec_format.case_path(dst_folder, dst_base, ext), fields, records)
    return len(records)
