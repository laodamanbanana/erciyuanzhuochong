"""
Desktop Pet — macOS Native Version.
Uses PyObjC NSWindow + custom NSView for rendering.
Pygame used only for surface operations (no pygame display).
"""
import os, sys, random, json, threading, datetime, math

# ── macOS native imports ──
import objc
from Foundation import (
    NSObject, NSRect, NSPoint, NSSize,
    NSWindow, NSBackingStoreBuffered,
    NSWindowStyleMaskBorderless,
    NSEvent, NSApplication, NSApp,
    NSTimer, NSRunLoop, NSDefaultRunLoopMode,
    NSRunLoopCommonModes,
    NSLog,
)
from AppKit import (
    NSApplication, NSApp, NSMenu, NSMenuItem,
    NSImage, NSImageView, NSColor, NSScreen,
    NSView, NSTrackingArea, NSTrackingMouseMoved,
    NSTrackingActiveInActiveApp, NSTrackingInVisibleRect,
    NSTrackingAssumeInside, NSTrackingEnabledDuringMouseDrag,
    NSGraphicsContext,
)
from Quartz import (
    CGWindowLevelForKey, kCGStatusWindowLevelKey,
    CGImageCreate, CGColorSpaceCreateDeviceRGB,
    kCGImageAlphaPremultipliedLast, kCGRenderingIntentDefault,
    CGImageRelease, CGDataProviderCreateWithData,
    CGDataProviderRelease, CGContextDrawImage,
    CGContextSaveGState, CGContextRestoreGState,
    CGContextTranslateCTM, CGContextScaleCTM,
    CGRectMake, CGContextSetRGBFillColor, CGContextFillRect,
)

import pygame

# ── Paths ──
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, u'素材')
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.deskpet')
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(CONFIG_DIR, 'ai_config.json')
SETTINGS_PATH = os.path.join(CONFIG_DIR, 'settings.json')
COMMAND_PATH = os.path.join(CONFIG_DIR, 'command.json')
STATUS_PATH = os.path.join(CONFIG_DIR, 'status.json')

# ── AI config ──
DEFAULT_CONFIG = {
    "api_key": "",
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "model": "deepseek-v4-pro",
    "system_prompt": "You are a helpful assistant living on the user's desktop as a cute pet."
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except: pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def ai_chat_completion(messages, api_key, api_url, model, timeout=30):
    if not api_key:
        return False, "Please set API key in settings"
    try:
        import requests
    except ImportError:
        return False, "Missing requests library. Run: pip install requests"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 2048}
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return False, f"API error ({resp.status_code}): {resp.text[:200]}"
        data = resp.json()
        return True, data["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return False, "Request timed out"
    except requests.exceptions.ConnectionError:
        return False, "Connection error"
    except Exception as e:
        return False, f"Request failed: {str(e)[:200]}"

# ════════════════════════════════════════════════════════════
# AI Chat Window (tkinter, works on macOS)
# ════════════════════════════════════════════════════════════
import tkinter as tk
from tkinter import scrolledtext, messagebox

class MacChatWindow:
    _instance = None

    @classmethod
    def toggle(cls, pet_x, pet_y):
        if cls._instance is not None:
            try:
                if cls._instance.winfo_exists():
                    cls._instance.close()
                    return
            except:
                cls._instance = None
        screen = NSScreen.mainScreen().frame()
        sw, sh = int(screen.size.width), int(screen.size.height)
        x = min(pet_x + 50, sw - 400)
        y = max(20, min(pet_y - 240, sh - 520))
        cls._instance = cls(x, y)

    def __init__(self, x, y):
        self.win = tk.Toplevel()
        self.win.title("AI 对话")
        self.win.geometry(f"360x480+{int(x)}+{int(y)}")
        self.win.configure(bg='#0D0D0D')
        self.win.resizable(True, True)
        self.win.minsize(280, 300)
        self.win.attributes('-topmost', True)

        self.config = load_config()
        self.waiting = False
        self.conversation = [{"role": "system", "content": self.config.get("system_prompt",
                              DEFAULT_CONFIG["system_prompt"])}]

        # Chat display
        self.display = scrolledtext.ScrolledText(
            self.win, bg='#0D0D0D', fg='#FFF8E7',
            font=('Helvetica', 11), wrap=tk.WORD,
            highlightthickness=0, borderwidth=0, padx=8, pady=8)
        self.display.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))
        self.display.config(state=tk.DISABLED)

        # Input frame
        frame = tk.Frame(self.win, bg='#0D0D0D')
        frame.pack(fill=tk.X, padx=4, pady=4)
        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(frame, textvariable=self.input_var,
            bg='#1A1A1A', fg='#D4AF37', font=('Helvetica', 11),
            insertbackground='#D4AF37', relief=tk.FLAT, bd=4)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.input_entry.bind('<Return>', lambda e: self.send_message())
        self.input_entry.focus()

        tk.Button(frame, text="发送", bg='#D4AF37', fg='#0A0A0A',
            font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=12,
            command=self.send_message).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(frame, text="⚙", bg='#1A1A1A', fg='#D4AF37',
            font=('Helvetica', 10), relief=tk.FLAT, padx=6,
            command=self.open_settings).pack(side=tk.RIGHT, padx=(2, 0))

        self._append("system", "✦ AI 对话已开启 ✦")
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    def _append(self, role, text):
        self.display.config(state=tk.NORMAL)
        tags = {'user': ('#D4AF37', 'bold'), 'assistant': ('#FFD700', 'bold'),
                'waiting': ('#FFA500', 'normal'), 'error': ('#FF4444', 'normal'),
                'system': ('#B49632', 'normal')}
        color, style = tags.get(role, ('#FFF8E7', 'normal'))
        w = 'bold' if style == 'bold' else 'normal'
        self.display.insert(tk.END, text + '\n\n', (color, w))
        self.display.tag_config(color, foreground=color,
            font=('Helvetica', 11 if role not in ('system','error','waiting') else 10))
        self.display.see(tk.END)
        self.display.config(state=tk.DISABLED)

    def send_message(self):
        text = self.input_var.get().strip()
        if not text or self.waiting:
            return
        self.input_var.set("")
        self.conversation.append({"role": "user", "content": text})
        self._append("user", f"你: {text}")
        self._append("waiting", "思考中...")
        self.waiting = True
        self.input_entry.config(state=tk.DISABLED)

        cfg = load_config()
        threading.Thread(target=self._do_api_call,
            args=(list(self.conversation), cfg), daemon=True).start()

    def _do_api_call(self, conversation, cfg):
        try:
            ok, result = ai_chat_completion(conversation,
                cfg.get("api_key",""), cfg.get("api_url",""),
                cfg.get("model",""), 30)
            if ok:
                self.conversation.append({"role": "assistant", "content": result})
                self.win.after(0, lambda: self._replace_last("assistant", f"AI: {result}"))
            else:
                self.win.after(0, lambda: self._replace_last("error", f"⚠ {result}"))
        except Exception as e:
            self.win.after(0, lambda: self._replace_last("error", f"⚠ {str(e)[:200]}"))
        self.win.after(0, self._enable_input)

    def _replace_last(self, role, text):
        self.display.config(state=tk.NORMAL)
        self.display.delete('1.0', tk.END)
        self.display.config(state=tk.DISABLED)
        self._append(role, text)

    def _enable_input(self):
        self.waiting = False
        self.input_entry.config(state=tk.NORMAL)
        self.input_entry.focus()

    def open_settings(self):
        d = tk.Toplevel(self.win)
        d.title("AI 设置")
        d.geometry("460x300")
        d.configure(bg='#0D0D0D')
        d.resizable(False, False)
        d.transient(self.win)
        d.grab_set()

        entries = {}
        fields = [("API 密钥:", "api_key", True), ("API 地址:", "api_url", False),
                  ("模型:", "model", False), ("系统提示词:", "system_prompt", False)]

        for i, (label, key, pw) in enumerate(fields):
            tk.Label(d, text=label, bg='#0D0D0D', fg='#D4AF37',
                font=('Helvetica', 10), anchor='w').grid(row=i, column=0, sticky='w', padx=10, pady=4)
            if key == "system_prompt":
                e = tk.Text(d, height=3, width=40, bg='#1A1A1A', fg='#D4AF37',
                    font=('Helvetica', 10), insertbackground='#D4AF37', relief=tk.FLAT, bd=4)
                e.grid(row=i, column=1, sticky='ew', padx=10, pady=4)
                e.insert('1.0', self.config.get(key, ""))
            else:
                e = tk.Entry(d, width=40, bg='#1A1A1A', fg='#D4AF37',
                    font=('Helvetica', 10), insertbackground='#D4AF37',
                    relief=tk.FLAT, bd=4, show='*' if pw else None)
                e.grid(row=i, column=1, sticky='ew', padx=10, pady=4)
                e.insert(0, self.config.get(key, ""))
            entries[key] = e

        def save():
            cfg = self.config.copy()
            cfg["api_key"] = entries["api_key"].get().strip()
            cfg["api_url"] = entries["api_url"].get().strip()
            cfg["model"] = entries["model"].get().strip()
            cfg["system_prompt"] = entries["system_prompt"].get('1.0', tk.END).strip()
            if not cfg["api_key"] or not cfg["api_url"]:
                messagebox.showwarning("提示", "API 密钥和地址不能为空")
                return
            save_config(cfg)
            self.config = cfg
            self.conversation[0] = {"role": "system", "content": cfg["system_prompt"]}
            d.destroy()

        tk.Button(d, text="保存", bg='#D4AF37', fg='#0A0A0A',
            font=('Helvetica', 10, 'bold'), relief=tk.FLAT, padx=16,
            command=save).place(relx=0.35, rely=0.85)
        tk.Button(d, text="取消", bg='#1A1A1A', fg='#D4AF37',
            font=('Helvetica', 10), relief=tk.FLAT, padx=16,
            command=d.destroy).place(relx=0.55, rely=0.85)

    def close(self):
        MacChatWindow._instance = None
        try:
            self.win.destroy()
        except: pass

# ════════════════════════════════════════════════════════════
# Custom NSView — renders pet via drawRect:
# ════════════════════════════════════════════════════════════
class PetView(NSView):
    """NSView subclass that renders a pygame surface in drawRect:."""

    def initWithFrame_(self, frame):
        self = objc.super(PetView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._surf = None
        self._overlay = None
        self._pet_inst = None
        self._bed_inst = None
        self.setWantsLayer_(True)
        return self

    def setSurfaces(self, surf, overlay):
        """Set the pygame surfaces to render."""
        self._surf = surf
        self._overlay = overlay

    def setInstances(self, pet_inst, bed_inst):
        self._pet_inst = pet_inst
        self._bed_inst = bed_inst

    def drawRect_(self, rect):
        ctx = NSGraphicsContext.currentContext().CGContext()
        if self._surf is None:
            return

        w, h = self._surf.get_size()

        # 1. Draw bed background
        if self._bed_inst and self._bed_inst.visible:
            b = self._bed_inst
            bx = b.x - (self._pet_inst.x if self._pet_inst else 0)
            by = b.y - (self._pet_inst.y if self._pet_inst else 0)
            CGContextSetRGBFillColor(ctx, 0.3, 0.2, 0.1, 0.8)
            CGContextFillRect(ctx, CGRectMake(bx, by, b.w, b.h))

        # 2. Draw pet surface → CGImage
        raw = pygame.image.tostring(self._surf, 'RGBA', True)
        provider = CGDataProviderCreateWithData(None, raw, len(raw), None)
        colorspace = CGColorSpaceCreateDeviceRGB()
        cg_image = CGImageCreate(
            w, h, 8, 32, w*4,
            colorspace, kCGImageAlphaPremultipliedLast,
            provider, None, False, kCGRenderingIntentDefault)
        if cg_image:
            # Flip Y because CG coordinates are flipped relative to NSView
            CGContextSaveGState(ctx)
            CGContextTranslateCTM(ctx, 0, h)
            CGContextScaleCTM(ctx, 1, -1)
            CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), cg_image)
            CGContextRestoreGState(ctx)
            CGImageRelease(cg_image)
        CGDataProviderRelease(provider)

        # 3. Draw overlay (gold particles, pet-relative)
        if self._overlay:
            ow, oh = self._overlay.get_size()
            raw2 = pygame.image.tostring(self._overlay, 'RGBA', True)
            provider2 = CGDataProviderCreateWithData(None, raw2, len(raw2), None)
            cg_image2 = CGImageCreate(
                ow, oh, 8, 32, ow*4,
                colorspace, kCGImageAlphaPremultipliedLast,
                provider2, None, False, kCGRenderingIntentDefault)
            if cg_image2:
                CGContextSaveGState(ctx)
                CGContextTranslateCTM(ctx, 0, oh)
                CGContextScaleCTM(ctx, 1, -1)
                CGContextDrawImage(ctx, CGRectMake(0, 0, ow, oh), cg_image2)
                CGContextRestoreGState(ctx)
                CGImageRelease(cg_image2)
            CGDataProviderRelease(provider2)


# ════════════════════════════════════════════════════════════
# MacPetWindow — transparent always-on-top window
# ════════════════════════════════════════════════════════════
class MacPetWindow:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.nswindow = None
        self.pet_view = None
        self._create()

    def _create(self):
        rect = NSRect((0, 0), (self.w, self.h))
        style = NSWindowStyleMaskBorderless
        self.nswindow = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        self.nswindow.setOpaque_(False)
        self.nswindow.setBackgroundColor_(NSColor.clearColor())
        self.nswindow.setLevel_(CGWindowLevelForKey(kCGStatusWindowLevelKey))
        self.nswindow.setIgnoresMouseEvents_(False)
        self.nswindow.setAcceptsMouseMovedEvents_(True)
        self.nswindow.setCollectionBehavior_(1 << 8 | 1 << 0 | 1 << 2)

        # Custom view
        frame = NSRect((0, 0), (self.w, self.h))
        self.pet_view = PetView.alloc().initWithFrame_(frame)
        self.nswindow.setContentView_(self.pet_view)
        self.nswindow.makeKeyAndOrderFront_(None)

    def set_view_surfaces(self, surf, overlay):
        if self.pet_view:
            self.pet_view.setSurfaces(surf, overlay)

    def set_view_instances(self, pet_inst, bed_inst):
        if self.pet_view:
            self.pet_view.setInstances(pet_inst, bed_inst)

    def set_position(self, x, y):
        screen_h = NSScreen.mainScreen().frame().size.height
        self.nswindow.setFrameOrigin_(NSPoint(x, screen_h - y - self.h))

    def get_position(self):
        f = self.nswindow.frame()
        screen_h = NSScreen.mainScreen().frame().size.height
        return (f.origin.x, screen_h - f.origin.y - self.h)

    def request_redraw(self):
        if self.pet_view:
            self.pet_view.setNeedsDisplay_(True)

    def close(self):
        self.nswindow.close()


# ════════════════════════════════════════════════════════════
# IPC helpers (control panel integration)
# ════════════════════════════════════════════════════════════

def _read_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return default

def _apply_pet_settings(pet, settings):
    if not settings: return
    if 'move_speed' in settings:
        pet.move_speed = float(settings['move_speed'])
    if 'particles_enabled' in settings:
        pet.particles_enabled = bool(settings['particles_enabled'])
    if 'freeze_on_chat' in settings:
        pet.freeze_on_chat = bool(settings['freeze_on_chat'])
    if 'auto_behavior' in settings:
        pet.auto_behavior = bool(settings['auto_behavior'])

def _process_commands(pet, bed, last_cmd_time):
    cmd_data = _read_json(COMMAND_PATH)
    if not cmd_data or not isinstance(cmd_data, dict):
        return last_cmd_time
    cmd = cmd_data.get("command")
    ts = cmd_data.get("timestamp", 0)
    if not cmd or ts <= last_cmd_time:
        return last_cmd_time
    if cmd == 'sleep':
        if not bed.visible: bed.visible = True
        fw, fh = pet.frame_size()
        pet.move_to(bed.x + (bed.w-fw)//2, bed.y - fh + 25)
    elif cmd == 'wakeup': pet.wakeup()
    elif cmd == 'walk': pet.set_mode('walk')
    elif cmd == 'idle': pet.set_mode('idle')
    elif cmd == 'show_bed': bed.visible = True
    elif cmd == 'hide_bed': bed.visible = False
    elif cmd == 'ai_chat':
        MacChatWindow.toggle(int(pet.x + pet.max_fw//2), int(pet.y + pet.max_fh//2))
    elif cmd == 'exit':
        return -1
    return ts

def _write_status(pet):
    try:
        a = pet.cur_anim()
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

# ════════════════════════════════════════════════════════════
# Animation & Particles (same logic as Windows)
# ════════════════════════════════════════════════════════════

class Anim:
    __slots__ = ('frames', 'ms', 'loop', 'idx', 'acc', 'done')
    def __init__(self, frames, ms, loop=True):
        self.frames = frames; self.ms = ms; self.loop = loop
        self.idx = 0; self.acc = 0; self.done = False
    def reset(self):
        self.idx = 0; self.acc = 0; self.done = False
    def tick(self, dt):
        if self.done or not self.frames:
            return
        self.acc += dt
        while self.acc >= self.ms:
            self.acc -= self.ms
            self.idx += 1
            if self.idx >= len(self.frames):
                if self.loop:
                    self.idx = 0
                else:
                    self.idx = len(self.frames) - 1
                    self.done = True
                    return
    def frame(self):
        return self.frames[self.idx] if self.frames else None

def load_anim(path, ms, loop=True, scale=0.7):
    frames = []
    if os.path.isdir(path):
        for f in sorted(os.listdir(path)):
            if f.lower().endswith('.png'):
                try:
                    img = pygame.image.load(os.path.join(path, f)).convert_alpha()
                    if scale != 1.0:
                        w = int(img.get_width() * scale)
                        h = int(img.get_height() * scale)
                        img = pygame.transform.scale(img, (w, h))
                    frames.append(img)
                except: pass
    return Anim(frames, ms, loop)

class Particle:
    __slots__ = ('x','y','vx','vy','life','max_life','color','size')
    def __init__(self, x, y, vx, vy, life, color, size):
        self.x=x; self.y=y; self.vx=vx; self.vy=vy
        self.life=life; self.max_life=life
        self.color=color; self.size=size
    def tick(self, dt):
        self.x += self.vx * (dt/16.667)
        self.y += self.vy * (dt/16.667)
        self.life -= dt
        self.vx *= 0.98
        self.vy *= 0.98


# ════════════════════════════════════════════════════════════
# Pet class (adapted for Mac)
# ════════════════════════════════════════════════════════════
PET_SCALE = 0.7

_ANIM_SPEC = {
    'walk':       ('动作图1/走动图',       120, True),
    'idle':       ('动作图2/呼吸起伏',      160, True),
    'sleep':      ('动作图2/小幅晃动',      200, True),
    'sit':        ('动作图1/躺下的动作',    120, False),
    'jump':       ('动作图1/拿枪开枪的动作', 100, False),
    'blink':      ('动作图2/眨眼',         200, False),
    'look_left':  ('动作图2/看左',         200, False),
    'look_right': ('动作图2/看右',         200, False),
    'shake':      ('动作图2/摇头',         120, False),
    'lie_down':   ('动作图1/躺下的动作',    120, False),
}

_FX_SPEC = {
    'orange_spark': ('特效/橙色_火花', 50, True),
    'gray_smoke':   ('特效/灰色_烟雾', 80, True),
    'white':        ('特效/白色',      50, True),
    'brown':        ('特效/棕色',      60, True),
    'blue':         ('特效/蓝色',      50, True),
    'red_fire':     ('特效/红色_火光', 100, False),
    'black_frag':   ('特效/黑色_碎片', 50, True),
}

class Pet:
    def __init__(self, sw, sh):
        self.sw = sw; self.sh = sh
        self.max_fw = 0; self.max_fh = 0

        # Measure max frame size
        for name, (folder, ms, loop) in _ANIM_SPEC.items():
            p = os.path.join(ASSETS, folder)
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    if f.lower().endswith('.png'):
                        try:
                            img = pygame.image.load(os.path.join(p, f)).convert_alpha()
                            self.max_fw = max(self.max_fw, int(img.get_width()*PET_SCALE))
                            self.max_fh = max(self.max_fh, int(img.get_height()*PET_SCALE))
                        except: pass

        # Load animations
        self.anim = {}
        for name, (folder, ms, loop) in _ANIM_SPEC.items():
            self.anim[name] = load_anim(os.path.join(ASSETS, folder), ms, loop, PET_SCALE)
        self.fx = {}
        for name, (folder, ms, loop) in _FX_SPEC.items():
            self.fx[name] = load_anim(os.path.join(ASSETS, folder), ms, loop, PET_SCALE)

        self.mode = 'idle'
        self.action = None
        self.ret_mode = 'idle'
        self.vx = random.choice([-1, 1])
        self.vy = random.choice([-0.5, 0, 0.5])
        self.x = random.randint(0, sw - self.max_fw)
        self.y = random.randint(0, sh // 2)
        self.mode_timer = 0
        self.auto_timer = 0
        self.dir_timer = 0
        self.dust_timer = 0
        self.idle_spark_timer = 0
        self.sleep_fx_timer = 0
        self.grabbed = False
        self.grab_ox = 0; self.grab_oy = 0
        self.pregrab_mode = 'idle'; self.pregrab_act = None
        self.on_bed = False
        self.target_x = 0; self.target_y = 0
        self.moving_to_target = False
        self.particles = []
        self.gold_particles = []
        self.cur_fx = None
        self.cur_fx_anim = None

        # IPC / control panel overridable settings
        self.move_speed = 1.0
        self.particles_enabled = True
        self.freeze_on_chat = True
        self.auto_behavior = True

    def cur_anim(self):
        if self.action:
            return self.anim.get(self.action, self.anim.get('idle'))
        return self.anim.get(self.mode, self.anim.get('idle'))

    def frame_size(self):
        f = self.cur_anim().frame()
        return f.get_size() if f else (self.max_fw, self.max_fh)

    def render_frame(self):
        a = self.cur_anim()
        return a.frame(), self.cur_fx_anim.frame() if self.cur_fx_anim else None

    def do(self, name):
        if name not in self.anim: return
        self.action = name; self.ret_mode = self.mode
        self.anim[name].reset(); self.vx = 0; self.vy = 0

    def set_mode(self, name):
        if name not in self.anim: return
        self.action = None; self.mode = name
        self.anim[name].reset(); self.vx = 0; self.vy = 0
        if name in ('walk',): self.mode_timer = 4000 + random.randint(0, 2000)

    def do_fx(self, name):
        if name in self.fx:
            self.cur_fx = name
            self.cur_fx_anim = self.fx[name]
            self.cur_fx_anim.reset()

    def move_to(self, tx, ty):
        if self.action: return
        self.target_x = tx; self.target_y = ty
        self.moving_to_target = True; self.set_mode('walk'); self.mode_timer = 0
        dx, dy = tx - self.x, ty - self.y
        dist = (dx*dx + dy*dy)**0.5
        if dist > 1: self.vx = dx/dist; self.vy = dy/dist

    def wakeup(self):
        self.on_bed = False; self.moving_to_target = False
        self.set_mode('idle'); self.mode_timer = 0

    def grab(self, mx, my):
        self.grabbed = True; self.grab_ox = mx - self.x; self.grab_oy = my - self.y

    def drag(self, mx, my):
        self.x = mx - self.grab_ox; self.y = my - self.grab_oy

    def release(self):
        self.grabbed = False; self.vx = 0; self.vy = 0

    def _dust(self):
        if not self.particles_enabled: return
        fw, fh = self.frame_size()
        cx, cy = self.x + fw//2, self.y + fh
        for _ in range(3):
            vx = random.uniform(-0.8, 0.8) + (self.vx or 0)*-0.5
            self.particles.append(Particle(cx, cy, vx, random.uniform(-1.5,0),
                random.randint(300,600), (180,180,180), random.uniform(2,5)))

    def _sparkle(self):
        if not self.particles_enabled: return
        cx = self.x + self.max_fw//2 + random.randint(-10,10)
        cy = self.y + random.randint(0, self.max_fh//2)
        for _ in range(6):
            self.particles.append(Particle(cx, cy,
                random.uniform(-0.8,0.8), random.uniform(-0.8,0.2),
                random.randint(400,800), (255,220,80), random.uniform(1.5,3.5)))

    def _gold_foil(self):
        if not self.particles_enabled: return
        cx = self.x + self.max_fw//2 + random.randint(-20,20)
        cy = self.y + random.randint(0, self.max_fh)
        for _ in range(4):
            s = random.randint(160,255)
            self.gold_particles.append(Particle(cx, cy,
                random.uniform(-1.5,1.5), random.uniform(-2,0.5),
                random.randint(600,1200), (s,s-40,0), random.uniform(1.5,4)))

    def _zzz(self):
        if not self.particles_enabled: return
        cx, cy = self.x + self.max_fw//2, self.y - 10
        for _ in range(4):
            self.particles.append(Particle(cx, cy,
                random.uniform(-0.5,0), random.uniform(-1.5,-0.5),
                random.randint(600,900), (200,220,255), random.uniform(2,5)))

    def _burst(self, color):
        if not self.particles_enabled: return
        cx, cy = self.x + self.max_fw//2, self.y + self.max_fh//2
        for _ in range(20):
            a = random.uniform(0, 6.283); s = random.uniform(1, 4)
            self.particles.append(Particle(cx, cy,
                (self.vx or 1)*2 + random.uniform(-1,1) + s*(random.random()-0.5)*3,
                random.uniform(-3,1) + s*(random.random()-0.5)*3,
                random.randint(300,700), color, random.uniform(2,5)))

    def update(self, dt):
        a = self.cur_anim(); a.tick(dt)
        chat_open = self.freeze_on_chat and (MacChatWindow._instance is not None)

        # One-shot completion
        if self.action and a.done:
            done = self.action; self.action = None
            self.mode = self.ret_mode; self.anim[self.mode].reset()
            if done in ('jump',): self._burst((255,200,80)); self.do_fx('orange_spark')
            elif done in ('shake',): self._burst((200,180,160)); self.do_fx('gray_smoke')

        # FX anim tick
        if self.cur_fx_anim:
            self.cur_fx_anim.tick(dt)
            if self.cur_fx_anim.done: self.cur_fx = None; self.cur_fx_anim = None

        # Movement
        if not chat_open and not self.grabbed:
            if self.moving_to_target:
                step = 4 * self.move_speed * (dt/16.667)
                self.x += self.vx * step; self.y += self.vy * step
                fw, fh = self.frame_size()
                hit = False
                if self.x < 0: self.x = 0; hit = True
                if self.x+fw > self.sw: self.x = self.sw-fw; hit = True
                if self.y < 0: self.y = 0; hit = True
                if self.y+fh > self.sh: self.y = self.sh-fh; hit = True
                if hit: self.moving_to_target = False; self.set_mode('idle'); return
                dx, dy = self.target_x-self.x, self.target_y-self.y
                if dx*dx+dy*dy < step*step:
                    self.x, self.y = self.target_x, self.target_y
                    self.moving_to_target = False; self.on_bed = True
                    self._burst((255,220,150)); self.do_fx('white'); self.set_mode('sleep')
            elif self.mode in ('walk','run') and not self.action:
                speed = (6 if self.mode=='run' else 3) * self.move_speed; step = speed*(dt/16.667)
                self.x += self.vx*step; self.y += self.vy*step
                fw, fh = self.frame_size()
                if self.x < 0: self.x = 0; self.vx = abs(self.vx)
                if self.x+fw > self.sw: self.x = self.sw-fw; self.vx = -abs(self.vx)
                if self.y < 0: self.y = 0; self.vy = abs(self.vy)
                if self.y+fh > self.sh: self.y = self.sh-fh; self.vy = -abs(self.vy)
                self.dust_timer += dt
                if self.dust_timer >= 300:
                    self.dust_timer = 0; self._dust()
                self.dir_timer += dt
                if self.dir_timer >= 2000:
                    self.dir_timer = 0
                    self.vx = random.choice([-1,1])
                    self.vy = random.choice([-0.5,0,0.5])

        # Gold foil while dragging
        if self.grabbed:
            self.dust_timer += dt
            if self.dust_timer >= 120: self.dust_timer = 0; self._gold_foil()

        # Sleep Z's
        if self.mode == 'sleep' and not self.grabbed:
            self.sleep_fx_timer += dt
            if self.sleep_fx_timer >= 2500:
                self.sleep_fx_timer = 0; self._zzz()
                self.do_fx(random.choice(['white','blue']))

        # Idle sparkle
        if self.mode == 'idle' and not self.action and not self.grabbed and not self.on_bed:
            self.idle_spark_timer += dt
            if self.idle_spark_timer >= 5000:
                self.idle_spark_timer = 0
                if random.random() < 0.5: self._sparkle()

        # Autonomous behavior
        if self.auto_behavior and self.mode == 'idle' and not self.action and not self.grabbed and not self.on_bed:
            self.auto_timer += dt
            if self.auto_timer >= 4000+random.randint(0,3000):
                self.auto_timer = 0; r = random.random()
                if r < 0.30: self.do(random.choice(['blink','look_left','look_right','shake']))
                elif r < 0.50:
                    if not chat_open: self.set_mode('walk')
                elif r < 0.58: self.set_mode('sit')
                elif r < 0.63: self.set_mode('lie_down')
                elif r < 0.68:
                    if not chat_open: self.do('jump')

        # Mode timeout
        if self.mode_timer > 0 and not self.action and not self.grabbed and not self.on_bed:
            self.mode_timer -= dt
            if self.mode_timer <= 0: self.mode_timer = 0; self.set_mode('idle')

        # Particle cleanup
        for p in self.particles[:]:
            p.tick(dt)
            if p.life <= 0: self.particles.remove(p)
        for p in self.gold_particles[:]:
            p.tick(dt)
            if p.life <= 0: self.gold_particles.remove(p)


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    pygame.init()
    pygame.font.init()

    screen = NSScreen.mainScreen().frame()
    sw, sh = int(screen.size.width), int(screen.size.height)

    pet = Pet(sw, sh)
    bed = type('Bed', (), {
        'x': sw-150, 'y': (sh-80)//2, 'w': 120, 'h': 80, 'visible': True
    })()

    # Window tracks pet at pet's max frame size
    win_w = max(pet.max_fw, 200)
    win_h = max(pet.max_fh, 300)
    pet_win = MacPetWindow(win_w, win_h)

    # Surfaces (same size as window, particles relative to pet)
    surf = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
    overlay = pygame.Surface((win_w, win_h), pygame.SRCALPHA)

    pet_win.set_view_surfaces(surf, overlay)
    pet_win.set_view_instances(pet, bed)
    pet_win.set_position(pet.x, pet.y)

    NSApplication.sharedApplication()

    # ── Global state for menu callback ──
    state = {'running': True, 'pet_dragging': False}
    menu_items_def = []

    def on_menu_cmd(cmd):
        if cmd == 'sleep':
            if not bed.visible: bed.visible = True
            fw, fh = pet.frame_size()
            pet.move_to(bed.x + (bed.w-fw)//2, bed.y - fh + 25)
        elif cmd == 'wakeup': pet.wakeup()
        elif cmd == 'show_bed': bed.visible = True
        elif cmd == 'hide_bed': bed.visible = False
        elif cmd == 'ai_chat':
            px, py = pet_win.get_position()
            MacChatWindow.toggle(px, py)
        elif cmd == 'exit':
            state['running'] = False

    # ── Build menu items ──
    def get_menu_items():
        items = []
        if pet.on_bed: items.append(("起床", 'wakeup'))
        else: items.append(("睡觉", 'sleep'))
        if not bed.visible: items.append(("显示床", 'show_bed'))
        items.append(("AI 对话", 'ai_chat'))
        items.append(("退出", 'exit'))
        return items

    # ── Attach event handlers to PetView ──

    # We need to subclass PetView with event handlers.
    # Since PetView is already defined above, we'll patch it at runtime.
    # This is done via objc to properly handle the event chain.

    # Actually, we'll use a local event monitor approach instead of subclass methods.
    # NSEvent.addLocalMonitorForEventsMatchingMask_handler_

    # Create a helper object for event monitoring
    class EventHandler(NSObject):
        def initWithPet_win_pet_bed_state_(self, pwin, pt, bd, st):
            self = objc.super(EventHandler, self).init()
            if self is None: return None
            self._pet_win = pwin
            self._pet = pt
            self._bed = bd
            self._state = st
            self._drag_start = NSPoint(0, 0)
            self._last_mouse = NSPoint(0, 0)
            return self

        def handleEvent_(self, event):
            if not self._state['running']:
                return event
            etype = event.type()
            loc = event.locationInWindow()

            if etype == 1:  # NSLeftMouseDown
                # Convert to pet coordinates
                wx, wy = self._pet_win.get_position()
                mx = loc.x
                my = loc.y
                # Check if click is on pet
                if 0 <= mx <= self._pet.max_fw and 0 <= my <= self._pet.max_fh:
                    pet_x, pet_y = self._pet.x, self._pet.y
                    self._pet.grab(mx, my)
                    self._state['pet_dragging'] = True
                return None  # consume

            elif etype == 2:  # NSLeftMouseDragged
                if self._state['pet_dragging']:
                    self._pet.drag(loc.x, loc.y)
                    self._pet_win.set_position(self._pet.x, self._pet.y)
                return None

            elif etype == 3:  # NSLeftMouseUp
                if self._state['pet_dragging']:
                    self._pet.release()
                    self._state['pet_dragging'] = False
                return None

            elif etype == 4:  # NSRightMouseDown
                items = get_menu_items()
                # Show tkinter popup
                wx, wy = self._pet_win.get_position()
                PetMenu.show(wx + loc.x, wy + loc.y, items, on_menu_cmd)
                return None

            elif etype == 10:  # NSKeyDown
                chars = event.characters()
                if chars == '\x1b' or chars == 'q' or chars == 'Q':
                    self._state['running'] = False
                elif chars == ' ':
                    if self._pet.mode == 'walk':
                        self._pet.set_mode('idle')
                    elif self._pet.mode == 'idle' and not self._pet.action:
                        self._pet.set_mode('walk')
                return None

            return event  # pass through

    # PetMenu using tkinter for context menu
    class PetMenu:
        @staticmethod
        def show(x, y, items, callback):
            import tkinter as tk
            win = tk.Toplevel()
            win.overrideredirect(True)
            win.geometry(f"+{int(x)}+{int(y)}")
            win.configure(bg='#1A1A1A')
            win.attributes('-topmost', True)
            for label, cmd in items:
                btn = tk.Button(win, text=label, bg='#0D0D0D', fg='#D4AF37',
                    font=('Helvetica', 11), relief=tk.FLAT, padx=12, pady=2,
                    anchor='w', width=12,
                    command=lambda c=cmd: [win.destroy(), callback(c)])
                btn.pack(fill=tk.X, ipady=2)
                btn.bind('<Enter>', lambda e, b=btn: b.configure(bg='#D4AF37', fg='#0A0A0A'))
                btn.bind('<Leave>', lambda e, b=btn: b.configure(bg='#0D0D0D', fg='#D4AF37'))
            win.focus_set()
            win.bind('<FocusOut>', lambda e: win.destroy())

    # Create event handler
    handler = EventHandler.alloc().initWithPet_win_pet_bed_state_(pet_win, pet, bed, state)

    # Register for events with correct bitmask values
    # NSEventType: LeftMouseDown=1, LeftMouseUp=2, RightMouseDown=4,
    #              LeftMouseDragged=6, KeyDown=10
    # NSEventMask = 1 << type
    masks = (
        (1 << 1) |  # NSLeftMouseDown
        (1 << 2) |  # NSLeftMouseUp
        (1 << 6) |  # NSLeftMouseDragged
        (1 << 4) |  # NSRightMouseDown
        (1 << 10)   # NSKeyDown
    )
    monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(masks, handler.handleEvent_)

    # ── Animation timer ──
    class TimerDelegate(NSObject):
        def initWithPet_win_pet_bed_overlay_state_(self, pwin, pt, bd, ov, st):
            self = objc.super(TimerDelegate, self).init()
            if self: self._pwin = pwin; self._pet = pt; self._bed = bd; self._overlay = ov; self._state = st
            self._ipc_counter = 0
            self._ipc_cmd_time = 0.0
            return self
        def tick_(self, timer):
            if not self._state['running']:
                timer.invalidate()
                NSApp().terminate_(None)
                return
            dt = 16.667

            # IPC: poll settings, process commands, write status (~every 2s = ~120 ticks)
            self._ipc_counter += 1
            if self._ipc_counter >= 120:
                self._ipc_counter = 0
                s = _read_json(SETTINGS_PATH)
                if s: _apply_pet_settings(self._pet, s)
                new_cmd = _process_commands(self._pet, self._bed, self._ipc_cmd_time)
                if new_cmd == -1:
                    self._state['running'] = False
                    return
                elif new_cmd != self._ipc_cmd_time:
                    self._ipc_cmd_time = new_cmd
                _write_status(self._pet)

            self._pet.update(dt)
            self._pwin.set_position(self._pet.x, self._pet.y)

            # Render
            s = self._pwin.pet_view._surf
            if s is None: return
            s.fill((0,0,0,0))
            f, fx = self._pet.render_frame()
            if f: s.blit(f, (0,0))

            # Particles on surf (pet-relative)
            for p in self._pet.particles:
                alpha = int(255 * p.life/p.max_life) if p.max_life > 0 else 0
                alpha = max(0, min(255, alpha))
                px = int(p.x - self._pet.x); py = int(p.y - self._pet.y)
                if 0 <= px < s.get_width() and 0 <= py < s.get_height():
                    pygame.draw.circle(s, (*p.color, alpha), (px, py), int(p.size))

            # Gold particles on overlay (pet-relative)
            ov = self._overlay
            ov.fill((0,0,0,0))
            for p in self._pet.gold_particles:
                alpha = int(255 * p.life/p.max_life) if p.max_life > 0 else 0
                alpha = max(0, min(255, alpha))
                px = int(p.x - self._pet.x); py = int(p.y - self._pet.y)
                if -50 <= px < ov.get_width()+50 and -50 <= py < ov.get_height()+50:
                    pygame.draw.circle(ov, (*p.color, alpha), (px, py), int(p.size))

            self._pwin.request_redraw()

    timer_del = TimerDelegate.alloc().initWithPet_win_pet_bed_overlay_state_(pet_win, pet, bed, overlay, state)

    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1/60, timer_del, 'tick:', None, True)
    NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)

    # ── Run the app ──
    NSApp().run()

    # ── Cleanup (reached when NSApp stops) ──
    if monitor: NSEvent.removeMonitor_(monitor)
    timer.invalidate()
    if MacChatWindow._instance is not None:
        MacChatWindow._instance.close()
    pet_win.close()
    pygame.quit()


if __name__ == '__main__':
    main()
