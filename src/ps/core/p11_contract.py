"""V90 bounded frame/LK transactions; V74 automatic and explicit manual stay separate."""
import hashlib
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

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
