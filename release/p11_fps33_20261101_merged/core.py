"""core —— 合并层，含 8 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


import hashlib
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr,contextmanager
from contextvars import ContextVar
from functools import wraps
from collections import deque
from collections.abc import Mapping
import datetime,hashlib,inspect,json,os,sys,threading,time,traceback,queue
import numpy as np
import faulthandler, hashlib, os, threading
from dataclasses import replace
from types import MappingProxyType
import gc,hashlib,threading,time
import gc,hashlib,time
import hashlib
import ctypes, hashlib, json, os, platform, struct, sys, time, zipfile
import hashlib,time
import cv2,numpy as np


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/08] p11_contract =====
# ======================================================================


"""V90 bounded frame/LK transactions; V74 automatic and explicit manual stay separate."""

RELEASE_ID = 'p11-rgb-pspl-v9-ai-fps-20261101-33'
HARDWARE_RELEASE_ID = 'p11_pwl_light_20261030_27'
EXACT_PAIR_SHA256 = {
    'system.bit': 'aaa9f632d3f8a7a11db14ae36876f0d40fa9d7fa2666d8a4894c2ca14ddef3d0',
    'system.hwh': 'deb1f5a620a74bae0cd74b25a223c4ab2beb319877e2cc74b675e66ac6e83637',
}
EXPECTED_HW = 0x00010005
CAPS = 0  # P1 has no V31 CAP register
PROFILE_CAPS = 0  # P1 row proof is handled by v64_p1_backend
BITFILE = 'system.bit'
HARDWARE_VARIANTS = {'system.bit':dict(release=HARDWARE_RELEASE_ID,version=EXPECTED_HW,ip='user.org:user:axis_remap_top:1.0')}
#   ⚠️ 2026-10-25：硬件改成 MAX_W=512 / ROWS=384（用宽度换深度，tile 4→2）
#      ⇒ 这里必须跟着改，否则 schedule/capacity_rows 会和硬件对不上。
#   ⚠️ BRAM 探测实测：512×384 = 96 块（与旧 1024×192 相同）；
#      640×320 实测 128 块（91%）不可用 —— 打包率取决于 HALF_W 能否整除 2048。
CACHE_PROFILES = ((512,384),)

#   ⭐⭐ 2026-10-25：行缓存的硬件参数**只在这里定义**。
#      ⚠️ 之前同一组数（MAX_W/ROWS）散在 3 处（hwh 回读校验、crop 宽度断言、
#         规划器 hint），改一次漏一处 —— 已经漏过 2 次，上板直接崩。
#      改硬件参数（`create_bd_hdmi.tcl` 里的 CONFIG.ROWS / CONFIG.MAX_W）时，
#      **只改这里 + C++ 那两处硬上限（v64_io.cpp 里 grep '512' / '384'）**。
LINE_BUF_W     = 512      # MAX_W：行缓存/输入 crop 的最大宽度
LINE_BUF_ROWS  = 384      # ROWS ：行缓存深度 = 允许的最大源行跨度
LINE_BUF_PIX_W = 16       # RGB565
MODULES = ('find_homography', 'p11_contract', 'p1_paper_quad', 'pl_fields', 'run_logging', 'v10_quad', 'v14_planner', 'v31_camera', 'v31_crash', 'v31_detection', 'v31_diagnostics', 'v31_gc_budget', 'v31_native', 'v31_pixels', 'v31_startup', 'v31_tracking', 'v41_quad', 'v45_color', 'v48_candidates', 'v49_boundary', 'v50_orientation', 'v51_target', 'v58_budget', 'v58_recovery', 'v62_boundary', 'v62_exterior', 'v62_policy', 'v64_camera_hdmi', 'v64_hdmi_display', 'v64_io', 'v64_p1_backend', 'v67_observation', 'v68_stability', 'v69_policy', 'v70_ps', 'v70_hdmi_timing', 'v71_display', 'v8_geometry', 'v8_plan', 'v8_surface', 'v8_tables', 'v75_ui', 'v75_touch', 'v76_snapshot', 'v78_localization', 'v79_acquire', 'v79_setup', 'v80_cache', 'v81_evidence', 'v82_interaction', 'v82_manual', 'v82_assets', 'v83_recovery', 'v84_prebuilt', 'v84_color', 'v84_snapshot', 'v85_boundary', 'v85_candidates', 'v86_policy', 'v86_candidates', 'v86_tracking', 'v87_v74_native', 'v87_v74_tracking', 'v87_acquire', 'v88_motion', 'v88_recovery', 'v90_transaction', 'v90_lk', 'v91_native', 'v91_policy', 'v92_manual_v87', 'v94_audit', 'v97_album')
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# UI modules are admitted once; the original per-frame MODULES guard is retained.
UI_MODULES = ('v73_ratio', 'v73_ratio_ui', 'v74_hold', 'v741_reading', 'v75_hotswitch', 'v98_ai_request', 'v98_ai_worker', 'v98_ai_geometry', 'v99_ai_protocol', 'v99_ai_worker', 'v99_ai_service', 'v99_ai_ui', 'v99_ai_selftest', 'v100_ai_image', 'v100_ai_tracking', 'v101_ai_camera', 'v102_ai_selection', 'v104_physical_tracking', 'v105_native', 'v105_reference', 'v105_manual_tracking', 'v107_policy', 'v107_hybrid', 'v108_hybrid_status', 'v109_target_cycle', 'v110_unified', 'v111_recovery', 'v112_display_hold', 'v113_live_preview', 'v114_geometry_overlay', 'v115_pair_display', 'v116_continuity', 'v117_manual_reference', 'v118_display_continuity', 'v119_profile_ui')
UI_ASSETS = ('v75_home.png', 'v75_header.png', 'v75_ui_layout.json', 'v77_header_rectified.png', 'v77_header_snapshot.png', 'v77_return_pressed.png', 'v79_status.png', 'v79_snapshot_busy.png', 'v79_setup_status.png', 'v79_placement_controls.png', 'v79_placement_help.png', 'v80_refind.png', 'v81_clipped_hint.png', 'v82_button_auto.png', 'v82_button_confirm.png', 'v82_button_refresh.png', 'v82_button_undo.png', 'v82_button_zoom_close.png', 'v82_button_zoom_scale.png', 'v82_calibration_help.png', 'v82_calibration_notices.png', 'v82_header_busy.png', 'v82_header_compare.png', 'v82_header_inspect.png', 'v82_header_rectified.png', 'v82_header_snapshot.png', 'v82_manual_badges.png', 'v82_reading_help.png', 'v82_refind.png', 'v97_media_bar.png', 'v97_media_notices.png', 'v97_album_header.png', 'v97_album_buttons.png', 'v97_1_button_left.png', 'v97_1_button_up.png', 'v97_1_button_down.png', 'v97_1_button_right.png', 'v97_3_target_hints.png', 'v73_ratio_panel.png', 'v73_ratio_atlas.png', 'v73_ratio_assets.json', 'v73_reading_header.png', 'v74_hold_badge.png', 'v98_ai_header.png', 'v98_ai_help.png', 'v98_ai_back.png', 'v98_ai_notices.png', 'v98_ai_manifest.json', 'v99_ai_home_status.png', 'v99_ai_selftest.json', 'v100_ai_badges.png', 'v102_ai_controls.png', 'v102_ai_stages.png', 'v108_hybrid_status.png', 'v119_bar_480p.png', 'v119_bar_600p.png', 'v119_panel_480p.png', 'v119_panel_600p.png', 'v119_opt_480p_active.png', 'v119_opt_480p_cand.png', 'v119_opt_600p_active.png', 'v119_opt_600p_cand.png', 'v119_apply_480p.png', 'v119_apply_600p.png', 'v119_apply_busy.png', 'v119_hint_reloc.png', 'v119_hint_keep.png', 'v119_hint_apply.png', 'v119_busy_480p.png', 'v119_busy_600p.png')
_FILE_DIGESTS = {}
_VERIFIED_SCOPE=ContextVar('p11_verified_package_scope',default=None)
_RECEIPTS=[]

UI_MODULES += ('v120_sharp', 'v120_image_settings', 'v121_selection', 'v121_target_switch', 'v122_light')
UI_ASSETS += ('v120_settings_atlas.png', 'v120_settings_atlas.json')
UI_MODULES += ('v123_live_ui',)
UI_ASSETS += ('v123_live_ui.png','v123_live_ui.json')
UI_ASSETS += ('v119_wait_480p.png','v119_wait_600p.png','v119_frame_timeout.png')

#   ⭐ 2026-11-02：新增「按层合并」发布布局。合并后只剩 6 个 .py（不是 114 个），
#      其余文件（界面资产 / .cpp / system.bit+hwh+manifest）一个不少。
#      布局写在 release_manifest.json 的 "layout" 字段：'layers-6' 或 'modules-114'。
#      缺字段时按旧的 114 模块布局处理 ⇒ 老发布包照常能过，不需要重打包。
LAYER_MODULES = ('core', 'geometry', 'tracking', 'display', 'ai', 'ui')
LAYOUT_LAYERS = 'layers-6'
LAYOUT_MODULES = 'modules-114'
#   合并布局还要多核两个文件：它们不是被 import 的模块，而是被 subprocess.Popen 拉起的
#   **子进程入口** ⇒ 合并工具不会碰它们，但必须是磁盘上的真实文件：
#     v99_ai_worker.py    ← v99_ai_service.py 拉起（常驻推理进程）
#     v99_ai_selftest.py  ← ai_selftest.ipynb 拉起（CPU 自检）
#   build/make_ai_entries.py 生成自包含版本（不导入任何层文件，免得把 cv2 拉进子进程）。
LAYER_EXTRA_FILES = ('v99_ai_worker.py', 'v99_ai_selftest.py')


def _module_names_for(release):
    layout = release.get('layout', LAYOUT_MODULES)
    if layout == LAYOUT_LAYERS:
        return list(LAYER_MODULES)
    if layout == LAYOUT_MODULES:
        return list(MODULES) + list(UI_MODULES)
    raise ValueError('未知的发布包布局：'+str(layout))

def cache_profile(width):
    #   ⚠️ 本函数有两个调用点传的是【输入图宽度】（v8_plan / pl_fields，相机 640），
    #      不是 crop 宽度。而行缓存只装 crop（≤512 由规划器保证）⇒ 这里**夹到 512**，
    #      统一返回唯一档位。**不要把上限改成 512 就完事** —— 那会让 640 宽的相机图
    #      在规划阶段直接抛异常（2026-10-25 差点这么上线）。
    if isinstance(width,bool) or int(width)!=width or not 2<=width<=1280:
        raise ValueError('输入宽度必须为 2..1280')
    width=min(int(width),512)
    for padded,rows in CACHE_PROFILES:
        if width<=padded:
            return padded,rows

def verify_package(bitfile=BITFILE):
    admission=_VERIFIED_SCOPE.get()
    if admission is not None and str(bitfile)==admission.bitfile:
        # The outer run/frame admission checks loaded module identities. Nested
        # tile/planner calls reuse it; hardware ACK/proof/cache guards are separate.
        return admission.manifest
    folder=Path(__file__).resolve().parent
    if (folder/'build_pending.json').exists():
        raise RuntimeError('V79发布包不完整；请上传完整V79目录与system成对文件。')
    path=Path(bitfile).expanduser().resolve()
    folder=Path(__file__).resolve().parent
    if path.name not in HARDWARE_VARIANTS or path.parent!=folder:
        raise ValueError('请从本版上传目录运行已登记的bit文件；Python 与 bit 必须在同一目录')
    release_path=folder/'release_manifest.json'
    if not release_path.is_file():
        raise ValueError('缺少 release_manifest.json，请完整复制新版目录，不要逐个覆盖旧目录')
    release=json.loads(release_path.read_text(encoding='utf-8'))
    hashes=release.get('sha256',{})
    if release.get('ready_for_board') is not True:raise ValueError('发布包未完成配对与来源核对')
    if release.get('release_id')!=RELEASE_ID:
        raise ValueError('发布版本不一致；请重启内核，从新版目录重新导入')
    if any(hashes.get(name)!=digest for name,digest in EXACT_PAIR_SHA256.items()):
        raise ValueError('本版只接受已登记的锐化 bit/HWH 配对；请完整上传本版目录')
    module_names=_module_names_for(release)
    required={name+'.py' for name in module_names}|{path.name,path.with_suffix('.hwh').name,path.with_suffix('.manifest.json').name,'v31_native.cpp','v31_camera_native.cpp','v64_io.cpp','v87_v74_native.cpp','v91_transaction.cpp','v105_edges.cpp'}|set(UI_ASSETS)
    if release.get('layout',LAYOUT_MODULES)==LAYOUT_LAYERS:required|=set(LAYER_EXTRA_FILES)
    if not required.issubset(hashes):
        raise ValueError('发布清单缺少必要文件')
    # Notebook execution/edits are expected: only executable drivers and the
    # hardware pair/manifest and native source are immutable at runtime. Other hashes document the delivered folder.
    for name in sorted(required):
        expected=hashes[name]
        if Path(name).name!=name or name in ('.','..'):
            raise ValueError('发布清单包含非法路径')
        p=folder/name
        if not p.is_file():
            raise ValueError('缺少文件 '+name)
        stat=p.stat()
        stamp=(str(p),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,expected)
        actual_digest=_FILE_DIGESTS.get(stamp)
        if actual_digest is None:
            actual_digest=hashlib.sha256(p.read_bytes()).hexdigest()
            _FILE_DIGESTS[stamp]=actual_digest
        if actual_digest!=expected:
            raise ValueError(f'文件版本或内容不一致：{name}。请重新完整复制发布目录')
    for name in module_names:
        module=sys.modules.get(name)
        if module is None:
            continue
        actual=Path(getattr(module,'__file__','')).resolve()
        if (actual!=folder/(name+'.py') or getattr(module,'RELEASE_ID',None)!=RELEASE_ID
                or getattr(module,'_SOURCE_SHA256',None)!=hashes[name+'.py']):
            raise ValueError(f'内核缓存了旧模块 {name}；请 Kernel -> Restart 后从新版目录运行')
    _RECEIPTS.append(release)
    del _RECEIPTS[:-16]
    return release


class PackageAdmission:
    """Pinned full-file receipt, with a cheap loaded-module guard per owner frame.

    Files remain immutable for a run. Each new public run still performs full
    digest admission. The object is owned by PreparedImage, not a global LRU.
    """
    def __init__(self,bitfile,manifest):
        if not any(item is manifest for item in _RECEIPTS):
            manifest=verify_package(bitfile)
        self.folder=Path(__file__).resolve().parent
        self.bitfile=str(Path(bitfile).expanduser().resolve())
        self.manifest=manifest
        hashes=manifest['sha256']
        self.expected=tuple((name,self.folder/(name+'.py'),hashes[name+'.py'])
                            for name in _module_names_for(manifest))
        self.loaded={}
        self.check()
    def check(self):
        for name,path,digest in self.expected:
            module=sys.modules.get(name)
            if module is None:continue
            actual=getattr(module,'__file__','')
            cached=self.loaded.get(name)
            if cached is None or cached[0] is not module:
                if Path(actual).resolve()!=path:
                    raise ValueError('本次运行混用了模块 '+name+'；请重启内核')
                self.loaded[name]=(module,actual)
            elif actual!=cached[1]:
                raise ValueError('本次运行模块路径改变 '+name+'；请重启内核')
            if (getattr(module,'RELEASE_ID',None)!=RELEASE_ID
                    or getattr(module,'_SOURCE_SHA256',None)!=digest):
                raise ValueError('本次运行混用了模块 '+name+'；请重启内核')
        return self.manifest

def bind_package(bitfile,manifest):
    return PackageAdmission(bitfile,manifest)

@contextmanager
def verified_package_scope(bitfile,manifest=None,check_modules=False):
    """One full admission per run; optional one identity guard per owner frame."""
    existing=_VERIFIED_SCOPE.get()
    same=(existing is not None and str(bitfile)==existing.bitfile and
          (manifest is existing or manifest is existing.manifest))
    if same:
        if check_modules:existing.check()
        yield
        return
    admission=manifest if isinstance(manifest,PackageAdmission) else bind_package(bitfile,manifest)
    if str(bitfile)!=admission.bitfile:
        if str(Path(bitfile).expanduser().resolve())!=admission.bitfile:
            raise ValueError('配对收据与bitfile不一致')
    # A fresh scope also admits lazy imports or module replacement exactly once.
    admission.check()
    token=_VERIFIED_SCOPE.set(admission)
    try:yield
    finally:_VERIFIED_SCOPE.reset(token)


# ======================================================================
# ===== [02/08] run_logging =====
# ======================================================================


"""One ordered run-result.log writer; JSON encoding is off the hardware owner."""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RUN_LOG=Path(__file__).resolve().parent/'run-result.log'
_CURRENT=ContextVar('p11_current_run_log',default=None)
_ACTIVE_FILE=ContextVar('p11_active_log_file',default=None)
_BUSY=threading.Lock()
_FRAME_POLICY=ContextVar('p11_frame_log_policy',default=('detailed',30,.120))
_DETAIL_SAMPLE=ContextVar('p11_detail_sample',default=None)

def _stderr_notice(value):
    try:
        stream=sys.__stderr__ or getattr(sys.stderr,'console',sys.stderr)
        stream.write(value);stream.flush()
    except BaseException:pass

def _json_default(value):
    if isinstance(value,Path):return str(value)
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    if type(value).__module__=='p11_runtime' and hasattr(value,'path'):
        return dict(type=type(value).__name__,bitfile=str(value.path))
    if callable(value):return getattr(value,'__qualname__',repr(value))
    return repr(value)

def _owned_payload(value):
    """Detach small record metadata before queuing; never retain mutable DMA views."""
    if value is None or isinstance(value,(str,int,float,bool)):return value
    if isinstance(value,Mapping):return {k:_owned_payload(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return tuple(_owned_payload(v) for v in value)
    if isinstance(value,np.ndarray):return value.tolist()
    return _json_default(value)

class _Writer:
    def __init__(self):
        self.queue=queue.Queue(maxsize=64);self.error=None;self.closed=False
        self.io_events=deque(maxlen=512);self.io_events_dropped=0
        self.stats_lock=threading.Lock()
        self.stats=dict(records=0,bytes=0,serialize_s=0.,serialize_cpu_s=0.,serialize_max_s=0.,
            snapshot_s=0.,snapshot_cpu_s=0.,snapshot_max_s=0.,
            enqueue_s=0.,enqueue_cpu_s=0.,enqueue_max_s=0.,queue_max=0,
            write_s=0.,write_cpu_s=0.,write_max_s=0.,flush_s=0.,flush_cpu_s=0.,flush_max_s=0.,
            fsync_s=0.,fsync_cpu_s=0.,fsync_max_s=0.,sync_count=0,barrier_wait_s=0.,
            serialize_scope='writer_thread',producer_scope='metadata_snapshot_and_bounded_enqueue')
        self.worker=threading.Thread(target=self._run,name='run_log_writer',daemon=True)
        self.worker.start()

    def _put(self,item):
        began=time.perf_counter();cpu=time.thread_time()
        while True:
            if self.error:raise RuntimeError('日志写入线程失败') from self.error
            if self.closed:raise RuntimeError('日志队列已关闭')
            try:self.queue.put(item,timeout=.1);break
            except queue.Full:
                if not self.worker.is_alive():raise RuntimeError('日志线程已退出')
        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
        with self.stats_lock:
            self.stats['enqueue_s']+=elapsed;self.stats['enqueue_cpu_s']+=used
            self.stats['enqueue_max_s']=max(self.stats['enqueue_max_s'],elapsed)
            self.stats['queue_max']=max(self.stats['queue_max'],self.queue.qsize())

    def record(self,payload):
        began=time.perf_counter();cpu=time.thread_time()
        owned=_owned_payload(payload)
        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
        with self.stats_lock:
            self.stats['snapshot_s']+=elapsed;self.stats['snapshot_cpu_s']+=used
            self.stats['snapshot_max_s']=max(self.stats['snapshot_max_s'],elapsed)
        self._put(('record',owned,None))

    def snapshot(self):
        with self.stats_lock:return dict(self.stats)

    def write(self,value):
        if value:self._put(('write',str(value),None))
        return len(value)

    def flush(self):
        if self.error:raise RuntimeError('日志文件错误') from self.error

    def barrier(self,durable=False):
        done=threading.Event();began=time.perf_counter()
        self._put(('sync' if durable else 'flush','',done))
        while not done.wait(.1):
            if self.error or not self.worker.is_alive():raise RuntimeError('日志同步失败') from self.error
            if time.perf_counter()-began>30:raise TimeoutError('日志同步超过30秒')
        with self.stats_lock:self.stats['barrier_wait_s']+=time.perf_counter()-began
        if self.error:raise RuntimeError('日志同步失败') from self.error

    def _io_event(self,kind,begin,cpu,always=False):
        end=time.perf_counter();used=time.thread_time()-cpu;wall=end-begin
        if always or wall>=.002:
            if len(self.io_events)==self.io_events.maxlen:self.io_events_dropped+=1
            self.io_events.append(dict(operation=kind,begin=begin,end=end,wall_s=wall,
                thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,wall-used),thread_id=threading.get_ident()))

    def _run(self):
        try:
            with RUN_LOG.open('a',encoding='utf-8',buffering=65536) as file:
                dirty=False;last=time.monotonic()
                def flush(durable=False):
                    began=time.perf_counter();cpu=time.thread_time();file.flush()
                    elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                    self._io_event('flush',began,cpu)
                    with self.stats_lock:
                        self.stats['flush_cpu_s']+=used;self.stats['flush_s']+=elapsed
                        self.stats['flush_max_s']=max(self.stats['flush_max_s'],elapsed)
                    if durable:
                        began=time.perf_counter();cpu=time.thread_time();os.fsync(file.fileno())
                        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                        self._io_event('fsync',began,cpu,True)
                        with self.stats_lock:
                            self.stats['fsync_cpu_s']+=used;self.stats['fsync_s']+=elapsed
                            self.stats['fsync_max_s']=max(self.stats['fsync_max_s'],elapsed)
                            self.stats['sync_count']+=1
                while True:
                    try:kind,value,event=self.queue.get(timeout=.05)
                    except queue.Empty:
                        if dirty and time.monotonic()-last>=.5:flush();dirty=False;last=time.monotonic()
                        continue
                    try:
                        if kind in ('record','write'):
                            if kind=='record':
                                began=time.perf_counter();cpu=time.thread_time()
                                value=json.dumps(value,ensure_ascii=False,default=_json_default)+'\n'
                                elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                                with self.stats_lock:
                                    self.stats['serialize_s']+=elapsed;self.stats['serialize_cpu_s']+=used
                                    self.stats['serialize_max_s']=max(self.stats['serialize_max_s'],elapsed)
                            began=time.perf_counter();cpu=time.thread_time();file.write(value)
                            elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                            self._io_event('write',began,cpu)
                            with self.stats_lock:
                                self.stats['records']+=1;self.stats['bytes']+=len(value.encode('utf-8'))
                                self.stats['write_s']+=elapsed;self.stats['write_cpu_s']+=used
                                self.stats['write_max_s']=max(self.stats['write_max_s'],elapsed)
                            dirty=True
                        else:flush(kind in ('sync','stop'));dirty=False;last=time.monotonic()
                        if kind=='stop':return
                        if dirty and time.monotonic()-last>=.5:flush();dirty=False;last=time.monotonic()
                    except BaseException as exc:self.error=exc;raise
                    finally:
                        if event:event.set()
                        self.queue.task_done()
        except BaseException as exc:self.error=exc

    def close(self):
        if self.closed:return
        if self.error:
            self.worker.join(1);self.closed=True
            raise RuntimeError('日志写入已经失败') from self.error
        done=threading.Event();self._put(('stop','',done));self.worker.join(30);self.closed=True
        if self.worker.is_alive():raise TimeoutError('日志线程未停止')
        if self.error:raise RuntimeError('日志关闭失败') from self.error

_CONSOLE_ENABLED=ContextVar('p11_console_enabled',default=False)

class _Tee:
    def __init__(self,console,file):self.console,self.file=console,file
    def write(self,value):
        self.file.write(value)
        return self.console.write(value) if _CONSOLE_ENABLED.get() else len(value)
    def flush(self):
        self.file.flush()
        if _CONSOLE_ENABLED.get():self.console.flush()
    def __getattr__(self,name):return getattr(self.console,name)

def current_log_metadata():return dict(_CURRENT.get() or {})
def log_metrics():
    active=_ACTIVE_FILE.get();return active.snapshot() if active else {}
def flush_log(durable=False):
    active=_ACTIVE_FILE.get()
    if active:active.barrier(durable)

@contextmanager
def frame_log_scope(mode='compact',detail_every=30,slow_ms=120.):
    if mode not in ('compact','detailed'):raise ValueError('log_mode须为compact/detailed')
    if isinstance(detail_every,bool) or not isinstance(detail_every,int) or detail_every<1:
        raise ValueError('log_detail_every须为正整数')
    if not np.isfinite(slow_ms) or slow_ms<=0:raise ValueError('log_slow_ms须为有限正数')
    token=_FRAME_POLICY.set((mode,detail_every,float(slow_ms)/1000.))
    sample_token=_DETAIL_SAMPLE.set(dict(lock=threading.Lock(),seen={},decisions={}))
    try:yield
    finally:
        _DETAIL_SAMPLE.reset(sample_token);_FRAME_POLICY.reset(token)

def _recovery_deferred(tracking):
    return (tracking.get('mode')=='lost_skip' and not tracking.get('valid',True)
            and tracking.get('recovery_attempt',{}).get('state')=='bounded_backoff')

def diagnostic_detail(index,wall=0.,tracking=None):
    """Keep first occurrence and periodic full detail, not every failed frame.

    Basic current corners/state/timings are always logged. Native/device errors
    using durable checkpoints bypass this sampler. A bounded shared ledger
    makes prepare/owner/retention choose the same detail for a frame.
    """
    mode,every,slow=_FRAME_POLICY.get();tracking=tracking or {}
    if mode=='detailed' or index==1 or index%every==0:return True
    state=_DETAIL_SAMPLE.get()
    if state is None:return False
    recovery=tracking.get('recovery_attempt',{})
    key=(tracking.get('mode'),tracking.get('tracking_state'),tracking.get('lk_trigger'),
        recovery.get('state'),recovery.get('last_stage'),wall>=slow)
    with state['lock']:
        cache_key=(index,key)
        if cache_key in state['decisions']:return state['decisions'][cache_key]
        previous=state['seen'].get(key);chosen=previous is None or index-previous>=max(every,60)
        if chosen:
            state['seen'][key]=index
            while len(state['seen'])>32:state['seen'].pop(next(iter(state['seen'])))
        state['decisions'][cache_key]=chosen
        while len(state['decisions'])>16:state['decisions'].pop(next(iter(state['decisions'])))
        return chosen

def native_os_sample(index):
    mode,every,_=_FRAME_POLICY.get()
    return mode=='detailed' or index==1 or index%every==0

def _scalars(value):
    return {k:v for k,v in value.items() if v is None or isinstance(v,(str,int,float,bool))}

def _compact_diagnostic(value):
    result=_scalars(value)
    result['native']={k:_scalars(v) for k,v in value.get('native',{}).items()}
    if 'os_thread_events' in value:result['os_thread_events']=_scalars(value['os_thread_events'])
    return result

_NORMAL_PHASES=frozenset(('FRAME_SOURCE_WAIT','FRAME_PS_BEGIN','FRAME_PS_READY','FRAME_BEGIN',
    'planner upload begin','planner exact scan done','planner import begin','planner import done'))

def frame_phase_enabled(stage):
    """Check before constructing a suppressed success-phase payload.

    Frame outcomes, current corners/timings and all error checkpoints remain
    recorded. This does not alter durable handling or throughput boundaries.
    """
    return _FRAME_POLICY.get()[0]=='detailed' or stage not in _NORMAL_PHASES


def _compact_stage_timings(value):
    # Keep every stage's wall, CPU and call count; derived wait can be rebuilt.
    # Full sampled/error rows retain the original nested diagnostic structure.
    keep=('wall_s','thread_cpu_s','calls')
    result={k:value[k] for k in ('wall_s','thread_cpu_s','exclusive_stages','accounting_residual_s') if k in value}
    result['stages']={name:{k:timing[k] for k in keep if k in timing}
        for name,timing in value.get('stages',{}).items()}
    return result

def _compact_record(stage,data):
    mode,every,slow=_FRAME_POLICY.get()
    if mode=='detailed':return data
    if stage in _NORMAL_PHASES:
        # Ordinary successful planning is queued, never serialized to console.
        return {k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    if stage=='GC_FRAME_BATCH':
        result=dict(data);result['events']=tuple(e for e in data.get('events',()) if e['wall_s']>=.002)
        return result
    if stage=='CAMERA_FRAME':
        tracking=data.get('tracking',{});index=data.get('index',0)
        if diagnostic_detail(index,max(data.get('ps_prepare_s',0.),data.get('owner_s',0.)),tracking):
            return dict(data,log_detail=True)
        result={k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
        result.update(log_detail=False,corners_used=data.get('corners_used',tracking.get('corners')),
            output_orientation=data.get('output_orientation',{}),
            tracking={k:tracking[k] for k in ('valid','mode','corners','confidence','lk_trigger','feature_count',
                'tracker_s','tracker_thread_cpu_s','lk_channel','gray_s','feature_update_s','lk_age_frames','gap_anchor_retained','reason','trigger','edge_gate',
                'tracking_state','recovery_confirmations','target_changed','color_boundary_continuity') if k in tracking},
            refresh={k:v for k,v in data.get('refresh',{}).items() if v is None or isinstance(v,(str,int,float,bool))})
        result['tracking']['recovery_attempt']=_scalars(tracking.get('recovery_attempt',{}))
        result['tracking']['same_target_recovery']=tracking.get('same_target_recovery')
        result['tracking']['current_proof_budget_ms']=tracking.get('current_proof_budget_ms')
        lk_budget=tracking.get('lk_timing',{}).get('entry_budget')
        if lk_budget:result['tracking']['lk_entry_budget']=_scalars(lk_budget)
        stable=tracking.get('stable_tracking_policy',{})
        if stable:result['tracking']['stable_tracking_policy']=_scalars(stable)
        proof=tracking.get('current_source_proof',{})
        if proof:
            result['tracking']['current_source_proof_summary']={k:proof[k] for k in
                ('verified','reason','admission_policy','admission_grade','source64_provenance_verified',
                 'independent_sampling_verified','stable_FB_support_tolerance','boundary_definition',
                 'min_support','max_rms','line_normal_difference','normal_limit',
                 'corner_difference','corner_limit','stable_FB_rms_limit',
                 'strict_new_candidate_support','strict_new_candidate_rms') if k in proof}
            timing=proof.get('current_proof_timing',{})
            result['tracking']['current_source_proof_summary']['timing']=_scalars(timing)
            result['tracking']['current_source_proof_summary']['physical_layer_continuity']=_scalars(timing.get('physical_layer_continuity',{}))
        result['tracking']['local_recovery']=_scalars(tracking.get('edge_recovery',{}))
        edge=tracking.get('edge_evidence',{})
        result['tracking']['physical_peak_lock']=edge.get('physical_peak_lock')
        result['tracking']['peak_lock_radius_source']=edge.get('peak_lock_radius_source')
        result['tracking']['signed_peak_lock']=edge.get('signed_peak_lock')
        gate=tracking.get('edge_gate',{})
        result['tracking'].update(min_edge_support=gate.get('min_support'),max_edge_rms=gate.get('max_rms'),
            feature_action=tracking.get('feature_detail',{}).get('action'),
            gap_anchor_action=tracking.get('edge_recovery',{}).get('anchor_action'),
            gap_anchor_guard_s=tracking.get('edge_recovery',{}).get('anchor_guard_s'),
            lk_max_gap=tracking.get('lk_max_gap'),
            edge_backend=tracking.get('edge_evidence',{}).get('edge_backend'),
            boundary_fallback_s=tracking.get('edge_evidence',{}).get('boundary_fallback_s',0.),
            boundary_fallback_thread_cpu_s=tracking.get('edge_evidence',{}).get('boundary_fallback_thread_cpu_s',0.))
        # All per-stage wall/CPU samples remain available for comparable summaries.
        for key in ('owner_stages','prepare_stages'):
            if key in data:result[key]=_compact_stage_timings(data[key])
        for key in ('owner_diagnostics','prepare_diagnostics'):
            if key in data:result[key]=_compact_diagnostic(data[key])
        result['parallel_plan']={k:(data.get('parallel_plan') or {}).get(k) for k in
            ('sequence','peak_rows','capacity_rows','receiver_acknowledged','imported_fields','imported_rows')}
        return result
    if stage=='DOCUMENT_DETECTION_FAILED' and mode=='compact':
        # The enclosing CAMERA_FRAME samples the full diagnostic tree. This
        # low-level repeated event carries an explicit rejection summary.
        result=_scalars(data);result.update(diagnostic_detail_deferred_to_camera_frame=True,
            candidate_rejection_count=len(data.get('rejected_candidates',()) or ()))
        return result
    if stage not in ('FRAME_DONE','FRAME_SKIPPED'):return data
    tracking=data.get('tracking',{});index=data.get('index',0)
    if (diagnostic_detail(index,data.get('bgr_latency_s',0.),tracking)
        or data.get('refresh',{}).get('surface_updated') or data.get('refresh',{}).get('light_updated')):
        return dict(data,log_detail=True)
    # One complete timing row, scalar state and current measured corners. Native
    # aggregates survive; result retention separately uses the same sampling policy.
    result={k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    result.update(log_detail=False,corners_used=data.get('corners_used'),
        tracking=dict(mode=tracking.get('mode'),valid=tracking.get('valid'),
            confidence=tracking.get('confidence'),lk_trigger=tracking.get('lk_trigger'),
            feature_count=tracking.get('feature_count'),feature_seed_count=tracking.get('feature_seed_count'),
            min_edge_support=tracking.get('edge_gate',{}).get('min_support'),
            max_edge_rms=tracking.get('edge_gate',{}).get('max_rms')),
        refresh={k:v for k,v in data.get('refresh',{}).items() if k in ('surface_updated','light_updated','full_observation','appearance_backend')},
        parallel_plan={k:(data.get('parallel_plan') or {}).get(k) for k in
            ('sequence','peak_rows','capacity_rows','scan_cycles','hardware_overlap_cycles',
             'receiver_acknowledged','imported_fields','imported_rows','early_control_published_at',
             'early_control_submit_delay_s','submitted_at','completed_at')})
    return result

def frame_record(stage,durable=False,**data):
    active=_ACTIVE_FILE.get()
    if active is None:raise RuntimeError('frame_record needs an active logged_run')
    selected=data if durable else _compact_record(stage,data)
    if selected is None:return
    active.record(dict(time=datetime.datetime.now().astimezone().isoformat(),stage=stage,**selected))
    if durable:active.barrier(True)

_ORDINARY_PLANNING=frozenset(('planner upload begin','planner exact scan done','planner import begin',
    'planner import done','plan candidate begin','plan candidate ready'))
_CONSOLE_MILESTONES=frozenset(('RUN_BEGIN','RUN_COMPLETED','RUN_FAILED','CAMERA_PROGRESS','CAMERA_SUMMARY',
    'NATIVE_READY','CAMERA_READY','CAMERA_SEQUENCE_READY','LIVE_PREVIEW_READY','CAMERA_FIRST_FRAME_VERIFY'))

def _console_payload(stage,data):
    if stage=='CAMERA_SUMMARY':
        return {k:data[k] for k in ('release_id','frames','delivered','lost','live_delivered_fps',
            'ps_prepare','owner','raw_ready_latency','driver_input_latency','preview','run_log_path','status') if k in data}
    if stage=='CAMERA_PROGRESS':
        camera=data.get('camera',{})
        return dict(index=data.get('index'),total=data.get('total'),delivered=data.get('delivered'),
            capture_frames=camera.get('capture_frames'),queue_drops=camera.get('latest_queue_drops'))
    if stage in ('NATIVE_READY','CAMERA_READY','CAMERA_SEQUENCE_READY','LIVE_PREVIEW_READY','RUN_BEGIN'):
        return {k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    return data

def checkpoint(stage,durable=False,**data):
    #   ⭐ 2026-10-29：**PC 侧主机测试必须能关掉写盘**。
    #      `RUN_LOG` 是【模块所在目录】的 `run-result.log`，不是 CWD ——
    #      所以只要 import 了本包的 run_logging，单测就会把事件写进
    #      **随包发布的那个 run-result.log**，然后被打进 zip 传到板上。
    #      现场就出过：板上日志开头 11 条 `CAMERA_PROFILE_*` 全是 PC 单测的，
    #      差点被当成"板子跑了新功能"。
    #      ⇒ 单测跑 `P11_TEST_NO_LOG=1`，checkpoint 直接变 no-op。
    if os.environ.get('P11_TEST_NO_LOG')=='1':return
    # ACK/row proofs are retained in file records. Only normal successful plan
    # events lose their fsync; startup checkpoints and errors remain durable.
    if stage in _ORDINARY_PLANNING:durable=False
    active=_ACTIVE_FILE.get()
    if active:frame_record(stage,durable=durable,**data)
    else:
        writer=_Writer()
        try:
            writer.record(dict(time=datetime.datetime.now().astimezone().isoformat(),stage=stage,**data))
            writer.barrier(durable)
        finally:writer.close()
    if not _CONSOLE_ENABLED.get():return
    error=any(word in stage.lower() for word in ('fail','error','timeout','lost'))
    if stage in _ORDINARY_PLANNING:return
    if _FRAME_POLICY.get()[0]=='compact' and stage not in _CONSOLE_MILESTONES and not error:return
    stream=sys.stdout.console if isinstance(sys.stdout,_Tee) else sys.stdout
    payload=_console_payload(stage,data) if _FRAME_POLICY.get()[0]=='compact' or stage in _CONSOLE_MILESTONES else data
    stream.write(stage+' '+json.dumps(payload,ensure_ascii=False,default=_json_default)+'\n');stream.flush()

def gc_summary(events):
    return dict(count=len(events),wall_s=sum(e['wall_s'] for e in events),
        thread_cpu_s=sum(e.get('thread_cpu_s',0.) for e in events),
        max_s=max((e['wall_s'] for e in events),default=0.),
        first_number=events[0]['number'] if events else None,last_number=events[-1]['number'] if events else None)

def log_gc_batch(stage,after,**metadata):
    """One incremental record, never one queue entry per GC event."""
    events=gc_records(after)
    if events:frame_record(stage,summary=gc_summary(events),events=events,retention=gc_retention(after),**metadata)
    return events[-1]['number'] if events else after

def _log_metadata_target(result):
    """Attach run details to a result dict or the metadata in (image, dict)."""
    if isinstance(result,dict):return result
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict):
        return result[1]
    return None


def logged_run(function):
    signature=inspect.signature(function)
    @wraps(function)
    def wrapped(*args,**kwargs):
        if not _BUSY.acquire(blocking=False):raise RuntimeError('同一内核已有PL任务运行')
        token=file_token=None;writer=None;began=time.perf_counter()
        result=None;result_metadata=None
        try:
            crash_info=install_crash_capture()
            gc_before=gc_cursor();enable_gc()
            bound=signature.bind_partial(*args,**kwargs);bound.apply_defaults()
            run_id=f'{os.getpid()}_{time.time_ns()}'
            metadata=dict(run_id=run_id,run_log_path=str(RUN_LOG),run_log_dir=str(RUN_LOG.parent),
                working_directory=str(Path.cwd()),gc_begin_number=gc_before)
            token=_CURRENT.set(metadata);writer=_Writer();file_token=_ACTIVE_FILE.set(writer)
            with redirect_stdout(_Tee(sys.stdout,writer)),redirect_stderr(_Tee(sys.stderr,writer)):
                checkpoint('RUN_BEGIN',durable=True,release_id=RELEASE_ID,run_id=run_id,parameters=dict(bound.arguments))
                checkpoint('CRASH_CAPTURE_READY',durable=True,**crash_info)
                try:
                    result=function(*args,**kwargs)
                    result_metadata=_log_metadata_target(result)
                except BaseException as exc:
                    try:
                        events=gc_records(gc_before)
                        frame_record('GC_FAILURE_BATCH',summary=gc_summary(events),events=events,retention=gc_retention(gc_before))
                        checkpoint('RUN_FAILED',durable=True,run_id=run_id,exception_type=type(exc).__name__,
                            exception=str(exc),logging=writer.snapshot(),gc_summary=gc_summary(events))
                        writer.write(traceback.format_exc());writer.barrier(True)
                    except BaseException as log_error:_stderr_notice('日志失败，保留原始异常：'+repr(log_error)+'\n')
                    raise
                events=gc_records(gc_before)
                frame_record('GC_RUN_SUMMARY',summary=gc_summary(events),retention=gc_retention(gc_before))
                writer.barrier(False)
                checkpoint('LOG_WRITER_SUMMARY',scope='through_summary_barrier_before_final_close',
                    metrics=writer.snapshot(),gc_events=len(events),slow_io_events=list(writer.io_events),
                    slow_io_events_dropped=writer.io_events_dropped)
                if result_metadata is not None:
                    result_metadata.update(metadata,logging=writer.snapshot(),gc_events=events,
                        log_io_events=list(writer.io_events))
                checkpoint('RUN_COMPLETED',durable=True,run_id=run_id,elapsed_wall_s=time.perf_counter()-began,
                    status=result_metadata.get('status','completed') if result_metadata is not None else 'completed')
                if result_metadata is not None:result_metadata['call_wall_s']=time.perf_counter()-began
                return result
        finally:
            try:
                original_error=sys.exc_info()[0] is not None
                if writer:
                    try:writer.close()
                    except BaseException as close_error:
                        if not original_error:raise
                        _stderr_notice('日志关闭失败，保留原始异常：'+repr(close_error)+'\n')
                if result_metadata is not None:
                    try:
                        result_metadata['call_wall_s']=time.perf_counter()-began
                        if writer is not None:
                            result_metadata['logging']=writer.snapshot()
                            result_metadata['log_io_events']=list(writer.io_events)
                    except BaseException as metadata_error:
                        if not original_error:raise
                        _stderr_notice('日志元数据收尾失败，保留原始异常：'+repr(metadata_error)+'\n')
            finally:
                disable_gc()
                if file_token is not None:_ACTIVE_FILE.reset(file_token)
                if token is not None:_CURRENT.reset(token)
                _BUSY.release()
    return wrapped


def retained_camera_row(data):
    return _compact_record('CAMERA_FRAME',data)


def retained_frame_row(data,policy='sampled'):
    """Keep every timing/id/corner; retain full trees only for sampled/errors."""
    if policy=='all':return data
    if policy!='sampled':raise ValueError('retain_details须为sampled/all')
    out=_compact_record('FRAME_DONE' if data['delivered'] else 'FRAME_SKIPPED',data)
    if out.get('log_detail'):return out
    # Summary counters need these small records, not a repeated native/GC tree.
    tracking=dict(out['tracking']);original=data.get('tracking',{})
    tracking['trigger']=original.get('trigger')
    tracking['gray_detail']={k:v for k,v in original.get('gray_detail',{}).items() if k in ('backend','blur_backend','transaction_backend','output_pool_reused','edge_error')}
    tracking['feature_detail']={k:v for k,v in original.get('feature_detail',{}).items() if k=='action'}
    out['tracking']=tracking
    detail=data.get('plan_detail',{}) or {}
    out['plan_detail']={k:int(detail.get(k) or 0) for k in ('tone_cache_hits','tone_cache_misses')}
    out['plan_detail'].update({k:detail[k] for k in ('geometry_backend','control_encode_backend') if k in detail})
    return out

@contextmanager
def console_output_scope(enabled=False):
    token=_CONSOLE_ENABLED.set(bool(enabled))
    try:yield
    finally:_CONSOLE_ENABLED.reset(token)

@contextmanager
def file_only_output():
    """Notebook setup/helper output to the same file; no device work is hidden."""
    writer=_Writer();token=_ACTIVE_FILE.set(writer)
    try:
        with console_output_scope(False),redirect_stdout(_Tee(sys.stdout,writer)),redirect_stderr(_Tee(sys.stderr,writer)):
            try:yield
            except BaseException:
                writer.write(traceback.format_exc());writer.barrier(True);raise
    finally:
        _ACTIVE_FILE.reset(token);writer.close()


# ======================================================================
# ===== [03/08] v31_crash =====
# ======================================================================


"""Fatal signal stacks and bounded startup breadcrumbs in run-result.log.

Fatal handlers write directly to a pinned append descriptor, bypassing the
Python logger queue. SIGKILL/OOM cannot be intercepted; inspect dmesg for those.
"""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FILE=None
_LOCK=threading.Lock()


def install_crash_capture():
    global _FILE
    with _LOCK:
        if _FILE is None:
            _FILE=(Path(__file__).resolve().parent/'run-result.log').open('ab',buffering=0)
        # Keep this descriptor open for the entire kernel lifetime. Re-enable
        # explicitly if another library changed the signal handler meanwhile.
        faulthandler.enable(file=_FILE,all_threads=True)
        return dict(pid=os.getpid(),enabled=faulthandler.is_enabled(),
            log_file=str(Path(__file__).resolve().parent/'run-result.log'),
            caught_signals=['SIGSEGV','SIGBUS','SIGABRT','SIGFPE','SIGILL'],
            sigkill_oom_captured=False,scope='kernel_lifetime_pinned_append_fd',
            startup_trace_scope='first frame; warmup if warmup_frames>=1')


def startup_stage(stage,index,**data):
    # Deliberately only the first frame. No per-pixel logging or formal-stream
    # fsync loop. With zero warmup this diagnostic overhead is measured.
    if int(index or 0)!=1:return
    checkpoint('STARTUP_'+stage,durable=True,index=1,pid=os.getpid(),
        thread_id=threading.get_ident(),**data)


# ======================================================================
# ===== [04/08] v31_diagnostics =====
# ======================================================================


"""Wall/OS-thread CPU and GC evidence; no MMIO and no callbacks doing I/O."""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DIAGNOSTICS_PATCH='v30-diagnostics-thread-os-20261005-1'
_OS_FIELDS=('voluntary_context_switches','involuntary_context_switches','minor_page_faults','major_page_faults')
_NATIVE_NAMES=('p11_lk_anchor', 'p11_lk_track', 'p11_lk_promote', 'p11_gray2', 'p11_gaussian3', 'p11_quad_valid', 'p11_spatial', 'p11_lk_filter', 'p11_edges', 'p11_guard', 'p11_plan_geometry', 'p11_prepare', 'p11_packet', 'p11_signature', 'p11_prepare_control', 'p11_probe', 'p11_wait_io', 'p11_observe2', 'p11_edges_motion', 'p11_copy_bgr', 'p11_arm_io', 'p11_plan_wait', 'p11_frame_state', 'p11_motion_values', 'outer_calls', 'p11_observe_edges', 'p11_lk_checked', 'p11_roi_features', 'p11_owner_batch', 'p11_owner_complete')
# Only these native scopes instrument OS counters in the existing C++ ABI.
_NATIVE_OS_INDICES=(1,7,17,18,24,25,26,27,28,29)
_LOCAL=threading.local();_EVENTS=deque(maxlen=4096);_GC_START={};_NUMBER=0
def _callback(action,info):
 global _NUMBER
 ident=threading.get_ident();now=time.perf_counter();cpu=time.thread_time()
 if action=='start':_GC_START[ident]=(now,cpu,getattr(_LOCAL,'phase',None),info.get('generation'))
 else:
  begin=_GC_START.pop(ident,None)
  if begin:
   _NUMBER+=1;_EVENTS.append(dict(number=_NUMBER,begin=begin[0],end=now,wall_s=now-begin[0],thread_cpu_s=cpu-begin[1],thread_id=ident,phase=begin[2],generation=begin[3],collected=info.get('collected'),uncollectable=info.get('uncollectable')))
def enable_gc():
 if _callback not in gc.callbacks:gc.callbacks.append(_callback)
def disable_gc():
 if _callback in gc.callbacks:gc.callbacks.remove(_callback)
 _GC_START.clear()
def gc_cursor():return _NUMBER

def gc_records(after=0):
 # Per-frame callers need only new events. Do not rebuild all historical
 # dictionaries on every frame or the diagnostic itself can trigger GC.
 if after>=_NUMBER:return []
 events=[]
 for event in reversed(list(_EVENTS)):
  if event['number']<=after:break
  events.append(dict(event))
 events.reverse();return events

def gc_retention(after=0):
 snapshot=list(_EVENTS)
 first=snapshot[0]['number'] if snapshot else _NUMBER+1
 return dict(cursor=_NUMBER,capacity=_EVENTS.maxlen,unavailable_since_cursor=max(0,first-after-1))
def _diagnostic_workspace(reuse=True):
 """Separate pre/post snapshots per OS thread; nested calls use private buffers."""
 import numpy as np
 cached=getattr(_LOCAL,'snapshot_workspace',None) if reuse else None
 if cached is None:
  cached=dict(native_before=np.empty(90,np.float64),native_after=np.empty(90,np.float64),
   native_delta=np.empty(90,np.float64),os_before=np.empty((30,4),np.float64),
   os_after=np.empty((30,4),np.float64),os_delta=np.empty((30,4),np.float64))
  if reuse:_LOCAL.snapshot_workspace=cached
 return cached

def _native(out=None):
 from tracking import profile_snapshot__v31_native as profile_snapshot
 return profile_snapshot(raw=True,out=out)
def delta(after,before,detailed=True,scratch=None):
 if after is None:return {}
 import numpy as np
 old=np.zeros_like(after) if before is None else before
 if scratch is None:raw=np.maximum(0.,after-old).reshape(-1,3)
 else:
  np.subtract(after,old,out=scratch);np.maximum(scratch,0.,out=scratch);raw=scratch.reshape(-1,3)
 indices=range(len(_NATIVE_NAMES)) if detailed else (24,)
 return {_NATIVE_NAMES[i]:dict(wall_s=float(raw[i,0]),thread_cpu_s=float(raw[i,1]),calls=int(raw[i,2]))
         for i in indices if raw[i,2]>0}

def _thread_usage():
 try:
  import resource
  u=resource.getrusage(resource.RUSAGE_THREAD)
  return (u.ru_nvcsw,u.ru_nivcsw,u.ru_minflt,u.ru_majflt)
 except (ImportError,AttributeError,OSError):return None

def _native_os(out=None):
 from tracking import profile_os_snapshot__v31_native as profile_os_snapshot
 return profile_os_snapshot(out=out)

def _usage_delta(after,before):
 """Difference of cumulative counters; unavailable data stays unavailable."""
 if after is None or before is None:return {}
 return {name:max(0,int(a)-int(b)) for name,a,b in zip(_OS_FIELDS,after,before)}

def _native_os_delta(after,before,detailed=True,scratch=None):
 if after is None or before is None:return {}
 import numpy as np
 after=np.asarray(after);before=np.asarray(before)
 expected=(len(_NATIVE_NAMES),len(_OS_FIELDS))
 if after.shape!=expected or before.shape!=expected:
  raise ValueError('Native OS profile layout mismatch')
 if scratch is None:raw=np.maximum(0.,after-before)
 else:
  np.subtract(after,before,out=scratch);np.maximum(scratch,0.,out=scratch);raw=scratch
 indices=_NATIVE_OS_INDICES if detailed else (24,)
 return {_NATIVE_NAMES[i]:{name:int(raw[i,j]) for j,name in enumerate(_OS_FIELDS)}
         for i in indices}

def measured(method):
 """Keep diagnostic overhead inside the existing PS/owner timing boundaries."""
 @wraps(method)
 def wrap(self,*args,**kwargs):
  previous_phase=getattr(_LOCAL,'phase',None);_LOCAL.phase=method.__name__
  depth=getattr(_LOCAL,'diagnostic_depth',0);_LOCAL.diagnostic_depth=depth+1
  begin=time.perf_counter();cpu=time.thread_time();event_cursor=gc_cursor()
  native=usage=native_os=None
  try:
   workspace=_diagnostic_workspace(reuse=depth==0)
   call_index=(args[1] if len(args)>1 else kwargs.get('index',1)) if method.__name__=='prepare_bgr' else args[0].index
   sample_os=native_os_sample(call_index)
   native=_native(workspace['native_before']);usage=_thread_usage()
   native_os=_native_os(workspace['os_before']) if sample_os else None
   value=method(self,*args,**kwargs)
   end=time.perf_counter();used=time.thread_time()-cpu
   if method.__name__=='prepare_bgr':index=value.index;tracking=value.record.get('tracking',{})
   else:index=args[0].index;tracking=value[1].get('tracking',{})
   detailed=diagnostic_detail(index,end-begin,tracking)
   nd=delta(_native(workspace['native_after']),native,detailed=detailed,scratch=workspace['native_delta'])
   usage_after=_thread_usage();native_os_after=_native_os(workspace['os_after']) if sample_os else None
   thread_os=_usage_delta(usage_after,usage)
   native_events=_native_os_delta(native_os_after,native_os,detailed=detailed,scratch=workspace['os_delta'])
   for name,metrics in nd.items():
    if name in native_events:metrics['os_thread_events']=native_events[name]
   events=[e for e in gc_records(event_cursor) if e['end']>=begin and e['begin']<=end]
   detail=dict(diagnostics_patch=DIAGNOSTICS_PATCH,os_thread_events=thread_os,os_thread_events_available=usage is not None and usage_after is not None,native_os_events_available=native_os is not None and native_os_after is not None,native_os_scope='per-function OS snapshots sampled first/periodic frames; wall/native/OS-thread CPU counters retained each frame',wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),thread_id=threading.get_ident(),native=nd,native_function_times_are_inclusive=True,native_details_sampled=detailed,gc_overlap_s=sum(max(0.,min(end,e['end'])-max(begin,e['begin'])) for e in events),gc_events=len(events))
   outer=nd.get('outer_calls',{})
   detail.update(native_wall_s=outer.get('wall_s',0.),native_thread_cpu_s=outer.get('thread_cpu_s',0.),python_thread_cpu_estimate_s=max(0.,used-outer.get('thread_cpu_s',0.)),outside_native_wall_minus_cpu_s=max(0.,end-begin-used-outer.get('wall_s',0.)+outer.get('thread_cpu_s',0.)))
   # Keep the main diagnostic assembly cost in the phase and report it.
   tail_begin=end;end=time.perf_counter();used=time.thread_time()-cpu
   detail.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),diagnostic_tail_s=end-tail_begin,
    python_thread_cpu_estimate_s=max(0.,used-outer.get('thread_cpu_s',0.)),outside_native_wall_minus_cpu_s=max(0.,end-begin-used-outer.get('wall_s',0.)+outer.get('thread_cpu_s',0.)))
   clock=getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None)
   partition=clock.report(begin,cpu,end,cpu+used) if clock is not None and clock.end is not None else {}
   # Partition assembly is diagnostic work, included in the same service scope.
   end=time.perf_counter();used=time.thread_time()-cpu
   detail.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),diagnostic_tail_s=end-tail_begin)
   if partition:
    tail=partition['stages']['diagnostic_after']
    tail.update(wall_s=max(0.,end-clock.end),thread_cpu_s=max(0.,cpu+used-clock.cpu_end))
    tail['wall_minus_thread_cpu_s']=max(0.,tail['wall_s']-tail['thread_cpu_s'])
    partition.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),
     accounting_residual_s=end-begin-sum(v['wall_s'] for v in partition['stages'].values()))
   if method.__name__=='prepare_bgr':
    record=dict(value.record);record['prepare_diagnostics']=detail;record['prepare_stages']=partition
    return replace(value,record=MappingProxyType(record),begin=begin,ready=end)
   lease,record=value;record['owner_diagnostics']=detail;record['owner_stages']=partition
   record.update(hardware_begin=begin,hardware_end=end,hardware_owner_s=end-begin,bgr_service_s=record['ps_prepare_s']+end-begin,bgr_latency_s=end-record['ps_prepare_begin'],prepared_queue_s=max(0.,begin-record['ps_prepare_end']))
   return lease,record
  except BaseException as error:
   # Failed native calls still have useful CPU/wall evidence. Logging must
   # never replace the original computation/hardware exception.
   try:
    if current_log_metadata():
     frame_record('PHASE_FAILED',durable=True,phase=method.__name__,thread_id=threading.get_ident(),diagnostics_patch=DIAGNOSTICS_PATCH,
      os_thread_events=_usage_delta(_thread_usage(),usage),native_os_events=_native_os_delta(_native_os(),native_os),
      wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,native=delta(_native(),native),
      gc_events=gc_records(event_cursor),exception_type=type(error).__name__,exception=str(error),
      partial_phase_stages=(getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None).stages
          if getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None) is not None else {}),
      prepare_stage=dict(getattr(self,'_last_prepare_stage',{})))
   except BaseException:pass
   raise
  finally:
   _LOCAL.phase=previous_phase;_LOCAL.diagnostic_depth=depth
 return wrap


# ======================================================================
# ===== [05/08] v31_gc_budget =====
# ======================================================================


"""Owner-scoped, bounded GC pause; always restore the process' prior state."""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def memory_state():
    try:
        values={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemAvailable','SwapFree','SwapTotal')}
        status=Path('/proc/self/status').read_text().splitlines()
        values.update({k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in status if ':' in line) if k in ('VmRSS','VmSwap')})
        return values
    except (OSError,ValueError):return {}

class GcBudget:
    def __init__(self,policy='bounded',max_frames=240,max_seconds=30.,growth_mb=24):
        if policy not in ('normal','bounded'):raise ValueError('gc_policy须为normal/bounded')
        if isinstance(max_frames,bool) or not isinstance(max_frames,int) or not 1<=max_frames<=1000:raise ValueError('gc_max_frames须为1..1000')
        if not 1.<=float(max_seconds)<=60. or not 4<=growth_mb<=64:raise ValueError('GC duration/growth budget invalid')
        self.policy=policy;self.max_frames=max_frames;self.max_seconds=float(max_seconds);self.growth_bytes=int(growth_mb)*1024*1024
        self.original=gc.isenabled();self.paused=False;self.reason=None;self.closed=False;self.frames=0
        self.start=time.perf_counter();self.start_count=gc.get_count()[0];self.initial=memory_state()
        self.startup_collect_s=0.;self.resume_at=None;self.pause_started=None
    def __enter__(self):
        if self.policy=='bounded' and self.original and self.initial.get('MemAvailable',0)>=96*1024*1024:
            began=time.perf_counter();gc.collect(2);self.startup_collect_s=time.perf_counter()-began
            self.initial=memory_state()
            if self.initial.get('MemAvailable',0)>=96*1024*1024:
                gc.disable();self.paused=True
        self.start=time.perf_counter();self.start_count=gc.get_count()[0]
        if self.paused:self.pause_started=self.start
        try:
            checkpoint('GC_BUDGET_BEGIN',policy=self.policy,paused=self.paused,prior_enabled=self.original,
                max_frames=self.max_frames,max_seconds=self.max_seconds,growth_bytes=self.growth_bytes,
                startup_collect_s=self.startup_collect_s,memory=self.initial,outside_frame_measurement=True)
        except BaseException:
            if self.original:gc.enable()
            else:gc.disable()
            self.paused=False;raise
        return self
    def check(self,index):
        if not self.paused:return
        self.frames+=1;reason=None;memory={}
        if self.frames>=self.max_frames:reason='frame_limit'
        elif time.perf_counter()-self.start>=self.max_seconds:reason='time_limit'
        elif gc.get_count()[0]-self.start_count>50000:reason='allocation_count_limit'
        if index%8==0 or reason:
            memory=memory_state()
            if memory.get('MemAvailable',0)<64*1024*1024:reason='available_memory_low'
            elif memory.get('VmRSS',0)-self.initial.get('VmRSS',0)>self.growth_bytes:reason='rss_growth_limit'
            elif memory.get('VmSwap',0)>self.initial.get('VmSwap',0)+1024*1024:reason='process_swap_growth'
        if reason:
            gc.enable();self.paused=False;self.reason=reason;self.resume_at=time.perf_counter()
            checkpoint('GC_BUDGET_RESTORED',index=index,reason=reason,memory=memory,
                measured_pause_s=self.resume_at-self.start,automatic_gc_enabled=True)
    def summary(self):
        return dict(policy=self.policy,prior_enabled=self.original,frames_checked=self.frames,
            pause_s=(self.resume_at or time.perf_counter())-self.pause_started if self.pause_started is not None else 0.,
            restored_early_reason=self.reason,startup_collect_s=self.startup_collect_s,memory=memory_state())
    def __exit__(self,*error):
        # ExitStack closes CPU/loader workers before restoring GC.
        if self.original:gc.enable()
        else:gc.disable()
        self.paused=False;self.closed=True
        return False


# ======================================================================
# ===== [06/08] v31_pixels =====
# ======================================================================


"""Explicit packed YUYV contract; no implicit BGR or MJPEG admission."""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MODE=0
_LUT=np.array([(min(219,max(0,x-16))*255+109)//219 for x in range(256)],np.uint8)
def set_color_mode(mode):
    global _MODE
    if isinstance(mode,bool) or mode not in (0,1,2,3):raise ValueError('YUYV CSC mode must be 0..3')
    _MODE=int(mode)
def color_mode():return _MODE
def require_yuyv(image):
    if (not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or image.ndim!=3
        or image.shape[2]!=2 or image.shape[1]%2 or image.strides[1:]!=(2,1)
        or image.strides[0]<image.shape[1]*2):raise ValueError('Expected even-width uint8 HxWx2 packed YUYV')
    return image
def luminance(image):
    require_yuyv(image); y=image[:,:,0]
    return y if _MODE&1 else _LUT[y]
def gray_half(image,out):
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or out.shape!=(h//2,w//2):raise ValueError('Y area2 layout')
    y=image[:,:,0].astype(np.uint16)
    value=((y[0::2,0::2]+y[0::2,1::2]+y[1::2,0::2]+y[1::2,1::2]+2)>>2).astype(np.uint8)
    out[:]=value if _MODE&1 else _LUT[value]
    return out
def model_bgr(image):
    """Only startup/reacquisition/model refresh. Ordinary tracking uses Y."""
    if image.shape[2]==3:return image
    require_yuyv(image)
    from tracking import yuyv_model_bgr__v31_native as yuyv_model_bgr
    native=yuyv_model_bgr(image,_MODE)
    if native is not None:return native
    h,w=image.shape[:2];pairs=image.reshape(h,w//2,4) if image.flags.c_contiguous else np.ascontiguousarray(image).reshape(h,w//2,4)
    y=image[:,:,0].astype(np.int32)
    u=np.repeat(pairs[:,:,1].astype(np.int32)-128,2,axis=1)
    v=np.repeat(pairs[:,:,3].astype(np.int32)-128,2,axis=1)
    coeff=((298,409,100,208,516),(256,359,88,183,454),(298,459,55,136,541),(256,403,48,120,475))[_MODE]
    c=y if _MODE&1 else np.maximum(y-16,0);cy,rv,gu,gv,bu=coeff
    rgb=(cy*c+bu*u,cy*c-gu*u-gv*v,cy*c+rv*v)
    return np.stack([np.clip((a+128)>>8,0,255).astype(np.uint8) for a in rgb],axis=2)
def copy_input(source,destination):
    require_yuyv(source);require_yuyv(destination)
    if source.shape!=destination.shape:raise ValueError('YUYV copy shape mismatch')
    from tracking import copy_yuyv_native__v31_native as copy_yuyv_native
    if copy_yuyv_native(source,destination):return 'cpp_yuyv_memcpy'
    np.copyto(destination,source);return 'numpy_yuyv_copy'


# ======================================================================
# ===== [07/08] v84_prebuilt =====
# ======================================================================


"""Verified CPU-only artifacts, portable receipts and optional board export."""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ENV=None


def environment():
    global _ENV
    if _ENV is None:
        import cv2
        _ENV=dict(system=platform.system(),architecture=platform.machine(),
            pointer_bits=struct.calcsize('P')*8,byteorder=sys.byteorder,
            libc=list(platform.libc_ver()),opencv_version=cv2.__version__)
    return dict(_ENV)


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise ValueError('CPU artifact receipt too large')
    return json.loads(path.read_text(encoding='utf-8'))


def _receipt(target):return Path(target).parent/'.native_receipts'/(Path(target).name+'.json')


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+str(os.getpid())+'.'+str(time.time_ns())+'.tmp')
    try:
        temporary.write_text(json.dumps(value,sort_keys=True)+'\n',encoding='utf-8')
        os.replace(str(temporary),str(path))
    finally:
        if temporary.exists():temporary.unlink()


def check_local(target,spec):
    """A newly distributed local artifact needs a full source/recipe/hash receipt."""
    target=Path(target)
    try:
        meta=_read(_receipt(target))
        return (meta.get('schema')==1 and meta.get('spec')==spec
            and meta.get('environment')==environment()
            and meta.get('artifact_sha256')==_hash(target))
    except (OSError,ValueError,TypeError):return False


def remember_local(target,spec):
    """Called only after the original loader has checked and bound its ABI."""
    meta=dict(schema=1,spec=spec,environment=environment(),artifact_sha256=_hash(target),
        created_by_release=RELEASE_ID,abi_checked=True)
    try:_write(_receipt(target),meta)
    except OSError as exc:checkpoint('CPU_NATIVE_LOCAL_RECEIPT_FAILED',family=spec['family'],exception=str(exc))
    return meta


def restore_pack(target,spec,cancel=None):
    """Only import declared same-environment binaries; no device operation."""
    from tracking import check_cancel as check_cancel
    from tracking import _probe as _probe; from tracking import _copy_atomic as _copy_atomic
    target=Path(target);folder=target.parent/'native_prebuilt';manifest=folder/'manifest.json'
    if not manifest.is_file():return False
    try:
        pack=_read(manifest)
        if pack.get('schema')!=1 or pack.get('environment')!=environment():
            raise ValueError('Prebuilt environment mismatch')
        entries=pack.get('artifacts',[])
        if not isinstance(entries,list) or len(entries)>12:raise ValueError('Invalid prebuilt inventory')
        selected=next((x for x in entries if x.get('spec')==spec),None)
        if selected is None:return False
        name=spec['target_name']
        if Path(name).name!=name or name in ('.','..'):raise ValueError('Invalid CPU artifact basename')
        artifact=folder/name
        if artifact.resolve().parent!=folder.resolve():raise ValueError('CPU artifact escapes prebuilt directory')
        check_cancel(cancel)
        if selected.get('artifact_sha256')!=_hash(artifact):raise ValueError('Prebuilt binary SHA256 mismatch')
        _probe(artifact,spec['family']);check_cancel(cancel);_copy_atomic(artifact,target)
        remember_local(target,spec)
        checkpoint('CPU_PREBUILT_LOADED',family=spec['family'],path=str(target),
            source_sha256=spec['source_sha256'],artifact_sha256=selected['artifact_sha256'],
            abi=spec['abi'],compiler_invoked=False,hardware_access=False)
        return True
    except (OSError,ValueError,TypeError,AttributeError) as exc:
        checkpoint('CPU_PREBUILT_REJECTED',family=spec['family'],exception=str(exc),fallback='verified shared or reviewed sibling cache')
        return False


def export_native_bundle(output=None):
    """Board-side preparation/export only. Does not open camera or download PL."""
    root=Path(__file__).resolve().parent
    verify_package(str(root/'system.bit'))
    from display import prepare_io as prepare_io
    from tracking import prepare_native__v31_native as prepare_native
    from tracking import prepare_native__v87_v74_native as prepare_v74
    from display import _library__v31_camera as _library
    from tracking import prepare_transactions as prepare_transactions
    from tracking import _probe as _probe
    io=prepare_io();tracker=prepare_native(required=True);v74=prepare_v74(required=True);capture=_library()
    transactions=prepare_transactions(required=True)
    artifacts=[];paths=[]
    for family,path in (('io',io._name),('tracker',tracker['path']),('tracker',v74['path']),('capture',capture._name),
                        ('transaction',transactions._name)):
        path=Path(path).resolve()
        if path.parent!=root:raise ValueError('CPU library was not loaded from this release')
        meta=_read(_receipt(path));spec=meta.get('spec',{})
        if spec.get('family')!=family or not check_local(path,spec):raise ValueError('CPU library export receipt mismatch')
        _probe(path,family);paths.append(path)
        artifacts.append(dict(spec=spec,artifact_sha256=_hash(path)))
    manifest=dict(schema=1,environment=environment(),artifacts=artifacts,created_by_release=RELEASE_ID,
        purpose='CPU-only helpers; no hardware/model/frame data')
    output=Path(output).expanduser().resolve() if output is not None else root/('p11_native_bundle_'+platform.machine()+'.zip')
    temporary=output.with_name(output.name+'.'+str(os.getpid())+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('native_prebuilt/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            for path in paths:archive.write(path,'native_prebuilt/'+path.name)
        os.replace(str(temporary),str(output))
    finally:
        if temporary.exists():temporary.unlink()
    checkpoint('CPU_PREBUILT_EXPORTED',path=str(output),artifacts=len(paths),hardware_access=False)
    return str(output)


def export_ready_upload(output=None):
    """Repackage declared release files plus verified CPU artifacts on the board.

    Mutable run logs/captured images/caches are excluded. Notebook execution
    output is cleared. Includes IO, capture, motion, V74 detector and V91 addon.
    """
    bundle=Path(export_native_bundle());root=Path(__file__).resolve().parent
    manifest=_read(root/'release_manifest.json');payload={}
    for name in manifest['sha256']:
        if name in ('run-result.log','release_manifest.json','upload_inventory.json'):continue
        if Path(name).suffix.lower()=='.md':continue
        local=root/name
        if local.resolve().parent!=root or Path(name).name!=name:continue
        data=local.read_bytes()
        if name.endswith('.ipynb'):
            notebook=json.loads(data)
            for cell in notebook.get('cells',[]):
                if cell.get('cell_type')=='code':cell.update(outputs=[],execution_count=None)
            data=(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n').encode('utf-8')
        payload[name]=data
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            name=info.filename
            if (name.startswith('native_prebuilt/') and len(Path(name).parts)==2
                    and Path(name).suffix.lower()!='.md'
                    and not info.is_dir() and info.file_size<=64*1024*1024):payload[name]=archive.read(info)
    payload['run-result.log']=b''
    manifest.update(precompiled_libraries_included=True,precompiled_environment=environment(),
        precompiled_binary_verification='full source+recipe+environment+binary SHA256+ELF/ABI before import')
    manifest['sha256']={name:hashlib.sha256(data).hexdigest() for name,data in sorted(payload.items())}
    payload['release_manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    inventory=dict(release_id=RELEASE_ID,root_folder=root.name,files=[dict(name=name,bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(payload.items())])
    payload['upload_inventory.json']=(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output=Path(output).expanduser().resolve() if output is not None else root/(root.name+'_prebuilt_upload.zip')
    temporary=output.with_name(output.name+'.'+str(os.getpid())+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in sorted(payload.items()):archive.writestr(root.name+'/'+name,data)
        os.replace(str(temporary),str(output))
    finally:
        if temporary.exists():temporary.unlink()
    checkpoint('CPU_PREBUILT_FULL_UPLOAD_EXPORTED',path=str(output),files=len(payload),
        hardware_access=False,run_log_included=False)
    return str(output)


# ======================================================================
# ===== [08/08] v94_audit =====
# ======================================================================


"""Failure-only current edge proof after a quiet scheduled FB audit.

No hardware calls, native compilation, altered LK gates or stored image/H.
"""
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def recover_audit_edges(tracker,image,gray,candidate,evidence,prediction,previous,gate,
                        reason,trigger,lost_at_entry,source_gap):
    """Independent current Y24/Y64 may reanchor; a failed LK is never promoted."""
    if (lost_at_entry or source_gap or tracker.lost or tracker.checks!='auto'
            or tracker.policy!='motion_adaptive' or trigger not in ('adaptive_age','hard_maximum_age')
            or candidate is None or evidence is None or not gate.get('reliable')
            or evidence.get('color_vector_proof') or not evidence.get('valid')
            or evidence.get('supported_edges')!=4 or evidence.get('refined_corners')!=4
            or gate.get('min_support',0.)<.80 or gate.get('max_rms',1e30)>.50
            or gate.get('prediction_correction',1e30)>.75):return None
    elapsed=getattr(tracker,'source_elapsed_s',None)
    timing=tracker.last_lk_timing;flow=timing.get('forward_backward_flow_s')
    code=timing.get('native_checked_code')
    if (elapsed is None or not np.isfinite(elapsed) or not 0<float(elapsed)<=.35
            or flow is None or not np.isfinite(flow) or flow<0
            or (code is not None and code<=-100)):return None
    q=np.asarray(candidate,np.float32);scale=tracker.scale
    if (q.shape!=(4,2) or not np.isfinite(q).all()
            or float(np.max(np.linalg.norm(q-previous,axis=1)))>1.):return None
    from geometry import array_key as array_key; from geometry import actual_source64 as actual_source64
    from geometry import proof_band as proof_band; from geometry import line_lock as line_lock; from geometry import declare_current_y24 as declare_current_y24; from geometry import current_agreement as current_agreement
    from tracking import _valid__v87_v74_tracking as _valid
    from tracking import _decode_source64 as _decode_source64
    # Match the current image/gray/index scope created by this update. The raw
    # camera lease stays owned by the sole PS producer throughout the call.
    scope=(id(image),array_key(image),id(gray),array_key(gray),int(tracker._update_index),tuple(float(v) for v in scale))
    if tracker.current_proofs.scope!=scope or tracker.last_gray is not gray:return None
    lock=line_lock(previous,q)
    if not lock.get('verified') or not _valid(q,gray.shape,previous,tracker.checks):return None
    if image.ndim!=3 or image.shape[2]!=2:return None
    require_yuyv(image)
    work=tracker.post_lk
    if work.kernels is None:return None
    begin=time.perf_counter();cpu=time.thread_time()
    deadline=min(begin+.075,tracker._frame_deadline or begin+.075)
    detail=dict(attempted=True,verified=False,failed_LK_reason=reason,failed_LK_trigger=trigger,
        LK_audit_passed=False,current_source_only=True,proof_cpu_budget_s=.025,
        independent_grids=[[24,.055,.945],[64,.06,.94]],old_H_used=False)
    timing['audit_current_reproof']=detail
    def finish(value=None,why=None):
        detail.update(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu)
        if why is not None:detail['reason']=why
        if detail['thread_cpu_s']>.025 or time.perf_counter()>deadline:
            detail.update(verified=False,reason='audit_current_reproof_budget_exceeded');return None
        return value
    try:
        # Discard pending source64 from the failed LK geometry. Reuse only its
        # allocated scratch and original pinned native library, never its proof.
        work.clear();tracker._promoted_points=None
        narrow,half=proof_band(scale,evidence)
        local=work.proposed;local[:]=(q+.5)*scale-.5
        h,w=image.shape[:2]
        if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
                or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):
            return finish(why='audit_source_quad_not_visible')
        if time.perf_counter()>deadline:return finish(why='audit_reproof_deadline_before_sampling')
        code=work.kernels.p11_yuyv_refine64(image.ctypes.data,w,h,image.strides[0],color_mode(),
            local.ctypes.data,half,work.source.ctypes.data,work.source_stats.ctypes.data)
        if code:return finish(why='audit_original_Y64_kernel_rejected:'+str(code))
        result,raw=_decode_source64(local,half,work.source,work.source_stats)
        edges=raw['edges'];support=[e.get('retained',0)/64. if e.get('accepted') else 0. for e in edges]
        rms=[float(e.get('tls_rms',1e30))/float(scale.min()) for e in edges]
        contrast=np.asarray([e.get('profile_contrast',0.) for e in edges],np.float64)
        valid=(raw.get('refined_corners')==4 and len(edges)==4 and all(e.get('accepted') for e in edges)
            and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
        observed=((result+.5)/scale-.5).astype(np.float32)
        source=dict(valid=bool(valid),refined_corners=4 if valid else 0,supported_edges=sum(s>=.60 for s in support),
            edge_support=support,edge_rms=rms,edge_polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist(),
            edge_backend='cpp_current_source_Y64',source_proof=raw,same_frame_source=True,
            profiles_per_edge=64,fraction_limits=[.06,.94],current_source_key=array_key(image),source_proof_kind='source_Y_profiles')
        checked=tracker._edge_gate(source,observed,q,3.)
        agreement=current_agreement(q,observed,declare_current_y24(evidence),source,scale,array_key(image),stable_fb=False)
        primary_lock=line_lock(q,observed);previous_lock=line_lock(previous,observed)
        detail.update(validation=checked,agreement=agreement,line_lock=primary_lock,previous_line_lock=previous_lock,
            narrow_radius_tracking=float(narrow),half_window_source=float(half),source64_reused_from_failed_LK=False)
        strict=(checked.get('reliable') and checked['min_support']>=.80 and checked['max_rms']<=.65
            and agreement.get('verified') and primary_lock.get('verified') and previous_lock.get('verified')
            and actual_source64(source,array_key(image)) and _valid(observed,gray.shape,previous,tracker.checks))
        if not strict:return finish(why='audit_current_independent_edges_rejected')
        # Completion is a CURRENT-edge success, not a successful optical-flow
        # audit. Seed real CURRENT points/gray later; do not promote failed flow.
        detail.update(verified=True,force_current_anchor=True,LK_audit_passed=False)
        outcome=finish((observed,source,dict(state='audit_failed_current_edges_twice_verified',
            audit_failure_reproved=True,force_current_anchor=True,first_validation=dict(gate),second_validation=checked,
            source_line_agreement=agreement,audit_current_reproof=detail,old_H_not_used=True)))
        if outcome is not None:
            tracker.last_source_confirmation=dict(agreement,verified=True,final_gate=dict(checked),audit_current_reproof=True)
        return outcome
    except (ValueError,cv2.error) as exc:return finish(why='audit_current_reproof_rejected:'+str(exc))
