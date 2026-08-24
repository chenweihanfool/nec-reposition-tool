"""地號比對 + 邊長比對抓控制點對 + 剛體（旋轉＋平移，無縮放無鏡射）最小二乘套合。

matched by 地號（母號,子號），因為兩邊界址點的「點號」是各自獨立編號、不能直接比對
（實測驗證：同點號座標差異從 +9m 到 -950m 不等）。同一宗地在兩邊資料裡點的「個數」相同時，
才視為候選控制宗地——用邊長（相鄰點距離，剛體轉換不改變邊長）比對找出正確的起點位移與方向。

2D 剛體最小二乘解法（封閉解，等價於 2D Kabsch/Procrustes）已用合成資料數值驗證：
給定已知旋轉角+平移，重建結果與真值誤差 < 1e-9。
"""
import math


def _ring_edges(ring):
    n = len(ring)
    return [math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][1] - ring[i][1]) for i in range(n)]


def _mean_edge_length(ring):
    edges = _ring_edges(ring)
    return sum(edges) / len(edges) if edges else 0.0


def _best_cyclic_alignment(src, dst):
    """回傳 (rms, aligned_src)，aligned_src[i] 對應 dst[i]。嘗試所有起點位移 x 正/反方向，
    以邊長差平方和最小者為最佳對齊。"""
    n = len(src)
    if n < 3 or len(dst) != n:
        return None
    dst_edges = _ring_edges(dst)
    best = None
    for direction in (1, -1):
        seq = src if direction == 1 else list(reversed(src))
        for shift in range(n):
            rotated = seq[shift:] + seq[:shift]
            edges = _ring_edges(rotated)
            sse = sum((e1 - e2) ** 2 for e1, e2 in zip(edges, dst_edges))
            rms = math.sqrt(sse / n)
            if best is None or rms < best[0]:
                best = (rms, rotated)
    return best


def match_control_points(bnp_points, coa_points, rings, confirmed_points,
                          abs_edge_tol=0.5, rel_edge_tol=0.05):
    """比對未定位資料（bnp_points/coa_points，NEC 原生格式）與參考資料
    （rings/confirmed_points，重測系統已確定新圖）的共同宗地，抓出逐點對應。

    bnp_points: {(母號,子號): [點號,...]}          coa_points: {點號: (Y,X,flag)}
    rings:      {(母號,子號): [D14點號,...]}        confirmed_points: {D14點號: (Y,X)}

    回傳 (pairs, diagnostics)：
      pairs: [((src_y,src_x), (dst_y,dst_x)), ...]，src=未定位座標，dst=正確座標
      diagnostics: dict，含命中/接受/拒絕的宗地清單，供 GUI 顯示與人工複核
    """
    common = sorted(set(bnp_points) & set(rings))
    count_mismatch = []
    accepted = []
    rejected = []
    pairs = []

    for key in common:
        src_ids = bnp_points[key]
        dst_ids = rings[key]
        if len(src_ids) != len(dst_ids) or len(src_ids) < 3:
            count_mismatch.append({'key': key, 'src_n': len(src_ids), 'dst_n': len(dst_ids)})
            continue

        src_coords, dst_coords = [], []
        missing = False
        for pid in src_ids:
            rec = coa_points.get(pid)
            if rec is None:
                missing = True
                break
            src_coords.append((rec[0], rec[1]))
        if not missing:
            for pid in dst_ids:
                rec = confirmed_points.get(pid)
                if rec is None:
                    missing = True
                    break
                dst_coords.append(rec)
        if missing:
            count_mismatch.append({'key': key, 'src_n': len(src_ids), 'dst_n': len(dst_ids), 'reason': 'missing_point'})
            continue

        best = _best_cyclic_alignment(src_coords, dst_coords)
        if best is None:
            rejected.append({'key': key, 'rms': None})
            continue
        rms, aligned_src = best
        threshold = max(abs_edge_tol, _mean_edge_length(dst_coords) * rel_edge_tol)
        if rms > threshold:
            rejected.append({'key': key, 'rms': rms, 'threshold': threshold})
            continue

        accepted.append({'key': key, 'rms': rms, 'n_points': len(aligned_src)})
        pairs.extend(zip(aligned_src, dst_coords))

    diagnostics = {
        'total_common_parcels': len(common),
        'count_mismatch': count_mismatch,
        'accepted_parcels': accepted,
        'rejected_parcels': rejected,
        'n_pairs': len(pairs),
    }
    return pairs, diagnostics


def fit_rigid_transform(pairs, weights=None):
    """2D 剛體（旋轉＋平移，無縮放無鏡射）最小二乘封閉解（加權 Procrustes/Kabsch）。
    pairs: [((src_y,src_x), (dst_y,dst_x)), ...]。
    weights: 逐點權重，None 時等權重（等權重時即一般最小二乘，與原行為相同）；
             權重越高的點對，套合結果在該點附近的殘差會被壓得越小
             （見 fit_rigid_transform_targeted：依離指定地號的距離加權，讓套合結果
             在該地號附近盡可能貼合，代價是其餘範圍誤差可能變大）。
    回傳 dict：theta_rad/theta_deg、centroid_src/dst、transform(y,x)->(y,x)、
    n_points、rmse（未加權，整體精度）、weighted_rmse（加權，等權重時等於 rmse）、
    max_residual、residuals（逐點，供離群點複查）。
    """
    n = len(pairs)
    if n < 2:
        raise ValueError('控制點不足（至少需要 2 個點才能求解剛體轉換，實際只有 %d 個）' % n)
    if weights is None:
        weights = [1.0] * n
    elif len(weights) != n:
        raise ValueError('weights 長度需與 pairs 相同')

    src = [p[0] for p in pairs]
    dst = [p[1] for p in pairs]
    wsum = sum(weights)
    csy = sum(w * p[0] for w, p in zip(weights, src)) / wsum
    csx = sum(w * p[1] for w, p in zip(weights, src)) / wsum
    cdy = sum(w * p[0] for w, p in zip(weights, dst)) / wsum
    cdx = sum(w * p[1] for w, p in zip(weights, dst)) / wsum

    syy = syx = sxy = sxx = 0.0
    for w, (sy, sx), (dy, dx) in zip(weights, src, dst):
        ay, ax = sy - csy, sx - csx
        by, bx = dy - cdy, dx - cdx
        syy += w * ay * by
        syx += w * ay * bx
        sxy += w * ax * by
        sxx += w * ax * bx

    theta = math.atan2(syx - sxy, syy + sxx)
    c, s = math.cos(theta), math.sin(theta)

    def transform(y, x):
        dy, dx = y - csy, x - csx
        ry = c * dy - s * dx
        rx = s * dy + c * dx
        return cdy + ry, cdx + rx

    residuals = []
    for (sy, sx), (dy, dx) in zip(src, dst):
        ny, nx = transform(sy, sx)
        residuals.append(math.hypot(ny - dy, nx - dx))
    rmse = math.sqrt(sum(r ** 2 for r in residuals) / n)
    weighted_rmse = math.sqrt(sum(w * r ** 2 for w, r in zip(weights, residuals)) / wsum)
    max_residual = max(residuals) if residuals else 0.0

    return {
        'theta_rad': theta,
        'theta_deg': math.degrees(theta),
        'centroid_src': (csy, csx),
        'centroid_dst': (cdy, cdx),
        'transform': transform,
        'n_points': n,
        'rmse': rmse,
        'weighted_rmse': weighted_rmse,
        'max_residual': max_residual,
        'residuals': residuals,
        'weights': weights,
    }


# 加權套合時的「軟化距離」（公尺）：權重 = 1 / (距離² + 此值²)，避免距離趨近 0 時
# 單一控制點權重趨近無限大、完全蓋掉其他控制點的貢獻（數值不穩定、也失去套合的意義）。
TARGET_WEIGHT_SOFTEN_M = 10.0


def _parcel_centroid(points_dict, ids):
    coords = [points_dict[pid][:2] for pid in ids if pid in points_dict]
    if not coords:
        return None
    n = len(coords)
    return (sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n)


def fit_rigid_transform_targeted(pairs, bnp_points, coa_points, target_key, iterations=3):
    """指定一個地號，讓套合結果在該地號座標附近盡可能貼合（代價是離該地號較遠處的
    整體精度可能變差）。

    做法：控制點離「指定地號的正確位置」越近，加權套合時權重越高（反距離平方）。
    但套合前並不知道指定地號的正確位置（它可能根本不是控制宗地，沒有參考資料夾裡
    的正確座標可查）——所以先用一般等權重套合估出它的大略正確位置，再依各控制點與
    這個位置的距離重新加權、重新套合，重複幾次讓「加權中心」跟著套合結果收斂。
    """
    src_ids = bnp_points.get(target_key)
    if not src_ids:
        raise ValueError(f'指定地號 {target_key[0]}-{target_key[1]} 在未定位資料夾（BNP）裡查無資料')
    centroid_src = _parcel_centroid(coa_points, src_ids)
    if centroid_src is None:
        raise ValueError(f'指定地號 {target_key[0]}-{target_key[1]} 的界址點座標（COA）查無資料')

    result = fit_rigid_transform(pairs)
    center_dst = None
    for _ in range(iterations):
        center_dst = result['transform'](*centroid_src)
        weights = [
            1.0 / (math.hypot(dy - center_dst[0], dx - center_dst[1]) ** 2 + TARGET_WEIGHT_SOFTEN_M ** 2)
            for (_sy, _sx), (dy, dx) in pairs
        ]
        result = fit_rigid_transform(pairs, weights)

    result['target_key'] = target_key
    result['target_center'] = center_dst
    return result
