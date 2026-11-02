"""Adapted P1 paper-mask algorithm, E:/P1/board/paper_quad.py (2026-10-01).
Connected-component reuse and HSV gates preserved. Original authorship stays in
P1; this snapshot is imported as a private V23 module, not an installed P1 tree.
"""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
import cv2
import numpy as np

# ===========================================================================
#  既有默认常量；camera_color调用使用有界自适应门限，不改这些默认值
# ===========================================================================
MIN_GAP = 50.0          # 白度可分性：两类均值差小于它 ⇒ 图里没有"白"的东西
MIN_AREA_FRAC = 0.03    # 最大连通域至少占整图的比例
OPEN_KERN = 5           # 开运算核（矩形 5x5）
SAT_MIN_PIX = 256       # 样本像素太少就不值得跑 Otsu（与第二刀那条阈值一致）

# ⭐ 粗检测的降采样宽度（2026-10-01 新增，原方案是 1024）
#
#   队友原版 `find_document_quad(work_width=1024)` 只把图缩到 1024 宽就开跑，
#   而**这一步在板子上极贵**：900x1200 上 `find_paper_quad` 整段 **785 ms**
#   （板上实测，`board/pynq/probe_quad_cost.py`）。降采样的收益是**超线性**的：
#
#       板上实测（4 张实拍，`probe_quad_opt.py`）：
#           work_width   粗检测ms   相对    角逐位差(vs 1024)
#              1024        784.9    1.00x        -
#               768        754.1    0.96x     1.53 px
#               640        552.8    0.70x     1.53 px
#               512        389.9    0.50x     2.78 px
#               448        296.6    0.38x     3.98 px
#             **384**      273.1    0.35x     3.31 px   ← 取它
#
#   ⇒ 每次检测 882 ms → 350 ms（0.40x），摊到 N=10 是 **88.6 → 35.0 ms/帧**。
#
#   ⚠️ **为什么可以放心降**：亚像素精度不由粗检测负责 —— `refine_quad_by_edges`
#      仍在**原图分辨率**上追刃边（它的 46 ms 不受本参数影响）。
#      粗检测只要把四角定到几个像素内，精修就能收敛。
#   ⚠️ **降过头的兜底**：本函数返回 None 时，`estimate_quad` 会自动降级到轮廓法
#      （173 ms），**不会崩**。最坏情况是那一帧退回轮廓法。
#   ⚠️ 只在 900~1200 这个量级的输入上验过；换大图/小图要重跑 `probe_quad_opt.py`。
QUAD_WORK_WIDTH = 384

# ---- v16「低饱和」门 ----
SAT_CUT_FIXED = 0.11     # 实测零损伤平台 [0.09, 0.13] 的中点
SAT_AUTO_LO, SAT_AUTO_HI = 0.09, 0.13
SAT_CUT_MODE = "fixed"   # "off"（= v15 行为）| "fixed" | "auto"


# ===========================================================================
#  一、几何小工具
# ===========================================================================
def _corner_array(pts, n):
    """入参统一：**保留浮点精度**，整数提升到 float64。

    ⚠️ 不要转 float32 —— 在 1000 像素尺度上 float32 只有约 1.2e-4 的绝对精度，
       调用方传进来的 float64 会被**静默**砍掉。亚像素角点指望这个精度。
    """
    p = np.asarray(pts)
    if not np.issubdtype(p.dtype, np.floating):
        p = p.astype(np.float64)
    return p.reshape(n, 2)      # ⚠️ n=-1 是「自动推断行数」（原版就用这个），别加守卫


def order_quad_polar(pts):
    """任意顺序四点 → tl,tr,br,bl（顺时针）；**不依赖输入顺序**，对 np.roll 不变。

    ⚠️ 为什么用【绕质心的极角排序】而不是"按 y 分上下组"：
       后者的经典写法是四个各自独立的极值判据
           tl=argmin(x+y)  tr=argmax(x−y)  br=argmax(x+y)  bl=argmin(x−y)
       四个判据**互不排斥** ⇒ 同一个点可能被选成两个角、另一个点整个丢掉，
       **不报错不警告**。实测（队友 `probe_v3j`）：roll=45° 时**全部断裂** ——
       而"把纸斜着放在桌上拍"就是 45°。

       极角排序保证输出是输入的**排列**，且对角一定配对（凸四点集上，绕内点的
       极角序就是边界序）。起点用 x+y 最小 —— 只决定从哪个角起算（一个约定），
       不再影响几何正确性。

    ⚠️ 本文件内部用它；**对外返回前**调用方还会过一遍
       `find_homography.order_quad`（那个是为 PL 的流式约束定制的）。
    """
    p = _corner_array(pts, 4)
    c = p.mean(axis=0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    q = p[np.argsort(ang, kind="stable")]
    return np.roll(q, -int(np.argmin(q.sum(axis=1))), axis=0)


def quad_quality(quad):
    """自洽质量指标：四边形离"矩形"有多远。

    不需要 ground truth —— 因为**透视校正的正确结果就应该是矩形**。
    返回 `dict(angle_err_deg, parallel_err, corners)`；角误差越小 = 越像纸。
    """
    q = order_quad_polar(quad)
    angs = []
    for i in range(4):
        v1 = q[(i - 1) % 4] - q[i]
        v2 = q[(i + 1) % 4] - q[i]
        c = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        angs.append(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))
    angle_err = max(abs(a - 90.0) for a in angs)

    e = [q[1] - q[0], q[2] - q[1], q[3] - q[2], q[0] - q[3]]

    def rel(a, b):
        la, lb = np.linalg.norm(a), np.linalg.norm(b)
        return abs(la - lb) / max(la, lb, 1e-9)

    return {"angle_err_deg": float(angle_err),
            "parallel_err": max(rel(e[0], e[2]), rel(e[1], e[3])),
            "corners": q}


def extreme_quad(pts):
    """四极端点：点集里取 x±y 的四个极值点。

    比 approxPolyDP 更鲁棒（不用调 epsilon），每步都是纯比较运算 ——
    将来搬 PL 时逻辑可以一一对应。
    """
    p = _corner_array(pts, -1)
    s = p.sum(axis=1)
    d = p[:, 0] - p[:, 1]
    return np.stack([p[np.argmin(s)], p[np.argmax(d)],
                     p[np.argmax(s)], p[np.argmin(d)]])


def _fill_holes(mask):
    """填充 mask 内部的封闭孔洞（**纸上印的黑色方格/文字**造成的）。

    ⭐ 就是这一步让掩膜法没有第二个解：黑框在掩膜里是孔洞，填掉之后
       连通域**天然是整张纸**，不会在"纸沿"和"黑框"之间二选一。
    不需要核大小参数（对比：闭运算的核大小是魔数）。
    """
    h, w = mask.shape
    ff = mask.copy()
    m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, m2, (0, 0), 255)      # 从角点灌满外部背景
    return cv2.bitwise_or(mask, cv2.bitwise_not(ff))


# ===========================================================================
#  二、掩膜工具
# ===========================================================================
def _biggest_cc(mask):
    """一次连通域分析 → `(n, labels, stats, biggest)`；`n<=1` 时 `biggest = -1`。

    ⚠️ 那个 `8` 的来历（队友 v17 实测，`_probe_cc_arg8_report.txt`）：
       OpenCV 的 Python 签名是
       `connectedComponentsWithStats(image[, labels[, stats[, centroids[, connectivity[, ltype]]]]])`
       ⇒ **第 2 个位置参数是 `labels`，不是 connectivity**。
       6x6 分辨性掩膜实测：`(m)` / `(m,8)` / `(m,4)` / `(m,0)` 四种写法结果**逐位全同**；
       而真 connectivity 旋钮 `(m,None,None,None,4)` 能把块数从 2 变成 4
       ⇒ **实验测得到那个旋钮，却没在这个 `8` 上测到差别** ⇒ 它不改变任何结果。
       保留只为不动原代码的形状。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return n, labels, stats, -1
    return n, labels, stats, 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def _touches_border(mask, tol=1, cc=None):
    """mask 里**最大的一块**是否贴到图像边界。贴 = 它一路延伸出了画面。

    跑飞的可靠征兆：纸和桌面亮区连成一片时，这块必然被画面裁断在边上。
    反过来，一块完整的纸在画面里四边都有背景 ⇒ 不贴。
    判据是**纯几何**的，不含任何阈值 —— 这是它比"面积比值"那类护栏准的原因。

    没有连通域（开运算把细点消光）时返回 False：**宁可不修，也不乱修**。
    """
    if cc is None:
        cc = _biggest_cc(mask)
    n, _, stats, b = cc
    if n <= 1 or b < 0:
        return False
    x = stats[b, cv2.CC_STAT_LEFT]
    y = stats[b, cv2.CC_STAT_TOP]
    w = stats[b, cv2.CC_STAT_WIDTH]
    h = stats[b, cv2.CC_STAT_HEIGHT]
    H, W = mask.shape
    return bool(x <= tol or y <= tol or x + w >= W - tol or y + h >= H - tol)


def _whiteness(img):
    """白度通道 = 每像素 `min(R,G,B)`，返回同尺寸 uint8 单通道。

    ⭐ 为什么用 min(R,G,B) 而不是 HSV 饱和度：
        白纸 (243,243,243) → 243
        木地板 (170,120,70) → 70      （蓝色通道低 ⇒ 它根本不是白的）

    ⚠️ **不要**改回 `np.min(img, axis=2)` —— 那个写法慢 **14.4 倍**。
       HWC 布局下 `axis=2` 归约时跨像素 stride=3，SIMD 预取吃不满；
       `np.minimum` 链是两次**连续内存**的二元运算。
       实测（1024x1366，9 张 × 25 次取中位）：15.98 ms → **1.11 ms**。
       五种写法全部 `np.array_equal` 逐位相同 —— min 是精确运算，零行为变化。
    """
    return np.minimum(np.minimum(img[:, :, 0], img[:, :, 1]), img[:, :, 2])


def _saturation(img):
    """HSV 的 S，uint8（0~255）。

    ⚠️ 通道顺序**无所谓** —— 所以这里**不做 BGR↔RGB 翻转**（那会多一次拷贝）：
       OpenCV 的 S = `(max-min)/max`，只由三个通道的**最大和最小**决定
       ⇒ BGR 和 RGB 走 `COLOR_RGB2HSV` 给出的 S **逐位相同**。
       （H 会不同，但本文件从不读 H。）
    """
    return cv2.cvtColor(img, cv2.COLOR_RGB2HSV)[:, :, 1]


def _sat_gate(img, white_hi, camera_color=False):
    """v16 的「低饱和」门 → `(cut, ok)`；`SAT_CUT_MODE == "off"` 时返回 `(None, None)`。

    病：纸右上方的**桌面高光**白度够高 ⇒ 被 Otsu 纳进掩膜 ⇒ 掩膜凸起顶到画面右缘
        ⇒ `extreme_quad` 把 `tr` 拉到画面角上。（实测 190 帧里 27 张判废的唯一成因，
        26 张的 `tr` 贴在 x=W-1。）

    为什么白度修不了而饱和度可以：**白度重叠 ≠ 饱和度重叠** ——
        纸是**无色**的（白/灰印刷，S.p50≈0.063，S>0.25 占比 0.000）、
        木桌是**有色**的（S.p50≈0.408，S>0.25 占比 0.848）。27/27 张完全分得开。

    ★ auto 为什么要**夹取**：干净纸的 S 是单峰分布 ⇒ Otsu 会从中间硬切一刀
      （与它在白度上的老毛病同源）。夹取范围取**实测零损伤平台的边界**，
      所以 auto 的值永远落在平台内。
    """
    if SAT_CUT_MODE == "off":
        return None, None
    sat = _saturation(img)
    cut = SAT_CUT_FIXED
    if camera_color:
        # Camera white balance can tint the paper. Estimate a bounded gate from
        # the least saturated part of the bright class, without changing RGB.
        v = sat[white_hi]
        if v.size:
            cut = float(np.clip(np.percentile(v, 20) / 255.0 + .06, .13, .26))
    elif SAT_CUT_MODE == "auto":
        v = sat[white_hi]
        if v.size >= SAT_MIN_PIX:
            t, _ = cv2.threshold(v.reshape(-1, 1), 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            cut = float(np.clip(t / 255.0, SAT_AUTO_LO, SAT_AUTO_HI))
    # ceil 而非 round：让 `u8 < ceil(cut*255)` 与 `u8/255.0 < cut` **逐个像素等价**
    return cut, (sat < int(np.ceil(cut * 255.0)))


def _mask_quad(mask, min_area_frac=MIN_AREA_FRAC, cc=None):
    """mask → 最大连通域的四边形（**mask 坐标**：未 order、未除 scale）；不成形返回 None。"""
    if cc is None:
        cc = _biggest_cc(mask)
    n, labels, stats, biggest = cc
    if n <= 1 or biggest < 0:
        return None
    if stats[biggest, cv2.CC_STAT_AREA] < min_area_frac * mask.size:
        return None

    comp = _fill_holes(np.where(labels == biggest, 255, 0).astype(np.uint8))
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)

    # 主路径：多边形逼近
    peri = cv2.arcLength(cnt, True)
    quad = None
    for eps in np.linspace(0.01, 0.08, 15):
        ap = cv2.approxPolyDP(cnt, eps * peri, True)
        if len(ap) == 4:
            quad = ap.reshape(4, 2).astype(np.float32)
            break

    # 兜底：四极端点
    hull = cv2.convexHull(cnt)
    if quad is None:
        quad = extreme_quad(hull)

    # 逼近出来的若明显不如极端点，用极端点
    if quad_quality(quad)["angle_err_deg"] > quad_quality(extreme_quad(hull))["angle_err_deg"]:
        quad = extreme_quad(hull)
    return quad


def _paper_like(mask, min_area_frac=MIN_AREA_FRAC, cc=None):
    """这块掩膜"像不像一张纸" = 其四边形的角误差（度），越小越像；不成形返回 None。"""
    q = _mask_quad(mask, min_area_frac, cc=cc)
    return None if q is None else float(quad_quality(q)["angle_err_deg"])


# ===========================================================================
#  三、纸掩膜（v7 / v9 / v16 三次修正史都在这里）
# ===========================================================================
def _paper_mask(img, min_gap=MIN_GAP, camera_color=False, diagnostics=None):
    """自适应分出"像纸的像素"，返回 `(uint8 mask, cc)`；图里没有可信的"白"目标则返回 `(None, None)`。

    ⭐ **2026-10-01：多返回一个 `cc`**（`_biggest_cc` 的结果）。
    原版把 `bw` 返回给 `find_document_quad` 后，`_mask_quad` 会**在同一个掩膜上
    再算一次** `connectedComponentsWithStats` —— 板上实测这一次要 **182.8 ms**
    （`probe_quad_cost.py`）。带出来复用后每次检测省 ~87 ms。
    （队友 v17 的 README §四 明确写过他知道这处重复，但"要改 `_paper_mask` 的
      返回值、会动公共接口"所以没做 —— 本函数是本文件私有的，改动安全。）

    ⚠️ **不能只用 Otsu**：Otsu 假定直方图双峰。纯木地板（白度只在 70±12 波动）
       是**单峰**，Otsu 仍会从中间强行切一刀，把噪声分成两半。
       所以加一道可分性检验：两类均值差不够大 = 这张图里没有"白"的东西。

    ★ **v7 修正** —— 修「纸 + 一片亮桌面」连成最大连通域
        实测 test-7：桌面被灯照亮的那片白度落在 130~190，把 Otsu 从纸边（~190）
        **拽到 132** ⇒ 纸与亮桌面连成一块，最大连通域外接框横跨整幅 x[0,1024]
        （填充率仅 21.3%）⇒ 四角被 extreme_quad 拉到图像边界 ⇒ 输出拉成 1:2.32 长条。
        Otsu 只保证"两类类间方差最大"，**不保证切在背景与纸之间**。
        修法：在它切出的高侧**再切一刀**（递归 Otsu 的最浅一层，只做一层）。
        **触发条件**：只看最大连通域贴不贴图像边界 —— 贴 ⇒ 混进了非纸的东西，该抬。

    ★ **v9 修正** —— 上面这条只看「贴不贴边界」，不看「切完还是不是纸」
        实测失效（合成视频第 4/5 帧）：亮桌面白度 > 第一刀 Otsu ⇒ 贴边界 ⇒
        抬到 185 ⇒ **纸自己被阴影压暗的右半边掉到 185 以下被切掉** ⇒ 切完确实不贴了
        ⇒ **残缺掩膜被当成成功**（角误差 6.5° → 60.8°，输出退化成 22x903 细条）。
        修法：抬完还**必须更像纸**（角误差更小）。不引入新魔数，用的就是 `quad_quality`。
        实测 4/4 分对（触发过第二刀的全部样本）：test-6 7.62°→0.94° 采纳；
        test-7 12.80°→10.39° 采纳；帧4 6.52°→60.78° **拒绝**；帧5 4.02°→62.66° **拒绝**。
        ⚠️ 附带堵掉的旧洞：`_touches_border` 对空掩膜返回 False ⇒ 旧条件会**采纳一张
           全黑的掩膜**。新条件里 `a2 is not None` 把这条堵死。

    ★ **v16 修正** —— 「低饱和」门，治「桌面高光顶到画面右缘」（见 `_sat_gate`）
    """
    white = _whiteness(img)
    thr, _ = cv2.threshold(white, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if camera_color:
        dynamic_range = float(np.percentile(white, 95) - np.percentile(white, 5))
        min_gap = float(np.clip(.20 * dynamic_range, 12., 32.))
    if diagnostics is not None:
        diagnostics.update(brightness_threshold=float(thr), required_brightness_gap=float(min_gap),
                           camera_color=bool(camera_color))

    lo, hi = white <= thr, white > thr
    if not lo.any() or not hi.any():
        if diagnostics is not None:diagnostics['mask_reason'] = 'no_brightness_classes'
        return None, None
    gap = float(white[hi].mean() - white[lo].mean())
    if diagnostics is not None:diagnostics['measured_brightness_gap'] = gap
    if gap < min_gap:
        if diagnostics is not None:diagnostics['mask_reason'] = 'brightness_contrast_too_small'
        return None, None                # 目标与背景分不开 → 没有纸

    cut, sat_ok = _sat_gate(img, hi, camera_color=camera_color)
    if diagnostics is not None:diagnostics['saturation_cut'] = cut
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (OPEN_KERN, OPEN_KERN))

    def _open(cond):
        """开运算出掩膜；`cut` 非 None 时同时要求 S < cut。"""
        if sat_ok is not None:
            cond = cond & sat_ok
        return cv2.morphologyEx(cond.astype(np.uint8) * 255, cv2.MORPH_OPEN, kern)

    bw = _open(hi)
    cc = _biggest_cc(bw)                 # ⭐ 算一次，带出去给 _mask_quad 复用
    if diagnostics is not None:
        diagnostics.update(initial_foreground_fraction=float(np.count_nonzero(bw) / bw.size),
                           initial_mask_touches_border=bool(_touches_border(bw, cc=cc)),
                           border_rethreshold_accepted=False)

    # v7：最大连通域贴图像边界 ⇒ 纸与非纸连成一片，在高侧再切一刀剔掉它
    if int(hi.sum()) >= SAT_MIN_PIX:
        if _touches_border(bw, cc=cc):
            thr2, _ = cv2.threshold(white[hi].reshape(-1, 1), 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if thr2 > thr:                   # 必须真的抬高，否则等于没改
                bw2 = _open(white > thr2)
                cc2 = _biggest_cc(bw2)
                # v9：抬完不光要「不贴边界」，还得**更像纸**
                a1, a2 = _paper_like(bw, cc=cc), _paper_like(bw2, cc=cc2)
                if not _touches_border(bw2, cc=cc2) and a2 is not None and (a1 is None or a2 < a1):
                    bw, cc = bw2, cc2        # ⚠️ cc 必须跟着换，否则复用了一个过期结果
                    if diagnostics is not None:diagnostics['border_rethreshold_accepted'] = True
    if diagnostics is not None:
        diagnostics.update(mask_reason='proposal_ready',
                           final_mask_touches_border=bool(_touches_border(bw, cc=cc)))
    return bw, cc


# ===========================================================================
#  四、对外接口
# ===========================================================================
def _as_3ch(img):
    """统一成 HxWx3。灰度图升成 3 通道 ——

    ⚠️ 灰度升 3 通道后 `_saturation` 恒为 0 ⇒ 「低饱和门」自动变成**空操作**。
       这是**正确**的行为：真·灰度图里没有"彩色桌面"这个概念。
       但也会因此**丢掉 v16 那道修正** ⇒ 有色输入请传彩色。
    """
    if img.ndim == 2:
        return np.repeat(img[:, :, None], 3, axis=2)
    if img.shape[2] == 4:
        return img[:, :, :3]
    return img


def find_paper_quad(img, work_width=QUAD_WORK_WIDTH, camera_color=False, diagnostics=None):
    """掩膜法找纸 → **原图坐标**、顺序 tl,tr,br,bl 的四角（float64）或 None。

    ⚠️ 只做**粗检测**，不做亚像素精修 —— 精修由调用方的
       `find_homography.refine_quad_by_edges` 负责（那是我们已经板上验证过的一段）。

    Args:
        img: HxWx3（BGR 或 RGB 都行，见模块头 ③）或 HxW（灰度）
        work_width: 粗检测前把图缩到这个宽度以内。
            ⚠️ **默认是 384，不是原方案的 1024** —— 理由见 `QUAD_WORK_WIDTH`。
            想让回原行为就传 1024。
        camera_color: 仅本次调用按摄像头亮度/饱和度统计调整有界门限。
        diagnostics: 可选字典，记录实际门限、连通域贴边与失败原因。
    Returns:
        (4,2) float64 原图坐标，顺序 tl,tr,br,bl；找不到纸返回 None
    """
    rgb = _as_3ch(np.asarray(img))
    H0, W0 = rgb.shape[:2]
    scale = min(1.0, work_width / float(W0))
    if scale < 1.0:
        small = cv2.resize(rgb, (int(round(W0 * scale)), int(round(H0 * scale))),
                           interpolation=cv2.INTER_LINEAR)
    else:
        small = rgb

    if diagnostics is not None:diagnostics['work_shape'] = list(small.shape)
    mask, cc = _paper_mask(small, camera_color=camera_color, diagnostics=diagnostics)
    if mask is None:
        return None

    quad = _mask_quad(mask, cc=cc)       # ⭐ 复用上面那次连通域分析（省 182.8 ms/次@板上）
    if quad is None:
        if diagnostics is not None:diagnostics['mask_reason'] = 'connected_component_has_no_quad'
        return None

    return order_quad_polar(np.asarray(quad, np.float64) / scale)
