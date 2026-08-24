"""NEC 地籍檔定位修正工具 - GUI

流程：選未定位資料夾（NEC 原生格式，如 KC0327）-> 選參考資料夾（重測系統格式，如 KC2327）
     -> 按「開始轉換」：用地號比對抓控制點、求剛體（旋轉＋平移）套合轉換、把未定位資料夾的
     所有界址點拉到正確位置，並把參考資料夾的參考點/參考線/補點一併轉出 -> 輸出新資料夾。
"""
import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import nec_format
import resurvey_format
import pipeline
import updater
from version import APP_TITLE, APP_VERSION, CHANGELOG


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP_TITLE} v{APP_VERSION}')
        self.geometry('760x820')
        self.minsize(700, 700)

        self.src_folder = None
        self.src_base = None
        self.ref_folder = None
        self.ref_base = None
        self.output_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.status_var = tk.StringVar(value='請先選擇未定位資料夾與參考資料夾')

        self._log_queue = queue.Queue()

        self._build_ui()
        self.after(100, self._poll_log_queue)
        self.after(300, self._start_update_check)

    # ── 自動更新（GitHub Releases，邏輯與 QGZ 複丈歷史資料匯出工具一致）───────
    def _start_update_check(self):
        threading.Thread(target=self._update_check_thread, daemon=True).start()

    def _update_check_thread(self):
        triggered = updater.check_and_prepare_update(APP_VERSION, log=self.log)
        if triggered:
            self.after(0, self._begin_restart_for_update)

    def _begin_restart_for_update(self):
        self.status_var.set('已下載新版本，即將重新啟動…')
        self.after(1200, self._finalize_update_and_exit)

    def _finalize_update_and_exit(self):
        self.destroy()
        os._exit(0)

    def show_changelog(self):
        win = tk.Toplevel(self)
        win.title('更新歷程')
        win.geometry('560x480')
        win.transient(self)

        frame = ttk.Frame(win)
        frame.pack(fill='both', expand=True, padx=12, pady=12)

        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        for entry in CHANGELOG:
            ttk.Label(inner, text=f"v{entry['version']}　{entry['date']}",
                      font=('', 11, 'bold'), foreground='#1a5cb8').pack(anchor='w', pady=(10, 2))
            for note in entry['notes']:
                ttk.Label(inner, text=f'• {note}', wraplength=500, justify='left').pack(anchor='w', padx=(12, 0))

        ttk.Button(win, text='關閉', command=win.destroy).pack(pady=(0, 10))

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        pad = {'padx': 10, 'pady': 6}

        header = ttk.Frame(self)
        header.pack(fill='x', padx=10, pady=(8, 0))
        ttk.Label(header, text=APP_TITLE, font=('', 12, 'bold')).pack(side='left')
        ver_link = ttk.Label(header, text=f'v{APP_VERSION}（點選查看更新歷程）',
                              foreground='#1a5cb8', cursor='hand2')
        ver_link.pack(side='left', padx=10)
        ver_link.bind('<Button-1>', lambda _e: self.show_changelog())

        step1 = ttk.LabelFrame(self, text='步驟 1 — 選擇未定位資料夾（NEC 原生格式，內含 .BNP/.COA/.PAR）')
        step1.pack(fill='x', **pad)
        row1 = ttk.Frame(step1)
        row1.pack(fill='x', padx=8, pady=6)
        ttk.Button(row1, text='📁 選擇資料夾…', command=self.pick_src_folder).pack(side='left')
        self.lbl_src = ttk.Label(row1, text='尚未選擇（例如 KC0327）', foreground='#888')
        self.lbl_src.pack(side='left', padx=10)

        step2 = ttk.LabelFrame(self, text='步驟 2 — 選擇參考資料夾（重測系統格式，內含 .D13/.D14/.D29）')
        step2.pack(fill='x', **pad)
        row2 = ttk.Frame(step2)
        row2.pack(fill='x', padx=8, pady=6)
        ttk.Button(row2, text='📁 選擇資料夾…', command=self.pick_ref_folder).pack(side='left')
        self.lbl_ref = ttk.Label(row2, text='尚未選擇（例如 KC2327）', foreground='#888')
        self.lbl_ref.pack(side='left', padx=10)

        step3 = ttk.LabelFrame(self, text='步驟 3 — 輸出位置')
        step3.pack(fill='x', **pad)
        row3 = ttk.Frame(step3)
        row3.pack(fill='x', padx=8, pady=6)
        ttk.Button(row3, text='📁 選擇輸出資料夾…', command=self.pick_output_folder).pack(side='left')
        self.lbl_output = ttk.Label(row3, text='尚未選擇（預設：未定位資料夾同層，加上「_定位」）', foreground='#888')
        self.lbl_output.pack(side='left', padx=10)

        step4 = ttk.LabelFrame(self, text='進階（選填）— 指定地號局部加權套合')
        step4.pack(fill='x', **pad)
        row4 = ttk.Frame(step4)
        row4.pack(fill='x', padx=8, pady=6)
        ttk.Label(row4, text='地號（母號-子號，例如 123-45）：').pack(side='left')
        ttk.Entry(row4, textvariable=self.target_var, width=14).pack(side='left', padx=6)
        ttk.Label(
            row4,
            text='留空＝一般套合（整體最準）；填寫則讓套合結果在此地號附近盡可能貼合，其餘範圍精度可能降低',
            foreground='#888', wraplength=560, justify='left',
        ).pack(side='left', padx=6)

        run_row = ttk.Frame(self)
        run_row.pack(fill='x', **pad)
        self.btn_run = ttk.Button(run_row, text='開始轉換', command=self.start_run, state='disabled')
        self.btn_run.pack(side='left')
        ttk.Label(run_row, textvariable=self.status_var, foreground='#555').pack(side='left', padx=10)

        log_frame = ttk.LabelFrame(self, text='紀錄')
        log_frame.pack(fill='both', expand=True, **pad)
        self.txt_log = tk.Text(log_frame, height=18, wrap='word', state='disabled')
        self.txt_log.pack(fill='both', expand=True, padx=8, pady=8)

    # ── 選資料夾 ──────────────────────────────────────────────────────────
    def pick_src_folder(self):
        folder = filedialog.askdirectory(title='選擇未定位資料夾（NEC 原生格式）')
        if not folder:
            return
        try:
            _prefix, base = nec_format.detect_case(folder)
        except nec_format.CaseNotFoundError as e:
            messagebox.showerror('選擇失敗', str(e))
            return
        self.src_folder = folder
        self.src_base = base
        self.lbl_src.config(text=f'{base}（{folder}）', foreground='#2a7a3a')
        self._update_default_output()
        self._update_run_state()

    def pick_ref_folder(self):
        folder = filedialog.askdirectory(title='選擇參考資料夾（重測系統格式）')
        if not folder:
            return
        try:
            _prefix, base = resurvey_format.detect_case(folder)
        except resurvey_format.CaseNotFoundError as e:
            messagebox.showerror('選擇失敗', str(e))
            return
        self.ref_folder = folder
        self.ref_base = base
        self.lbl_ref.config(text=f'{base}（{folder}）', foreground='#2a7a3a')
        self._update_run_state()

    def pick_output_folder(self):
        folder = filedialog.askdirectory(title='選擇輸出資料夾')
        if not folder:
            return
        self.output_var.set(folder)
        self.lbl_output.config(text=folder, foreground='#2a7a3a')

    def _update_default_output(self):
        if self.src_folder and not self.output_var.get():
            default = self.src_folder.rstrip('\\/') + '_定位'
            self.output_var.set(default)
            self.lbl_output.config(text=f'{default}（預設）', foreground='#888')

    def _update_run_state(self):
        self.btn_run.config(state='normal' if (self.src_folder and self.ref_folder) else 'disabled')

    # ── 執行 ──────────────────────────────────────────────────────────────
    def log(self, msg):
        self._log_queue.put(msg)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.txt_log.config(state='normal')
                self.txt_log.insert('end', msg + '\n')
                self.txt_log.see('end')
                self.txt_log.config(state='disabled')
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _parse_target_parcel(self):
        text = self.target_var.get().strip()
        if not text:
            return None
        sep = '-' if '-' in text else ('.' if '.' in text else None)
        if sep is None:
            raise ValueError(f'地號格式錯誤：「{text}」，請用「母號-子號」格式（例如 123-45）')
        main_s, _, sub_s = text.partition(sep)
        try:
            return (int(main_s.strip()), int(sub_s.strip()))
        except ValueError:
            raise ValueError(f'地號格式錯誤：「{text}」，請用「母號-子號」格式（例如 123-45），母號子號需為數字')

    def start_run(self):
        try:
            target_parcel = self._parse_target_parcel()
        except ValueError as e:
            messagebox.showerror('地號格式錯誤', str(e))
            return
        output = self.output_var.get() or (self.src_folder.rstrip('\\/') + '_定位')
        if os.path.exists(output) and os.listdir(output):
            if not messagebox.askyesno(
                '輸出資料夾非空',
                f'輸出資料夾「{output}」已存在且非空，繼續執行可能覆蓋裡面同名檔案，是否繼續？',
            ):
                return
        self.btn_run.config(state='disabled')
        self.status_var.set('轉換中…')
        threading.Thread(target=self._run_thread, args=(output, target_parcel), daemon=True).start()

    def _run_thread(self, output, target_parcel):
        try:
            result = pipeline.run(self.src_folder, self.ref_folder, output, target_parcel=target_parcel, log=self.log)
            self.after(0, lambda: self._on_run_done(result))
        except Exception as e:
            traceback.print_exc()
            self.after(0, lambda: self._on_run_error(e))

    def _on_run_done(self, result):
        self.status_var.set('完成')
        self.btn_run.config(state='normal')
        fit_result = result['fit_result']
        lines = [
            f"轉換完成！輸出資料夾：\n{result['output_folder']}\n",
            f"界址點 {result['n_coa']} 個、參考點 {result['n_rfp']} 個、"
            f"參考線 {result['n_rfl']} 條、補點 {result['n_sup']} 個",
        ]
        if fit_result.get('target_key'):
            mk, sk = fit_result['target_key']
            lines.append(
                f"已針對地號 {mk}-{sk} 加權套合：該地號附近 RMSE {fit_result['weighted_rmse'] * 100:.1f} cm"
                f"（整體 RMSE {fit_result['rmse'] * 100:.1f} cm，{fit_result['n_points']} 個控制點）"
            )
        else:
            lines.append(
                f"套合 RMSE：{fit_result['rmse'] * 100:.1f} cm（{fit_result['n_points']} 個控制點）"
            )
        msg = '\n'.join(lines)
        if result['warnings']:
            msg += '\n\n注意：\n' + '\n'.join(f'• {w}' for w in result['warnings'])
            messagebox.showwarning('轉換完成（請留意警告）', msg)
        else:
            messagebox.showinfo('轉換完成', msg)
        try:
            os.startfile(result['output_folder'])
        except Exception:
            pass

    def _on_run_error(self, e):
        self.status_var.set('發生錯誤')
        self.btn_run.config(state='normal')
        messagebox.showerror('轉換失敗', str(e))


if __name__ == '__main__':
    App().mainloop()
