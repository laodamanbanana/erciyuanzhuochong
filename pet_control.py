"""
Desktop Pet Control Panel — configure pet settings, check AI API balance.
Standalone tkinter app, cross-platform (Windows / macOS).
"""
import os, sys, json, threading, datetime, time, math, subprocess
import tkinter as tk
from tkinter import ttk

# ── Paths (shared with pet) ──
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.deskpet')
os.makedirs(CONFIG_DIR, exist_ok=True)

AI_CONFIG_PATH = os.path.join(CONFIG_DIR, 'ai_config.json')
SETTINGS_PATH = os.path.join(CONFIG_DIR, 'settings.json')
COMMAND_PATH = os.path.join(CONFIG_DIR, 'command.json')
STATUS_PATH = os.path.join(CONFIG_DIR, 'status.json')

DEFAULT_AI_CONFIG = {
    "api_key": "",
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "model": "deepseek-v4-pro",
    "system_prompt": "You are a helpful assistant living on the user's desktop as a cute pet."
}

DEFAULT_SETTINGS = {
    "pet_scale": 0.7,
    "move_speed": 1.0,
    "particles_enabled": True,
    "freeze_on_chat": True,
    "auto_behavior": True,
}

# ── Pet launch paths ──
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

def _find_pet_path():
    """Find the pet executable or script (cross-platform)."""
    is_mac = sys.platform == 'darwin'
    if is_mac:
        # macOS: look for .app bundle or pet_mac.py
        for p in [os.path.join(_BASE, 'dist', 'DesktopPet.app'),
                  os.path.join(_BASE, 'DesktopPet.app')]:
            if os.path.exists(p):
                return p
        s = os.path.join(_BASE, 'pet_mac.py')
        if os.path.exists(s):
            return s
        s = os.path.join(_BASE, 'pet_main.py')
        if os.path.exists(s):
            return s
    else:
        # Windows: check dist/ or base directory for compiled EXE
        for p in [os.path.join(_BASE, 'dist', 'DesktopPet.exe'),
                  os.path.join(_BASE, 'DesktopPet.exe')]:
            if os.path.exists(p):
                return p
        # Fallback to source script
        s = os.path.join(_BASE, 'pet_main.py')
        if os.path.exists(s):
            return s
    return None

LAUNCH_PATH = _find_pet_path()

def is_pet_running():
    """Check if pet is running by status.json freshness."""
    try:
        if os.path.exists(STATUS_PATH):
            return time.time() - os.path.getmtime(STATUS_PATH) < 10
    except: pass
    return False

def _autostart_plist_path():
    return os.path.join(os.path.expanduser('~'), 'Library', 'LaunchAgents',
                        'com.deskpet.plist')

def _make_plist(launch_path):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.deskpet</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{launch_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>'''

def get_autostart():
    """Check autostart status (Windows registry or macOS LaunchAgents)."""
    if sys.platform == 'darwin':
        plist = _autostart_plist_path()
        return plist if os.path.exists(plist) else None
    # Windows
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "DesktopPet")
        winreg.CloseKey(key)
        return val
    except: return None

def set_autostart(enabled):
    """Enable/disable boot autostart (cross-platform)."""
    if sys.platform == 'darwin':
        plist = _autostart_plist_path()
        if enabled and LAUNCH_PATH:
            try:
                os.makedirs(os.path.dirname(plist), exist_ok=True)
                with open(plist, 'w') as f:
                    f.write(_make_plist(LAUNCH_PATH))
                # Load into launchd
                os.system(f'launchctl load "{plist}"')
                return True
            except: return False
        else:
            try:
                if os.path.exists(plist):
                    os.system(f'launchctl unload "{plist}"')
                    os.remove(plist)
                return True
            except: return False
    # Windows
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if enabled and LAUNCH_PATH:
            winreg.SetValueEx(key, "DesktopPet", 0, winreg.REG_SZ, LAUNCH_PATH)
        else:
            try: winreg.DeleteValue(key, "DesktopPet")
            except: pass
        winreg.CloseKey(key)
        return True
    except: return False

# ── File helpers ──

def read_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(default, dict):
                for k, v in default.items():
                    data.setdefault(k, v)
            return data
    except: pass
    return default

def write_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except: return False

# ════════════════════════════════════════════════════════════
# API Balance Checker
# ════════════════════════════════════════════════════════════

def check_deepseek_balance(api_key):
    """Call DeepSeek /user/balance endpoint."""
    if not api_key:
        return None, "未设置 API 密钥"
    try:
        import requests
        headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
        resp = requests.get("https://api.deepseek.com/user/balance",
                           headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data, None
        elif resp.status_code == 401:
            return None, "API 密钥无效 (401)"
        elif resp.status_code == 429:
            return None, "请求过于频繁 (429)"
        else:
            return None, f"API 错误 ({resp.status_code})"
    except ImportError:
        return None, "缺少 requests 库"
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except requests.exceptions.ConnectionError:
        return None, "网络连接失败"
    except Exception as e:
        return None, str(e)[:100]

# ════════════════════════════════════════════════════════════
# Main Application
# ════════════════════════════════════════════════════════════

class PetControlPanel:
    def __init__(self):
        self.win = tk.Tk()
        self.win.title("✦ 桌宠控制面板")
        self.win.configure(bg='#0D0D0D')
        self.win.geometry("420x580")
        self.win.resizable(False, False)
        self.win.minsize(380, 500)
        if os.name == 'nt':
            self.win.iconbitmap(default='')
        self.win.attributes('-topmost', False)

        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('gold.Horizontal.TScale', background='#0D0D0D',
                       troughcolor='#1A1A1A', slidercolor='#D4AF37')

        # Data
        self.ai_config = read_json(AI_CONFIG_PATH, DEFAULT_AI_CONFIG)
        self.settings = read_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        self.balance_data = None
        self.balance_error = None
        self.balance_timer = None
        self.status_timer = None
        self.pet_status_timer = None
        self._pet_process = None
        self._loading = False

        # Build UI
        self._build_ui()

        # Auto-refresh
        self._refresh_balance()
        self._poll_status()

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.mainloop()

    # ── UI Build ──

    def _build_ui(self):
        w = self.win
        # Title
        tk.Label(w, text="✦ 桌宠控制面板", bg='#0D0D0D', fg='#D4AF37',
                font=('Helvetica', 16, 'bold')).pack(pady=(12, 4))
        tk.Frame(w, height=2, bg='#D4AF37').pack(fill=tk.X, padx=30, pady=(0, 12))

        # Notebook
        nb = ttk.Notebook(w)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # ── Tab 1: AI API ──
        tab1 = tk.Frame(nb, bg='#0D0D0D')
        nb.add(tab1, text="  AI API  ")

        self._build_ai_tab(tab1)

        # ── Tab 2: 设置 ──
        tab2 = tk.Frame(nb, bg='#0D0D0D')
        nb.add(tab2, text="  设置  ")

        self._build_settings_tab(tab2)

        # ── Tab 3: 桌宠状态 ──
        tab3 = tk.Frame(nb, bg='#0D0D0D')
        nb.add(tab3, text="  状态  ")

        self._build_status_tab(tab3)

        # ── Tab 4: 快捷操作 ──
        tab4 = tk.Frame(nb, bg='#0D0D0D')
        nb.add(tab4, text="  操作  ")

        self._build_actions_tab(tab4)

        # ── Tab 5: 启动 ──
        tab5 = tk.Frame(nb, bg='#0D0D0D')
        nb.add(tab5, text="  启动  ")

        self._build_launch_tab(tab5)

    def _make_row(self, parent, label, widget, padx=8):
        row = tk.Frame(parent, bg='#0D0D0D')
        row.pack(fill=tk.X, padx=padx, pady=3)
        tk.Label(row, text=label, bg='#0D0D0D', fg='#B49632',
                font=('Helvetica', 10), width=12, anchor='w').pack(side=tk.LEFT)
        widget.pack(side=tk.RIGHT if hasattr(widget, 'pack') else None, fill=tk.X, expand=True)
        return row

    # ── Tab 1: AI API ──

    def _build_ai_tab(self, parent):
        # Balance card
        card = tk.Frame(parent, bg='#111111', relief=tk.FLAT, bd=1,
                       highlightbackground='#222', highlightthickness=1)
        card.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(card, text="账户余额", bg='#111111', fg='#D4AF37',
                font=('Helvetica', 12, 'bold')).pack(anchor='w', padx=12, pady=(8, 4))

        self.balance_text = tk.Text(card, height=6, bg='#111111', fg='#C0B89A',
            font=('Helvetica', 10), relief=tk.FLAT, bd=0, padx=12, pady=4)
        self.balance_text.pack(fill=tk.X, padx=0, pady=(0, 4))
        self.balance_text.insert('1.0', "点击刷新获取余额...")
        self.balance_text.config(state=tk.DISABLED)

        row = tk.Frame(card, bg='#111111')
        row.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.balance_status = tk.Label(row, text="", bg='#111111', fg='#908A70',
                                       font=('Helvetica', 9))
        self.balance_status.pack(side=tk.LEFT)

        tk.Button(row, text="⟳ 刷新", bg='#1A1A1A', fg='#D4AF37',
                 font=('Helvetica', 9), relief=tk.FLAT, padx=10,
                 command=self._refresh_balance).pack(side=tk.RIGHT)

        # Config display
        card2 = tk.Frame(parent, bg='#111111', highlightbackground='#222', highlightthickness=1)
        card2.pack(fill=tk.X, padx=12, pady=6)

        tk.Label(card2, text="API 配置", bg='#111111', fg='#D4AF37',
                font=('Helvetica', 12, 'bold')).pack(anchor='w', padx=12, pady=(8, 4))

        info = [
            ("接口:", self.ai_config.get("api_url", "")),
            ("模型:", self.ai_config.get("model", "")),
        ]
        for label, val in info:
            r = tk.Frame(card2, bg='#111111')
            r.pack(fill=tk.X, padx=12, pady=1)
            tk.Label(r, text=label, bg='#111111', fg='#908A70',
                    font=('Helvetica', 9), width=6, anchor='w').pack(side=tk.LEFT)
            tk.Label(r, text=val, bg='#111111', fg='#D4AF37',
                    font=('Helvetica', 9), anchor='w').pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Edit config button
        tk.Button(card2, text="编辑 API 配置", bg='#1A1A1A', fg='#D4AF37',
                 font=('Helvetica', 9), relief=tk.FLAT, padx=8,
                 command=self._edit_ai_config).pack(pady=(4, 8))

    # ── Tab 2: Settings ──

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent, bg='#0D0D0D', highlightthickness=0)
        scroll = tk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = tk.Frame(canvas, bg='#0D0D0D')

        scrollable.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=scrollable, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Pet Scale
        self._add_slider_setting(scrollable, "宠物缩放", "pet_scale", 0.3, 1.5, 0.1)

        # Move Speed
        self._add_slider_setting(scrollable, "移动速度", "move_speed", 0.3, 3.0, 0.1)

        # Separator
        tk.Frame(scrollable, height=1, bg='#222').pack(fill=tk.X, padx=12, pady=8)

        # Toggles
        self._add_toggle_setting(scrollable, "粒子特效", "particles_enabled")
        self._add_toggle_setting(scrollable, "AI 对话时冻结", "freeze_on_chat")
        self._add_toggle_setting(scrollable, "自动行为", "auto_behavior")

        # Save button
        tk.Button(scrollable, text="保存设置", bg='#D4AF37', fg='#0A0A0A',
                 font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=20,
                 command=self._save_settings).pack(pady=(16, 8))

        self.settings_status = tk.Label(scrollable, text="", bg='#0D0D0D',
                                         fg='#908A70', font=('Helvetica', 9))
        self.settings_status.pack()

    def _add_slider_setting(self, parent, label, key, min_v, max_v, step):
        row = tk.Frame(parent, bg='#0D0D0D')
        row.pack(fill=tk.X, padx=12, pady=(6, 0))

        lbl_row = tk.Frame(row, bg='#0D0D0D')
        lbl_row.pack(fill=tk.X)
        tk.Label(lbl_row, text=label, bg='#0D0D0D', fg='#D4AF37',
                font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
        val_label = tk.Label(lbl_row, text=f"{self.settings.get(key, min_v):.1f}",
                             bg='#0D0D0D', fg='#B49632', font=('Helvetica', 10))
        val_label.pack(side=tk.RIGHT)

        var = tk.DoubleVar(value=self.settings.get(key, min_v))
        slider = tk.Scale(row, from_=min_v, to=max_v, resolution=step,
                         orient=tk.HORIZONTAL, bg='#0D0D0D', fg='#D4AF37',
                         troughcolor='#222', highlightthickness=0,
                         activebackground='#D4AF37', bd=0, length=250,
                         variable=var, showvalue=False,
                         command=lambda v, k=key, vl=val_label: self._on_slider(k, v, vl))
        slider.pack(fill=tk.X, pady=(2, 0))

        setattr(self, f'_slider_{key}', var)

    def _on_slider(self, key, val_str, label):
        val = round(float(val_str), 1)
        label.config(text=f"{val:.1f}")
        self.settings[key] = val

    def _add_toggle_setting(self, parent, label, key):
        row = tk.Frame(parent, bg='#0D0D0D')
        row.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(row, text=label, bg='#0D0D0D', fg='#D4AF37',
                font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
        var = tk.BooleanVar(value=self.settings.get(key, True))
        cb = tk.Checkbutton(row, bg='#0D0D0D', fg='#D4AF37',
                           activebackground='#0D0D0D', activeforeground='#D4AF37',
                           selectcolor='#1A1A1A', variable=var,
                           command=lambda k=key, v=var: self._on_toggle(k, v))
        cb.pack(side=tk.RIGHT)
        setattr(self, f'_cb_{key}', var)

    def _on_toggle(self, key, var):
        self.settings[key] = var.get()

    def _save_settings(self):
        if write_json(SETTINGS_PATH, self.settings):
            self.settings_status.config(text="✓ 设置已保存", fg='#4CAF50')
        else:
            self.settings_status.config(text="✗ 保存失败", fg='#FF4444')
        self.win.after(2000, lambda: self.settings_status.config(text=""))

    # ── Tab 3: Status ──

    def _build_status_tab(self, parent):
        self.status_labels = {}
        fields = [
            ("mode", "当前模式"),
            ("action", "当前动作"),
            ("position", "位置"),
            ("on_bed", "在床上"),
            ("grabbed", "被拖拽"),
            ("anim_frame", "动画帧"),
        ]
        for key, label in fields:
            row = tk.Frame(parent, bg='#0D0D0D')
            row.pack(fill=tk.X, padx=16, pady=3)
            tk.Label(row, text=label, bg='#0D0D0D', fg='#B49632',
                    font=('Helvetica', 10), width=10, anchor='w').pack(side=tk.LEFT)
            lbl = tk.Label(row, text="-", bg='#0D0D0D', fg='#C0B89A',
                          font=('Helvetica', 10), anchor='w')
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.status_labels[key] = lbl

        tk.Label(parent, text="", bg='#0D0D0D').pack(pady=4)

        tk.Label(parent, text="状态文件由桌宠自动更新", bg='#0D0D0D',
                fg='#555', font=('Helvetica', 9)).pack()

        # Force refresh button
        tk.Button(parent, text="⟳ 刷新状态", bg='#1A1A1A', fg='#D4AF37',
                 font=('Helvetica', 9), relief=tk.FLAT, padx=10,
                 command=self._update_status_display).pack(pady=6)

    # ── Tab 4: Quick Actions ──

    def _build_actions_tab(self, parent):
        tk.Label(parent, text="快捷操作", bg='#0D0D0D', fg='#D4AF37',
                font=('Helvetica', 13, 'bold')).pack(pady=(14, 10))

        btn_frame = tk.Frame(parent, bg='#0D0D0D')
        btn_frame.pack(pady=6)

        actions = [
            ("😴 睡觉", "sleep"),
            ("☀️ 起床", "wakeup"),
            ("🚶 行走", "walk"),
            ("🧘 待机", "idle"),
            ("🛏️ 显示床", "show_bed"),
            ("🙈 隐藏床", "hide_bed"),
            ("💬 打开 AI", "ai_chat"),
            ("❌ 退出桌宠", "exit"),
        ]

        for i, (text, cmd) in enumerate(actions):
            bg = '#8B0000' if cmd == 'exit' else '#1A1A1A'
            fg = '#FF6666' if cmd == 'exit' else '#D4AF37'
            btn = tk.Button(btn_frame, text=text, bg=bg, fg=fg,
                          font=('Helvetica', 10), relief=tk.FLAT, padx=14,
                          width=10, command=lambda c=cmd: self._send_command(c))
            btn.grid(row=i//2, column=i%2, padx=4, pady=3)

        self.action_status = tk.Label(parent, text="", bg='#0D0D0D',
                                       fg='#908A70', font=('Helvetica', 9))
        self.action_status.pack(pady=6)

        # Refresh settings from pet button
        tk.Button(parent, text="⟳ 从桌宠读取当前设置", bg='#1A1A1A', fg='#B49632',
                 font=('Helvetica', 9), relief=tk.FLAT, padx=10,
                 command=self._reload_settings).pack(pady=(14, 4))

    # ── Commands ──

    def _send_command(self, cmd):
        data = {
            "command": cmd,
            "timestamp": time.time(),
        }
        if write_json(COMMAND_PATH, data):
            self.action_status.config(text=f"✓ 命令已发送: {cmd}", fg='#4CAF50')
        else:
            self.action_status.config(text="✗ 发送失败", fg='#FF4444')
        self.win.after(2000, lambda: self.action_status.config(text=""))

    # ── Balance ──

    def _refresh_balance(self):
        self.balance_status.config(text="查询中...", fg='#FFA500')
        self.balance_text.config(state=tk.NORMAL)
        self.balance_text.delete('1.0', tk.END)
        self.balance_text.insert('1.0', "正在查询余额...")
        self.balance_text.config(state=tk.DISABLED)

        api_key = self.ai_config.get("api_key", "")
        threading.Thread(target=self._do_balance_check, args=(api_key,), daemon=True).start()

        # Auto-refresh every 60s
        if self.balance_timer:
            self.win.after_cancel(self.balance_timer)
        self.balance_timer = self.win.after(60000, self._refresh_balance)

    def _do_balance_check(self, api_key):
        data, err = check_deepseek_balance(api_key)
        self.win.after(0, lambda: self._show_balance_result(data, err))

    def _show_balance_result(self, data, err):
        self.balance_text.config(state=tk.NORMAL)
        self.balance_text.delete('1.0', tk.END)

        if err:
            self.balance_text.insert('1.0', f"⚠ {err}\n\n")
            self.balance_text.insert(tk.END, "请检查 API 密钥设置\n")
            self.balance_status.config(text=err, fg='#FF4444')
        elif data:
            self.balance_data = data
            infos = data.get("balance_infos", [])
            if infos:
                info = infos[0]
                total = info.get("total_balance", "0.00")
                granted = info.get("granted_balance", "0.00")
                topped = info.get("topped_up_balance", "0.00")
                currency = info.get("currency", "CNY")
                available = data.get("is_available", False)

                status_text = "✅ 可用" if available else "❌ 余额不足"
                self.balance_text.insert('1.0', f"总余额:      ¥{total}\n", ('big',))
                self.balance_text.insert(tk.END, f"赠送余额:   ¥{granted}\n")
                self.balance_text.insert(tk.END, f"充值余额:   ¥{topped}\n")
                self.balance_text.insert(tk.END, f"货币:        {currency}\n")
                self.balance_text.insert(tk.END, f"状态:        {status_text}\n")
                self.balance_text.tag_config('big', foreground='#FFD700',
                    font=('Helvetica', 13, 'bold'))
                self.balance_status.config(text=f"✅ 余额: ¥{total}", fg='#4CAF50')
            else:
                self.balance_text.insert('1.0', "未找到余额信息")
                self.balance_status.config(text="未知余额", fg='#FFA500')
        else:
            self.balance_text.insert('1.0', "无法获取余额信息")
            self.balance_status.config(text="查询失败", fg='#FF4444')

        self.balance_text.config(state=tk.DISABLED)

    # ── Status Polling ──

    def _poll_status(self):
        self._update_status_display()
        self.status_timer = self.win.after(2000, self._poll_status)

    def _update_status_display(self):
        status = read_json(STATUS_PATH, {})
        for key, label in [
            ("mode", "mode"), ("action", "action"), ("position", "position"),
            ("on_bed", "on_bed"), ("grabbed", "grabbed"), ("anim_frame", "anim_frame"),
        ]:
            val = status.get(key, "-")
            if isinstance(val, bool):
                val = "✓" if val else "✗"
            elif isinstance(val, (list, tuple)):
                val = f"({val[0]}, {val[1]})"
            lbl = self.status_labels.get(key)
            if lbl:
                lbl.config(text=str(val))

    # ── Edit AI Config ──

    def _edit_ai_config(self):
        dialog = tk.Toplevel(self.win)
        dialog.title("编辑 API 配置")
        dialog.geometry("460x320")
        dialog.configure(bg='#0D0D0D')
        dialog.resizable(False, False)
        dialog.transient(self.win)
        dialog.grab_set()

        entries = {}
        fields = [
            ("API 密钥:", "api_key", True),
            ("API 地址:", "api_url", False),
            ("模型:", "model", False),
            ("系统提示词:", "system_prompt", False),
        ]

        for i, (label, key, pw) in enumerate(fields):
            tk.Label(dialog, text=label, bg='#0D0D0D', fg='#D4AF37',
                    font=('Helvetica', 10), anchor='w').grid(row=i, column=0, sticky='w',
                                                              padx=(12, 4), pady=6)
            if key == "system_prompt":
                e = tk.Text(dialog, height=3, bg='#1A1A1A', fg='#D4AF37',
                          font=('Helvetica', 10), insertbackground='#D4AF37',
                          relief=tk.FLAT, bd=4)
                e.grid(row=i, column=1, sticky='ew', padx=(0, 12), pady=6)
                e.insert('1.0', self.ai_config.get(key, ""))
            else:
                e = tk.Entry(dialog, bg='#1A1A1A', fg='#D4AF37',
                           font=('Helvetica', 10), insertbackground='#D4AF37',
                           relief=tk.FLAT, bd=4, show='*' if pw else None)
                e.grid(row=i, column=1, sticky='ew', padx=(0, 12), pady=6, ipady=2)
                e.insert(0, self.ai_config.get(key, ""))
            entries[key] = e

        dialog.columnconfigure(1, weight=1)

        btn_frame = tk.Frame(dialog, bg='#0D0D0D')
        btn_frame.grid(row=len(fields), column=0, columnspan=2, pady=12)

        def save():
            cfg = {}
            for key in ["api_key", "api_url", "model"]:
                cfg[key] = entries[key].get().strip()
            cfg["system_prompt"] = entries["system_prompt"].get('1.0', tk.END).strip()
            if not cfg["api_key"] or not cfg["api_url"]:
                from tkinter import messagebox
                messagebox.showwarning("提示", "API 密钥和地址不能为空")
                return
            write_json(AI_CONFIG_PATH, cfg)
            self.ai_config = cfg
            dialog.destroy()
            # Refresh balance
            self._refresh_balance()

        tk.Button(btn_frame, text="保存", bg='#D4AF37', fg='#0A0A0A',
                 font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=16,
                 command=save).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="取消", bg='#1A1A1A', fg='#D4AF37',
                 font=('Helvetica', 10), relief=tk.FLAT, padx=16,
                 command=dialog.destroy).pack(side=tk.LEFT, padx=4)

    # ── Reload ──

    def _reload_settings(self):
        self.settings = read_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        for key, val in self.settings.items():
            var = getattr(self, f'_slider_{key}', None)
            if var is not None:
                var.set(val)
            cb = getattr(self, f'_cb_{key}', None)
            if cb is not None:
                cb.set(val)
        self.action_status.config(text="✓ 已从桌宠读取设置", fg='#4CAF50')
        self.win.after(2000, lambda: self.action_status.config(text=""))

    # ── Tab 5: Launch ──

    def _build_launch_tab(self, parent):
        # --- Pet status card ---
        card = tk.Frame(parent, bg='#111111', highlightbackground='#222', highlightthickness=1)
        card.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(card, text="桌宠状态", bg='#111111', fg='#D4AF37',
                font=('Helvetica', 12, 'bold')).pack(anchor='w', padx=12, pady=(8, 4))

        self.pet_status_label = tk.Label(card, text="检测中...", bg='#111111', fg='#FFA500',
            font=('Helvetica', 16, 'bold'))
        self.pet_status_label.pack(anchor='center', padx=12, pady=(4, 6))

        btn_frame = tk.Frame(card, bg='#111111')
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.launch_btn = tk.Button(btn_frame, text="▶ 启动桌宠", bg='#1A1A1A', fg='#4CAF50',
            font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=14,
            command=self._launch_pet, state=tk.NORMAL if LAUNCH_PATH else tk.DISABLED)
        self.launch_btn.pack(side=tk.LEFT, padx=4)

        self.stop_btn = tk.Button(btn_frame, text="⏹ 停止桌宠", bg='#1A1A1A', fg='#FF6666',
            font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=14,
            command=self._stop_pet, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        path_str = LAUNCH_PATH or "未找到桌宠程序"
        tk.Label(card, text=f"路径: {path_str}", bg='#111111', fg='#555',
            font=('Helvetica', 8), wraplength=360, anchor='w').pack(anchor='w', padx=12, pady=(0, 6))

        # --- Autostart card ---
        card2 = tk.Frame(parent, bg='#111111', highlightbackground='#222', highlightthickness=1)
        card2.pack(fill=tk.X, padx=12, pady=6)

        tk.Label(card2, text="开机自启动", bg='#111111', fg='#D4AF37',
                font=('Helvetica', 12, 'bold')).pack(anchor='w', padx=12, pady=(8, 4))

        auto_val = bool(get_autostart())
        self.autostart_var = tk.BooleanVar(value=auto_val)
        tk.Checkbutton(card2, text="系统启动时自动运行桌宠", bg='#111111', fg='#D4AF37',
            activebackground='#111111', activeforeground='#D4AF37', selectcolor='#1A1A1A',
            variable=self.autostart_var, command=self._toggle_autostart).pack(anchor='w', padx=12, pady=4)

        info = "启用后，每次开机登录时桌宠将自动启动。\n关闭控制面板不影响桌宠运行。"
        if not LAUNCH_PATH:
            info = "未找到桌宠程序，请在 pet_main.py 所在目录运行此程序。"
        tk.Label(card2, text=info, bg='#111111', fg='#555',
            font=('Helvetica', 9), justify=tk.LEFT).pack(anchor='w', padx=12, pady=(0, 8))

        self.launch_status = tk.Label(parent, text="", bg='#0D0D0D', fg='#908A70',
            font=('Helvetica', 9))
        self.launch_status.pack(pady=4)

        # Start polling
        self._poll_pet_status()

    def _launch_pet(self):
        if not LAUNCH_PATH:
            self.launch_status.config(text="✗ 未找到桌宠程序", fg='#FF4444')
            return
        if self._pet_process is not None:
            ret = self._pet_process.poll()
            if ret is None:
                self.launch_status.config(text="桌宠已在运行中", fg='#FFA500')
                return
            self._pet_process = None
        try:
            if LAUNCH_PATH.endswith('.py'):
                self._pet_process = subprocess.Popen(
                    [sys.executable, LAUNCH_PATH],
                    cwd=_BASE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            elif LAUNCH_PATH.endswith('.app'):
                # macOS .app bundle
                self._pet_process = subprocess.Popen(
                    ['open', LAUNCH_PATH],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                self._pet_process = subprocess.Popen(
                    [LAUNCH_PATH],
                    cwd=os.path.dirname(LAUNCH_PATH),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            self.launch_status.config(text="✓ 桌宠已启动", fg='#4CAF50')
        except Exception as e:
            self.launch_status.config(text=f"✗ 启动失败: {str(e)[:60]}", fg='#FF4444')
            self._pet_process = None
        self._update_launch_buttons()

    def _stop_pet(self):
        # Send exit command via IPC
        write_json(COMMAND_PATH, {"command": "exit", "timestamp": time.time()})
        # Also terminate subprocess if we launched it
        if self._pet_process is not None:
            try:
                self._pet_process.terminate()
                self._pet_process.wait(timeout=3)
            except: pass
            self._pet_process = None
        self.launch_status.config(text="⏹ 已发送停止命令", fg='#FFA500')
        self._update_launch_buttons()

    def _toggle_autostart(self):
        enabled = self.autostart_var.get()
        ok = set_autostart(enabled)
        if ok:
            status = "已启用开机自启动" if enabled else "已关闭开机自启动"
            self.launch_status.config(text=f"✓ {status}", fg='#4CAF50')
        else:
            self.autostart_var.set(not enabled)
            self.launch_status.config(text="✗ 设置失败", fg='#FF4444')
        self.win.after(2000, lambda: self.launch_status.config(text=""))

    def _poll_pet_status(self):
        running = is_pet_running()
        self._update_launch_buttons(running)

        if running:
            self.pet_status_label.config(text="● 运行中", fg='#4CAF50')
        else:
            self.pet_status_label.config(text="○ 已停止", fg='#FF6666')
            # Clean up stale process handle
            if self._pet_process is not None:
                try:
                    if self._pet_process.poll() is not None:
                        self._pet_process = None
                except: self._pet_process = None

        self.pet_status_timer = self.win.after(2000, self._poll_pet_status)

    def _update_launch_buttons(self, running=None):
        if running is None:
            running = is_pet_running()
        if running:
            self.launch_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.launch_btn.config(state=tk.NORMAL if LAUNCH_PATH else tk.DISABLED)
            self.stop_btn.config(state=tk.DISABLED)

    # ── Close ──

    def _on_close(self):
        if self.balance_timer:
            self.win.after_cancel(self.balance_timer)
        if self.status_timer:
            self.win.after_cancel(self.status_timer)
        if self.pet_status_timer:
            self.win.after_cancel(self.pet_status_timer)
        self.win.destroy()


if __name__ == '__main__':
    PetControlPanel()
