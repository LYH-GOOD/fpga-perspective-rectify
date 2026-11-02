"""相机输入档位（480P / 600P）：左下角按钮 + 弹出面板 + 选档。

⚠️ 分工说明（2026-10-29）
    - 本模块只管 **UI 状态机 + 绘制 + 热区**，不做任何设备操作。
    - 真正的「切档」是一次**输入会话切换**（关相机 → 改模式 → 重开 → 新代次），
      需要相机/backend/display 三方协调，接口预留在 `request_camera_profile()`：
      接不上时只写一条 `CAMERA_PROFILE_SWITCH_UNAVAILABLE` checkpoint 并关面板，
      **绝不假装切换成功**。
    - 素材由 `build/make_ui_profile_assets.py` 生成（PIL + 系统中文字体）——
      OpenCV 的 putText 不支持中文，所以中文必须预渲染成 PNG。

坐标系：1280×720，与 `v75_ui_layout.json` 一致。
"""
from pathlib import Path
import hashlib,time,threading

from p11_contract import RELEASE_ID
from run_logging import checkpoint

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# ---- 布局（绝对坐标）------------------------------------------------------
BAR = (20, 640, 300, 56)          # Keep clear of native512px output ending636.
PANEL = (20, 128, 448, 488)       # Leave the fixed source/FPS strip visible.
CLOSE = (404, 140, 48, 48)
OPT_480 = (36, 256, 416, 84)
OPT_600 = (36, 352, 416, 84)
APPLY = (36, 528, 416, 64)
HINT = (340, 656, 240, 24)
#   切换中的居中卡片（420x140）与它里面的空进度条轨道
BUSY_CARD = (430, 290, 420, 140)
BUSY_TRACK = (470, 352, 340, 16)
# 21版日志切档2.22~2.92秒。沿用附件的1秒快速推进与后续缓进，
# 这只是等待提示；只有新档位画面提交成功才画满。
BUSY_FAST_S = 1.0
BUSY_CAP = 0.95
BUSY_CREEP_PER_S = 0.03

def progress_at(view, now):
    """Visual wait indicator, not a hardware percentage. Pure metadata only."""
    if view.get('complete'):return 1.
    elapsed=max(0.,now-float(view.get('started',now)))
    return min(.99,BUSY_CAP*elapsed/BUSY_FAST_S if elapsed<BUSY_FAST_S
               else BUSY_CAP+BUSY_CREEP_PER_S*(elapsed-BUSY_FAST_S))

PROFILES = ('480P', '600P')

# 素材尺寸断言：素材被改动时立刻报错，而不是画歪
SHAPES = {
    'v119_bar_480p.png': (56, 300, 3), 'v119_bar_600p.png': (56, 300, 3),
    'v119_panel_480p.png': (528, 448, 3), 'v119_panel_600p.png': (528, 448, 3),
    'v119_opt_480p_active.png': (84, 416, 3), 'v119_opt_480p_cand.png': (84, 416, 3),
    'v119_opt_600p_active.png': (84, 416, 3), 'v119_opt_600p_cand.png': (84, 416, 3),
    'v119_apply_480p.png': (64, 416, 3), 'v119_apply_600p.png': (64, 416, 3),
    'v119_apply_busy.png': (64, 416, 3),
    'v119_hint_reloc.png': (30, 420, 3), 'v119_hint_keep.png': (26, 420, 3),
    'v119_hint_apply.png': (24, 240, 3),
    'v119_busy_480p.png': (140, 420, 3), 'v119_busy_600p.png': (140, 420, 3),
    'v119_wait_480p.png': (140,420,3),'v119_wait_600p.png': (140,420,3),
    'v119_frame_timeout.png': (140,420,3),
}


def inside(point, rect):
    return (point is not None and rect[0] <= point[0] < rect[0] + rect[2]
            and rect[1] <= point[1] < rect[1] + rect[3])


def load_assets(assets, root):
    """一次性解码到 assets.profile_parts；运行时不再读盘。"""
    import cv2
    root = Path(root)
    parts = {}
    for name, shape in SHAPES.items():
        image = cv2.imread(str(root / name), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Missing camera profile UI asset ' + name)
        if image.shape != shape:
            raise ValueError('Invalid camera profile asset %s: %s != %s' % (name, image.shape, shape))
        image.setflags(write=False)
        parts[name] = image
    assets.profile_parts = parts
    assets.profile_asset_bytes = sum(p.nbytes for p in parts.values())


def _put(canvas, image, x, y):
    h, w = image.shape[:2]
    if y < 0 or x < 0 or y + h > canvas.shape[0] or x + w > canvas.shape[1]:
        return False
    canvas[y:y + h, x:x + w] = image
    return True


def render_overlay(canvas, view, assets):
    """只由 HDMI owner 调用。view 由 `ProfileUI.publish()` 产出。

    ⚠️ **不在这里判断"是否可见"** —— 可见性由调用方按**当前页面**决定
       （`_show` 里 `view in ('compare','rectified')`）。
       2026-10-29 上板：`publish()` 只在构造时调过一次，那时还在 home，
       `visible=False` 之后再没人刷新 ⇒ **按钮一次都没画出来**。
    """
    if not view:
        return
    parts = assets.profile_parts
    active = view['active']
    _put(canvas, parts['v119_bar_%s.png' % active.lower()], BAR[0], BAR[1])
    if view.get('timeout_notice'):
        _put(canvas,parts['v119_frame_timeout.png'],BUSY_CARD[0],BUSY_CARD[1]);return
    if view.get('busy'):
        #   切换中：居中卡片 + 按【已用时间】推进的进度条。
        # 正常随帧推进，停流期间由现有owner最多10Hz绘制切档UI。
        target = view.get('target') or active
        phase='wait' if view.get('phase')=='waiting_frame' else 'busy'
        _put(canvas, parts['v119_%s_%s.png' % (phase,target.lower())], BUSY_CARD[0], BUSY_CARD[1])
        frac = progress_at(view, time.perf_counter())
        tx, ty, tw, th = BUSY_TRACK
        filled = int(tw * max(0., min(1., frac)))
        if filled > 0:
            canvas[ty + 2:ty + th - 2, tx:tx + filled] = (210, 224, 78)   # ACCENT 的 BGR
        return
    if not view.get('open'):
        return
    x, y, w, h = PANEL
    _put(canvas, parts['v119_panel_%s.png' % active.lower()], x, y)
    for name in PROFILES:
        rect = OPT_480 if name == '480P' else OPT_600
        state = 'active' if name == active else 'cand'
        _put(canvas, parts['v119_opt_%s_%s.png' % (name.lower(), state)], rect[0], rect[1])
    _put(canvas, parts['v119_hint_reloc.png'], x + 16, y + 302)
    _put(canvas, parts['v119_hint_keep.png'], x + 16, y + 340)
    other = '600P' if active == '480P' else '480P'
    label = 'busy' if view.get('busy') else other.lower()
    _put(canvas, parts['v119_apply_%s.png' % label], APPLY[0], APPLY[1])
    _put(canvas, parts['v119_hint_apply.png'], HINT[0], HINT[1])


class ProfileUI:
    """事件驱动：没有常驻循环；只在状态变化时把 view 推给显示层。"""

    def __init__(self, state, display):
        self.state = state
        self.display = display
        self.active = getattr(state, 'camera_profile', None) or '480P'
        self.open = False
        self.busy = False
        self.contact = None
        #   进度条时钟：`apply()` 记起点，`view()` 按已用时间算进度，`applied/failed` 清零。
        self.switch_started = None
        self.switch_target = None
        self.lock=threading.RLock();self.revision=0;self.serial=0
        self.generation=None;self.ready_after=None;self.first_frame_deadline=None
        self.phase='idle';self.completed=False
        display.profile_controller=self
        #   ⚠️ 不需要"吞掉抬起"的机制：按下 `consumed=True` 时 `v75_touch` 根本
        #      不派发抬起（见 `v75_touch.py:170`）。留一个跨接触的标志反而会把
        #      **下一次**触摸的抬起吃掉。
        self.publish()

    # ---- 状态 → 显示 ------------------------------------------------------
    def view(self):
        # Published snapshots never mutate. The renderer advances time only
        # while busy; healthy frames reuse this dictionary without allocation.
        with self.lock:
            return dict(open=self.open,active=self.active,busy=self.busy,target=self.switch_target,
                started=self.switch_started,phase=self.phase,generation=self.generation,
                revision=self.revision,serial=self.serial,complete=self.completed)

    def publish(self):
        self.display.profile_overlay = self.view()

    def request_redraw(self):
        d = self.display
        try:
            d.request_view(d.ui_view, d.ui_generation)
        except Exception:
            pass

    # ---- 面板开关 --------------------------------------------------------
    def show(self):
        with self.lock:
            if self.busy:return
            self.open = True; self.busy = False;self.phase='idle'
            self.switch_target=None;self.switch_started=None;self.revision+=1;self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_PANEL_OPEN', active_profile=self.active,
                   available=list(PROFILES), event_only=True)

    def hide(self, reason='user'):
        with self.lock:
            if not self.open:return
            self.open = False; self.busy = False; self.contact = None;self.revision+=1;self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_PANEL_CLOSED', active_profile=self.active, reason=reason)

    # ---- 触摸 ------------------------------------------------------------
    def touch(self, event, generation):
        """返回 dict 交给 `v75_ui` 合并；返回 None 表示不归我管。"""
        if self.state.page not in ('compare', 'rectified'):
            return None
        if self.busy:
            # Keep the existing top-left Return available while changing format.
            if inside(event.get('press'),(0,0,180,72)):return None
            return dict(target='camera_profile', consumed=True, reason='camera_profile_busy')
        phase = event.get('phase'); press = event.get('press')
        if self.open:
            if phase == 'cancel':
                self.hide('contact_cancelled')
                return dict(target='camera_profile', consumed=True, reason='camera_profile_cancelled')
            if press is None:
                return None
            target = self._target(press)
            if phase == 'press':
                self.contact = target
                #   ⚠️⚠️ **`consumed` 决定"抬起会不会派发"** —— 见 `v75_touch.py:170`：
                #      `if outcome and outcome.get('consumed'): decision=dict(outcome,...)`
                #      ⇒ 按下时 `consumed=True` 的话，**抬起根本不会回调 on_touch**。
                #      2026-10-29 现场："点了应用没反应"就是这个 —— 应用按钮的按下
                #      返回了 `consumed=True`，`apply()` 一次都没执行。
                #      ⇒ **按下即生效的（关面板/选档）用 True；要等抬起的（应用）必须 False。**
                if target == 'close':
                    self.hide('close_press')
                    return dict(target='camera_profile_close', accepted=True, consumed=True)
                if target in ('opt_480P', 'opt_600P'):
                    return dict(target='camera_profile_' + target, accepted=True, consumed=True,
                                reason='profile_option_press')
                if target == 'apply':
                    #   必须 False：抬起事件要回来才执行 apply()
                    return dict(target='camera_profile_apply', consumed=False, reason='await_release')
                return dict(target='camera_profile_panel', consumed=True, reason='panel_background_press')
            origin = event.get('press_outcome') or {}
            accept = bool(target and origin.get('generation') == generation
                          and origin.get('target') == 'camera_profile_' + str(target)
                          and self._target(event.get('release')) == target
                          and event.get('peak_motion', 0) <= 32)
            if accept and target == 'apply':
                self.apply()
            return dict(target='camera_profile_' + str(target or 'panel'), accepted=accept, consumed=True,
                        reason='camera_profile_apply' if accept and target == 'apply' else 'camera_profile_release')
        # 面板关着：只有按钮能打开
        if phase == 'press':
            if inside(press, BAR):
                self.contact = 'bar'
                return dict(target='camera_profile_open', reason='await_release')
            return None
        origin = event.get('press_outcome') or {}
        if origin.get('generation') == generation and origin.get('target') == 'camera_profile_open':
            if inside(event.get('release'), BAR) and event.get('peak_motion', 0) <= 32:
                self.show(); return dict(target='camera_profile_open', accepted=True, consumed=True,
                                         reason='camera_profile_opened')
            return dict(target='camera_profile_open', consumed=True, reason='camera_profile_open_rejected')
        return None

    def _target(self, point):
        if inside(point, CLOSE):
            return 'close'
        if inside(point, OPT_480):
            return 'opt_480P'
        if inside(point, OPT_600):
            return 'opt_600P'
        if inside(point, APPLY):
            return 'apply'
        return None

    # ---- 应用 ------------------------------------------------------------
    def apply(self):
        """请求切档。**这里绝不改 `active`** —— 只有后端换好之后 `applied()` 才改。"""
        with self.lock:
            if self.busy:return False
            other = '600P' if self.active == '480P' else '480P'
        handler = getattr(self.state, 'request_camera_profile', None)
        if handler is None:
            checkpoint('CAMERA_PROFILE_SWITCH_UNAVAILABLE', requested=other,
                       active_profile=self.active, reason='backend_not_wired',
                       previous_setting_retained=True)
            self.hide('backend_not_wired')
            return False
        # Publish before requesting the new session: the UI owner may begin
        # device preparation immediately after request() wakes it.
        with self.lock:
            self.serial+=1;self.revision+=1;self.open=False;self.busy=True
            self.switch_target=other;self.switch_started=time.perf_counter()
            self.phase='switching';self.generation=None;self.ready_after=None
            self.first_frame_deadline=None;self.completed=False;self.publish()
        if not bool(handler(other)):
            checkpoint('CAMERA_PROFILE_SWITCH_REJECTED', requested=other,
                       active_profile=self.active, reason='request_not_accepted',
                       previous_setting_retained=True)
            self.cancel('rejected')
            return False
        # 请求已受理；设备生效后继续等待实际新画面提交。
        self.request_redraw()
        return True

    def bind_request(self,generation):
        with self.lock:
            if not self.busy:return
            self.generation=int(generation);self.publish()

    def applied(self, name, generation=None):
        """设备参数已经生效；进度仍等待新画面，不碰相机。"""
        if name not in PROFILES:
            raise ValueError('Unknown camera profile ' + str(name))
        with self.lock:
            self.active=name
            if not self.busy or generation!=self.generation:
                self.publish();return False
            self.phase='waiting_frame';self.ready_after=time.perf_counter()
            self.first_frame_deadline=self.ready_after+float(getattr(self.display,'timeout',3.))
            self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_APPLIED',active_profile=name,generation=generation,
                   completion='waiting_for_new_profile_frame_submission')
        return True

    def frame_view(self,view,generation,shape,ready,sequence,now):
        """Candidate for THIS canvas; completion is committed only after submit."""
        if not view or not view.get('busy'):return view
        expected=(480,640) if view['target']=='480P' else (600,800)
        with self.lock:
            valid=(self.busy and view['serial']==self.serial and generation==self.generation
                and self.phase=='waiting_frame' and tuple(shape[:2])==expected
                and ready is not None and self.ready_after is not None
                and self.ready_after<=ready<=now+.02 and now-ready<=.5 and sequence is not None and sequence>=0)
        return dict(view,complete=True) if valid else view

    def submitted(self,view,generation,ready,sequence):
        if not view or not view.get('complete'):return False
        with self.lock:
            if not self.busy or view['serial']!=self.serial or generation!=self.generation:return False
            self.busy=False;self.phase='idle';self.completed=False;self.revision+=1
            self.switch_target=None;self.switch_started=None;self.first_frame_deadline=None
            self.publish()
        checkpoint('CAMERA_PROFILE_FIRST_FRAME_SUBMITTED',active_profile=self.active,generation=generation,
            request_serial=view['serial'],camera_sequence=sequence,capture_ready_at=ready,
            physical_scan_time_measured=False)
        return True

    def expire(self,now):
        with self.lock:
            expired=self.busy and self.first_frame_deadline is not None and now>=self.first_frame_deadline
            if expired:
                self.busy=False;self.phase='failed';self.first_frame_deadline=None
                self.revision+=1;self.publish()
        if expired:
            checkpoint('CAMERA_PROFILE_SWITCH_FAILED',active_profile=self.active,
                reason='new_profile_first_frame_timeout',device_configuration_retained=True)
        return expired

    def cancel(self,reason='page_left'):
        with self.lock:
            changed=self.busy or self.open
            self.busy=False;self.open=False;self.contact=None;self.phase='idle'
            self.generation=None;self.switch_target=None;self.switch_started=None
            self.ready_after=None;self.first_frame_deadline=None;self.completed=False
            if changed:self.revision+=1
            self.publish()
        if changed:checkpoint('CAMERA_PROFILE_CANCELLED',active_profile=self.active,reason=reason)

    def failed(self, reason='switch_failed'):
        """换档失败：保留旧档位，退出等待态。"""
        self.cancel(reason);self.request_redraw()
        checkpoint('CAMERA_PROFILE_SWITCH_FAILED', active_profile=self.active,
                   reason=reason, previous_setting_retained=True)
