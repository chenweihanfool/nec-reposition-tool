"""版本與更新來源設定。"""

APP_TITLE = 'NEC地籍檔定位修正工具'
APP_VERSION = '1.0.0'

GITHUB_OWNER = 'chenweihanfool'
GITHUB_REPO = 'nec-reposition-tool'

# 更新歷程（新版在前），供 GUI 點選版本號時顯示。
CHANGELOG = [
    {
        'version': '1.0.0', 'date': '2026-08-24',
        'notes': [
            '初始版本：讀取未定位資料夾（BNP/COA/PAR，NEC 原生格式）與參考資料夾（重測系統'
            'DBF 格式，D13/D14 已確定新圖 + D2C 舊圖 + D29 參考線 + D20 補點），以「地號」比對'
            '找出共同宗地的界址點，用邊長比對抓出逐點對應，再以最小二乘剛體（旋轉＋平移，無縮放）'
            '套合，把未定位資料夾的所有界址點拉到正確位置',
            '輸出新資料夾：COA 套用轉換後座標，BNP/PAR/CTL/DIS/MAP/RCO/UPN 原樣複製，並新增'
            'RFP（參考點）/RFL（參考線）/SUP（補點）三個檔案，直接採用參考資料夾裡已正確定位的座標',
        ],
    },
]
