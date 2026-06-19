"""
AI Chat module for Desktop Pet.
Pure Win32 implementation — no tkinter dependency.
Provides a small draggable chat window with RichEdit message display,
EDIT input, and OpenAI-compatible API integration.
"""
import os, sys, json, threading, ctypes, datetime
from ctypes import wintypes
import win32gui, win32con, win32api

# Debug log (next to exe/config, writable)
if getattr(sys, 'frozen', False):
    _DEBUG_LOG = os.path.join(os.path.dirname(sys.executable), 'AI', 'chat_debug.log')
else:
    _DEBUG_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'AI', 'chat_debug.log')
def _log(msg):
    try:
        with open(_DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.datetime.now().strftime("%H:%M:%S.%f")}] {msg}\n')
    except:
        pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _BASE = sys._MEIPASS  # temp dir where PyInstaller extracts files
    # Store config in app dir (same dir as exe), writable location
    _CONFIG_DIR = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(__file__))
    _CONFIG_DIR = _BASE
BASE = _BASE
CONFIG_PATH = os.path.join(_CONFIG_DIR, 'AI', 'ai_config.json')
# Shared config path for control panel integration
SHARED_CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.deskpet', 'ai_config.json')

DEFAULT_CONFIG = {
    "api_key": "",
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "model": "deepseek-v4-pro",
    "system_prompt": "You are a helpful assistant living on the user's desktop as a cute pet."
}

# ---------------------------------------------------------------------------
# Win32 constants not in win32con
# ---------------------------------------------------------------------------
# RichEdit specific
EM_EXLIMITTEXT     = 0x435
EM_SETBKGNDCOLOR   = 0x443
EM_SETCHARFORMAT   = 0x444

# CHARFORMAT2W masks
CFM_BOLD      = 0x00000001
CFM_COLOR     = 0x40000000
CFM_FACE      = 0x20000000
CFM_SIZE      = 0x80000000
CFM_WEIGHT    = 0x00400000
CFE_BOLD      = 0x00000001
CFE_AUTOCOLOR = 0x40000000
SCF_SELECTION = 0x0001
SCF_ALL       = 0x0004

# Custom messages for thread-safe UI updates
WM_AI_UPDATE = win32con.WM_APP + 10

# LOWORD / HIWORD helpers (not available in all pywin32 builds)
def _LOWORD(x):
    return x & 0xFFFF

def _HIWORD(x):
    return (x >> 16) & 0xFFFF

# Control IDs
IDC_DISPLAY  = 100
IDC_INPUT    = 101
IDC_SEND     = 102
IDC_SETTINGS = 103

# Settings dialog control IDs
IDS_API_KEY    = 200
IDS_API_URL    = 201
IDS_MODEL      = 202
IDS_PROMPT     = 203
IDS_SAVE       = 204
IDS_CANCEL     = 205
IDS_TOGGLE_KEY = 206

# ---------------------------------------------------------------------------
# ctypes structures
# ---------------------------------------------------------------------------
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved",     POINT),
        ("ptMaxSize",      POINT),
        ("ptMaxPosition",  POINT),
        ("ptMinTrackSize", POINT),
        ("ptMaxTrackSize", POINT),
    ]

class CHARFORMAT2W(ctypes.Structure):
    _fields_ = [
        ("cbSize",          wintypes.UINT),
        ("dwMask",          wintypes.DWORD),
        ("dwEffects",       wintypes.DWORD),
        ("yHeight",         wintypes.LONG),
        ("yOffset",         wintypes.LONG),
        ("crTextColor",     wintypes.COLORREF),
        ("bCharSet",        ctypes.c_byte),
        ("bPitchAndFamily", ctypes.c_byte),
        ("szFaceName",      ctypes.c_wchar * 32),
        ("wWeight",         wintypes.WORD),
        ("sSpacing",        wintypes.SHORT),
        ("crBackColor",     wintypes.COLORREF),
        ("lcid",            wintypes.DWORD),
        ("dwReserved",      wintypes.DWORD),
        ("sStyle",          wintypes.SHORT),
        ("wKerning",        wintypes.WORD),
        ("bUnderlineType",  ctypes.c_byte),
        ("bAnimation",      ctypes.c_byte),
        ("bRevAuthor",      ctypes.c_byte),
        ("bReserved1",      ctypes.c_byte),
    ]

# ---------------------------------------------------------------------------
# Helper: convert RGB tuple to COLORREF (BGR format)
# ---------------------------------------------------------------------------
def rgb_to_colorref(r, g, b):
    return (b << 16) | (g << 8) | r

# Color scheme (黑金/Black-Gold theme)
C_GOLD        = rgb_to_colorref(212, 175, 55)    # #D4AF37 - classic gold
C_GOLD_BRIGHT = rgb_to_colorref(255, 215, 0)     # #FFD700 - bright gold
C_GOLD_DIM    = rgb_to_colorref(180, 150, 50)    # #B49632 - dim gold
C_BODY_TEXT   = rgb_to_colorref(255, 248, 231)   # #FFF8E7 - warm white
C_WAITING     = rgb_to_colorref(255, 165, 0)     # orange-amber
C_ERROR       = rgb_to_colorref(255, 68, 68)     # red
C_BG_DARK     = 0x000D0D0D                       # BGR: #0D0D0D - near black
C_BG_INPUT    = 0x001A1A1A                       # BGR: #1A1A1A - dark input bg

# Track registered window classes
_registered_classes = set()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config():
    # Check shared config (written by control panel) first
    for path in (SHARED_CONFIG_PATH, CONFIG_PATH):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    cfg.setdefault(k, v)
                return cfg
            except:
                pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    # Save to shared path (read by control panel)
    os.makedirs(os.path.dirname(SHARED_CONFIG_PATH), exist_ok=True)
    with open(SHARED_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    # Also save to local path for backward compatibility
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# AI API call (blocking — runs in worker thread)
# ---------------------------------------------------------------------------
def ai_chat_completion(messages, api_key, api_url, model, timeout=30):
    if not api_key:
        return False, "请先在设置中填写 API 密钥"
    try:
        import requests
    except ImportError:
        return False, "缺少 requests 库，请运行: pip install requests"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return False, f"API 错误 ({resp.status_code}): {resp.text[:200]}"
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
        return True, content
    except requests.exceptions.Timeout:
        return False, "请求超时，请检查网络连接"
    except requests.exceptions.ConnectionError:
        return False, "无法连接服务器，请检查 API 地址"
    except Exception as e:
        return False, f"请求失败: {str(e)[:200]}"

# ---------------------------------------------------------------------------
# Module-level state shared by WndProcs
# ---------------------------------------------------------------------------
_chat_instances = {}          # hwnd -> ChatWindow
_input_instance_map = {}       # hwnd -> ChatWindow (for subclass proc)
_input_orig_procs = {}         # hwnd -> original WNDPROC address
_update_queue = []             # list of (method_name, args)
_update_lock = threading.Lock()
_settings_instances = {}       # hwnd -> SettingsDialog

# ---------------------------------------------------------------------------
# Chat window WndProc (module-level)
# ---------------------------------------------------------------------------
def _chat_wndproc(hwnd, msg, wparam, lparam):
    inst = _chat_instances.get(hwnd)
    if inst is None:
        _log(f'chat_wndproc: msg={msg} no instance, defproc')
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # Log WM_CLOSE and WM_DESTROY specifically
    if msg in (win32con.WM_CLOSE, win32con.WM_DESTROY, 0x0082):  # 0x0082 = WM_NCDESTROY
        _log(f'chat_wndproc: msg=0x{msg:04X} (CLOSE/DESTROY)')

    if msg == win32con.WM_SIZE:
        inst._on_size(wparam, lparam)
        return 0
    elif msg == win32con.WM_COMMAND:
        inst._on_command(wparam, lparam)
        return 0
    elif msg == win32con.WM_CLOSE:
        _log('chat_wndproc: WM_CLOSE received')
        inst.close()
        return 0
    elif msg == win32con.WM_GETMINMAXINFO:
        inst._on_minmaxinfo(lparam)
        return 0
    elif msg == win32con.WM_CTLCOLOREDIT:
        hdc = wparam
        hwnd_edit = lparam
        if hwnd_edit == getattr(inst, 'hwnd_input', None):
            win32gui.SetTextColor(hdc, C_GOLD)
            win32gui.SetBkColor(hdc, C_BG_INPUT)
            if hasattr(inst, '_hbr_input_bg'):
                return inst._hbr_input_bg
        return win32gui.GetStockObject(win32con.BLACK_BRUSH)
    elif msg == win32con.WM_CTLCOLORBTN:
        hdc = wparam
        win32gui.SetTextColor(hdc, C_GOLD)
        win32gui.SetBkColor(hdc, C_BG_INPUT)
        if hasattr(inst, '_hbr_input_bg'):
            return inst._hbr_input_bg
        return win32gui.GetStockObject(win32con.BLACK_BRUSH)
    elif msg == WM_AI_UPDATE:
        inst._on_ai_update()
        return 0
    elif msg == win32con.WM_ACTIVATE:
        # Pass keyboard focus to input when window activates
        if wparam != 0:  # WA_ACTIVE or WA_CLICKACTIVE
            if hasattr(inst, 'hwnd_input') and inst.hwnd_input:
                try:
                    win32gui.SetFocus(inst.hwnd_input)
                except Exception as e:
                    _log(f'chat_wndproc: SetFocus error: {e}')
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

# ---------------------------------------------------------------------------
# Input EDIT subclass proc (catches Enter key)
# ---------------------------------------------------------------------------
def _input_subclass_proc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_CHAR and wparam == 13:  # Enter key
        inst = _input_instance_map.get(hwnd)
        if inst and not inst.waiting:
            inst.send_message()
        return 0
    # Forward to original wndproc
    orig = _input_orig_procs.get(hwnd)
    if orig:
        return win32gui.CallWindowProc(orig, hwnd, msg, wparam, lparam)
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

# ---------------------------------------------------------------------------
# Settings dialog WndProc
# ---------------------------------------------------------------------------
def _settings_wndproc(hwnd, msg, wparam, lparam):
    inst = _settings_instances.get(hwnd)
    if inst is None:
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    if msg == win32con.WM_COMMAND:
        inst._on_command(wparam, lparam)
        return 0
    elif msg == win32con.WM_CLOSE:
        inst.close()
        return 0
    elif msg == win32con.WM_CTLCOLORSTATIC:
        hdc = wparam
        win32gui.SetTextColor(hdc, C_GOLD)
        win32gui.SetBkColor(hdc, 0)
        if hasattr(inst, '_hbr_edit_bg'):
            return inst._hbr_edit_bg
        return win32gui.GetStockObject(win32con.BLACK_BRUSH)
    elif msg == win32con.WM_CTLCOLOREDIT:
        hdc = wparam
        win32gui.SetTextColor(hdc, C_GOLD)
        win32gui.SetBkColor(hdc, C_BG_INPUT)
        if hasattr(inst, '_hbr_edit_bg'):
            return inst._hbr_edit_bg
        return win32gui.GetStockObject(win32con.BLACK_BRUSH)
    elif msg == win32con.WM_CTLCOLORBTN:
        hdc = wparam
        win32gui.SetTextColor(hdc, C_GOLD)
        win32gui.SetBkColor(hdc, C_BG_INPUT)
        if hasattr(inst, '_hbr_edit_bg'):
            return inst._hbr_edit_bg
        return win32gui.GetStockObject(win32con.BLACK_BRUSH)

    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


# ===================================================================
# ChatWindow
# ===================================================================
class ChatWindow:
    """Pure Win32 chat popup. Singleton via ChatWindow.instance."""

    instance = None

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    @classmethod
    def _ensure_class(cls):
        if "PetAIChatCls" not in _registered_classes:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = _chat_wndproc
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
            wc.lpszClassName = "PetAIChatCls"
            wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            try:
                win32gui.RegisterClass(wc)
            except:
                pass
            _registered_classes.add("PetAIChatCls")

    # ------------------------------------------------------------------
    # Toggle singleton
    # ------------------------------------------------------------------
    @classmethod
    def toggle(cls, pet_x, pet_y):
        """Open or close the chat window."""
        _log(f'toggle() called, instance={cls.instance is not None}')
        try:
            if cls.instance is not None:
                is_open = cls.instance.is_open
                _log(f'toggle(): existing instance is_open={is_open}')
                if is_open:
                    cls.instance.close()
                    cls.instance = None
                    _log('toggle(): closed existing window')
                    return
        except Exception as e:
            _log(f'toggle(): error checking instance: {e}')
            cls.instance = None

        # Create new window
        _log('toggle(): creating new window')
        try:
            cls.instance = cls(pet_x, pet_y)
            _log('toggle(): new window created successfully')
        except Exception as e:
            _log(f'toggle(): FAILED to create window: {e}')
            cls.instance = None

    # ------------------------------------------------------------------
    # __init__
    # ------------------------------------------------------------------
    def __init__(self, pet_x, pet_y):
        self.is_open = False
        self.waiting = False
        self.config = load_config()
        self._display_entries = []  # list of (role, text)
        self._fonts_created = False

        _log('__init__: start')

        # Build conversation with system prompt
        system_content = self.config.get("system_prompt", DEFAULT_CONFIG["system_prompt"])
        self.conversation = [{"role": "system", "content": system_content}]

        # Ensure RichEdit DLL is loaded
        try:
            ctypes.windll.LoadLibrary("msftedit.dll")
            _log('__init__: msftedit.dll loaded')
        except Exception as e:
            _log(f'__init__: msftedit.dll load failed: {e}')

        # Register window class
        self._ensure_class()

        # Calculate position
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        win_w, win_h = 360, 480
        x = min(pet_x + 50, sw - win_w - 20)
        y = max(20, min(pet_y - win_h // 2, sh - win_h - 40))

        # Create window — WS_EX_DLGMODALFRAME removes system icon
        _log('__init__: creating window...')
        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOPMOST | win32con.WS_EX_APPWINDOW | win32con.WS_EX_DLGMODALFRAME,
            "PetAIChatCls", "AI 对话",
            win32con.WS_OVERLAPPEDWINDOW,
            x, y, win_w, win_h,
            0, 0, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, 0)
        win32gui.SendMessage(self.hwnd, win32con.WM_SETICON, win32con.ICON_BIG, 0)
        _log(f'__init__: window created, hwnd={self.hwnd}')

        # Register in dispatch map
        _chat_instances[self.hwnd] = self

        # Create child controls
        _log('__init__: creating controls...')
        self._create_controls()
        _log('__init__: controls created')

        # Show window
        _log('__init__: showing window...')
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(self.hwnd)
        _log('__init__: window shown')

        # Show welcome message with gold decorative character
        self._append_display("system", "✦ AI 对话已开启，有什么想问的吗？ ✦")

        self.is_open = True
        _log('__init__: done')

    # ------------------------------------------------------------------
    # Create child controls
    # ------------------------------------------------------------------
    def _create_controls(self):
        rc = win32gui.GetClientRect(self.hwnd)
        w = rc[2]
        h = rc[3]

        SIDE = 6
        INPUT_H = 28
        BOTTOM_MARGIN = 6
        SEND_W = 50
        SETTINGS_W = 26
        GAP = 4

        bottom_y = h - BOTTOM_MARGIN - INPUT_H
        input_w = w - SIDE * 2 - SEND_W - SETTINGS_W - GAP * 3
        msg_h = bottom_y - SIDE * 2

        # Create fonts
        self._create_fonts()

        # --- RichEdit (message display) ---
        self.hwnd_richedit = win32gui.CreateWindowEx(
            0, "RICHEDIT50W", "",
            win32con.WS_CHILD | win32con.WS_VISIBLE |
            win32con.ES_MULTILINE | win32con.ES_READONLY |
            win32con.ES_AUTOVSCROLL | win32con.WS_VSCROLL |
            win32con.ES_NOHIDESEL,
            SIDE, SIDE, w - SIDE * 2, msg_h,
            self.hwnd, IDC_DISPLAY, win32api.GetModuleHandle(None), None
        )
        # Set font
        win32gui.SendMessage(self.hwnd_richedit, win32con.WM_SETFONT,
                             self.hFont, 1)
        # Set dark background
        ctypes.windll.user32.SendMessageW(
            self.hwnd_richedit, EM_SETBKGNDCOLOR, 0, C_BG_DARK
        )
        # Set text limit (very large)
        ctypes.windll.user32.SendMessageW(
            self.hwnd_richedit, EM_EXLIMITTEXT, 0, 0x7FFFFFFF
        )

        # --- Input edit ---
        self.hwnd_input = win32gui.CreateWindowEx(
            win32con.WS_EX_CLIENTEDGE, "EDIT", "",
            win32con.WS_CHILD | win32con.WS_VISIBLE |
            win32con.ES_AUTOHSCROLL | win32con.ES_NOHIDESEL,
            SIDE, bottom_y, input_w, INPUT_H,
            self.hwnd, IDC_INPUT, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_input, win32con.WM_SETFONT,
                             self.hFont, 1)

        # Subclass input for Enter key handling
        orig_proc = win32gui.SetWindowLong(
            self.hwnd_input, win32con.GWL_WNDPROC, _input_subclass_proc
        )
        _input_orig_procs[self.hwnd_input] = orig_proc
        _input_instance_map[self.hwnd_input] = self

        # Create brush for input field background
        self._hbr_input_bg = win32gui.CreateSolidBrush(C_BG_INPUT)

        # Try to enable dark theme for controls (Windows 10/11)
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_input, "DarkMode_Explorer", None)
        except:
            pass
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_richedit, "DarkMode_Explorer", None)
        except:
            pass

        # --- Send button ---
        self.hwnd_send = win32gui.CreateWindowEx(
            0, "BUTTON", "发送",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            SIDE + input_w + GAP, bottom_y, SEND_W, INPUT_H,
            self.hwnd, IDC_SEND, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_send, win32con.WM_SETFONT,
                             self.hFont, 1)

        # --- Settings button ---
        self.hwnd_settings = win32gui.CreateWindowEx(
            0, "BUTTON", "⚙",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            SIDE + input_w + GAP * 2 + SEND_W, bottom_y, SETTINGS_W, INPUT_H,
            self.hwnd, IDC_SETTINGS, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_settings, win32con.WM_SETFONT,
                             self.hFont, 1)

        # Focus input
        win32gui.SetFocus(self.hwnd_input)

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------
    def _create_fonts(self):
        if self._fonts_created:
            return
        # CreateFontIndirect with LOGFONT object
        lf = win32gui.LOGFONT()
        lf.lfHeight = -14
        lf.lfWeight = win32con.FW_NORMAL
        lf.lfCharSet = win32con.DEFAULT_CHARSET
        lf.lfOutPrecision = win32con.OUT_DEFAULT_PRECIS
        lf.lfClipPrecision = win32con.CLIP_DEFAULT_PRECIS
        lf.lfQuality = win32con.DEFAULT_QUALITY
        lf.lfPitchAndFamily = win32con.DEFAULT_PITCH | win32con.FF_DONTCARE
        lf.lfFaceName = "Microsoft YaHei"
        self.hFont = win32gui.CreateFontIndirect(lf)

        lf_bold = win32gui.LOGFONT()
        lf_bold.lfHeight = -14
        lf_bold.lfWeight = win32con.FW_BOLD
        lf_bold.lfCharSet = win32con.DEFAULT_CHARSET
        lf_bold.lfOutPrecision = win32con.OUT_DEFAULT_PRECIS
        lf_bold.lfClipPrecision = win32con.CLIP_DEFAULT_PRECIS
        lf_bold.lfQuality = win32con.DEFAULT_QUALITY
        lf_bold.lfPitchAndFamily = win32con.DEFAULT_PITCH | win32con.FF_DONTCARE
        lf_bold.lfFaceName = "Microsoft YaHei"
        self.hFontBold = win32gui.CreateFontIndirect(lf_bold)
        self._fonts_created = True

    # ------------------------------------------------------------------
    # WM_SIZE handler
    # ------------------------------------------------------------------
    def _on_size(self, wparam, lparam):
        w = _LOWORD(lparam)
        h = _HIWORD(lparam)
        if w == 0 or h == 0:
            return

        SIDE = 6
        INPUT_H = 28
        BOTTOM_MARGIN = 6
        SEND_W = 50
        SETTINGS_W = 26
        GAP = 4

        bottom_y = h - BOTTOM_MARGIN - INPUT_H
        input_w = w - SIDE * 2 - SEND_W - SETTINGS_W - GAP * 3
        msg_h = bottom_y - SIDE * 2

        if self.hwnd_richedit:
            win32gui.MoveWindow(self.hwnd_richedit, SIDE, SIDE,
                                max(1, w - SIDE * 2), max(1, msg_h), True)
        if self.hwnd_input:
            win32gui.MoveWindow(self.hwnd_input, SIDE, bottom_y,
                                max(1, input_w), INPUT_H, True)
        if self.hwnd_send:
            win32gui.MoveWindow(self.hwnd_send, SIDE + input_w + GAP,
                                bottom_y, SEND_W, INPUT_H, True)
        if self.hwnd_settings:
            win32gui.MoveWindow(self.hwnd_settings,
                                SIDE + input_w + GAP * 2 + SEND_W,
                                bottom_y, SETTINGS_W, INPUT_H, True)

    # ------------------------------------------------------------------
    # WM_COMMAND handler
    # ------------------------------------------------------------------
    def _on_command(self, wparam, lparam):
        ctrl_id = _LOWORD(wparam)
        notify_code = _HIWORD(wparam)
        if ctrl_id == IDC_SEND and notify_code == win32con.BN_CLICKED:
            self.send_message()
        elif ctrl_id == IDC_SETTINGS and notify_code == win32con.BN_CLICKED:
            self.open_settings()
        return 0

    # ------------------------------------------------------------------
    # WM_GETMINMAXINFO handler
    # ------------------------------------------------------------------
    def _on_minmaxinfo(self, lparam):
        mmi = MINMAXINFO.from_address(lparam)
        mmi.ptMinTrackSize.x = 280
        mmi.ptMinTrackSize.y = 300
        return 0

    # ------------------------------------------------------------------
    # WM_AI_UPDATE handler — drain thread-safe queue on main thread
    # ------------------------------------------------------------------
    def _on_ai_update(self):
        global _update_queue
        with _update_lock:
            updates = list(_update_queue)
            _update_queue.clear()
        for method_name, args in updates:
            try:
                getattr(self, method_name)(*args)
            except Exception:
                pass
        return 0

    # ------------------------------------------------------------------
    # Display: append entry and rebuild
    # ------------------------------------------------------------------
    def _append_display(self, role, text):
        self._display_entries.append((role, text))
        self._rebuild_display()

    def _replace_last_display(self, role, text):
        if not self.is_open or not self.hwnd:
            return
        if self._display_entries:
            self._display_entries[-1] = (role, text)
        else:
            self._display_entries.append((role, text))
        self._rebuild_display()

    # ------------------------------------------------------------------
    # Rebuild RichEdit content from _display_entries
    # ------------------------------------------------------------------
    def _rebuild_display(self):
        if not self.is_open or not self.hwnd_richedit:
            return

        # Disable redraw to avoid flicker
        win32gui.SendMessage(self.hwnd_richedit, win32con.WM_SETREDRAW, 0, 0)

        # Select all and delete
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_SETSEL, 0, -1)
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_REPLACESEL, 0, "")

        # Rebuild
        for role, text in self._display_entries:
            if role == "user":
                self._insert_formatted("✦ 你:\n",
                                       CFM_BOLD | CFM_COLOR, CFE_BOLD,
                                       C_GOLD, self.hFontBold)
                self._insert_formatted(text + "\n\n",
                                       CFM_COLOR, 0, C_BODY_TEXT, self.hFont)
            elif role == "assistant":
                self._insert_formatted("✦ AI:\n",
                                       CFM_BOLD | CFM_COLOR, CFE_BOLD,
                                       C_GOLD_BRIGHT, self.hFontBold)
                self._insert_formatted(text + "\n\n",
                                       CFM_COLOR, 0, C_BODY_TEXT, self.hFont)
            elif role == "waiting":
                self._insert_formatted("✦ AI:\n",
                                       CFM_BOLD | CFM_COLOR, CFE_BOLD,
                                       C_GOLD_BRIGHT, self.hFontBold)
                self._insert_formatted(text + "\n",
                                       CFM_COLOR, 0, C_WAITING, self.hFont)
            elif role == "error":
                self._insert_formatted(text + "\n\n",
                                       CFM_COLOR, 0, C_ERROR, self.hFont)
            elif role == "system":
                self._insert_formatted(text + "\n\n",
                                       CFM_COLOR, 0, C_GOLD_DIM, self.hFont)

        # Scroll to end
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_SCROLLCARET, 0, 0)

        # Re-enable redraw
        win32gui.SendMessage(self.hwnd_richedit, win32con.WM_SETREDRAW, 1, 0)
        win32gui.InvalidateRect(self.hwnd_richedit, None, True)

    # ------------------------------------------------------------------
    # Insert formatted text into RichEdit
    # ------------------------------------------------------------------
    def _insert_formatted(self, text, mask, effects, color, font):
        """Insert text and apply CHARFORMAT2W formatting."""
        # Get current text length
        start = win32gui.SendMessage(self.hwnd_richedit,
                                     win32con.WM_GETTEXTLENGTH, 0, 0)

        # Move cursor to end and insert
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_SETSEL,
                             start, start)
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_REPLACESEL,
                             1, text)

        # Calculate end position (approximate: each BMP char = 1 UTF-16 unit)
        end = start + len(text)

        # Select inserted text
        win32gui.SendMessage(self.hwnd_richedit, win32con.EM_SETSEL,
                             start, end)

        # Apply CHARFORMAT2W
        cf = CHARFORMAT2W()
        cf.cbSize = ctypes.sizeof(CHARFORMAT2W)
        cf.dwMask = mask
        cf.dwEffects = effects
        cf.crTextColor = color
        cf.yHeight = 14 * 20  # 14pt in twips
        ctypes.windll.user32.SendMessageW(
            self.hwnd_richedit, EM_SETCHARFORMAT, SCF_SELECTION,
            ctypes.byref(cf)
        )

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------
    def send_message(self):
        if not self.is_open or not self.hwnd:
            return
        text = win32gui.GetWindowText(self.hwnd_input).strip()
        if not text or self.waiting:
            return

        # Clear input
        if self.hwnd_input and win32gui.IsWindow(self.hwnd_input):
            win32gui.SetWindowText(self.hwnd_input, "")
            win32gui.SetFocus(self.hwnd_input)

        # Add to conversation
        self.conversation.append({"role": "user", "content": text})

        # Display
        self._append_display("user", text)
        self._append_display("waiting", "思考中...")

        # Disable input while waiting
        self.waiting = True
        if self.hwnd_input and win32gui.IsWindow(self.hwnd_input):
            win32gui.EnableWindow(self.hwnd_input, False)
        if self.hwnd_send and win32gui.IsWindow(self.hwnd_send):
            win32gui.EnableWindow(self.hwnd_send, False)

        # Start API call in daemon thread
        cfg = load_config()
        api_key = cfg.get("api_key", "")
        threading.Thread(
            target=self._do_api_call,
            args=(list(self.conversation), cfg, api_key),
            daemon=True
        ).start()

    # ------------------------------------------------------------------
    # API call (runs in worker thread)
    # ------------------------------------------------------------------
    def _do_api_call(self, conversation, cfg, api_key):
        try:
            success, result = ai_chat_completion(
                conversation, api_key,
                cfg.get("api_url", DEFAULT_CONFIG["api_url"]),
                cfg.get("model", DEFAULT_CONFIG["model"]),
            )
            if not self.is_open:
                return
            if success:
                self.conversation.append({"role": "assistant", "content": result})
                self._post_update("_replace_last_display", "assistant", result)
            else:
                self._post_update("_replace_last_display", "error", "⚠ " + result)
        except Exception as e:
            if self.is_open:
                self._post_update("_replace_last_display", "error",
                                  "⚠ " + str(e)[:200])
        finally:
            if self.is_open:
                self._post_update("_enable_input")

    # ------------------------------------------------------------------
    # Thread-safe update posting
    # ------------------------------------------------------------------
    def _post_update(self, method_name, *args):
        global _update_queue
        with _update_lock:
            _update_queue.append((method_name, args))
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_AI_UPDATE, 0, 0)

    # ------------------------------------------------------------------
    # Re-enable input (called on main thread via update queue)
    # ------------------------------------------------------------------
    def _enable_input(self):
        if not self.is_open or not self.hwnd:
            return
        self.waiting = False
        if self.hwnd_input and win32gui.IsWindow(self.hwnd_input):
            win32gui.EnableWindow(self.hwnd_input, True)
        if self.hwnd_send and win32gui.IsWindow(self.hwnd_send):
            win32gui.EnableWindow(self.hwnd_send, True)
        if self.hwnd_input and win32gui.IsWindow(self.hwnd_input):
            win32gui.SetFocus(self.hwnd_input)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def open_settings(self):
        _log('open_settings() called')
        try:
            SettingsDialog(self.hwnd, self.config, self._on_config_saved)
            _log('open_settings(): dialog created')
        except Exception as e:
            _log(f'open_settings() ERROR: {e}')
            import traceback
            _log(traceback.format_exc())

    def _on_config_saved(self, cfg):
        self.config = cfg
        system_content = cfg.get("system_prompt", DEFAULT_CONFIG["system_prompt"])
        self.conversation[0] = {"role": "system", "content": system_content}

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    def close(self):
        _log(f'close() called, hwnd={self.hwnd}')
        self.is_open = False
        ChatWindow.instance = None

        # Clean up dispatch maps
        if self.hwnd:
            _chat_instances.pop(self.hwnd, None)
        if hasattr(self, 'hwnd_input') and self.hwnd_input:
            _input_orig_procs.pop(self.hwnd_input, None)
            _input_instance_map.pop(self.hwnd_input, None)

        # Destroy window (this triggers WM_DESTROY)
        if self.hwnd:
            hwnd = self.hwnd
            self.hwnd = None
            _log(f'close(): destroying window {hwnd}')
            win32gui.DestroyWindow(hwnd)
            _log('close(): window destroyed')

        # Clean up GDI brush for input background
        if hasattr(self, '_hbr_input_bg') and self._hbr_input_bg:
            try:
                win32gui.DeleteObject(self._hbr_input_bg)
            except:
                pass
            self._hbr_input_bg = None

        # Clean up GDI fonts
        if self._fonts_created:
            try:
                win32gui.DeleteObject(self.hFont)
                win32gui.DeleteObject(self.hFontBold)
            except:
                pass
            self._fonts_created = False
        _log('close(): done')


# ===================================================================
# SettingsDialog
# ===================================================================
class SettingsDialog:
    """Popup dialog for AI chat configuration."""

    _registered = False

    def __init__(self, parent_hwnd, config, on_save):
        self.parent_hwnd = parent_hwnd
        self.config = dict(config)
        self.on_save = on_save
        self.hwnd = None

        # Register class once
        if not SettingsDialog._registered:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = _settings_wndproc
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
            wc.lpszClassName = "PetAISettingsCls"
            wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            try:
                win32gui.RegisterClass(wc)
            except:
                pass
            SettingsDialog._registered = True

        # Center on parent
        parent_rect = win32gui.GetWindowRect(parent_hwnd)
        pw = parent_rect[2] - parent_rect[0]
        ph = parent_rect[3] - parent_rect[1]
        dw, dh = 460, 300
        x = parent_rect[0] + (pw - dw) // 2
        y = parent_rect[1] + (ph - dh) // 2

        # Create window — WS_EX_DLGMODALFRAME removes the system icon from title bar
        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_DLGMODALFRAME, "PetAISettingsCls", "AI 设置",
            win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU |
            win32con.WS_VISIBLE,
            x, y, dw, dh,
            parent_hwnd, 0, win32api.GetModuleHandle(None), None
        )
        # Also explicitly clear any icon
        win32gui.SendMessage(self.hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, 0)
        win32gui.SendMessage(self.hwnd, win32con.WM_SETICON, win32con.ICON_BIG, 0)
        _settings_instances[self.hwnd] = self

        # Create controls
        self._create_controls()

        # Modal-like: disable parent
        win32gui.EnableWindow(parent_hwnd, False)

        self.key_visible = False

    def _create_controls(self):
        rc = win32gui.GetClientRect(self.hwnd)
        w = rc[2]
        h = rc[3]

        # Font
        lf = win32gui.LOGFONT()
        lf.lfHeight = -13
        lf.lfWeight = win32con.FW_NORMAL
        lf.lfCharSet = win32con.DEFAULT_CHARSET
        lf.lfOutPrecision = win32con.OUT_DEFAULT_PRECIS
        lf.lfClipPrecision = win32con.CLIP_DEFAULT_PRECIS
        lf.lfQuality = win32con.DEFAULT_QUALITY
        lf.lfPitchAndFamily = win32con.DEFAULT_PITCH | win32con.FF_DONTCARE
        lf.lfFaceName = "Microsoft YaHei"
        self.hFont = win32gui.CreateFontIndirect(lf)

        LABEL_W = 80
        EDIT_W = w - LABEL_W - 30
        ROW_H = 22
        GAP_Y = 6
        LEFT = 14
        LABEL_LEFT = 10
        EDIT_LEFT = LEFT + LABEL_W
        START_Y = 14

        def make_row(row, label_text, edit_id, edit_w=None, edit_h=None,
                     is_password=False, multiline=False):
            y = START_Y + row * (ROW_H + GAP_Y)
            ew = edit_w or EDIT_W
            eh = edit_h or ROW_H
            # Label
            win32gui.CreateWindowEx(
                0, "STATIC", label_text,
                win32con.WS_CHILD | win32con.WS_VISIBLE,
                LABEL_LEFT, y + 2, LABEL_W, ROW_H,
                self.hwnd, 0, win32api.GetModuleHandle(None), None
            )
            # Edit
            styles = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_AUTOHSCROLL
            if is_password:
                styles |= win32con.ES_PASSWORD
            if multiline:
                styles = (win32con.WS_CHILD | win32con.WS_VISIBLE |
                          win32con.ES_MULTILINE | win32con.ES_AUTOVSCROLL |
                          win32con.WS_VSCROLL)
            edit_hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_CLIENTEDGE, "EDIT", "",
                styles,
                EDIT_LEFT, y, ew, eh,
                self.hwnd, edit_id, win32api.GetModuleHandle(None), None
            )
            win32gui.SendMessage(edit_hwnd, win32con.WM_SETFONT, self.hFont, 1)
            return edit_hwnd

        # API Key row
        self.hwnd_api_key = make_row(0, "API 密钥:", IDS_API_KEY,
                                     is_password=True, edit_w=300)
        # Toggle visibility button
        self.hwnd_toggle = win32gui.CreateWindowEx(
            0, "BUTTON", "显示",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            EDIT_LEFT + 300 + 4, START_Y + 0 * (ROW_H + GAP_Y), 40, ROW_H,
            self.hwnd, IDS_TOGGLE_KEY, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_toggle, win32con.WM_SETFONT, self.hFont, 1)

        # API URL
        self.hwnd_api_url = make_row(1, "API 地址:", IDS_API_URL)

        # Model
        self.hwnd_model = make_row(2, "模型:", IDS_MODEL)

        # System prompt (multiline)
        self.hwnd_prompt = make_row(3, "系统提示词:", IDS_PROMPT,
                                    edit_h=60, multiline=True)

        # Buttons
        btn_y = START_Y + 4 * (ROW_H + GAP_Y) + 10
        self.hwnd_save = win32gui.CreateWindowEx(
            0, "BUTTON", "保存",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            w // 2 - 80, btn_y, 70, 26,
            self.hwnd, IDS_SAVE, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_save, win32con.WM_SETFONT, self.hFont, 1)

        self.hwnd_cancel = win32gui.CreateWindowEx(
            0, "BUTTON", "取消",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            w // 2 + 10, btn_y, 70, 26,
            self.hwnd, IDS_CANCEL, win32api.GetModuleHandle(None), None
        )
        win32gui.SendMessage(self.hwnd_cancel, win32con.WM_SETFONT, self.hFont, 1)

        # Set initial values
        win32gui.SetWindowText(self.hwnd_api_key, self.config.get("api_key", ""))
        win32gui.SetWindowText(self.hwnd_api_url, self.config.get("api_url", ""))
        win32gui.SetWindowText(self.hwnd_model, self.config.get("model", ""))
        win32gui.SetWindowText(self.hwnd_prompt, self.config.get("system_prompt", ""))

        # Create brush for edit controls background
        self._hbr_edit_bg = win32gui.CreateSolidBrush(C_BG_INPUT)

        # Try to enable dark theme for controls
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_api_key, "DarkMode_Explorer", None)
        except:
            pass
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_api_url, "DarkMode_Explorer", None)
        except:
            pass
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_model, "DarkMode_Explorer", None)
        except:
            pass
        try:
            ctypes.windll.uxtheme.SetWindowTheme(self.hwnd_prompt, "DarkMode_Explorer", None)
        except:
            pass

    def _on_command(self, wparam, lparam):
        ctrl_id = _LOWORD(wparam)
        notify_code = _HIWORD(wparam)

        if ctrl_id == IDS_TOGGLE_KEY and notify_code == win32con.BN_CLICKED:
            self.key_visible = not self.key_visible
            # Toggle password mode
            if self.key_visible:
                ctypes.windll.user32.SendMessageW(
                    self.hwnd_api_key, win32con.EM_SETPASSWORDCHAR, 0, 0
                )
                win32gui.SetWindowText(self.hwnd_toggle, "隐藏")
            else:
                ctypes.windll.user32.SendMessageW(
                    self.hwnd_api_key, win32con.EM_SETPASSWORDCHAR, ord('*'), 0
                )
                win32gui.SetWindowText(self.hwnd_toggle, "显示")
            win32gui.InvalidateRect(self.hwnd_api_key, None, True)

        elif ctrl_id == IDS_SAVE and notify_code == win32con.BN_CLICKED:
            self._save()
        elif ctrl_id == IDS_CANCEL and notify_code == win32con.BN_CLICKED:
            self.close()

    def _save(self):
        new_key = win32gui.GetWindowText(self.hwnd_api_key).strip()
        new_url = win32gui.GetWindowText(self.hwnd_api_url).strip()
        new_model = win32gui.GetWindowText(self.hwnd_model).strip()
        new_prompt = win32gui.GetWindowText(self.hwnd_prompt).strip()

        if not new_key:
            win32gui.MessageBox(self.hwnd, "请输入 API 密钥", "提示",
                                win32con.MB_ICONWARNING)
            return
        if not new_url:
            win32gui.MessageBox(self.hwnd, "请输入 API 地址", "提示",
                                win32con.MB_ICONWARNING)
            return

        self.config["api_key"] = new_key
        self.config["api_url"] = new_url
        self.config["model"] = new_model
        self.config["system_prompt"] = new_prompt

        save_config(self.config)
        self.on_save(self.config)
        self.close()

    def close(self):
        # Re-enable parent
        if self.parent_hwnd and win32gui.IsWindow(self.parent_hwnd):
            win32gui.EnableWindow(self.parent_hwnd, True)
            win32gui.SetForegroundWindow(self.parent_hwnd)

        # Clean up
        _settings_instances.pop(self.hwnd, None)
        if hasattr(self, '_hbr_edit_bg') and self._hbr_edit_bg:
            try:
                win32gui.DeleteObject(self._hbr_edit_bg)
            except:
                pass
            self._hbr_edit_bg = None
        if hasattr(self, 'hFont'):
            try:
                win32gui.DeleteObject(self.hFont)
            except:
                pass
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            hwnd = self.hwnd
            self.hwnd = None
            win32gui.DestroyWindow(hwnd)
