r"""
Desktop Pet — single-file, straightforward implementation.
Right-click menu → actions. Left-click drag → move. Space → toggle walk.
"""
import os, sys, random, ctypes, json, tempfile, time
from ctypes import wintypes
import pygame
import win32gui, win32con, win32api
from AI.pet_ai import ChatWindow

# PyInstaller frozen path support
if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(__file__)
ASSETS = os.path.join(BASE, '素材')
PET_SCALE = 0.7
DEBUG_STATE_FILE = os.path.join(tempfile.gettempdir(), 'pet_debug_state.json')

# ── Shared control panel IPC paths ──
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.deskpet')
os.makedirs(CONFIG_DIR, exist_ok=True)
SETTINGS_PATH = os.path.join(CONFIG_DIR, 'settings.json')
COMMAND_PATH = os.path.join(CONFIG_DIR, 'command.json')
STATUS_PATH = os.path.join(CONFIG_DIR, 'status.json')

# ---------------------------------------------------------------------------
# win32 structs & helpers
# ---------------------------------------------------------------------------
class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class _BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]

def cursor_pos():
    p = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y

def screen_size():
    info = pygame.display.Info()
    return info.current_w, info.current_h

# ── IPC helpers (control panel integration) ──
def read_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return default

def apply_pet_settings(pet, settings):
    if not settings: return
    if 'move_speed' in settings:
        pet.move_speed = float(settings['move_speed'])
    if 'particles_enabled' in settings:
        pet.particles_enabled = bool(settings['particles_enabled'])
    if 'freeze_on_chat' in settings:
        pet.freeze_on_chat = bool(settings['freeze_on_chat'])
    if 'auto_behavior' in settings:
        pet.auto_behavior = bool(settings['auto_behavior'])

def process_pet_commands(pet, bed, last_cmd_time):
    cmd_data = read_json(COMMAND_PATH)
    if not cmd_data or not isinstance(cmd_data, dict):
        return last_cmd_time
    cmd = cmd_data.get("command")
    ts = cmd_data.get("timestamp", 0)
    if not cmd or ts <= last_cmd_time:
        return last_cmd_time
    if cmd == 'sleep':
        if not bed.visible: bed.show()
        fw, fh = pet.frame_size()
        tx = bed.x + (bed.w - fw) // 2
        ty = bed.y - fh + 25
        pet.move_to(tx, ty)
    elif cmd == 'wakeup':
        pet.wakeup()
    elif cmd == 'walk':
        pet.set_mode('walk')
    elif cmd == 'idle':
        pet.set_mode('idle')
    elif cmd == 'show_bed':
        bed.show()
    elif cmd == 'hide_bed':
        bed.hide()
    elif cmd == 'ai_chat':
        mx = int(pet.x + pet.win_w // 2)
        my = int(pet.y + pet.win_h // 2)
        ChatWindow.toggle(mx, my)
    elif cmd == 'exit':
        return -1  # signal to exit main loop
    return ts

def write_pet_status(pet):
    try:
        a = pet.cur_anim()
        fw, fh = pet.frame_size()
        state = {
            "mode": pet.mode,
            "action": pet.action,
            "position": (round(pet.x, 1), round(pet.y, 1)),
            "on_bed": pet.on_bed,
            "grabbed": pet.grabbed,
            "anim_frame": a.idx if a else 0,
            "timestamp": time.time(),
        }
        with open(STATUS_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except: pass

# ---------------------------------------------------------------------------
# frame loading
# ---------------------------------------------------------------------------
def load_frames(folder):
    frames = []
    path = os.path.join(ASSETS, folder)
    if not os.path.isdir(path):
        return frames
    files = sorted([f for f in os.listdir(path) if f.endswith('.png')],
                   key=lambda x: int(''.join(c for c in x if c.isdigit()) or 0))
    for f in files:
        try:
            s = pygame.image.load(os.path.join(path, f)).convert_alpha()
            frames.append(s)
        except: pass
    return frames

def scale_frames(frames, s):
    return [pygame.transform.scale(f, (int(f.get_width()*s), int(f.get_height()*s))) for f in frames]

# ---------------------------------------------------------------------------
# animation player
# ---------------------------------------------------------------------------
class Anim:
    def __init__(self, frames, ms, loop=True):
        self.frames = frames
        self.ms = ms
        self.loop = loop
        self.idx = 0
        self.acc = 0
        self.done = False
    def reset(self):
        self.idx = 0; self.acc = 0; self.done = False
    def tick(self, dt):
        if self.done or not self.frames: return
        self.acc += dt
        while self.acc >= self.ms:
            self.acc -= self.ms
            self.idx += 1
            if self.idx >= len(self.frames):
                if self.loop: self.idx = 0
                else: self.idx = len(self.frames)-1; self.done = True; break
    def frame(self):
        return self.frames[self.idx] if self.frames else None

# ---------------------------------------------------------------------------
# layered window
# ---------------------------------------------------------------------------
class LWindow:
    _registered = set()

    @staticmethod
    def _reg(cls_name):
        if cls_name in LWindow._registered: return
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = win32gui.DefWindowProc
        wc.lpszClassName = cls_name
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        try: win32gui.RegisterClass(wc)
        except: pass
        LWindow._registered.add(cls_name)

    def __init__(self, w, h, cls_name="PetWinCls", ex_style=None):
        self.w = w; self.h = h
        LWindow._reg(cls_name)
        if ex_style is None:
            ex_style = win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
        self.hwnd = win32gui.CreateWindowEx(
            ex_style, cls_name, "pet", win32con.WS_POPUP,
            0, 0, w, h, 0, 0, win32api.GetModuleHandle(None), None)
        # GDI
        self.memdc = ctypes.windll.gdi32.CreateCompatibleDC(0)
        bmi = _BMIH()
        bmi.biSize = ctypes.sizeof(_BMIH); bmi.biWidth = w; bmi.biHeight = -h
        bmi.biPlanes = 1; bmi.biBitCount = 32
        self._pbits = ctypes.c_void_p()
        self.bmp = ctypes.windll.gdi32.CreateDIBSection(self.memdc, ctypes.byref(bmi), 0, ctypes.byref(self._pbits), None, 0)
        ctypes.windll.gdi32.SelectObject(self.memdc, self.bmp)
        self.bgra = bytearray(w*h*4)
        self.canvas = pygame.Surface((w, h), pygame.SRCALPHA)

    def paint(self, surf, x, y, fx=None):
        self.canvas.fill((0,0,0,0))
        sw, sh = surf.get_width(), surf.get_height()
        self.canvas.blit(surf, ((self.w-sw)//2, (self.h-sh)//2))
        if fx:
            fw, fh = fx.get_width(), fx.get_height()
            self.canvas.blit(fx, ((self.w-fw)//2, (self.h-fh)//2))
        raw = pygame.image.tostring(self.canvas, "RGBA")
        self.bgra[0::4] = raw[2::4]; self.bgra[1::4] = raw[1::4]
        self.bgra[2::4] = raw[0::4]; self.bgra[3::4] = raw[3::4]
        ctypes.memmove(self._pbits, bytes(self.bgra), len(self.bgra))
        blend = _BLEND(0, 0, 255, 1)  # AC_SRC_OVER, 0, 255, AC_SRC_ALPHA
        dst = _POINT(x, y); sz = _SIZE(self.w, self.h); src = _POINT(0, 0)
        ctypes.windll.user32.UpdateLayeredWindow(self.hwnd, 0, ctypes.byref(dst), ctypes.byref(sz),
                                                  self.memdc, ctypes.byref(src), 0, ctypes.byref(blend), 2)
    def show(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)

    def cleanup(self):
        if self.bmp: ctypes.windll.gdi32.DeleteObject(self.bmp); self.bmp = None
        if self.memdc: ctypes.windll.gdi32.DeleteDC(self.memdc); self.memdc = None
        if self.hwnd: win32gui.DestroyWindow(self.hwnd); self.hwnd = None

# ---------------------------------------------------------------------------
# all animation definitions  (folder, ms_per_frame, loop)
# ---------------------------------------------------------------------------
ANIMS = {
    'idle':         ('动作图2/呼吸起伏',    150, True),
    'walk':         ('动作图1/走动图',      120, True),
    'blink':        ('动作图2/眨眼',        100, False),
    'look_left':    ('动作图2/看左',        150, False),
    'look_right':   ('动作图2/看右',        150, False),
    'shake':        ('动作图2/小幅晃动',    100, False),
    'expression':   ('动作图4/表情特写',    200, False),
    'tap':          ('动作图4/轻点',        150, False),
    'run':          ('动作图3/跑步动作',     80, True),
    'jump':         ('动作图3/跳跃动作',     80, False),
    'turn_l2r':     ('动作图3/左转右',      100, False),
    'turn_r2l':     ('动作图3/右转左',      100, False),
    'sit':          ('动作图5/坐下',        150, True),
    'patrol':       ('动作图5/巡逻',        120, True),
    'lie_down':     ('动作图1/躺下的动作',  150, True),
    'sleep':        ('动作图5/睡觉',        200, True),
    'shoot':        ('动作图1/拿枪开枪的动作', 100, False),
    'gun_warn':     ('动作图4/拿枪警告',    150, False),
    'tactical':     ('动作图5/战术操作',    120, False),
    'clean_gun':    ('动作图5/擦枪',        120, False),
    'check_wpn':    ('动作图5/检查武器',    150, False),
    'salute':       ('动作图5/敬礼',        120, False),
    'victory':      ('动作图5/胜利动作',    120, False),
    'air_struggle': ('动作图4/悬空挣扎',    120, False),
    'slip':         ('动作图5/滑倒',        100, False),
    'fall':         ('动作图5/摔倒',        100, False),
    'grabbed':      ('动作图4/被抓起来',    200, True),
    'dropping':     ('动作图4/放下摔坐',    100, False),
}

EFFECTS = {
    'brown':       ('特效/棕色',       60, True),
    'orange_spark':('特效/橙色_火花',  100, False),
    'mixed':       ('特效/混合色',     80, True),
    'gray_smoke':  ('特效/灰色_烟雾',  80, True),
    'white':       ('特效/白色',       50, True),
    'red_fire':    ('特效/红色_火光',  100, False),
    'blue':        ('特效/蓝色',       100, False),
    'black_frag':  ('特效/黑色_碎片',  50, True),
}

# ---------------------------------------------------------------------------
# popup menu — generic flat menu, takes list of (label, cmd) pairs
# ---------------------------------------------------------------------------
def popup_menu(hwnd, x, y, items):
    """Show right-click context menu. Returns command string or None."""
    if not items: return None
    menu = win32gui.CreatePopupMenu()
    id_to_cmd = {}
    for i, (label, cmd) in enumerate(items):
        id_to_cmd[i + 1] = cmd
        win32gui.AppendMenu(menu, win32con.MF_STRING, i + 1, label)
    flags = win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY | win32con.TPM_LEFTALIGN
    item_id = ctypes.windll.user32.TrackPopupMenu(menu, flags, x, y, 0, hwnd, None)
    win32gui.DestroyMenu(menu)
    return id_to_cmd.get(item_id) if item_id != 0 else None


# ---------------------------------------------------------------------------
# bed — separate layered window, draggable, positioned on right side
# ---------------------------------------------------------------------------
class Bed:
    def __init__(self, sw, sh):
        self.sw = sw; self.sh = sh
        path = os.path.join(ASSETS, '家具', '床.png')
        b = pygame.image.load(path).convert_alpha()
        w = int(b.get_width() * PET_SCALE)
        h = int(b.get_height() * PET_SCALE)
        self.img = pygame.transform.scale(b, (w, h))
        self.w, self.h = w, h
        # Default: right side, vertically centered
        self.x = sw - w - 30
        self.y = (sh - h) // 2
        self.visible = True
        self.win = LWindow(w, h, "PetBedCls")
        self.win.show()
        # drag
        self.dragging = False
        self.grab_ox = 0; self.grab_oy = 0

    def paint(self):
        if self.visible and self.win:
            self.win.paint(self.img, int(self.x), int(self.y))

    def contains(self, mx, my):
        return (self.x <= mx <= self.x + self.w and
                self.y <= my <= self.y + self.h)

    def grab(self, mx, my):
        self.dragging = True
        self.grab_ox = mx - self.x
        self.grab_oy = my - self.y

    def drag(self, mx, my):
        self.x = mx - self.grab_ox
        self.y = my - self.grab_oy

    def release(self):
        self.dragging = False

    def hide(self):
        if self.win:
            self.win.cleanup()
            self.win = None
        self.visible = False

    def show(self):
        if not self.visible:
            self.win = LWindow(self.w, self.h)
            self.win.show()
            self.visible = True

    def reset_position(self):
        self.x = self.sw - self.w - 30
        self.y = (self.sh - self.h) // 2

# ---------------------------------------------------------------------------
# scan max frame size
# ---------------------------------------------------------------------------
def scan_max():
    from PIL import Image
    mw = mh = 0
    for _, (folder, _, _) in {**ANIMS, **EFFECTS}.items():
        path = os.path.join(ASSETS, folder)
        if not os.path.isdir(path): continue
        for f in os.listdir(path):
            if f.endswith('.png'):
                w, h = Image.open(os.path.join(path, f)).size
                if w > mw: mw = w
                if h > mh: mh = h
    return int(mw*PET_SCALE), int(mh*PET_SCALE)

# ---------------------------------------------------------------------------
# particle system — lightweight, no external deps
# ---------------------------------------------------------------------------
class Particle:
    """Single particle: offset from pet center, velocity, lifetime, color/size."""
    __slots__ = ('x','y','vx','vy','life','max_life','color','size','rot')
    def __init__(self, x, y, vx, vy, life, color, size, rot=0.0):
        self.x = x; self.y = y
        self.vx = vx; self.vy = vy
        self.life = life; self.max_life = life
        self.color = color; self.size = size
        self.rot = rot

    @property
    def dead(self): return self.life <= 0

    def tick(self, dt):
        self.life -= dt
        if self.life > 0:
            self.x += self.vx * (dt / 16.667)
            self.y += self.vy * (dt / 16.667)

    @property
    def alpha(self):
        return max(0, min(255, int(255 * self.life / self.max_life)))

    @property
    def cur_size(self):
        return max(0.5, self.size * (0.5 + 0.5 * self.life / self.max_life))


# ---------------------------------------------------------------------------
# pet
# ---------------------------------------------------------------------------
class Pet:
    def __init__(self, sw, sh, win_w, win_h):
        self.sw = sw; self.sh = sh
        self.win_w = win_w; self.win_h = win_h
        self.x = sw - 200; self.y = 10   # top-right corner
        self.mode = 'idle'        # base mode
        self.action = None        # one-shot override
        self.ret_mode = 'idle'    # return mode after one-shot
        self.vx = 0.0; self.vy = 0.0
        self.dir_timer = 0
        self.auto_timer = 0       # autonomous action timer
        self.mode_timer = 0       # timeout for temporary continuous modes
        self.on_bed = False       # currently sleeping on bed
        self.target_x = 0; self.target_y = 0   # walk-to-target destination
        self.moving_to_target = False

        # particle effects
        self.particles = []
        self.gold_particles = []  # gold foil with screen coordinates (separate overlay)
        self.dust_timer = 0        # walk dust spawn interval
        self.sleep_fx_timer = 0    # sleep Z/glow interval
        self.idle_spark_timer = 0  # idle sparkle interval
        self.landed_spark = False  # flag for jump-land spark

        # load animations
        self.anim = {}
        for k, (folder, ms, loop) in ANIMS.items():
            f = load_frames(folder)
            f = scale_frames(f, PET_SCALE)
            self.anim[k] = Anim(f, ms, loop)

        # effects
        self.fx = {}
        for k, (folder, ms, loop) in EFFECTS.items():
            f = load_frames(folder)
            f = scale_frames(f, PET_SCALE)
            self.fx[k] = Anim(f, ms, loop)

        self.cur_fx = None     # active effect name
        self.cur_fx_anim = None
        self.boxed = False     # package mode
        self.box_fx = None     # brown box anim

        self.bed_img = None     # set by main() from bed.img for sleep composite

        # drag state
        self.grabbed = False
        self.grab_ox = 0.0; self.grab_oy = 0.0
        self.pregrab_mode = 'idle'
        self.pregrab_act = None
        self.pregrab_on_bed = False

        # IPC / control panel overridable settings
        self.move_speed = 1.0
        self.particles_enabled = True
        self.freeze_on_chat = True
        self.auto_behavior = True

    # -- current animation --
    def cur_anim(self):
        if self.grabbed: return self.anim['grabbed']
        if self.action: return self.anim[self.action]
        if self.boxed: return self.anim['sit']
        return self.anim[self.mode]

    def cur_frame(self):
        a = self.cur_anim()
        return a.frame() if a else None

    def cur_fx_frame(self):
        if self.box_fx: return self.box_fx.frame()
        if self.cur_fx_anim: return self.cur_fx_anim.frame()
        return None

    def render_frame(self):
        """Return (surface, fx_surface) for painting. Composites bed + particles."""
        f = self.cur_frame()
        fx = self.cur_fx_frame()
        if f is None: return None, None

        # 1) Bed sleep composite
        if self.mode == 'sleep' and self.bed_img and not self.action and not self.grabbed:
            bw, bh = self.bed_img.get_size()
            fw, fh = f.get_size()
            cw, ch = max(bw, fw), bh + fh - 15
            combo = pygame.Surface((cw, ch), pygame.SRCALPHA)
            combo.blit(self.bed_img, ((cw-bw)//2, ch-bh))
            combo.blit(f, ((cw-fw)//2, ch-fh))
            # Draw particles on composite
            self._draw_particles(combo, cw, ch, fw, fh)
            return combo, fx

        # 2) Normal frame with particles
        if self.particles:
            f = f.copy()
            fw, fh = f.get_size()
            self._draw_particles(f, fw, fh, fw, fh)
        return f, fx

    def _draw_particles(self, surf, cw, ch, fw, fh):
        """Draw particles onto surf. (cw,ch)=canvas size; (fw,fh)=frame size."""
        if not self.particles: return
        ox = cw // 2
        oy = ch - fh // 2
        for p in self.particles:
            lx = int(ox + p.x)
            ly = int(oy + p.y)
            a = p.alpha
            if a <= 0: continue
            is_gold = p.color[0] > 220 and p.color[1] > 170 and p.color[2] < 150
            # Gold foil: hold brightness then fade gradually
            if is_gold:
                ratio = p.life / p.max_life
                if ratio > 0.45:     a = 255
                else:                a = int(255 * ratio / 0.45)
                a = max(0, min(255, a))

            s_f = p.cur_size
            s = max(1, int(s_f))
            c = (*p.color, a)

            if is_gold:
                # ---- varied foil shapes ----
                shape_id = (int(p.x * 13 + p.y * 7) & 3)  # 0-3
                if shape_id == 0:
                    # Diamond (rotated square)
                    pts = [(lx, ly - s), (lx + s, ly), (lx, ly + s), (lx - s, ly)]
                elif shape_id == 1:
                    # Horizontal bar (wider than tall)
                    pts = [(lx - s, ly - s // 2), (lx + s, ly - s // 2),
                           (lx + s, ly + s // 2), (lx - s, ly + s // 2)]
                elif shape_id == 2:
                    # Tall hexagon / stretched diamond
                    sh = int(s * 1.4); sw = int(s * 0.6)
                    pts = [(lx, ly - sh), (lx + sw, ly - sh // 3),
                           (lx + sw, ly + sh // 3), (lx, ly + sh),
                           (lx - sw, ly + sh // 3), (lx - sw, ly - sh // 3)]
                else:
                    # Small thin rectangle (gold bar)
                    pts = [(lx - s, ly - s // 3), (lx + s, ly - s // 3),
                           (lx + s, ly + s // 3), (lx - s, ly + s // 3)]

                pygame.draw.polygon(surf, c, pts)

                # Inner highlight — lighter smaller version of same shape
                if s > 2:
                    hl = max(1, s - 1)
                    hc = (min(255, p.color[0] + 50), min(255, p.color[1] + 50),
                           max(0, p.color[2] - 10), max(0, a - 40))
                    if shape_id == 0:
                        hl_pts = [(lx, ly - hl), (lx + hl, ly), (lx, ly + hl), (lx - hl, ly)]
                    elif shape_id == 1:
                        hl_pts = [(lx - hl, ly - hl // 2), (lx + hl, ly - hl // 2),
                                  (lx + hl, ly + hl // 2), (lx - hl, ly + hl // 2)]
                    elif shape_id == 2:
                        hsh = int(hl * 1.4); hsw = int(hl * 0.6)
                        hl_pts = [(lx, ly - hsh), (lx + hsw, ly - hsh // 3),
                                  (lx + hsw, ly + hsh // 3), (lx, ly + hsh),
                                  (lx - hsw, ly + hsh // 3), (lx - hsw, ly - hsh // 3)]
                    else:
                        hl_pts = [(lx - hl, ly - hl // 3), (lx + hl, ly - hl // 3),
                                  (lx + hl, ly + hl // 3), (lx - hl, ly + hl // 3)]
                    pygame.draw.polygon(surf, hc, hl_pts)
            else:
                pygame.draw.circle(surf, c, (lx, ly), s)

    def _draw_gold_particles(self, surf):
        """Draw gold foil particles at screen coordinates onto surf (full-screen overlay)."""
        for p in self.gold_particles:
            sx, sy = int(p.x), int(p.y)
            a = p.alpha
            if a <= 0: continue
            # Gold alpha: hold full brightness for first 45% life, then fade
            ratio = p.life / p.max_life
            if ratio > 0.45:
                a = 255
            else:
                a = int(255 * ratio / 0.45)
            a = max(0, min(255, a))
            # Size grows over lifetime (1.0x to 1.3x) for a gentle increase as it falls
            t = 1.0 - ratio
            s = max(1, int(p.size * (1.0 + 0.3 * t)))
            c = (*p.color, a)

            # ---- varied foil shapes (same as in _draw_particles) ----
            shape_id = (int(p.x * 13 + p.y * 7) & 3)
            if shape_id == 0:
                pts = [(sx, sy - s), (sx + s, sy), (sx, sy + s), (sx - s, sy)]
            elif shape_id == 1:
                pts = [(sx - s, sy - s // 2), (sx + s, sy - s // 2),
                       (sx + s, sy + s // 2), (sx - s, sy + s // 2)]
            elif shape_id == 2:
                sh = int(s * 1.4); sw = int(s * 0.6)
                pts = [(sx, sy - sh), (sx + sw, sy - sh // 3),
                       (sx + sw, sy + sh // 3), (sx, sy + sh),
                       (sx - sw, sy + sh // 3), (sx - sw, sy - sh // 3)]
            else:
                pts = [(sx - s, sy - s // 3), (sx + s, sy - s // 3),
                       (sx + s, sy + s // 3), (sx - s, sy + s // 3)]
            pygame.draw.polygon(surf, c, pts)

            # Inner highlight — smaller, lighter version of same shape
            if s > 2:
                hl = max(1, s - 1)
                hc = (min(255, p.color[0] + 50), min(255, p.color[1] + 50),
                      max(0, p.color[2] - 10), max(0, a - 40))
                if shape_id == 0:
                    hl_pts = [(sx, sy - hl), (sx + hl, sy), (sx, sy + hl), (sx - hl, sy)]
                elif shape_id == 1:
                    hl_pts = [(sx - hl, sy - hl // 2), (sx + hl, sy - hl // 2),
                              (sx + hl, sy + hl // 2), (sx - hl, sy + hl // 2)]
                elif shape_id == 2:
                    hsh = int(hl * 1.4); hsw = int(hl * 0.6)
                    hl_pts = [(sx, sy - hsh), (sx + hsw, sy - hsh // 3),
                              (sx + hsw, sy + hsh // 3), (sx, sy + hsh),
                              (sx - hsw, sy + hsh // 3), (sx - hsw, sy - hsh // 3)]
                else:
                    hl_pts = [(sx - hl, sy - hl // 3), (sx + hl, sy - hl // 3),
                              (sx + hl, sy + hl // 3), (sx - hl, sy + hl // 3)]
                pygame.draw.polygon(surf, hc, hl_pts)

    # -- one-shot action --
    def do(self, name):
        if name not in self.anim: return
        self.action = name
        self.ret_mode = self.mode
        self.anim[name].reset()
        self.vx = 0; self.vy = 0

    # -- continuous mode --
    def set_mode(self, name):
        if name not in self.anim: return
        self.action = None
        self.mode = name
        self.anim[name].reset()
        self.vx = 0; self.vy = 0
        # Temporary continuous modes — auto-return to idle after timeout
        if name in ('walk',):       self.mode_timer = 4000 + random.randint(0, 2000)
        elif name in ('run',):      self.mode_timer = 3000 + random.randint(0, 2000)
        elif name in ('patrol',):   self.mode_timer = 5000 + random.randint(0, 3000)
        elif name in ('sit',):      self.mode_timer = 4000 + random.randint(0, 3000)
        elif name in ('lie_down',): self.mode_timer = 6000 + random.randint(0, 3000)
        # sleep is manual (bed) — no auto-timeout
        elif name in ('sleep',):    self.mode_timer = 0
        else:                       self.mode_timer = 0
        if name in ('walk','run','patrol'):
            self.dir_timer = 0
            self.vx = random.choice([-1,1])
            self.vy = random.choice([-0.5,0,0.5])

    # -- effect --
    def do_fx(self, name):
        if name == 'clear':
            self.cur_fx = None; self.cur_fx_anim = None
            self.boxed = False; self.box_fx = None
            return
        if name not in self.fx: return
        self.cur_fx = name
        self.cur_fx_anim = self.fx[name]
        self.cur_fx_anim.reset()

    # -- package / unbox --
    def do_box(self):
        self.boxed = True
        self.action = None
        self.mode = 'sit'
        self.anim['sit'].reset()
        self.vx = 0; self.vy = 0
        self.box_fx = self.fx['brown']
        self.box_fx.reset()
        self.cur_fx = None; self.cur_fx_anim = None

    def do_unbox(self):
        if not self.boxed: return
        self.boxed = False
        self.box_fx = None
        self.do_fx('black_frag')
        self.do('victory')
        self.ret_mode = 'idle'

    # -- particle emitter helpers --
    def _emit(self, count, spread, life_range, color, size_range, vy_range=(-0.5, 0.5)):
        """Emit `count` particles at pet center with given spread."""
        cx, cy = 0, -self.frame_size()[1] // 4  # roughly chest height
        for _ in range(count):
            rx = cx + random.uniform(-spread, spread)
            ry = cy + random.uniform(-spread, spread)
            vx = random.uniform(-1.5, 1.5)
            vy = random.uniform(*vy_range)
            life = random.randint(*life_range)
            size = random.uniform(*size_range)
            self.particles.append(Particle(rx, ry, vx, vy, life, color, size))

    def _dust(self):
        """Dust puffs behind walking pet."""
        if not self.particles_enabled: return
        self._emit(2, 8, (250, 500), (160, 140, 100), (2, 5), (-0.8, 0.2))

    def _zzz(self):
        """Sleep Z bubbles."""
        if not self.particles_enabled: return
        self._emit(1, 6, (800, 1500), (200, 220, 255), (3, 6), (-0.3, -0.1))

    def _sparkle(self):
        """Tiny golden spark."""
        if not self.particles_enabled: return
        self._emit(3, 15, (300, 600), (255, 220, 100), (1, 3), (-1.0, 1.0))

    def _burst(self, color):
        """Sudden burst of particles."""
        if not self.particles_enabled: return
        self._emit(8, 20, (200, 500), color, (2, 4), (-2.0, 2.0))

    def _gold_foil(self):
        """Golden foil flakes fall from below the pet, drawn on full-screen overlay."""
        if not self.particles_enabled: return
        fw, fh = self.frame_size()
        # Screen position of pet's visual center (where the window is placed)
        cx = self.x + self.win_w // 2
        cy = self.y + self.win_h // 2
        # Emit from the bottom edge of the pet body, in screen coordinates
        for _ in range(2):
            rx = random.uniform(-fw // 2, fw // 2)     # horizontal spread across pet width
            ry = fh // 2 + 3 + random.uniform(-4, 4)  # below the pet frame bottom
            vx = random.uniform(-0.5, 0.5)
            vy = random.uniform(1.0, 2.8)              # fall speed (px per ~16ms)
            life = random.randint(5000, 10000)          # long life — falls past screen bottom
            shade = random.choice([
                (255, 215, 0), (255, 200, 50), (255, 180, 20),
                (240, 200, 30), (255, 230, 100), (220, 180, 10),
                (255, 210, 80), (230, 190, 40),
            ])
            size = random.uniform(2.0, 5.0)
            rot = random.uniform(0, 6.28)               # random orientation
            # Store in gold_particles with screen coordinates
            self.gold_particles.append(Particle(cx + rx, cy + ry, vx, vy, life, shade, size, rot))

    # -- update --
    def update(self, dt):
        a = self.cur_anim()
        a.tick(dt)

        # one-shot completion — with particle burst on specific actions
        if self.action and a.done:
            done_action = self.action
            self.action = None
            self.mode = self.ret_mode
            self.anim[self.mode].reset()
            # Particle burst on action-complete
            if done_action in ('jump', 'victory'):
                self._burst((255, 200, 80))
                self.do_fx('orange_spark')
            elif done_action in ('air_struggle', 'slip', 'fall'):
                self._burst((200, 180, 160))
                self.do_fx('gray_smoke')
            elif done_action == 'turn_l2r':
                self._sparkle()

        # effect
        if self.cur_fx_anim:
            self.cur_fx_anim.tick(dt)
            if self.cur_fx_anim.done:
                self.cur_fx = None; self.cur_fx_anim = None
        if self.box_fx:
            self.box_fx.tick(dt)

        # —— freeze movement when AI chat is open (respect control panel setting) ——
        chat_open = self.freeze_on_chat and (ChatWindow.instance is not None and ChatWindow.instance.is_open)

        # —— movement: directed (to bed) or random (walk/run/patrol) ——
        cur = self.mode
        if not chat_open:
            if self.moving_to_target and not self.grabbed:
                speed = 4 * self.move_speed
                step = speed * (dt / 16.667)
                self.x += self.vx * step
                self.y += self.vy * step
                # Screen boundary clamp — prevent walking off-screen
                fw, fh = self.frame_size()
                hit = False
                if self.x < 0: self.x = 0; hit = True
                if self.x + fw > self.sw: self.x = self.sw - fw; hit = True
                if self.y < 0: self.y = 0; hit = True
                if self.y + fh > self.sh: self.y = self.sh - fh; hit = True
                if hit:
                    # Can't reach bed, cancel and go idle
                    self.moving_to_target = False
                    self.set_mode('idle')
                    return
                dx = self.target_x - self.x
                dy = self.target_y - self.y
                if dx*dx + dy*dy < step*step:
                    self.x = self.target_x
                    self.y = self.target_y
                    self.moving_to_target = False
                    self.on_bed = True
                    self._burst((255, 220, 150))
                    self.do_fx('white')
                    self.set_mode('sleep')
                    self.mode_timer = 0  # manual sleep, no auto-wake
            elif cur in ('walk','run','patrol') and not self.action and not self.grabbed:
                fw, fh = self.frame_size()
                speed = (6 if cur == 'run' else 3) * self.move_speed
                step = speed * (dt/16.667)
                self.x += self.vx * step
                self.y += self.vy * step
                # Bounce off edges + spark effect
                bounced = False
                if self.x < 0: self.x = 0; self.vx = abs(self.vx); bounced = True
                if self.x + fw > self.sw: self.x = self.sw - fw; self.vx = -abs(self.vx); bounced = True
                if self.y < 0: self.y = 0; self.vy = abs(self.vy); bounced = True
                if self.y + fh > self.sh: self.y = self.sh - fh; self.vy = -abs(self.vy); bounced = True
                if bounced:
                    self._burst((200, 180, 200))
                    self.do_fx('orange_spark')
                # Dust while moving
                self.dust_timer += dt
                if self.dust_timer >= 300:
                    self.dust_timer = 0
                    self._dust()
                    if cur == 'run':
                        self.do_fx(random.choice(['gray_smoke', 'brown']))
                self.dir_timer += dt
                if self.dir_timer >= 2000:
                    self.dir_timer = 0
                    self.vx = random.choice([-1,1])
                    self.vy = random.choice([-0.5,0,0.5])

        # —— gold foil pours down while being grabbed/dragged ——
        if self.grabbed:
            self.dust_timer += dt
            if self.dust_timer >= 120:  # ~8 bursts/sec
                self.dust_timer = 0
                self._gold_foil()

        # —— sleep Z bubbles ——
        if self.mode == 'sleep' and not self.grabbed:
            self.sleep_fx_timer += dt
            if self.sleep_fx_timer >= 2500:
                self.sleep_fx_timer = 0
                self._zzz()
                self.do_fx(random.choice(['white', 'blue']))

        # —— idle sparkle ——
        if self.mode == 'idle' and not self.action and not self.grabbed and not self.boxed and not self.on_bed:
            self.idle_spark_timer += dt
            if self.idle_spark_timer >= 5000:
                self.idle_spark_timer = 0
                if random.random() < 0.5:
                    self._sparkle()

        # —— natural autonomous behavior (no walking/jumping if chat open, skip if disabled) ——
        if self.auto_behavior and self.mode == 'idle' and not self.action and not self.grabbed and not self.boxed and not self.on_bed:
            self.auto_timer += dt
            if self.auto_timer >= 4000 + random.randint(0, 3000):
                self.auto_timer = 0
                r = random.random()
                if r < 0.30:
                    self.do(random.choice(['blink','look_left','look_right','shake']))
                elif r < 0.50:
                    if not chat_open:
                        self.set_mode('walk')
                elif r < 0.58:
                    self.set_mode('sit')
                elif r < 0.63:
                    self.set_mode('lie_down')
                elif r < 0.68:
                    if not chat_open:
                        self.do('jump')
                # else: 32% — stay idle

        # —— mode timeout: auto-return to idle (skip if on bed) ——
        if self.mode_timer > 0 and not self.action and not self.grabbed and not self.on_bed:
            self.mode_timer -= dt
            if self.mode_timer <= 0:
                self.mode_timer = 0
                self.set_mode('idle')

        # —— tick & cull particles ——
        dead = []
        for p in self.particles:
            p.tick(dt)
            if p.dead: dead.append(p)
        for p in dead:
            self.particles.remove(p)

        # —— gold particles (screen-space, separate overlay) ——
        dead = []
        for p in self.gold_particles:
            p.tick(dt)
            if p.dead: dead.append(p)
        for p in dead:
            self.gold_particles.remove(p)

    def frame_size(self):
        f = self.cur_frame()
        return (f.get_width(), f.get_height()) if f else (0,0)

    # -- toggle --
    def toggle(self):
        self.grabbed = False
        self.vx = 0; self.vy = 0
        if self.action:
            self.action = None
            self.mode = self.ret_mode
            self.anim[self.mode].reset()
            return
        if self.mode in ('walk','run','patrol'):
            self.set_mode('idle')
        else:
            self.set_mode('walk')

    # -- walk to a screen position (used for going to bed) --
    def move_to(self, tx, ty):
        self.target_x = tx; self.target_y = ty
        self.moving_to_target = True
        self.set_mode('walk')
        self.mode_timer = 0
        # Calculate velocity AFTER set_mode (which randomizes walk velocity)
        dx, dy = tx - self.x, ty - self.y
        dist = (dx*dx + dy*dy) ** 0.5
        if dist > 1:
            self.vx = dx / dist
            self.vy = dy / dist

    def wakeup(self):
        """Get up from bed back to idle."""
        self.on_bed = False
        self.moving_to_target = False
        self.set_mode('idle')
        self.mode_timer = 0

    # -- drag --
    def grab(self, mx, my):
        self.pregrab_mode = self.mode
        self.pregrab_act = self.action
        self.pregrab_on_bed = self.on_bed
        self.on_bed = False
        self.grabbed = True
        self.grab_ox = mx - self.x
        self.grab_oy = my - self.y
        self.anim['grabbed'].reset()

    def drag(self, mx, my):
        self.x = mx - self.grab_ox
        self.y = my - self.grab_oy

    def release(self):
        was_on_bed = self.pregrab_on_bed
        self.grabbed = False
        self.action = 'dropping'
        self.anim['dropping'].reset()
        self.ret_mode = 'idle' if was_on_bed else self.pregrab_mode
        self.vx = 0; self.vy = 0
        self._burst((255, 200, 100))
        self.do_fx('orange_spark')

    # -- debug state --
    def get_debug_state(self, fps=0, mouse_pos=(0,0)):
        fw, fh = self.frame_size()
        a = self.cur_anim()
        return {
            'fps': round(fps, 1),
            'mouse_x': mouse_pos[0], 'mouse_y': mouse_pos[1],
            'pet_x': round(self.x, 1), 'pet_y': round(self.y, 1),
            'frame_w': fw, 'frame_h': fh,
            'screen_w': self.sw, 'screen_h': self.sh,
            'mode': self.mode, 'action': self.action,
            'ret_mode': self.ret_mode,
            'grabbed': self.grabbed, 'boxed': self.boxed,
            'on_bed': self.on_bed, 'moving_to_target': self.moving_to_target,
            'target_x': round(self.target_x, 1), 'target_y': round(self.target_y, 1),
            'vx': round(self.vx, 3), 'vy': round(self.vy, 3),
            'anim_idx': a.idx, 'anim_len': len(a.frames), 'anim_ms': a.ms,
            'anim_done': a.done, 'anim_loop': a.loop,
            'cur_fx': self.cur_fx, 'box_fx': 'brown' if self.box_fx else None,
            'particles': len(self.particles), 'gold_particles': len(self.gold_particles),
            'auto_timer': round(self.auto_timer, 0),
            'mode_timer': round(self.mode_timer, 0),
            'dir_timer': round(self.dir_timer, 0),
            'dust_timer': round(self.dust_timer, 0),
            'sleep_fx_timer': round(self.sleep_fx_timer, 0),
            'idle_spark_timer': round(self.idle_spark_timer, 0),
        }

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def export_debug_state(pet, fps, mouse_pos):
    try:
        state = pet.get_debug_state(fps, mouse_pos)
        with open(DEBUG_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
    except:
        pass

def main():
    max_w, max_h = scan_max()
    pygame.init()
    SW, SH = screen_size()

    # tiny hidden window for pygame (timing/image loading)
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    ph = pygame.display.get_wm_info()['window']
    win32gui.ShowWindow(ph, win32con.SW_HIDE)

    pet = Pet(SW, SH, max_w, max_h)
    apply_pet_settings(pet, read_json(SETTINGS_PATH))
    pet_win = LWindow(max_w, max_h, "PetWinCls")
    pet_win.show()

    bed = Bed(SW, SH)
    pet.bed_img = bed.img  # share image for sleep composite

    # Gold foil overlay — full-screen transparent window, on top of everything
    OVERLAY_EX = (win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST |
                  win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT)
    overlay_win = LWindow(SW, SH, "PetDropCls", ex_style=OVERLAY_EX)
    overlay_win.show()
    overlay_surf = pygame.Surface((SW, SH), pygame.SRCALPHA)
    overlay_win.paint(overlay_surf, 0, 0)  # initial transparent paint

    clock = pygame.time.Clock()
    running = True
    pet_dragging = False
    drag_start = (0, 0)
    DRAG_THRESH = 5

    esc_prev = False

    # FPS tracking
    fps_counter = 0
    fps_timer = 0.0
    fps_display = 60.0
    debug_export_counter = 0
    ipc_settings_timer = 0.0
    ipc_cmd_time = 0.0

    # initial paint
    f, fx = pet.render_frame()
    if f: pet_win.paint(f, int(pet.x + 0.5), int(pet.y + 0.5), fx)
    bed.paint()

    while running:
        dt = clock.tick(60)

        # FPS calculation
        fps_counter += 1
        fps_timer += dt
        if fps_timer >= 500:
            fps_display = fps_counter / (fps_timer / 1000.0)
            fps_counter = 0
            fps_timer = 0.0

        # --- IPC: poll settings from control panel (every 2s) ---
        ipc_settings_timer += dt
        if ipc_settings_timer >= 2000:
            ipc_settings_timer = 0
            s = read_json(SETTINGS_PATH)
            if s:
                apply_pet_settings(pet, s)

        # --- IPC: process control panel commands ---
        new_cmd_time = process_pet_commands(pet, bed, ipc_cmd_time)
        if new_cmd_time == -1:
            running = False
        elif new_cmd_time != ipc_cmd_time:
            ipc_cmd_time = new_cmd_time

        # --- message pump for BOTH windows ---
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            h = msg.hWnd

            # --- Pet window messages ---
            if h == pet_win.hwnd:
                if msg.message == win32con.WM_LBUTTONDOWN:
                    if not pet.grabbed and pet.action != 'dropping':
                        mx, my = cursor_pos()
                        pet.grab(mx, my)
                        drag_start = (mx, my)
                        pet_dragging = False
                        ctypes.windll.user32.SetCapture(pet_win.hwnd)
                elif msg.message == win32con.WM_RBUTTONUP:
                    ctypes.windll.user32.ReleaseCapture()
                    pet.grabbed = False
                    pet_dragging = False
                    mx, my = cursor_pos()
                    # Pet right-click menu
                    menu_items = []
                    if pet.on_bed:
                        menu_items.append(("起床", 'wakeup'))
                    else:
                        menu_items.append(("睡觉", 'sleep'))
                    if not bed.visible:
                        menu_items.append(("显示床", 'show_bed'))
                    menu_items.append(("AI 对话", 'ai_chat'))
                    menu_items.append(("退出", 'exit'))

                    cmd = popup_menu(pet_win.hwnd, mx, my, menu_items)
                    if cmd == 'sleep':
                        # Show bed if hidden, then walk to it
                        if not bed.visible:
                            bed.show()
                        fw, fh = pet.frame_size()
                        tx = bed.x + (bed.w - fw) // 2
                        ty = bed.y - fh + 25
                        pet.move_to(tx, ty)
                    elif cmd == 'wakeup':
                        pet.wakeup()
                    elif cmd == 'show_bed':
                        bed.show()
                    elif cmd == 'ai_chat':
                        ChatWindow.toggle(mx, my)
                    elif cmd == 'exit':
                        running = False

            # --- Bed window messages ---
            elif bed.visible and bed.win and h == bed.win.hwnd:
                if msg.message == win32con.WM_LBUTTONDOWN:
                    mx, my = cursor_pos()
                    bed.grab(mx, my)
                    ctypes.windll.user32.SetCapture(bed.win.hwnd)
                elif msg.message == win32con.WM_RBUTTONUP:
                    mx, my = cursor_pos()
                    cmd = popup_menu(bed.win.hwnd, mx, my,
                                     [("重置位置", 'reset'), ("隐藏床", 'close')])
                    if cmd == 'close':
                        bed.hide()
                    elif cmd == 'reset':
                        bed.reset_position()
                        if pet.on_bed:
                            fw, fh = pet.frame_size()
                            tx = bed.x + (bed.w - fw) // 2
                            ty = bed.y - fh + 25
                            pet.x = tx; pet.y = ty

            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        # --- pygame events ---
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

        # --- keyboard: ESC / Q to quit ---
        esc = (win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000) or \
              (win32api.GetAsyncKeyState(ord('Q')) & 0x8000)
        if esc and not esc_prev:
            running = False
        esc_prev = esc

        # --- pet drag ---
        if pet.grabbed:
            btn = win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000
            if btn:
                mx, my = cursor_pos()
                if not pet_dragging:
                    dx = mx - drag_start[0]
                    dy = my - drag_start[1]
                    if dx * dx + dy * dy >= DRAG_THRESH * DRAG_THRESH:
                        pet_dragging = True
                if pet_dragging:
                    pet.drag(mx, my)
            else:
                ctypes.windll.user32.ReleaseCapture()
                if pet_dragging:
                    pet.release()
                else:
                    pet.grabbed = False
                    pet.toggle()
                pet_dragging = False

        # --- bed drag ---
        if bed.dragging:
            btn = win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000
            if btn:
                mx, my = cursor_pos()
                bed.drag(mx, my)
                # Move pet with bed if pet is on it
                if pet.on_bed:
                    fw, fh = pet.frame_size()
                    tx = bed.x + (bed.w - fw) // 2
                    ty = bed.y - fh + 25
                    pet.x = tx; pet.y = ty
            else:
                ctypes.windll.user32.ReleaseCapture()
                bed.release()

        # --- update ---
        pet.update(dt)

        # --- render pet ---
        f, fx = pet.render_frame()
        if f:
            pet_win.paint(f, int(pet.x + 0.5), int(pet.y + 0.5), fx)

        # --- render bed ---
        if bed.visible:
            bed.paint()

        # --- render gold foil overlay (topmost, full-screen) ---
        overlay_surf.fill((0, 0, 0, 0))
        if pet.gold_particles:
            pet._draw_gold_particles(overlay_surf)
        overlay_win.paint(overlay_surf, 0, 0)

        # --- export debug state & IPC status (every 6 frames) ---
        debug_export_counter += 1
        if debug_export_counter >= 6:
            debug_export_counter = 0
            mx, my = cursor_pos()
            export_debug_state(pet, fps_display, (mx, my))
            write_pet_status(pet)

    # cleanup
    pet_win.cleanup()
    if overlay_win and overlay_win.hwnd:
        overlay_win.cleanup()
    if bed.visible and bed.win:
        bed.win.cleanup()
    # Close AI chat if open
    if ChatWindow.instance and ChatWindow.instance.is_open:
        ChatWindow.instance.close()
    pygame.quit()
    sys.exit()

if __name__ == '__main__':
    main()
