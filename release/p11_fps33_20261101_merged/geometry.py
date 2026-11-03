"""geometry —— 合并层，含 22 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


import hashlib as _hashlib
from pathlib import Path as _SourcePath
import sys
import numpy as np
import cv2
from pathlib import Path
import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
import hashlib,struct
import hashlib,time
from functools import lru_cache
import hashlib, time
import hashlib,itertools,time
import cv2,numpy as np
from pathlib import Path
import hashlib,copy
import numpy as np
from dataclasses import dataclass
import hashlib,time
import copy,hashlib
import hashlib,threading,time
import hashlib,threading


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/22] find_homography =====
# ======================================================================


"""P11 PS corner detection and inverse homography; copied from ../P1/board.
This project uses this local copy; register normalization remains unchanged.
"""

from core import RELEASE_ID as RELEASE_ID; from core import cache_profile as cache_profile
_SOURCE_SHA256 = _hashlib.sha256(_SourcePath(__file__).read_bytes()).hexdigest()


"""
src/ps/find_homography.py
    PS 侧核心：从一张倾斜拍摄的图里找出平面目标，算出单应变换

PC 和 PYNQ 板上都用这个模块。刻意不依赖任何 FPGA 相关库，
所以可以在笔记本上先跑通、验证透了再搬上板。

---------------------------------------------------------------------------
   ⭐ 最重要的一条：四个角点的顺序不是随便排的
---------------------------------------------------------------------------
本模块输出的四角点顺序，会被 PL 的流式架构【强制依赖】：

    【文档的上边缘】必须映射到【输出图像的第 0 行】

为什么：PL 用行缓存做流式重映射，要求"输出第 v 行所需的输入行区间随 v
单调后移"。如果顺序反了，行缓存必须退化成整帧缓冲，"零访存"这个核心
卖点就没了（详见 docs/pl_remap_interface.md §五）。

`order_quad()` 负责保证这个顺序，它会把四角排成 (左上, 右上, 右下, 左下)，
且满足"上边的图像 y 小于下边"。

---------------------------------------------------------------------------
   关于降级链的一个实测观察
---------------------------------------------------------------------------
蓝图写的降级链是「轮廓法 → 特征点法 → 手动角点」。但：

  · 轮廓法（找边界）—— 图片阶段适用 ✓
  · 特征点法（ORB/FAST + 匹配）—— ⚠️ **图片阶段基本用不上**
      它需要"参考图"才能匹配。视频里参考图是【上一帧】（帧间跟踪），
      单张图没有上一帧，除非事先拍了文档正的模板。
      → 所以特征点法是【视频阶段】的主力，图片阶段降级不到它。
  · 手动四角点 —— 图片阶段的真正兜底 ✓

本模块因此实现：轮廓法（首选） → 手动四角点（兜底）。
特征点法留给视频阶段。
"""


# Windows 控制台默认 GBK，强制 UTF-8 免得中文乱码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 与 PL 的硬约定（改这里必须同步改 RTL 和文档）
# ---------------------------------------------------------------------------
NORM_SCALE = 2048       # 坐标归一化尺度（必须是 2 的幂）
FRAC_BITS  = 16         # Q16.16
Q_ONE      = 1 << FRAC_BITS


# ===========================================================================
# 一、四角点排序
# ===========================================================================
def order_quad(pts):
    """
    把 4 个点排成 (左上, 右上, 右下, 左下)，且满足 PL 的流式约束。

    规则：先按 y 分成上下两组各两点，组内按 x 排序。
    这样"上边"（TL→TR）的图像 y 必然小于"下边"（BL→BR），
    正好满足"输出第 0 行 ← 文档上边缘"。

    ⚠️ 适用前提：文档在画面里的旋转不超过约 45°（本来就是演示约束）。

    Args:
        pts: shape (4,2) 的四个角点，顺序任意
    Returns:
        shape (4,2) float32，顺序为 (TL, TR, BR, BL)
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    # 按 y 排序，前两个是"上面"的点
    idx = np.argsort(pts[:, 1])
    top = pts[idx[:2]]
    bot = pts[idx[2:]]
    # 组内按 x 排：小的在左
    top = top[np.argsort(top[:, 0])]
    bot = bot[np.argsort(bot[:, 0])]
    return np.array([top[0], top[1], bot[1], bot[0]], dtype=np.float32)


def verify_quad_order(quad):
    """
    自检：确认排序满足 PL 的流式约束。

    判据：上边的平均 y 必须【明显小于】下边的平均 y，
    且左右两侧的高度（TL→BL、TR→BR）方向一致。

    返回 (是否通过, 诊断字符串)
    """
    tl, tr, br, bl = quad
    y_top = (tl[1] + tr[1]) / 2.0
    y_bot = (bl[1] + br[1]) / 2.0
    if y_bot <= y_top:
        return False, "下边(%0.1f) 不低于 上边(%0.1f)：角点顺序反了" % (y_bot, y_top)

    # 左右两侧的高度差异不该太悬殊（否则可能是菱形排序）
    h_l = bl[1] - tl[1]
    h_r = br[1] - tr[1]
    if h_l <= 0 or h_r <= 0:
        return False, "左右边不是自上而下：顺序可能乱"
    return True, "上边 y=%.1f < 下边 y=%.1f，左右边高 %.0f/%.0f —— 顺序正确" % (
        y_top, y_bot, h_l, h_r)


# ===========================================================================
# 二、轮廓法（首选）：靠目标的边界
# ===========================================================================
# 多档 Canny 阈值。为什么要多档（实测踩出来的）：
#   浅色纸压在浅色木桌上时，纸边对比度低，默认阈值【只找得到纸上的黑框】，
#   找不到整张纸；调灵敏又会在别的图里捡到"整幅画面边界"。
#   所以一次跑三档，把所有候选收集起来，再按下面的规则挑。
CANNY_LEVELS = [(50, 150), (30, 90), (15, 50)]


def touches_border(quad, w, h, margin_ratio=0.01):
    """
    判断四边形是否贴着图像边界（多半是"整幅画面"这种假目标）。

    实测的反例：某张图在灵敏阈值下检出的"四边形"四角正好落在
    (0,y) 和 (W,y) 上 —— 那是整张图的边框，不是文档。
    """
    mx = max(2.0, margin_ratio * w)
    my = max(2.0, margin_ratio * h)
    for x, y in quad:
        if x <= mx or x >= w - 1 - mx or y <= my or y >= h - 1 - my:
            return True
    return False


def find_quad_by_contour(img, min_area_ratio=0.05, debug=False):
    """
    用 findContours + approxPolyDP 找文档四边形。

    强项：空白纸、纯色白板也能做（靠边界，不靠纹理）。

    ⭐ 两条挑选规则（都是为了"优先取最外围的白纸"，实测定的）：

      ① **排除贴着图像边界的候选** —— 那是"整幅画面"，不是文档
      ② **多档 Canny 阈值全跑，取面积最大的** —— 面积最大 = 最外围

    实测效果（方格纸三张真实照片）：
        默认阈值 50/150 时，浅色纸压浅色桌面那张只找得到纸上的黑框；
        加灵敏档 15/50 后能找到整张白纸（41% > 32%），取大的就对 ✓
        而另一张图在灵敏档会捡到整幅画面边界 → 被规则 ① 排除 ✓

    Args:
        img: 灰度或彩色图
        min_area_ratio: 四边形面积至少占整图的比例（过滤小噪点）
    Returns:
        (quad, info) —— quad 为 (4,2) float32 或 None；info 是诊断信息
    """
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    h, w = gray.shape[:2]
    img_area = float(h * w)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    kernel = np.ones((3, 3), np.uint8)

    candidates = []      # (面积, quad, 阈值档)
    n_border = 0
    n_order = 0

    for (lo, hi) in CANNY_LEVELS:
        edges = cv2.dilate(cv2.Canny(blur, lo, hi), kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            area = cv2.contourArea(c)
            if area < img_area * min_area_ratio:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue

            quad = order_quad(approx.reshape(4, 2))
            ok, _ = verify_quad_order(quad)
            if not ok:
                n_order += 1
                continue
            if touches_border(quad, w, h):
                n_border += 1
                continue
            candidates.append((area, quad, (lo, hi)))

    if not candidates:
        return None, ("轮廓法失败：多档阈值下都没有有效四边形"
                      "（排除贴边 %d 个、顺序不符 %d 个）—— "
                      "可能边界被裁切、背景太乱、或目标无清晰边界"
                      % (n_border, n_order))

    # ⭐ 取面积最大的 = 最外围
    area, quad, (lo, hi) = max(candidates, key=lambda t: t[0])
    return quad, ("轮廓法成功：面积占比 %.1f%%（Canny %d/%d，共 %d 个候选）"
                  % (100 * area / img_area, lo, hi, len(candidates)))


# ===========================================================================
# 三、手动四角点（兜底）
# ===========================================================================
def find_quad_manual(img, points=None):
    """
    手动四角：给定 4 个点，或者弹出窗口让人点。

    Args:
        img: 图像（显示用）
        points: 若给出则直接用（便于脚本化测试），否则交互式点选
    Returns:
        (quad, info)
    """
    if points is not None:
        quad = order_quad(points)
        ok, msg = verify_quad_order(quad)
        return (quad if ok else None), "手动四角：" + msg

    disp = img.copy()
    pts = []

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))
            cv2.circle(disp, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(disp, str(len(pts)), (x + 8, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imshow("click 4 corners (TL,TR,BR,BL)", disp)

    cv2.namedWindow("click 4 corners (TL,TR,BR,BL)")
    cv2.setMouseCallback("click 4 corners (TL,TR,BR,BL)", on_click)
    cv2.imshow("click 4 corners (TL,TR,BR,BL)", disp)
    print("  请按顺序点四个角：左上 → 右上 → 右下 → 左下（按 q 取消）")
    while len(pts) < 4:
        if cv2.waitKey(20) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()

    if len(pts) < 4:
        return None, "手动四角：被取消"
    quad = order_quad(pts)
    ok, msg = verify_quad_order(quad)
    return (quad if ok else None), "手动四角：" + msg


# ===========================================================================
# 四、统一的估计入口（降级链）
# ===========================================================================
def estimate_quad(img, method="auto", manual_points=None):
    """
    按降级链找四角：轮廓法 → 手动四角。

    Args:
        method: "auto" / "contour" / "manual"
    Returns:
        (quad, info)
    """
    if method in ("auto", "contour"):
        quad, info = find_quad_by_contour(img)
        if quad is not None:
            return quad, info
        if method == "contour":
            return None, info
        print("  [降级] " + info)

    # 降级到手动
    return find_quad_manual(img, manual_points)


# ===========================================================================
# 五、算单应矩阵（输出像素 → 输入像素）
# ===========================================================================
def suggest_output_size(quad, max_dim=1280):
    """
    由检测到的四边形推算合适的【输出尺寸】。

    ⚠️ 为什么必须这么做（踩过的坑）：
        如果输出尺寸写死成 640×480（横向），而目标是一张纵向的纸，
        校正结果会被【横向压扁】—— 看起来"校正成功了"，但形状是错的。
        输出长宽比必须与检测到的四边形一致。

    旧版兼容估计：对边平均投影长度不能恢复真实宽高比；v7使用独立尺寸模型。

    Args:
        quad: (4,2) 顺序为 (TL, TR, BR, BL)
        max_dim: 输出长边的上限（PL 的行缓存深度、吞吐都要考虑）
    Returns:
        (W_out, H_out) 两个整数
    """
    tl, tr, br, bl = np.asarray(quad, dtype=np.float64)
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
    h = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
    if w <= 1 or h <= 1:
        return 640, 480

    scale = min(1.0, float(max_dim) / max(w, h))
    W_out = max(16, int(round(w * scale)))
    H_out = max(16, int(round(h * scale)))
    return W_out, H_out


def load_image(path, max_dim=1280):
    """
    读图并限制最大边长。

    ⚠️ 为什么要限尺寸：
        手机照片动辄 4000+ 像素宽，而 **PL 的行缓存 MAX_W = 2048**，
        超过就放不下（会截断地址）。PC 上跑不受限，但为了和上板一致，
        建议 PC 上也先缩到同样的尺寸。
    """
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        s = float(max_dim) / max(h, w)
        img = cv2.resize(img, (int(round(w * s)), int(round(h * s))),
                         interpolation=cv2.INTER_AREA)
    return img


def compute_H_out2in(quad, W_out, H_out):
    """
    由文档四角点算出「输出像素 → 输入像素」的单应矩阵。

    ⚠️ 方向不能搞反：
        PL 要的是【反向映射】——给定输出像素，反查它在输入图里的位置。
        所以是 getPerspectiveTransform(输出矩形四角, 文档四角)。

    Returns:
        (3,3) float64，已归一化使 [2,2] == 1
    """
    dst = np.array([[0, 0],
                    [W_out - 1, 0],
                    [W_out - 1, H_out - 1],
                    [0, H_out - 1]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(dst, quad.astype(np.float32))
    return H / H[2, 2]


# ===========================================================================
# 六、换算成 PL 的 8 个寄存器值
# ===========================================================================
def homography_to_regs(H_out2in, norm_scale=NORM_SCALE):
    """
    把浮点单应矩阵换算成 PL 要的 8 个 Q16.16 参数。

    ⚠️⚠️ 最容易搞错的地方：
        只有 a13 / a23 【不乘】 norm_scale，其余 6 个都要乘。

    为什么：坐标归一化把 u,v 从像素换算到 [0,1]，乘上 norm_scale 的是
    u/v 的系数，而 a13/a23 是常数项（u=v=0 处的偏移），不在归一化坐标上。

    为什么必须归一化：h31/h32 量级只有 1e-4，而 Q16.16 的分辨率是 1.5e-5，
    只剩约 3 位有效数字；再乘 u（最大 1279）进分母，误差被放大上千倍。
    实测：不归一化误差 11.57 px，归一化后 0.033 px，差 351 倍。

    Returns:
        list[8] of int32（有符号，可直接写寄存器）
    """
    S, Q = norm_scale, Q_ONE
    return [
        int(round(H_out2in[0][0] * S * Q)),   # a11
        int(round(H_out2in[0][1] * S * Q)),   # a12
        int(round(H_out2in[0][2]     * Q)),   # a13  ← 不乘 S
        int(round(H_out2in[1][0] * S * Q)),   # a21
        int(round(H_out2in[1][1] * S * Q)),   # a22
        int(round(H_out2in[1][2]     * Q)),   # a23  ← 不乘 S
        int(round(H_out2in[2][0] * S * Q)),   # a31
        int(round(H_out2in[2][1] * S * Q)),   # a32
    ]


def regs_to_homography(regs, norm_scale=NORM_SCALE):
    """反换算：寄存器值 → 浮点矩阵。用于回读校验。"""
    S, Q = float(norm_scale), float(Q_ONE)
    a11, a12, a13, a21, a22, a23, a31, a32 = [float(v) for v in regs]
    H = np.array([[a11 / S / Q, a12 / S / Q, a13 / Q],
                  [a21 / S / Q, a22 / S / Q, a23 / Q],
                  [a31 / S / Q, a32 / S / Q, 1.0]])
    return H / H[2, 2]


# ===========================================================================
# 七、黄金参考（PC 端对比用）
# ===========================================================================
def warp_golden(img, H_out2in, W_out, H_out, border=0):
    """
    用 OpenCV 做校正 —— 这就是 PL 硬件要做的事情的浮点版。

    ⚠️⚠️ 必须加 WARP_INVERSE_MAP 标志（踩过的坑）：
        cv2.warpPerspective 默认把传入矩阵当作【源→目标】的正向变换，
        内部会【自己去求逆】再采样。而我们的 H_out2in 本身就是
        "输出像素 → 输入像素"的【采样映射】，不是正向变换。
        不加这个标志，OpenCV 会再求一次逆 → 结果完全错乱
        （症状：输出的还是歪的图，但 H 算得没错，很难一眼看出）。

        加了标志后： dst(x,y) = src(H_out2in · (x,y)) ✓ 正是我们要的。
    """
    return cv2.warpPerspective(img, H_out2in, (W_out, H_out),
                               flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(border,) * (3 if img.ndim == 3 else 1))


def golden_remap_fixed(img, regs, w_out, h_out):
    """
    PL 的【逐位定点模型】—— 与 RTL 应当逐字节一致。

    ⚠️ 和 warp_golden() 的区别（两个都要，别混用）：
        warp_golden()       OpenCV 浮点双线性 → 「算法正确吗」（效果参考）
        golden_remap_fixed() 定点逐位复刻 RTL → 「硬件实现对吗」（正确性判据）

    上板时【必须】用本函数做 PASS/FAIL 判据：
        max|FPGA - golden_remap_fixed| 必须 == 0（逐字节一致）
    而 max|FPGA - warp_golden| 会有 1~3 灰阶的差 —— 那是 Q16.16 定点与
    浮点双线性在高对比度边缘上的固有舍入差，不是 bug。

    ⚠️ 本函数已被真实 RTL 仿真验证过：960x540 → 320x240、ROWS=256、
       板上实测的那组参数下，RTL 输出与本模型 76800 像素逐字节一致。
       （想复现：见 report/llm_log 里 2026-09-26 那条记录）

    Args:
        regs: 8 个 Q16.16 寄存器值（直接用写进硬件的那一组，最可靠）
    """
    def trunc_div(a, b):
        # div_seq 是符号-数值法，向零截断（不是 Python 的向下取整）
        q = abs(a) // abs(b)
        return q if (a >= 0) == (b >= 0) else -q

    def clamp_axis(cq, n):
        # 与 remap_core.v §4 的钳位完全一致
        if cq < 0:
            return 0, 0                    # 左越界 → 采边界像素
        iv = cq >> 16
        if iv >= n - 1:
            return n - 2, 0xFFFF           # 右越界 → 采边界像素
        return iv, (cq & 0xFFFF)

    h_in, w_in = img.shape
    a11, a12, a13, a21, a22, a23, a31, a32 = [int(v) for v in regs]
    out = np.zeros((h_out, w_out), dtype=np.uint8)

    for v in range(h_out):
        sv = v << 5                        # NORM_SCALE=2048 → FRAC_BITS-clog2(S)=5
        XN = a12 * sv + (a13 << 16)        # 行初值（u=0）
        YN = a22 * sv + (a23 << 16)
        DD = a32 * sv + (1 << 32)
        for u in range(w_out):
            xn, yn, d = XN >> 16, YN >> 16, DD >> 16
            if d == 0:
                xq = yq = 0
            else:
                xq = trunc_div(xn << 16, d)
                yq = trunc_div(yn << 16, d)
            x0, fx = clamp_axis(xq, w_in)
            y0, fy = clamp_axis(yq, h_in)
            ifx, ify = Q_ONE - fx, Q_ONE - fy
            aa = ifx * int(img[y0,     x0])     + fx * int(img[y0,     x0 + 1])
            bb = ifx * int(img[y0 + 1, x0])     + fx * int(img[y0 + 1, x0 + 1])
            out[v, u] = ((ify * aa + fy * bb + (1 << 31)) >> 32) & 0xFF
            XN += a11 << 5                 # 沿行递推（精确整数域，只在最后舍入一次）
            YN += a21 << 5
            DD += a31 << 5
    return out


def full_pipeline(img, W_out=None, H_out=None, method="auto",
                  manual_points=None, max_dim=1280):
    """
    一条龙：找四角 → 算 H → 换算寄存器。

    ⚠️ W_out / H_out 建议留空：留空时会由检测到的四边形【自动推算】，
       保持长宽比不被拉伸。写死尺寸是踩过的坑（纵向文档会被压扁）。

    Returns:
        dict(quad=..., H=..., regs=..., W_out=..., H_out=..., info=...)
        失败时 quad 为 None
    """
    quad, info = estimate_quad(img, method, manual_points)
    if quad is None:
        return dict(quad=None, H=None, regs=None, W_out=None, H_out=None,
                    info=info)

    if W_out is None or H_out is None:
        W_out, H_out = suggest_output_size(quad, max_dim)
        info += "；输出尺寸自动推算为 %dx%d" % (W_out, H_out)

    H = compute_H_out2in(quad, W_out, H_out)
    regs = homography_to_regs(H)
    return dict(quad=quad, H=H, regs=regs, W_out=W_out, H_out=H_out, info=info)


# ===========================================================================
# 自测
# ===========================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("find_homography.py 自测")
    print("=" * 70)

    # 造一张倾斜的"文档"图：白底 + 黑框 + 里面的图案
    img = np.full((480, 640), 40, dtype=np.uint8)
    quad_true = np.array([[180, 90], [520, 130], [480, 400], [140, 350]], np.float32)
    cv2.fillConvexPoly(img, quad_true.astype(np.int32), 230)
    # 加一点内部纹理（模拟文字）
    for i in range(6):
        y = 150 + i * 35
        cv2.line(img, (200, y), (480 - i * 10, y + 20), 60, 2)

    quad, info = find_quad_by_contour(img)
    print("轮廓法:", info)
    if quad is not None:
        print("  找到的四角:\n", quad)
        ok, msg = verify_quad_order(quad)
        print("  顺序校验:", msg)

        H = compute_H_out2in(quad, 320, 240)
        print("  H_out2in =\n", np.round(H, 6))
        regs = homography_to_regs(H)
        print("  8 个寄存器值:", regs)

        # 反换算回来自检：量化步长随元素量级变化
        #   h13/h23（像素量级）步长 = 1/65536 ≈ 1.5e-5
        #   h11/h12（无量纲）  步长 = 1/(2048*65536) ≈ 7.5e-12
        #   → 往返误差应远小于【粗的那个】步长
        H_back = regs_to_homography(regs)
        err = np.abs(H_back - H).max()
        step_coarse = 1.0 / (1 << 16)
        print("  寄存器往返误差: %.3e  (最粗量化步长 %.3e，占比 %.1f%%)"
              % (err, step_coarse, 100.0 * err / step_coarse))


# ======================================================================
# ===== [02/22] p1_paper_quad =====
# ======================================================================


"""Adapted P1 paper-mask algorithm, E:/P1/board/paper_quad.py (2026-10-01).
Connected-component reuse and HSV gates preserved. Original authorship stays in
P1; this snapshot is imported as a private V23 module, not an installed P1 tree.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

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


# ======================================================================
# ===== [03/22] pl_fields =====
# ======================================================================


"""Shared Q8 field and exact integer reference arithmetic (no PYNQ import)."""
from core import RELEASE_ID as RELEASE_ID; from core import cache_profile as cache_profile
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
N=21
PITCH=64

def identity_field():
    field=np.zeros((N,N,4),dtype=np.int32)
    field[:,:,2]=256
    return field

def validate_field(field):
    a=np.asarray(field)
    if a.shape!=(N,N,4) or a.dtype!=np.int32:
        raise ValueError('field 必须为 int32 [21,21,4]，Q8 dx/dy/gain/offset')
    if np.any(np.abs(a[:,:,:2].astype(np.int64))>128*256):
        raise ValueError('局部位移超过 +/-128 源像素，请降低尺寸/形变')
    if np.any(a[:,:,2]<128) or np.any(a[:,:,2]>768) or np.any(np.abs(a[:,:,3].astype(np.int64))>192*256):
        raise ValueError('gain 必须为0.5..3.0，offset 为 +/-192 (HW ABI 9)')
    return a

def interpolate(field,u,v):
    u,v=np.broadcast_arrays(np.asarray(u,dtype=np.int64),np.asarray(v,dtype=np.int64))
    x,y=u//64,v//64
    fx,fy=(u%64)[...,None],(v%64)[...,None]
    a=field[y,x].astype(np.int64);b=field[y,x+1].astype(np.int64)
    c=field[y+1,x].astype(np.int64);d=field[y+1,x+1].astype(np.int64)
    return (((a*(64-fx)+b*fx)*(64-fy)+(c*(64-fx)+d*fx)*fy)>>12)

def coordinates(regs,u,v,field):
    a,b,c,d,e,f,g,h=map(int,regs)
    u,v=np.broadcast_arrays(np.asarray(u,dtype=np.int64),np.asarray(v,dtype=np.int64))
    denominator=(g*u*32+h*v*32+(1<<32))>>16
    nx=(a*u*32+b*v*32+(c<<16))>>16
    ny=(d*u*32+e*v*32+(f<<16))>>16
    if np.any(denominator<16384) or np.any(denominator>=(1<<31)) or any(np.any(t<-(1<<31)) or np.any(t>=(1<<31)) for t in (nx,ny)):
        raise ValueError('H 超出 v4 除法器安全范围；未启动 DMA')
    def divide(t):
        t=t<<16
        return np.where(t<0,-(np.abs(t)//denominator),t//denominator)
    x,y=divide(nx),divide(ny)
    local=interpolate(field,u,v)
    x=x+(local[...,0]<<8);y=y+(local[...,1]<<8)
    if any(np.any(t<-(1<<31)) or np.any(t>=(1<<31)) for t in (x,y)):
        raise ValueError('局部校正坐标超出 Q16.16')
    return x,y,local

def schedule(regs,w_out,h_out,h_in,rows,field):
    validate_field(field)
    lows=[]; highs=[]
    u=np.arange(w_out,dtype=np.int64)
    for v in range(h_out):
        _,y,_=coordinates(regs,u,v,field)
        y0=np.clip(y>>16,0,h_in-2)
        lows.append(int(y0.min()));highs.append(int(y0.max())+1)
    floor=np.minimum.accumulate(np.asarray(lows)[::-1])[::-1]
    high=np.asarray(highs)
    span=high-floor+1
    if np.any(span>rows):
        row=int(np.argmax(span))
        raise ValueError(f'含局部位移的未来行窗口在第{row}行需要{span[row]}行，容量{rows}；未启动DMA。降低max_dim。')
    return ((high.astype(np.uint32)<<16)|floor.astype(np.uint32)),int(span.max())

def tone(rgb,local,shoulder=True):
    gain=local[...,2,None];offset=local[...,3,None]
    maximum=rgb.max(axis=-1).astype(np.int64)
    weights=np.array([255,253,251,249,247,245,243,241],dtype=np.int64)
    s=np.where(maximum<224,256,weights[np.clip((maximum-224)//4,0,7)]) if shoulder else np.full(maximum.shape,256)
    return np.clip(((rgb.astype(np.int64)*gain+offset)*s[...,None]+32768)>>16,0,255).astype(np.uint8)

def reference(image,regs,w_out,h_out,field,shoulder=True):
    h,w=image.shape[:2];out=np.empty((h_out,w_out,3),np.uint8)
    u=np.arange(w_out,dtype=np.int64)
    for v in range(h_out):
        x,y,local=coordinates(regs,u,v,field)
        xi,yi=x>>16,y>>16
        fx=np.where(x<0,0,np.where(xi>=w-1,65535,x&65535)).astype(np.uint64)[:,None]
        fy=np.where(y<0,0,np.where(yi>=h-1,65535,y&65535)).astype(np.uint64)[:,None]
        x0,y0=np.clip(xi,0,w-2),np.clip(yi,0,h-2)
        p00=image[y0,x0].astype(np.uint64);p10=image[y0,x0+1].astype(np.uint64)
        p01=image[y0+1,x0].astype(np.uint64);p11=image[y0+1,x0+1].astype(np.uint64)
        top=(65536-fx)*p00+fx*p10
        bottom=(65536-fx)*p01+fx*p11
        rgb=(((65536-fy)*top+fy*bottom+(1<<31))>>32).astype(np.uint8)
        out[v]=tone(rgb,local,shoulder)
    return out

def project__pl_fields(H,x,y):
    den=H[2,0]*x+H[2,1]*y+H[2,2]
    if np.any(np.abs(den)<1e-6):
        raise ValueError('校正场 H 分母接近零')
    return (H[0,0]*x+H[0,1]*y+H[0,2])/den,(H[1,0]*x+H[1,1]*y+H[1,2])/den

def load_calibration(path,image_shape):
    if path is None:return None
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    K=np.asarray(data['camera_matrix'],float)
    D=np.asarray(data['dist_coeffs'],float).reshape(-1)
    size=np.asarray(data['image_size'],float)
    if K.shape!=(3,3) or D.size!=5 or size.shape!=(2,) or np.any(size<=0) or not np.all(np.isfinite(K)) or not np.all(np.isfinite(D)) or not np.all(np.isfinite(size)) or K[0,0]<=0 or K[1,1]<=0:
        raise ValueError('需要有限的3x3 K、5系数[k1,k2,p1,p2,k3]、image_size=[宽,高]')
    if abs(K[0,1])>1e-8 or not np.allclose(K[2],[0,0,1]) or abs(K[1,0])>1e-8:
        raise ValueError('此版本仅支持零 skew 的 OpenCV 标准针孔相机模型')
    h,w=image_shape[:2]
    sx,sy=w/size[0],h/size[1]
    if abs(sx/sy-1)>0.01:
        raise ValueError('照片与标定图宽高比不符；不可用于不同裁剪/旋转的相机图像')
    K=K.copy();K[0,0]*=sx;K[1,1]*=sy
    K[0,2]=(K[0,2]+0.5)*sx-0.5;K[1,2]=(K[1,2]+0.5)*sy-0.5
    return K,D

def distort(K,D,x,y):
    xn=(x-K[0,2])/K[0,0];yn=(y-K[1,2])/K[1,1]
    k1,k2,p1,p2,k3=D
    r=xn*xn+yn*yn;rad=1+k1*r+k2*r*r+k3*r*r*r
    return K[0,0]*(xn*rad+2*p1*xn*yn+p2*(r+2*xn*xn))+K[0,2],K[1,1]*(yn*rad+p1*(r+2*yn*yn)+2*p2*xn*yn)+K[1,2]

def edge_bend(image,H,w_out,h_out):
    """Conservative outer-boundary estimator, not a grid/interior line detector."""
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),50,150)
    t=np.linspace(0,1,65)
    h,w=image.shape[:2];radius=max(2,min(12,round(min(h,w)*0.018)))
    fits=[];reports=[]
    for name,uu,vv in [('top',t*(w_out-1),np.zeros_like(t)),('bottom',t*(w_out-1),np.full_like(t,h_out-1)),('left',np.zeros_like(t),t*(h_out-1)),('right',np.full_like(t,w_out-1),t*(h_out-1))]:
        x,y=project__pl_fields(H,uu,vv)
        tangent=np.array([x[-1]-x[0],y[-1]-y[0]])
        normal=np.array([-tangent[1],tangent[0]])/max(1e-9,np.linalg.norm(tangent))
        chosen=[];tt=[]
        for j in range(3,62):
            offsets=np.arange(-radius,radius+1)
            xx=np.rint(x[j]+normal[0]*offsets).astype(int)
            yy=np.rint(y[j]+normal[1]*offsets).astype(int)
            inside=(xx>=0)&(xx<w)&(yy>=0)&(yy<h)
            hit=offsets[inside & (edges[np.clip(yy,0,h-1),np.clip(xx,0,w-1)]>0)]
            if len(hit):
                chosen.append(float(hit[np.argmin(np.abs(hit))]));tt.append(t[j])
        accepted=False;amplitude=0.;rms=None
        if len(tt)>=42:
            tt=np.asarray(tt);chosen=np.asarray(chosen)
            basis=4*tt*(1-tt)
            amplitude=float(np.dot(basis,chosen)/np.dot(basis,basis))
            residual=chosen-amplitude*basis
            rms=float(np.sqrt(np.mean(residual**2)))
            accepted=(rms<0.85 and 0.7<abs(amplitude)<radius*0.7 and np.mean(np.abs(residual)<1.25)>0.8)
        fits.append((normal,amplitude if accepted else 0.))
        reports.append(dict(edge=name,samples=len(tt),accepted=bool(accepted),amplitude_px=amplitude,rms_px=rms))
    def delta(u,v):
        s=np.clip(u/max(1,w_out-1),0,1);t0=np.clip(v/max(1,h_out-1),0,1)
        shape=np.broadcast(s,t0).shape;d=np.zeros(shape+(2,),float)
        for idx,weight,curve in [(0,1-t0,4*s*(1-s)),(1,t0,4*s*(1-s)),(2,1-s,4*t0*(1-t0)),(3,s,4*t0*(1-t0))]:
            normal,amp=fits[idx];d+= (weight*curve*amp)[...,None]*normal
        return d
    return delta,reports


def control_field(template_path,output_points,source_points,output_path='local_field.npz'):
    """Build a general smooth displacement field from explicit correspondences.
    Output points: desired pixel positions in the rectified output.
    Source points: matching observed positions in the PL INPUT (saved input PNG).
    These are correspondences, not automatically guessed straightness constraints.
    Four corners are fixed to the template mapping; do not repeat corner anchors.
    """
    with np.load(template_path,allow_pickle=False) as data:
        field=validate_field(data['field']).copy();regs=data['regs'].copy()
        input_shape=data['input_shape'].copy();output_shape=data['output_shape'].copy()
    ho,wo=map(int,output_shape);hi,wi=map(int,input_shape)
    target=np.asarray(output_points,float);source=np.asarray(source_points,float)
    if target.ndim!=2 or target.shape[1]!=2 or target.shape!=source.shape or len(target)<1 or len(target)>64:
        raise ValueError('需要1..64对二维对应点')
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(source)) or np.any(target<0) or np.any(target>[wo-1,ho-1]) or np.any(source<0) or np.any(source>[wi-1,hi-1]):
        raise ValueError('控制点超出输入/输出坐标范围')
    if not np.allclose(target,np.rint(target)):raise ValueError('输出控制点使用整数像素坐标')
    anchors=np.array([[0,0],[wo-1,0],[wo-1,ho-1],[0,ho-1]],float)
    xy=np.vstack([anchors,target]);scaled=xy/[max(1,wo-1),max(1,ho-1)]
    dist=np.linalg.norm(scaled[:,None,:]-scaled[None,:,:],axis=2)
    if np.any((dist+np.eye(len(xy)))<1e-4):raise ValueError('控制点重复或与固定四角过近')
    px,py,_=coordinates(regs,target[:,0],target[:,1],field)
    delta=np.vstack([np.zeros((4,2)),source-np.column_stack([px,py])/65536])
    def kernel(r):return r*r*np.log(np.maximum(r,1e-12))
    K=kernel(dist);P=np.column_stack([np.ones(len(xy)),scaled])
    system=np.block([[K+np.eye(len(xy))*1e-7,P],[P.T,np.zeros((3,3))]])
    coefficients=np.linalg.solve(system,np.vstack([delta,np.zeros((3,2))]))
    u,v=np.meshgrid(np.arange(N)*64.,np.arange(N)*64.)
    uv=np.column_stack([np.minimum(u.ravel(),wo-1)/(wo-1),np.minimum(v.ravel(),ho-1)/(ho-1)])
    basis=np.column_stack([kernel(np.linalg.norm(uv[:,None,:]-scaled[None,:,:],axis=2)),np.ones(len(uv)),uv])
    change=(basis@coefficients).reshape(N,N,2)
    if not np.all(np.isfinite(change)) or np.max(np.abs(change))>128:raise ValueError('控制点形成过大/不稳定位移')
    field[:,:,:2]+=np.rint(change*256).astype(np.int32)
    validate_field(field)
    # Re-evaluate true integer row lifetimes before writing a usable field.
    schedule(regs,wo,ho,hi,cache_profile(wi)[1],field)
    np.savez(output_path,field=field,regs=regs,input_shape=input_shape,output_shape=output_shape)
    return str(output_path)


# ======================================================================
# ===== [04/22] v8_plan =====
# ======================================================================


"""Immutable snapshots of plans already validated by the geometry planner.

Not a security boundary against hostile Python code. Prevents accidental mutation
and substitution of a stale table in the supported runner/runtime path.
"""
from core import RELEASE_ID as RELEASE_ID; from core import EXPECTED_HW as EXPECTED_HW; from core import cache_profile as cache_profile
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_TOKEN=object()

def _parameters(data):
    return (tuple(data['input_shape']),data['width'],data['height'],
            tuple(data['regs']),data['border_flags'])

class ControlSnapshot:
    """Checked immutable wire bytes shared by preflight and sealed execution."""
    __slots__=('parameters','field','packet','key','backend','_token')
    def __init__(self,data,packet,backend,token):
        if token is not _TOKEN:raise TypeError('Use internal control preparation')
        if len(packet)!=1776*4:raise ValueError('ABI9控制包长度错误')
        object.__setattr__(self,'parameters',_parameters(data))
        object.__setattr__(self,'key',packet)
        object.__setattr__(self,'packet',np.frombuffer(packet,dtype='<u4'))
        object.__setattr__(self,'field',np.frombuffer(packet,dtype='<i4',offset=48).reshape(21,21,4))
        object.__setattr__(self,'backend',backend)
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Control snapshot is immutable')
    def matches(self,data,field):
        return field is self.field and self._token is _TOKEN and _parameters(data)==self.parameters

def checked_control(data,field):
    saved=data.get('_control_snapshot')
    return saved if type(saved) is ControlSnapshot and saved.matches(data,field) else None

class ControlContractError(RuntimeError):
    """A producer/consumer mismatch, not a geometry fallback or a PL proof."""

class InputLayoutError(ControlContractError):
    """Invalid YUYV metadata cannot be repaired by subdividing output tiles."""

def require_yuyv_shape(input_shape):
    """Keep source storage metadata distinct from a temporary BGR model image."""
    try:
        shape=tuple(input_shape)
        valid=(len(shape)==3 and shape[2]==2 and shape[1]%2==0
               and all(not isinstance(n,(bool,np.bool_)) and int(n)==n and int(n)>=2 for n in shape))
    except (TypeError,ValueError,OverflowError):
        valid=False
    if not valid:
        raise InputLayoutError('V31 plans require pair-aligned YUYV; actual input_shape='+repr(input_shape))
    return tuple(int(n) for n in shape)

def require_control_snapshot(data):
    """One key/packet API for frozen candidates and PL-certified plans.

    This checks CPU packet identity only. It never grants row-lifetime safety,
    seals a candidate, or accesses hardware. The key is the immutable wire bytes;
    no per-frame re-encoding or hashing is necessary.
    """
    if type(data) in (FrozenControlCandidate,ValidatedPlan) and data._token is _TOKEN:
        # Factory checked metadata once; every reachable parameter/field/packet
        # is immutable. This path confers no hardware row-lifetime certificate.
        return data['_control_snapshot']
    if not isinstance(data,Mapping):raise ControlContractError('Control candidate must be a mapping')
    try:
        saved=checked_control(data,data['field'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ControlContractError('Control candidate metadata is incomplete') from exc
    if saved is None:raise ControlContractError('Control snapshot missing or parameters/field changed after freezing')
    if (saved.packet.dtype!=np.dtype('<u4') or saved.packet.shape!=(1776,)
            or saved.packet.flags.writeable or saved.field.flags.writeable):
        raise ControlContractError('Control snapshot layout/immutability mismatch')
    if 'control_key' in data and data['control_key']!=saved.key:
        raise ControlContractError('Published control key differs from checked snapshot')
    if 'control_packet' in data and data['control_packet'] is not saved.packet:
        raise ControlContractError('Published control packet differs from checked snapshot')
    return saved

def _freeze_control(data,backend='auto'):
    """Validate every channel before image DMA, then retain the exact wire bytes."""
    if backend not in ('auto','legacy'):raise ValueError('control_backend须为auto/legacy')
    require_yuyv_shape(data['input_shape'])
    hi,wi=data['input_shape'][:2];wo,ho=data['width'],data['height']
    if any(isinstance(n,bool) or int(n)!=n or not 2<=int(n)<=1280 for n in (wi,hi,wo,ho)):
        raise ValueError('单块尺寸必须为2..1280整数')
    regs=tuple(data['regs']);flags=data['border_flags']
    if len(regs)!=8 or any(isinstance(n,bool) or int(n)!=n or not -(1<<31)<=int(n)<(1<<31) for n in regs):
        raise ValueError('H寄存器必须为signed32整数')
    if isinstance(flags,bool) or int(flags)!=flags or not 0<=int(flags)<16:raise ValueError('源图边界标记错误')
    f=np.asarray(data['field']);packet=None
    if backend=='auto':
        from tracking import encode_packet__v31_native as encode_packet
        packet=encode_packet(f,regs,int(wi),int(hi),int(wo),int(ho),int(flags))
    name='cpp_checked_immutable_packet'
    if packet is None:
        f=validate_field(f)
        packet=struct.pack('<3I8iI',0x50394c44,(int(wi)<<16)|int(hi),(int(wo)<<16)|int(ho),
                           *regs,int(flags))+f.tobytes()
        name='python_checked_immutable_packet'
    data['regs']=regs
    frozen=ControlSnapshot(data,packet,name,_TOKEN)
    data['_control_snapshot']=frozen;data['field']=frozen.field
    return frozen


class ValidatedPlan(Mapping):
    __slots__=('_data','_token')
    def __init__(self,data,token):
        if token is not _TOKEN:raise TypeError('Use the geometry planner to create a validated plan')
        snapshot=dict(data)
        require_yuyv_shape(snapshot['input_shape'])
        for name in ('box','crop','regs','input_shape'):snapshot[name]=tuple(snapshot[name])
        # bytes-backed arrays cannot have WRITEABLE re-enabled by the caller.
        frozen=checked_control(data,data['field'])
        if frozen is None:frozen=_freeze_control(snapshot)
        snapshot['field']=frozen.field
        snapshot['descriptors']=np.frombuffer(np.asarray(data['descriptors'],np.uint32).tobytes(),np.uint32)
        # Encode once, after the same planner/field checks. Both views are backed
        # by immutable bytes: later table edits cannot retain a stale packet key.
        snapshot['_control_snapshot']=frozen
        snapshot['control_key']=frozen.key
        snapshot['control_packet']=frozen.packet
        object.__setattr__(self,'_data',MappingProxyType(snapshot))
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Validated plan is immutable')
    def __getitem__(self,key):return self._data[key]
    def __iter__(self):return iter(self._data)
    def __len__(self):return len(self._data)


class FrozenControlCandidate(Mapping):
    """Factory-owned immutable CPU packet; deliberately distinct from ValidatedPlan."""
    __slots__=('_data','_token')
    def __init__(self,data,token):
        if token is not _TOKEN:raise TypeError('Use internal candidate factory')
        snapshot=dict(data)
        for name in ('box','crop','regs','input_shape'):snapshot[name]=tuple(snapshot[name])
        frozen=require_control_snapshot(snapshot)
        snapshot['field']=frozen.field
        snapshot['control_key']=frozen.key;snapshot['control_packet']=frozen.packet
        snapshot['descriptors']=np.frombuffer(np.asarray(snapshot['descriptors'],np.uint32).tobytes(),np.uint32)
        object.__setattr__(self,'_data',MappingProxyType(snapshot))
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Frozen candidate is immutable')
    def __getitem__(self,key):return self._data[key]
    def __iter__(self):return iter(self._data)
    def __len__(self):return len(self._data)

def freeze_candidate(data):
    if type(data) in (FrozenControlCandidate,ValidatedPlan) and data._token is _TOKEN:return data
    return FrozenControlCandidate(data,_TOKEN)

def _seal_checked(data,input_shape):
    """Internal: caller checked crop/model guards and exact PL row planning."""
    shape=require_yuyv_shape(input_shape)
    if require_yuyv_shape(data['input_shape'])!=shape:
        raise InputLayoutError('Certified candidate input_shape differs from execution input_shape')
    if '_control_snapshot' in data:require_control_snapshot(data)
    d=dict(data);d.update(input_shape=shape,hardware_abi=EXPECTED_HW,release_id=RELEASE_ID)
    return ValidatedPlan(d,_TOKEN)


def require_plan(plan,input_shape):
    if type(plan) is not ValidatedPlan or plan._token is not _TOKEN:
        raise ValueError('需要本版规划器生成的不可变计划，不能传入自行修改的dict')
    if tuple(input_shape)!=plan['input_shape'] or plan['hardware_abi']!=EXPECTED_HW or plan['release_id']!=RELEASE_ID:
        raise ValueError('计划的输入尺寸、硬件ABI或发布版本不匹配')
    if plan.get('planning_backend')!='pl_exact_suffix_rows':raise ValueError('需要ABI9的PL规划证明')
    if cache_profile(input_shape[1])[1]!=plan['capacity_rows']:
        raise ValueError('缓存档位与计划不匹配')
    return plan


def with_tone(plan,gain_q8,offset_q8):
    """Replace only photometric channels: dx/dy, crop and row lifetime are intact."""
    require_plan(plan,plan['input_shape'])
    if np.shape(gain_q8)!=(21,21) or np.shape(offset_q8)!=(21,21):
        raise ValueError('光补系数须为21x21')
    field=plan['field'].copy();field[:,:,2]=gain_q8;field[:,:,3]=offset_q8
    validate_field(field)
    d=dict(plan);d['field']=field
    return ValidatedPlan(d,_TOKEN)


def _bind_native_control(data,packet):
    """Internal output of checked native preparation; still NOT a PL proof."""
    if not isinstance(packet,bytes) or len(packet)!=1776*4:
        raise ValueError('native control packet length invalid')
    require_yuyv_shape(data['input_shape'])
    hi,wi=data['input_shape'][:2];wo,ho=data['width'],data['height']
    header=struct.unpack_from('<3I8iI',packet)
    if header[:3]!=(0x50394c44,(wi<<16)|hi,(wo<<16)|ho) or header[-1]!=data['border_flags']:
        raise ValueError('native control packet dimensions/flags mismatch')
    data['regs']=tuple(header[3:11])
    frozen=ControlSnapshot(data,packet,'cpp_geometry_guard_tone_packet',_TOKEN)
    data['_control_snapshot']=frozen;data['field']=frozen.field
    return frozen


# ======================================================================
# ===== [05/22] v8_surface =====
# ======================================================================


"""Regularized local surface from long dark-line centres, no grid-spacing prior."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
NX,NY=7,5


@lru_cache(maxsize=4)
def _knots(n):
    knots=np.r_[np.zeros(4),np.linspace(0,1,n-2)[1:-1],np.ones(4)]
    knots.setflags(write=False)
    return knots


def basis(z,n):
    """Open uniform cubic B-spline basis with polynomial end continuation.

    Continuation matters: hardware nodes can lie past the last active pixel.
    Clamping the function there creates derivative discontinuities.
    """
    z=np.asarray(z,float)
    knots=_knots(n)
    b=((z[...,None]>=knots[:-1])&(z[...,None]<knots[1:])).astype(float)
    b[...,3]=np.where(z<0,1.,b[...,3])
    b[...,n-1]=np.where(z>=1,1.,b[...,n-1])
    for degree in (1,2,3):
        size=len(knots)-degree-1
        out=np.zeros(z.shape+(size,))
        for i in range(size):
            left=knots[i+degree]-knots[i]
            right=knots[i+degree+1]-knots[i+1]
            if left:out[...,i]+=(z-knots[i])/left*b[...,i]
            if right:out[...,i]+=(knots[i+degree+1]-z)/right*b[...,i+1]
        b=out
    return b


def design(x,y):
    x,y=np.broadcast_arrays(np.asarray(x,float),np.asarray(y,float))
    bx=basis(x,NX)*((x*(1-x))[...,None]);by=basis(y,NY)
    return (by[..., :,None]*bx[...,None,:]).reshape(x.shape+(NX*NY,))


@lru_cache(maxsize=24)
def _grid_basis(x_axis,y_axis):
    x=np.asarray(x_axis,float);y=np.asarray(y_axis,float)
    bx=basis(x,NX)*(x*(1-x))[:,None];by=basis(y,NY)
    bx.setflags(write=False);by.setflags(write=False)
    return bx,by


_PENALTY=np.vstack([.20*np.kron(np.eye(NY),np.diff(np.eye(NX),n=2,axis=0)),
                    .20*np.kron(np.diff(np.eye(NY),n=2,axis=0),np.eye(NX)),
                    .01*np.eye(NX*NY)])
_PENALTY.setflags(write=False)


def evaluate_grid(coeff,x_axis,y_axis):
    """Return (len(y_axis), len(x_axis)) samples of the SAME cubic surface."""
    x_axis=np.asarray(x_axis,float);y_axis=np.asarray(y_axis,float)
    if not np.any(coeff):return np.zeros((y_axis.size,x_axis.size),float)
    if max(x_axis.size,y_axis.size)<=128:
        bx,by=_grid_basis(tuple(x_axis),tuple(y_axis))
    else:
        bx=basis(x_axis,NX)*(x_axis*(1-x_axis))[:,None]
        by=basis(y_axis,NY)
    return cv2.gemm(cv2.gemm(np.ascontiguousarray(by),np.ascontiguousarray(coeff,dtype=np.float64),1.,None,0.),
                    np.ascontiguousarray(bx.T),1.,None,0.)


def evaluate(coeff,x,y):
    x,y=np.broadcast_arrays(np.asarray(x,float),np.asarray(y,float))
    if not np.any(coeff):return np.zeros(x.shape,float)
    if x.ndim==2:
        if np.array_equal(x,np.broadcast_to(x[:1,:],x.shape)) and np.array_equal(y,np.broadcast_to(y[:,:1],y.shape)):
            return evaluate_grid(coeff,x[0,:],y[:,0])
        if np.array_equal(x,np.broadcast_to(x[:,:1],x.shape)) and np.array_equal(y,np.broadcast_to(y[:1,:],y.shape)):
            return evaluate_grid(coeff,x[:,0],y[0,:]).T
    bx=basis(x,NX);by=basis(y,NY)
    # Avoid a dense (...,35) tensor for preview/full-map points.
    result=np.zeros(x.shape,float)
    for j in range(NY):
        row=np.zeros(x.shape,float)
        for i in range(NX):row+=coeff[j,i]*bx[...,i]
        result+=row*by[...,j]
    return result*x*(1-x)


def _peaks(values,gap):
    values=np.asarray(values,float)
    candidates=np.flatnonzero((values>=np.roll(values,1))&(values>=np.roll(values,-1))&
                             (values>max(4,.25*values.max())))
    chosen=[]
    for i in sorted(candidates,key=lambda i:values[i],reverse=True):
        if all(abs(int(i)-j)>=gap for j in chosen):chosen.append(int(i))
    return sorted(chosen)


def line_surface(gray,ink=None,solver='qr',tracking_backend='batch'):
    """Track subpixel line centres; fit a shared smooth local displacement.

    A whole family of genuinely curved artwork is ambiguous: caller must use
    document/lines mode only where straight-line evidence is appropriate.
    """
    started=time.perf_counter()
    h,w=gray.shape
    if solver not in ('qr','svd'):raise ValueError('surface_solver须为qr/svd')
    if tracking_backend not in ('batch','legacy'):raise ValueError('surface_tracking须为batch/legacy')
    batch_count=0
    threshold_s=morphology_s=profile_prepare_s=profile_stats_s=crossing_s=track_filter_s=0.
    def inactive(reason,n=0,**evidence):
        defaults=dict(tracking_backend=tracking_backend,profile_batches=batch_count,tracking_s=time.perf_counter()-started,fit_s=0.,solves=0,
                      threshold_s=threshold_s,morphology_s=morphology_s,
                      profile_prepare_s=profile_prepare_s,profile_statistics_s=profile_stats_s,
                      crossing_s=crossing_s,track_filter_s=track_filter_s)
        defaults.update(evidence)
        return np.zeros((65,65),np.float32),dict(state='inactive',accepted=0,candidates=n,
                       reason=reason,**defaults),np.zeros((NY,NX))
    if min(h,w)<48:return inactive('preview_too_small')
    t=time.perf_counter()
    if ink is None:
        ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,9)
    elif ink.shape!=gray.shape or ink.dtype!=np.uint8:
        raise ValueError('shared threshold shape/dtype mismatch')
    threshold_s=time.perf_counter()-t;t=time.perf_counter()
    horizontal=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(9,w//35)),np.uint8))
    seeds=_peaks((horizontal>0).sum(axis=1),max(6,h//70))
    morphology_s=time.perf_counter()-t
    if len(seeds)<5:
        return inactive('fewer_than_five_seed_candidates',len(seeds),tracking_s=time.perf_counter()-started,
                        fit_s=0.,solves=0,threshold_s=threshold_s,morphology_s=morphology_s)
    xs=np.linspace(.04*(w-1),.96*(w-1),41)
    tracks=[];half=max(2,w//90)
    bounds=[(max(0,int(x)-half),min(w,int(x)+half+1)) for x in xs]
    equal_width=len({b-a for a,b in bounds})==1
    windows=[]
    for seed in seeds:
        neighbours=[abs(seed-other) for other in seeds if other!=seed]
        radius=int(max(3,min(h*.03,(min(neighbours) if neighbours else h*.06)*.43)))
        windows.append((max(0,seed-radius),min(h,seed+radius+1),radius))
    # Median of the SAME source strip is independent of which line is tracked.
    # Compute each needed row once, even when neighbouring search windows overlap.
    t=time.perf_counter();needed=np.zeros(h,bool)
    for lo,hi,_ in windows:needed[lo:hi]=True
    needed_rows=np.flatnonzero(needed);source=gray[needed_rows]
    if equal_width and tracking_backend=='batch':
        strips=np.stack([source[:,a:b] for a,b in bounds])
        median_index=strips.shape[2]//2
        # Strip widths here are odd (2*half+1); uint8 selection is the exact median.
        strips.partition(median_index,axis=2)
        all_profiles=strips[:,:,median_index].astype(float)
    elif equal_width:
        all_profiles=np.median(np.stack([source[:,a:b] for a,b in bounds]),axis=2).astype(float)
    else:
        all_profiles=np.stack([np.median(source[:,a:b],axis=1) for a,b in bounds]).astype(float)
    profiles_by_row=np.zeros((len(xs),h),float)
    profiles_by_row[:,needed_rows]=all_profiles
    profile_prepare_s=time.perf_counter()-t
    if tracking_backend=='batch':
        batch_hits,batch_stats,batch_count=_batch_crossings(profiles_by_row,windows,xs)
        profile_stats_s+=batch_stats['statistics_s'];crossing_s+=batch_stats['crossing_s']
    for window_index,(lo,hi,radius) in enumerate(windows):
        if tracking_backend=='batch':
            hits=batch_hits[window_index]
        else:
            profiles=profiles_by_row[:,lo:hi];t=time.perf_counter()
            backgrounds=np.percentile(profiles,80,axis=1)
            minima=np.argmin(profiles,axis=1)
            profile_stats_s+=time.perf_counter()-t;t=time.perf_counter()
            # Exact contiguous half-depth component around each minimum. Batch all
            # profiles; no per-pixel/profile while loops, same strict '< level' rule.
            depth=backgrounds-profiles[np.arange(len(xs)),minima]
            levels=backgrounds-depth*.5
            axis=np.arange(profiles.shape[1])[None,:]
            below=profiles<levels[:,None]
            left=np.max(np.where((axis<minima[:,None])&~below,axis,-1),axis=1)+1
            right=np.min(np.where((axis>minima[:,None])&~below,axis,profiles.shape[1]),axis=1)-1
            good=(depth>=18)&(minima>0)&(minima<profiles.shape[1]-1)
            good&=(left>0)&(right<profiles.shape[1]-1)&(right-left+1<=max(7,radius))
            k=np.flatnonzero(good);l=left[k];r=right[k]
            edge_l=l-1+(profiles[k,l-1]-levels[k])/np.maximum(profiles[k,l-1]-profiles[k,l],1e-6)
            edge_r=r+(levels[k]-profiles[k,r])/np.maximum(profiles[k,r+1]-profiles[k,r],1e-6)
            hits=np.column_stack([xs[k],lo+(edge_l+edge_r)/2])
            crossing_s+=time.perf_counter()-t
        if len(hits)<30:continue
        t=time.perf_counter()
        xy=np.asarray(hits);z=xy[:,0]/(w-1)
        # Polynomial only rejects mis-tracked samples; actual samples feed the
        # spline, so the final local model is not limited to cubic tracks.
        c=np.polyfit(z,xy[:,1],3);errors=xy[:,1]-np.polyval(c,z)
        keep=abs(errors)<1.8
        if keep.sum()<30:
            track_filter_s+=time.perf_counter()-t
            continue
        xy=xy[keep];z=z[keep]
        c=np.polyfit(z,xy[:,1],3);ends=np.polyval(c,[0.,1.])
        chord=ends[0]+(ends[1]-ends[0])*z;delta=xy[:,1]-chord
        if np.max(abs(delta))>max(4,h*.04):
            track_filter_s+=time.perf_counter()-t
            continue
        level=float(np.median(chord))
        if 2<level<h-3:tracks.append((level,z,chord/(h-1),delta))
        track_filter_s+=time.perf_counter()-t
    tracks.sort(key=lambda p:p[0]);unique=[]
    for track in tracks:
        if not unique or track[0]-unique[-1][0]>2:unique.append(track)
    tracks=unique;n=len(tracks)
    if n<5:return inactive('fewer_than_five_supported_curves',n)
    coverage=(tracks[-1][0]-tracks[0][0])/(h-1)
    if coverage<.45:return inactive('insufficient_coverage',n,coverage=float(coverage))
    tracking_s=time.perf_counter()-started
    fit_started=time.perf_counter()
    target=np.concatenate([t[3] for t in tracks])
    baseline=float(np.sqrt(np.mean(target**2)))
    if baseline<.15:
        return inactive('curvature_below_preview_resolution',n,
            model='regularized_cubic_bspline_5x7',coverage=float(coverage),
            uncorrected_curve_rms=baseline,validation_folds=0,measured_points=len(target),
            tracking_s=tracking_s,fit_s=time.perf_counter()-fit_started,solves=0)
    A=design(np.concatenate([t[1] for t in tracks]),np.concatenate([t[2] for t in tracks]))
    ids=np.concatenate([np.full(len(t[1]),i) for i,t in enumerate(tracks)])
    # Second differences suppress spurious waves while allowing local curvature.
    penalty=_PENALTY
    solve_seconds=0.;qr_fallbacks=0;solve_count=0
    def product(a,b):
        return _native_matvec(a,b) if tracking_backend=='batch' else a@b
    def solve(a,b,weights=None):
        nonlocal solve_seconds,qr_fallbacks,solve_count
        solve_count+=1;t=time.perf_counter()
        weights=np.ones(len(b)) if weights is None else weights
        root=np.sqrt(weights)
        augmented=np.ascontiguousarray(np.vstack([a*root[:,None],penalty]),dtype=np.float64)
        rhs=np.ascontiguousarray(np.r_[b*root,np.zeros(len(penalty))],dtype=np.float64)
        coeff=None
        if solver=='qr':
            # Solve the augmented least-squares system directly: no normal
            # equations, no squared condition number, same regularized objective.
            try:
                ok,value=cv2.solve(augmented,rhs[:,None],flags=cv2.DECOMP_QR)
                if ok and value is not None:
                    trial=value.reshape(-1)
                    if trial.size==NX*NY and np.all(np.isfinite(trial)):
                        residual=product(augmented,trial)-rhs
                        gradient=product(augmented.T,residual)
                        # Backward stationarity guard; retain SVD as fallback.
                        scale=max(1.,np.linalg.norm(augmented,1)*np.linalg.norm(augmented,np.inf)*
                                  np.linalg.norm(trial,np.inf)+np.linalg.norm(product(augmented.T,rhs),np.inf))
                        if np.linalg.norm(gradient,np.inf)<=1e-9*scale:coeff=trial
            except cv2.error:
                pass
            if coeff is None:qr_fallbacks+=1
        if coeff is None:
            coeff=np.linalg.lstsq(augmented,rhs,rcond=None)[0]
        solve_seconds+=time.perf_counter()-t
        return coeff
    coefficients=solve(A,target)
    for _ in range(2):
        error=product(A,coefficients)-target
        coefficients=solve(A,target,np.minimum(1.,.6/np.maximum(abs(error),1e-6)))
    # Three interleaved folds hold out whole curves. A fixed number of solves
    # replaces one solve for every line, bounding work on densely ruled pages.
    held=np.zeros_like(target)
    for fold in range(3):
        train=ids%3!=fold;c=solve(A[train],target[train])
        held[~train]=product(A[~train],c)-target[~train]
    baseline=float(np.sqrt(np.mean(target**2)))
    rms=float(np.sqrt(np.mean((product(A,coefficients)-target)**2)))
    cv=float(np.sqrt(np.mean(held**2)))
    info=dict(model='regularized_cubic_bspline_5x7',coverage=float(coverage),fit_rms=rms,
              held_out_rms=cv,uncorrected_curve_rms=baseline,validation_folds=3,solves=solve_count,
              solver='opencv_qr_with_svd_fallback' if solver=='qr' else 'svd_lstsq',
              tracking_backend=tracking_backend,profile_batches=batch_count,
              matrix_backend='opencv_gemm' if tracking_backend=='batch' else 'numpy',
              qr_fallbacks=qr_fallbacks,solve_s=solve_seconds,
              threshold_s=threshold_s,morphology_s=morphology_s,
              profile_prepare_s=profile_prepare_s,profile_statistics_s=profile_stats_s,
              crossing_s=crossing_s,track_filter_s=track_filter_s,
              measured_points=int(len(target)),tracking_s=tracking_s,
              fit_s=time.perf_counter()-fit_started)
    if baseline<.15:return inactive('curvature_below_preview_resolution',n,**info)
    if cv>min(.85,.85*baseline) or rms>.75:
        return inactive('curves_do_not_support_local_surface',n,**info)
    coefficients=coefficients.reshape(NY,NX)
    # Displacement/Jacobian guards need a small geometry grid, not full-resolution
    # images. Coefficients remain authoritative at PL node evaluation time.
    yy,xx=np.meshgrid(np.linspace(0,1,65),np.linspace(0,1,65),indexing='ij')
    field=evaluate(coefficients,xx,yy).astype(np.float32)
    if np.max(abs(field))>max(4,h*.04):return inactive('extrapolation_too_large',n,**info)
    return field,dict(state='active',accepted=n,candidates=n,
                     max_preview_displacement=float(np.max(abs(field))),**info),coefficients


def _native_matvec(matrix,vector):
    """Float64 products without dispatching small problems to threaded BLAS."""
    matrix=np.ascontiguousarray(matrix,dtype=np.float64)
    vector=np.ascontiguousarray(vector,dtype=np.float64).reshape(-1,1)
    return cv2.gemm(matrix,vector,1.,None,0.).reshape(-1)


def _batch_crossings(profiles_by_row,windows,xs):
    """Same 80% quantile and contiguous half-depth rule, grouped by length.

    Grouping retains each window's exact samples. There is no padded quantile,
    changed threshold, grid-spacing prior or reduction of held-out curves.
    """
    groups={};hits=[None]*len(windows);statistics_s=crossing_s=0.
    for i,(lo,hi,radius) in enumerate(windows):
        groups.setdefault(hi-lo,[]).append(i)
    count=len(xs)
    for length,indices in groups.items():
        profiles=np.stack([profiles_by_row[:,windows[i][0]:windows[i][1]] for i in indices])
        t=time.perf_counter()
        backgrounds=np.percentile(profiles,80,axis=2)
        minima=np.argmin(profiles,axis=2)
        statistics_s+=time.perf_counter()-t;t=time.perf_counter()
        rows=np.arange(count)[None,:]
        batches=np.arange(len(indices))[:,None]
        depth=backgrounds-profiles[batches,rows,minima]
        levels=backgrounds-depth*.5
        axis=np.arange(length)[None,None,:]
        below=profiles<levels[:,:,None]
        left=np.max(np.where((axis<minima[:,:,None])&~below,axis,-1),axis=2)+1
        right=np.min(np.where((axis>minima[:,:,None])&~below,axis,length),axis=2)-1
        radius=np.array([windows[i][2] for i in indices])[:,None]
        good=(depth>=18)&(minima>0)&(minima<length-1)
        good&=(left>0)&(right<length-1)&(right-left+1<=np.maximum(7,radius))
        batch_index,k=np.nonzero(good);l=left[batch_index,k];r=right[batch_index,k]
        q=profiles[batch_index,k];level=levels[batch_index,k]
        sample=np.arange(len(k))
        edge_l=l-1+(q[sample,l-1]-level)/np.maximum(q[sample,l-1]-q[sample,l],1e-6)
        edge_r=r+(level-q[sample,r])/np.maximum(q[sample,r+1]-q[sample,r],1e-6)
        centre=(edge_l+edge_r)/2
        for local,i in enumerate(indices):
            selected=batch_index==local
            hits[i]=np.column_stack([xs[k[selected]],windows[i][0]+centre[selected]])
        crossing_s+=time.perf_counter()-t
    return hits,dict(statistics_s=statistics_s,crossing_s=crossing_s),len(groups)


# ======================================================================
# ===== [06/22] v8_tables =====
# ======================================================================


"""Small-array Gaussian/CLAHE LUT construction and conservative row schedule."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def tile_shift(width,height):
    return max(5,(max(width,height)-1).bit_length()-3)

def _range_grid(wo,ho,field):
    starts=np.arange(0,wo,64,dtype=np.int64)
    u=np.stack([starts,np.minimum(starts+63,wo-1)],axis=-1)[None,:,:]
    v=np.arange(ho,dtype=np.int64)[:,None,None]
    local=interpolate(field[:,:,:2],u,v)/256.
    return u,v,local.min(axis=2),local.max(axis=2)


def mapping_ranges(regs,wo,ho,field=None,*,_grid=None):
    field=identity_field() if field is None else validate_field(field)
    if len(regs)!=8 or any(not -(1<<31)<=int(r)<(1<<31) for r in regs):
        raise ValueError('H 参数超出int32')
    a,b,c,d,e,f,g,h=map(int,regs)
    u,v,shift_low,shift_high=_range_grid(wo,ho,field) if _grid is None else _grid
    den=g*u*32+h*v*32+(1<<32)
    nums=[a*u*32+b*v*32+(c<<16),d*u*32+e*v*32+(f<<16)]
    if np.any((den>>16)<16384) or np.any((den>>16)>=(1<<31)):
        raise ValueError('H分母不安全，未启动DMA')
    ranges=[]
    for axis,num in enumerate(nums):
        if np.any((num>>16)<-(1<<31)) or np.any((num>>16)>=(1<<31)):
            raise ValueError('H被除数不安全')
        ratios=num/den
        dmin=np.min(den,axis=-1)/65536.
        # Truncation of N,D before division + final signed Q16 truncation.
        guard=(1+np.max(np.abs(ratios),axis=-1))/(dmin-1)+1/65536.+1e-7
        low=np.min(ratios,axis=-1)-guard+shift_low[...,axis]
        high=np.max(ratios,axis=-1)+guard+shift_high[...,axis]
        if np.any(low<=-32768) or np.any(high>=32767):raise ValueError('校正坐标越界')
        ranges.append((low.min(axis=1),high.max(axis=1)))
    return ranges

class WindowOverflow(ValueError):
    def __init__(self,message,split_axis):
        super().__init__(message)
        self.split_axis=split_axis


def schedule_from_ranges(ranges,hi,rows):
    lo,high=ranges[1]
    lowrows=np.clip(np.floor(lo),0,hi-2).astype(np.int64)
    highrows=np.clip(np.floor(high),0,hi-2).astype(np.int64)+1
    floor=np.minimum.accumulate(lowrows[::-1])[::-1]
    span=highrows-floor+1
    if np.any(span>rows):
        k=int(np.argmax(span))
        # Width helps when ONE row spans too many source rows. Height helps
        # when later output rows force much earlier source data to remain live.
        axis='x' if highrows[k]-lowrows[k]+1>rows else 'y'
        raise WindowOverflow(f'含局部校正的保守窗口第{k}行需要{span[k]}行，容量{rows}；未启动DMA。',axis)
    return ((highrows.astype(np.uint32)<<16)|floor.astype(np.uint32)),int(span.max())


def safe_schedule(regs,wo,ho,hi,rows=128,field=None):
    return schedule_from_ranges(mapping_ranges(regs,wo,ho,field),hi,rows)


def tables_from_histogram(counts,width,height,shift,profile='photo',strength=.7,clip_limit=2.0):
    if profile not in ('document','photo'):raise ValueError('profile 为 document/photo')
    if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError('strength 为0..1')
    if not np.isfinite(clip_limit) or not 1<=clip_limit<=8:raise ValueError('clip_limit 为1..8')
    hist=np.asarray(counts,dtype=np.uint32).reshape(8,8,64)
    pitch=1<<shift;nx=(width+pitch-1)//pitch;ny=(height+pitch-1)//pitch
    totals=hist.astype(np.uint64).sum(axis=2)
    expected=np.zeros((8,8),np.uint64)
    for y in range(ny):
        for x in range(nx):expected[y,x]=min(pitch,height-y*pitch)*min(pitch,width-x*pitch)
    if not np.array_equal(totals,expected):raise ValueError('PL分块直方图像素数不符，不进行第二遍')
    # Quantile background for documents; broad scene illumination for photographs.
    active=hist[:ny,:nx].astype(np.float64)
    sums=active.sum(axis=2)
    centers=np.arange(64)*4+1.5
    if profile=='document':
        bg=(np.argmax(np.cumsum(active,axis=2)>=sums[:,:,None]*.90,axis=2)*4+3).astype(np.float32)
    else:bg=((active*centers).sum(axis=2)/sums).astype(np.float32)
    smooth=cv2.GaussianBlur(bg,(5,5),0,borderType=cv2.BORDER_REPLICATE)
    target=float(np.median(smooth))
    normalized_gain=np.clip(target/np.maximum(smooth,24),.65,1.6)
    light_strength=strength if profile=='document' else strength*.4
    gains=1+light_strength*(normalized_gain-1)
    lut=np.empty((8,8,256),np.uint8)
    levels=np.arange(256,dtype=float)
    for y in range(ny):
        for x in range(nx):
            # Build the local CDF in the normalized luminance domain.
            mapped=np.clip(np.floor(centers*gains[y,x]/4),0,63).astype(int)
            rebinned=np.bincount(mapped,weights=active[y,x],minlength=64)
            cap=clip_limit*sums[y,x]/64.
            clipped=np.minimum(rebinned,cap)
            clipped+=(sums[y,x]-clipped.sum())/64.
            cdf=np.cumsum(clipped)/sums[y,x]*255.
            normal=np.clip(levels*gains[y,x],0,255)
            contrast=np.interp(normal,centers,cdf,left=0,right=255)
            amount=strength if profile=='document' else strength*.5
            result=(1-amount)*normal+amount*contrast
            # Constant/near-constant tiles contain no reliable local contrast.
            if np.count_nonzero(active[y,x])<=1:result=normal
            lut[y,x]=np.clip(np.rint(result),0,255).astype(np.uint8)
    for y in range(8):
        for x in range(8):
            if y>=ny or x>=nx:lut[y,x]=lut[min(y,ny-1),min(x,nx-1)]
    return lut,dict(profile=profile,strength=strength,clip_limit=clip_limit,tiles=[nx,ny],pitch=pitch,
                   background=smooth.tolist(),gains=gains.tolist(),histogram_pixels=int(totals.sum()))

def pack_tables(lut):
    q=np.asarray(lut,dtype=np.uint8).reshape(-1,4).astype(np.uint32)
    return q[:,0]|(q[:,1]<<8)|(q[:,2]<<16)|(q[:,3]<<24)

def apply_tables(rgb,lut,shift):
    h,w=rgb.shape[:2];pitch=1<<shift;nx=(w+pitch-1)//pitch;ny=(h+pitch-1)//pitch
    def positions(p,n):
        relative=np.maximum(p-pitch//2,0)
        base=relative>>shift;frac=(relative&(pitch-1))<<(8-shift)
        if n<=1:return np.zeros_like(base),np.zeros_like(frac)
        end=base>=n-1
        return np.where(end,n-2,base),np.where(end,256,frac)
    xx,fx=positions(np.arange(w)[None,:],nx);yy,fy=positions(np.arange(h)[:,None],ny)
    q=rgb.astype(np.int32);Y=(q[:,:,2]*77+q[:,:,1]*150+q[:,:,0]*29+128)>>8
    a=lut[yy,xx,Y].astype(np.int64);b=lut[yy,xx+1,Y].astype(np.int64)
    c=lut[yy+1,xx,Y].astype(np.int64);d=lut[yy+1,xx+1,Y].astype(np.int64)
    new=(((a*(256-fx)+b*fx)*(256-fy)+(c*(256-fx)+d*fx)*fy+32768)>>16)
    return np.clip(q+(new-Y)[:,:,None],0,255).astype(np.uint8)


# ======================================================================
# ===== [07/22] v8_geometry =====
# ======================================================================


"""Small-image geometry estimation; original-resolution PL tile plans.

No camera metadata is assumed. Automatic metric aspect is conditional on a
centered square-pixel pinhole camera and a flat rectangular target.
"""
from core import RELEASE_ID as RELEASE_ID; from core import cache_profile as cache_profile
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_IMAGE_CACHE={}

def read_image(path,source_max_dim=4096,source_max_pixels=8_000_000):
    """Inspect header first, select bounded JPEG IDCT decoding, then orient once.
    Original coordinates refer to the EXIF-oriented original, as in the old imread.
    """
    from PIL import Image as PILImage
    if source_max_dim is not None and (isinstance(source_max_dim,bool) or not isinstance(source_max_dim,int) or source_max_dim<32):
        raise ValueError('source_max_dim为None或>=32的整数')
    if isinstance(source_max_pixels,bool) or not isinstance(source_max_pixels,int) or not 100_000<=source_max_pixels<=24_000_000:
        raise ValueError('source_max_pixels须为10万..2400万；默认800万')
    p=Path(path).expanduser().resolve();st=p.stat()
    key=(str(p),st.st_size,st.st_mtime_ns,source_max_dim,source_max_pixels)
    if key in _IMAGE_CACHE:
        image,info=_IMAGE_CACHE[key]
        return image,True,dict(info)
    with PILImage.open(str(p)) as header:
        rw,rh=header.size;fmt=header.format
        try:orientation=int(header.getexif().get(274,1))
        except (ValueError,TypeError,AttributeError):orientation=1
    if min(rw,rh)<2:raise ValueError('图像宽高至少为2')
    if orientation not in range(1,9):orientation=1
    ow,oh=(rh,rw) if orientation in (5,6,7,8) else (rw,rh)
    divisor=1
    if fmt=='JPEG':
        for d in (1,2,4,8):
            divisor=d;dw,dh=(rw+d-1)//d,(rh+d-1)//d
            if dw*dh<=source_max_pixels and (source_max_dim is None or max(dw,dh)<=source_max_dim):break
        if ((rw+divisor-1)//divisor)*((rh+divisor-1)//divisor)>source_max_pixels:
            raise ValueError('JPEG缩小解码至1/8后仍超内存预算，请在电脑缩小后上传；尚未解码像素')
    elif rw*rh>source_max_pixels:
        raise ValueError('大尺寸非JPEG不能保证低内存解码，请在电脑转为JPEG或缩小后上传；尚未解码像素')
    flags={1:cv2.IMREAD_COLOR,2:cv2.IMREAD_REDUCED_COLOR_2,4:cv2.IMREAD_REDUCED_COLOR_4,8:cv2.IMREAD_REDUCED_COLOR_8}
    _IMAGE_CACHE.clear()  # Release the previous working image BEFORE allocating another.
    image=cv2.imread(str(p),flags[divisor]|cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None or min(image.shape[:2])<2:raise ValueError('无法读取有效彩色图片')
    if image.shape[0]*image.shape[1]>source_max_pixels:
        raise ValueError('解码器返回尺寸超过预算，停止处理')
    if orientation==2:image=cv2.flip(image,1)
    elif orientation==3:image=cv2.rotate(image,cv2.ROTATE_180)
    elif orientation==4:image=cv2.flip(image,0)
    elif orientation==5:image=cv2.transpose(image)
    elif orientation==6:image=cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
    elif orientation==7:image=cv2.flip(cv2.transpose(image),-1)
    elif orientation==8:image=cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE)
    h,w=image.shape[:2]
    if source_max_dim is not None and max(h,w)>source_max_dim:
        scale=source_max_dim/max(h,w)
        image=cv2.resize(image,(max(2,round(w*scale)),max(2,round(h*scale))),interpolation=cv2.INTER_AREA)
    h,w=image.shape[:2]
    info=dict(original_shape=[oh,ow,3],encoded_shape=[rh,rw,3],working_shape=[h,w,3],
              jpeg_decode_divisor=divisor,exif_orientation=orientation,
              original_to_working_scale=[w/ow,h/oh],source_max_dim=source_max_dim,
              source_max_pixels=source_max_pixels,reduced=(w!=ow or h!=oh))
    _IMAGE_CACHE[key]=(image,info)
    return image,False,dict(info)


def resize_view(image,limit=640):
    h,w=image.shape[:2];s=min(1.,limit/max(h,w))
    # Coarse proposals only; original-resolution edge refinement follows.
    return cv2.resize(image,(max(2,round(w*s)),max(2,round(h*s))),interpolation=cv2.INTER_LINEAR) if s<1 else image

def order_corners(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    center=q.mean(axis=0)
    q=q[np.argsort(np.arctan2(q[:,1]-center[1],q[:,0]-center[0]))]
    q=np.roll(q,-int(np.argmin(q.sum(axis=1))),axis=0)
    if np.cross(q[1]-q[0],q[2]-q[1])<0:q=q[[0,3,2,1]]
    if not cv2.isContourConvex(q) or abs(cv2.contourArea(q))<16:raise ValueError('四角退化或非凸')
    return q

def detect_quad(image,limit=640):
    view=resize_view(image,limit);h,w=view.shape[:2]
    gray=view if view.ndim==2 else cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
    blur=cv2.GaussianBlur(gray,(5,5),0);candidates=[]
    # Both thresholds on the SMALL image: the outer paper can be weaker than its black frame.
    for low,high in ((50,150),(15,50)):
        edge=cv2.dilate(cv2.Canny(blur,low,high),np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:16]:
            area=cv2.contourArea(c)
            if area<.05*w*h:continue
            p=cv2.approxPolyDP(c,.018*cv2.arcLength(c,True),True)
            if len(p)!=4 or not cv2.isContourConvex(p):continue
            q=order_corners(p)
            if np.any(q[:,0]<2) or np.any(q[:,1]<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3):continue
            candidates.append((area,q))
    if not candidates:raise ValueError('缩略图未找到外框；可提高detection_max_dim或给manual_points（原图坐标）')
    area,q=max(candidates,key=lambda item:item[0])
    H,W=image.shape[:2]
    q=(q+.5)*[W/w,H/h]-.5
    return q.astype(np.float32),dict(view_shape=[h,w],candidates=len(candidates),area_ratio=area/(w*h))

def project__v8_geometry(H,x,y):
    d=H[2,0]*x+H[2,1]*y+H[2,2]
    if np.any(d<=1e-7):raise ValueError('映射分母非正或接近零')
    return (H[0,0]*x+H[0,1]*y+H[0,2])/d,(H[1,0]*x+H[1,1]*y+H[1,2])/d

def _aspect_once(q,image_shape):
    h,w=image_shape[:2]
    G=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),q.astype(np.float32)).astype(float)
    A=np.array([[1,0,-(w-1)/2],[0,1,-(h-1)/2],[0,0,1.]])@G
    denom=A[2,0]*A[2,1]
    if abs(denom)<1e-9:raise ValueError('焦距估计退化')
    f2=-np.dot(A[:2,0],A[:2,1])/denom
    if not np.isfinite(f2) or f2<=0:raise ValueError('无有效实数焦距')
    f=np.sqrt(f2)
    if not .2*max(w,h)<f<8*max(w,h):raise ValueError('估计焦距不可信')
    a=A[:,0]*[1/f,1/f,1];b=A[:,1]*[1/f,1/f,1]
    r=np.linalg.norm(a)/np.linalg.norm(b)
    if not .1<r<10:raise ValueError('估计比例不可信')
    return float(r),float(f)

def aspect_ratio(q,image_shape,known_ratio=None):
    if known_ratio is not None:
        if not np.isfinite(known_ratio) or not .05<float(known_ratio)<20:raise ValueError('aspect_ratio须为0.05..20')
        return float(known_ratio),dict(method='user_ratio',confidence='user_supplied')
    tl,tr,br,bl=q
    fallback=(np.linalg.norm(tr-tl)+np.linalg.norm(br-bl))/(np.linalg.norm(bl-tl)+np.linalg.norm(br-tr))
    try:
        r,f=_aspect_once(q,image_shape);samples=[]
        # Deterministic sensitivity check, not a confidence interval or calibration.
        eps=max(image_shape[:2])/640.
        for i in range(4):
            for axis in range(2):
                for sign in (-1,1):
                    perturbed=q.copy();perturbed[i,axis]+=sign*eps
                    samples.append(_aspect_once(perturbed,image_shape)[0])
        spread=float(max(abs(np.asarray(samples)/r-1)))
        if spread>.10:raise ValueError('角点扰动导致比例不稳定')
        return r,dict(method='rectangle_self_calibration',confidence='conditional',focal_pixels=f,
                      aspect_sensitivity=spread,assumptions='原图中心主点、方形像素、平面矩形；弯曲纸面可能不满足')
    except (ValueError,cv2.error) as e:
        return float(fallback),dict(method='projected_edge_fallback',confidence='low',reason=str(e),
                                   warning='没有足够信息恢复真实比例；当前保留投影估计，不强制A4或正方格')

def build_model(image,quad,ratio=None,output_size=None,max_dim=None,dewarp='auto',preview_dim=640,preview_backend='opencv',surface_solver='qr',surface_tracking='batch',preserve_corner_order=False):
    started=time.perf_counter()
    if preview_backend not in ('opencv','numpy'):raise ValueError('geometry_preview_backend须为opencv/numpy')
    if surface_solver not in ('qr','svd'):raise ValueError('surface_solver须为qr/svd')
    if surface_tracking not in ('batch','legacy'):raise ValueError('surface_tracking须为batch/legacy')
    if dewarp not in ('auto','off','lines'):raise ValueError('dewarp为auto/lines/off')
    q=np.asarray(quad,np.float32).reshape(4,2).copy() if preserve_corner_order else order_corners(quad)
    if not np.isfinite(q).all() or not cv2.isContourConvex(q) or cv2.contourArea(q,oriented=True)<=16:raise ValueError('ordered output corners must be finite convex clockwise image coordinates')
    r,metric=aspect_ratio(q,image.shape,ratio)
    aspect_s=time.perf_counter()-started;t=time.perf_counter()
    tl,tr,br,bl=q
    ew=max(np.linalg.norm(tr-tl),np.linalg.norm(br-bl));eh=max(np.linalg.norm(bl-tl),np.linalg.norm(br-tr))
    if output_size is None:
        wo=max(ew,eh*r);ho=wo/r
        scale=1 if max_dim is None else min(1,float(max_dim)/max(wo,ho))
        wo,ho=max(16,round(wo*scale)),max(16,round(ho*scale))
    else:
        wo,ho=map(int,output_size)
        if tuple(output_size)!=(wo,ho):raise ValueError('output_size应为整数(宽,高)')
        metric=dict(method='explicit_output_size',confidence='user_supplied')
    if min(wo,ho)<16 or wo*ho>12_000_000 or max(wo,ho)>16384:raise ValueError('输出须>=16、<=1200万像素、单边<=16384；请设置max_dim')
    H=compute_H_out2in(q,wo,ho).astype(float)
    h_s=time.perf_counter()-t;t=time.perf_counter()
    scale=min(1,preview_dim/max(wo,ho));pw=max(16,round(wo*scale));ph=max(16,round(ho*scale))
    preview=None;preview_coordinates_s=preview_remap_s=0.
    if dewarp!='off':
        if preview_backend=='opencv':
            # Preview endpoints are EXACTLY the former linspace endpoints:
            # pixel (0,0)->(0,0), (pw-1,ph-1)->(wo-1,ho-1).
            # Only this small observation preview changes raster implementation.
            # H and the authoritative nonlinear model/PL numeric ABI are intact.
            denominator=H[2,0]*np.array([0.,wo-1,wo-1,0.])+H[2,1]*np.array([0.,0.,ho-1,ho-1])+H[2,2]
            if (not np.all(np.isfinite(H)) or not np.all(np.isfinite(denominator)) or
                    np.min(abs(denominator))<1e-6 or denominator.min()<=0<=denominator.max()):
                raise ValueError('几何预览H分母不安全')
            transform=H@np.diag([(wo-1)/(pw-1),(ho-1)/(ph-1),1.])
            preview_coordinates_s=time.perf_counter()-t;t=time.perf_counter()
            preview=cv2.warpPerspective(image,transform,(pw,ph),
                flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
            preview_remap_s=time.perf_counter()-t
        else:
            u,v=np.meshgrid(np.linspace(0,wo-1,pw),np.linspace(0,ho-1,ph));x,y=project__v8_geometry(H,u,v)
            preview_coordinates_s=time.perf_counter()-t;t=time.perf_counter()
            preview=cv2.remap(image,x.astype(np.float32),y.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
            preview_remap_s=time.perf_counter()-t
    perspective_preview_s=time.perf_counter()-started
    horizontal_s=vertical_s=gray_s=threshold_s=transpose_s=0.
    dx=np.zeros((ph,pw),np.float32);dy=dx.copy();details={'state':'off','strength':0.}
    cx=np.zeros((NY,NX));cy=np.zeros((NY,NX))
    if dewarp!='off':
        t=time.perf_counter();gray=cv2.cvtColor(preview,cv2.COLOR_BGR2GRAY)
        gray_s=time.perf_counter()-t;t=time.perf_counter()
        ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,9)
        threshold_s=time.perf_counter()-t
        t=time.perf_counter();dy,details['horizontal'],cy=line_surface(gray,ink=ink,solver=surface_solver,tracking_backend=surface_tracking)
        horizontal_s=time.perf_counter()-t
        t=time.perf_counter()
        vertical_gray=np.ascontiguousarray(gray.T);vertical_ink=np.ascontiguousarray(ink.T)
        transpose_s=time.perf_counter()-t;t=time.perf_counter()
        vertical,details['vertical'],cx=line_surface(vertical_gray,ink=vertical_ink,solver=surface_solver,tracking_backend=surface_tracking);dx=vertical.T
        vertical_s=time.perf_counter()-t
        # Validate no folds on the composed displacement grid; reduce strength if necessary.
        strength=1. if (np.any(cx) or np.any(cy)) else 0.
        dxx=np.gradient(dx,(pw-1)/64,axis=1);dxy=np.gradient(dx,(ph-1)/64,axis=0)
        dyx=np.gradient(dy,(pw-1)/64,axis=1);dyy=np.gradient(dy,(ph-1)/64,axis=0)
        for _ in range(5):
            if np.min((1+dxx*strength)*(1+dyy*strength)-dxy*dyx*strength**2)>.35:break
            strength*=.5
        else:strength=0.
        cx*=strength;cy*=strength;details['strength']=strength
        details['state']='active' if strength else 'inactive'
    # Analytic smooth field is authoritative; 33x33 maps are saved for inspection.
    # Evaluate beyond page bounds smoothly for the last partial hardware cell.
    cx*=(wo-1)/(pw-1);cy*=(ho-1)/(ph-1)
    uu,vv=np.meshgrid(np.linspace(0,1,33),np.linspace(0,1,33))
    mx=evaluate(cx,vv,uu);my=evaluate(cy,uu,vv)
    return dict(H=H,width=wo,height=ho,mesh_x=mx,mesh_y=my,bend_x=cx,bend_y=cy,
                quad=q,metric=metric,dewarp=details,preview=preview,
                geometry_timing=dict(perspective_preview_s=perspective_preview_s,
                    aspect_s=aspect_s,h_and_size_s=h_s,preview_coordinates_s=preview_coordinates_s,
                    preview_remap_s=preview_remap_s,preview_backend=preview_backend,
                    preview_skipped=dewarp=='off',preview_shape=[ph,pw],surface_solver=surface_solver,surface_tracking=surface_tracking,
                    gray_s=gray_s,threshold_s=threshold_s,
                    horizontal_s=horizontal_s,vertical_s=vertical_s,transpose_s=transpose_s,
                    guards_and_export_s=time.perf_counter()-started-perspective_preview_s-horizontal_s-vertical_s-gray_s-threshold_s-transpose_s))

def map_points(model,u,v):
    u,v=np.broadcast_arrays(np.asarray(u,float),np.asarray(v,float))
    gx=u/(model['width']-1);gy=v/(model['height']-1)
    cache=model.get('_motion_bend_cache')
    if cache is not None and u.size<=16384:
        # Only the paper-coordinate bend is cached. H is applied afresh on
        # every call. Exact coordinate/coefficient bytes prevent stale fields
        # after re-estimation or the planner's perspective-only fallback.
        key=(model['width'],model['height'],u.shape,u.tobytes(),v.tobytes(),
             model['bend_x'].tobytes(),model['bend_y'].tobytes())
        warped=cache.get(key)
        if warped is None:
            warped=(u+evaluate(model['bend_x'],gy,gx),v+evaluate(model['bend_y'],gx,gy))
            cache[key]=warped
            while (len(cache)>8 or sum(len(k[3])+len(k[4])+x.nbytes+y.nbytes
                                      for k,(x,y) in cache.items())>2*1024*1024):
                cache.popitem(last=False)
        else:
            cache.move_to_end(key)
        return project__v8_geometry(model['H'],*warped)
    return project__v8_geometry(model['H'],u+evaluate(model['bend_x'],gy,gx),
                   v+evaluate(model['bend_y'],gx,gy))


class TileGeometryError(ValueError):
    pass


class GeometryPlanFallback(ValueError):
    pass

def coordinate_bounds(regs,wo,ho,field):
    return [(float(low.min()),float(high.max())) for low,high in mapping_ranges(regs,wo,ho,field)]


def make_tile(model,box,image_shape,validator):
    require_yuyv_shape(image_shape)
    x0,y0,x1,y1=map(int,box);wo,ho=x1-x0,y1-y0
    if min(wo,ho)<2:raise ValueError('分块宽高不足2')
    if max(wo,ho)>1280:raise ValueError('输出分块超过硬件1280上限')
    # Shift ONE global H. Refitting H to four warped corners for each tiny tile
    # used to create unstable extrapolation at its final partial 64px cell.
    H=model['H']@np.array([[1.,0,x0],[0,1.,y0],[0,0,1.]])
    if H[2,2]<=1e-7:raise ValueError('分块基准H分母不安全')
    H=H/H[2,2]
    # Control nodes cover the active hardware cells, including the last partial cell.
    nx=(wo-1+63)//64+1;ny=(ho-1+63)//64+1
    u,v=np.meshgrid(np.arange(nx)*64.,np.arange(ny)*64.)
    xx,yy=map_points(model,u+x0,v+y0);bx,by=project__v8_geometry(H,u,v)
    delta=np.rint(np.stack([xx-bx,yy-by],-1)*256).astype(np.int64)
    if np.any(abs(delta)>32768):raise TileGeometryError('局部位移超界')
    field=identity_field();field[:ny,:nx,:2]=delta.astype(np.int32)
    field[ny:,:,:2]=field[ny-1:ny,:,:2];field[:,nx:,:2]=field[:,nx-1:nx,:2]
    # Reject inaccurate geometry BEFORE building the expensive row schedules.
    # This is a sampling guard, not a mathematical bound on every output pixel.
    tu,tv=np.meshgrid(np.unique(np.r_[0,np.arange(16,wo,16),wo-1]),np.unique(np.r_[0,np.arange(16,ho,16),ho-1]))
    tx,ty=map_points(model,tu+x0,tv+y0);ax,ay=project__v8_geometry(H,tu,tv)
    local=interpolate(field,tu,tv)
    residual=float(np.max(np.hypot(ax+local[...,0]/256-tx,ay+local[...,1]/256-ty)))
    if residual>.65:raise TileGeometryError('控制网格近似误差超过0.65源像素')
    grid=_range_grid(wo,ho,field)
    regs=homography_to_regs(H)
    bounds=[(float(low.min()),float(high.max())) for low,high in mapping_ranges(regs,wo,ho,field,_grid=grid)]
    ih,iw=image_shape[:2]
    left=max(0,min(iw-2,int(np.floor(bounds[0][0]))-2));right=min(iw,max(left+2,int(np.ceil(bounds[0][1]))+3))
    top=max(0,min(ih-2,int(np.floor(bounds[1][0]))-2));bottom=min(ih,max(top+2,int(np.ceil(bounds[1][1]))+3))
    if len(image_shape)==3 and image_shape[2]==2:
        left&=~1;right=min(iw,(right+1)&~1)
    wi,hi=right-left,bottom-top
    if wi>512 or hi>1280:raise ValueError('源区域宽度超出512输入限制（行缓存 MAX_W=512）')
    # Translate homography output to cropped source coordinates, preserving h33=1.
    H=np.array([[1,0,-left],[0,1,-top],[0,0,1.]])@H
    regs=homography_to_regs(H);field=validate_field(field)
    qx,qy,_=coordinates(regs,tu,tv,field)
    residual=float(np.max(np.hypot(qx/65536.+left-tx,qy/65536.+top-ty)))
    if residual>.65:raise TileGeometryError('定点映射采样误差超过0.65源像素')
    padded,rows=cache_profile(wi)
    candidate=dict(box=list(box),crop=[left,top,right,bottom],regs=regs,field=field,
        descriptors=np.empty(0,np.uint32),input_shape=(hi,wi,image_shape[2]),width=wo,height=ho,
        capacity_rows=rows,approximation_error=residual,planning_backend='pl_exact_suffix_rows',
        border_flags=int(left==0)|(int(top==0)<<1)|(int(right==iw)<<2)|(int(bottom==ih)<<3))
    if validator is None:raise RuntimeError('v9必须由PL规划器确认候选，不能用未验证行表')
    info=validator(candidate)
    candidate.update(peak_rows=info['peak_rows'],pl_preflight=info)
    return _seal_checked(candidate,candidate['input_shape'])


def _plan_tiles_v11(model,image_shape,tile_size=1280,max_tiles=512,planner='adaptive',validator=None):
    """Hints select candidates only; every leaf passes make_tile's full guards.

    Small sampled maps NEVER supply DMA row descriptors or certify cache safety.
    A bounded hint budget avoids turning heuristic search into another bottleneck.
    """
    reasons={};attempts=[];fallback=None;hints={}
    counters=dict(full_validation_attempts=0,predictive_splits=0,hint_evaluations=0,
                  hint_s=0.,full_validation_s=0.)
    if planner not in ('adaptive','legacy'):raise ValueError('planner=adaptive/legacy')
    if not 64<=tile_size<=1280:raise ValueError('tile_size须为64..1280')

    def hint(box):
        if box in hints:return hints[box]
        if counters['hint_evaluations']>=128:return None
        t=time.perf_counter();counters['hint_evaluations']+=1
        try:
            x0,y0,x1,y1=box
            u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
            xx,yy=map_points(model,u,v)
            if not np.all(np.isfinite(xx)) or not np.all(np.isfinite(yy)):return None
            ih,iw=image_shape[:2]
            left=max(0,min(iw-2,int(np.floor(xx.min()))-3));right=min(iw,max(left+2,int(np.ceil(xx.max()))+4))
            top=max(0,min(ih-2,int(np.floor(yy.min()))-3));bottom=min(ih,max(top+2,int(np.ceil(yy.max()))+4))
            if len(image_shape)==3 and image_shape[2]==2:
                left&=~1;right=min(iw,(right+1)&~1)
            wi,hi=right-left,bottom-top
            #   ⚠️ 2026-10-25：行缓存是**固定** ROWS=384（不是按宽度分档的老模型）
            rows=384
            low=np.clip(np.floor(yy.min(axis=1)),0,ih-2)
            high=np.clip(np.floor(yy.max(axis=1)),0,ih-2)+1
            future=np.minimum.accumulate(low[::-1])[::-1]
            peak=float(np.max(high-future+1))+4
            single=float(np.max(high-low+1))+4
            axis='x' if single>rows else 'y'
            if wi>512 or hi>1280:
                # Candidate scoring below can change this preliminary axis.
                axis='x' if wi>=hi else 'y'
            result=dict(width=wi,height=hi,rows=rows,peak=peak,axis=axis,
                        overload=max(wi/512.,hi/1280.,peak/rows),traffic=wi*hi,
                        obvious=(wi>520 or hi>1296 or peak>rows*1.18+8))
            hints[box]=result
            return result
        except (ValueError,OverflowError,FloatingPointError):return None
        finally:counters['hint_s']+=time.perf_counter()-t

    def children(box,axis,cut):
        x0,y0,x1,y1=box
        if axis=='x':return (x0,y0,cut,y1),(cut,y0,x1,y1)
        return (x0,y0,x1,cut),(x0,cut,x1,y1)

    def choose_split(box,preferred,depth):
        x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
        if (preferred=='x' and w<4) or (preferred=='y' and h<4):preferred='y' if preferred=='x' else 'x'
        start,size=(x0,w) if preferred=='x' else (y0,h)
        selected=(preferred,start+size//2)
        if planner=='legacy' or depth>=5 or counters['hint_evaluations']>=116:return selected
        best=None
        # Six cuts at most. Include an estimated cache-width transition when useful.
        parent=hint(box)
        for axis in (preferred,'y' if preferred=='x' else 'x'):
            start,size=(x0,w) if axis=='x' else (y0,h)
            if size<128:continue
            fractions=[.375,.5,.625]
            if axis=='x' and parent is not None:
                boundary=640 if parent['width']>640 else 320
                f=(boundary-12)/max(parent['width'],1)
                if .25<f<.75:fractions=[.5,f,1-f]
            for fraction in fractions:
                cut=start+int(round(size*fraction))
                if min(cut-start,start+size-cut)<64:continue
                a,b=children(box,axis,cut);ha,hb=hint(a),hint(b)
                if ha is None or hb is None:continue
                # Failed children dominate the cost; then prefer lower estimated
                # overflow, less duplicated source traffic and balanced partitions.
                overloads=[ha['overload'],hb['overload']]
                score=(sum(o>1 for o in overloads),sum(max(0,o-1) for o in overloads),
                       (ha['traffic']+hb['traffic'])/(w*h)+.05*abs(fraction-.5))
                if best is None or score<best:best=score;selected=(axis,cut)
        return selected

    def plan_once():
        plans=[]
        def split(box,depth=0):
            x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
            prediction=hint(box) if planner=='adaptive' and depth<3 and min(w,h)>=128 else None
            predict_split=(prediction is not None and prediction['obvious'] and counters['predictive_splits']<8)
            if predict_split:
                counters['predictive_splits']+=1
                error=None;reason='采样预测超限，提前选择子块（未作为安全证明）';preferred=prediction['axis']
            else:
                t=time.perf_counter();counters['full_validation_attempts']+=1
                try:tile=make_tile(model,box,image_shape,validator)
                except (ValueError,cv2.error) as e:
                    error=e;reason=str(e);preferred=getattr(e,'split_axis','x' if w>=h else 'y')
                else:
                    plans.append(tile)
                    if len(plans)>max_tiles:raise ValueError('分块数超过上限，请设置较小max_dim')
                    return
                finally:counters['full_validation_s']+=time.perf_counter()-t
            reasons[reason]=reasons.get(reason,0)+1
            if isinstance(error,TileGeometryError) and min(w,h)<=128:
                raise GeometryPlanFallback(reason+'；停止把局部曲率误差细分成微小块') from error
            if depth>=14 or max(w,h)<4:raise ValueError('无法安全分块: '+reason) from error
            axis,cut=choose_split(box,preferred,depth)
            attempts.append(dict(box=list(box),reason=reason,depth=depth,split_axis=axis,
                                 split_coordinate=cut,predictive=bool(predict_split)))
            a,b=children(box,axis,cut)
            split(a,depth+1);split(b,depth+1)
        xs=np.linspace(0,model['width'],int(np.ceil(model['width']/tile_size))+1).astype(int)
        ys=np.linspace(0,model['height'],int(np.ceil(model['height']/tile_size))+1).astype(int)
        for ya,yb in zip(ys[:-1],ys[1:]):
            for xa,xb in zip(xs[:-1],xs[1:]):split((int(xa),int(ya),int(xb),int(yb)))
        return plans
    try:plans=plan_once()
    except GeometryPlanFallback as e:
        if not (np.any(model['bend_x']) or np.any(model['bend_y'])):raise
        fallback=str(e);hints.clear()
        model['bend_x']=np.zeros((NY,NX));model['bend_y']=np.zeros((NY,NX))
        model['mesh_x']=np.zeros((33,33));model['mesh_y']=np.zeros((33,33))
        model['dewarp'].update(state='perspective_fallback',strength=0.,fallback_reason=fallback)
        plans=plan_once()
    model['plan_stats']=dict(initial_tile_size=tile_size,tile_count=len(plans),planner=planner,
                            min_tile_width=min(p['width'] for p in plans),min_tile_height=min(p['height'] for p in plans),
                            split_reason_counts=reasons,split_events=attempts,geometry_fallback=fallback,
                            geometry_guard_sample_step=16,geometry_guard_threshold=.65,
                            hint_budget=128,**counters)
    return plans


def plan_tiles(model,image_shape,tile_size=1280,max_tiles=512,planner='adaptive',validator=None):
    # Lazy import avoids the geometry/planner dependency cycle.
    if planner in ('legacy','adaptive_v11'):
        plans=_plan_tiles_v11(model,image_shape,tile_size,max_tiles,
                             'legacy' if planner=='legacy' else 'adaptive',validator)
        model['plan_stats'].update(planner=planner,search_backend='v11_direct_hints')
        return plans
    if planner!='adaptive':raise ValueError('planner=adaptive/adaptive_v11/legacy')
    return plan_tiles_fast(model,image_shape,tile_size,max_tiles,validator)


# ======================================================================
# ===== [08/22] v10_quad =====
# ======================================================================


"""P1-style pyramid contour + subpixel edge profiles on the working image.

No fixed paper aspect, grid spacing, camera focal length or lens coefficients.
Manual points are kept as supplied by the caller. TLS is for approximately
straight document boundaries; individual unsupported edges keep coarse corners.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _tls__v10_quad(points):
    points = np.asarray(points, np.float64)
    for _ in range(3):
        center = points.mean(axis=0)
        _, _, axes = np.linalg.svd(points - center, full_matrices=False)
        direction = axes[0]
        normal = np.array([-direction[1], direction[0]])
        residual = np.abs((points-center) @ normal)
        keep = residual <= max(1., 3.*float(np.median(residual)))
        if keep.all() or keep.sum() < 20:
            break
        points = points[keep]
    # Refit the last retained set, so the reported RMS matches the actual line.
    center = points.mean(axis=0)
    _, _, axes = np.linalg.svd(points-center, full_matrices=False)
    normal = np.array([-axes[0, 1], axes[0, 0]])
    line = np.r_[normal, -normal @ center]
    rms = float(np.sqrt(np.mean(((points-center) @ normal)**2)))
    return line, rms, len(points)


def refine_edges(image, quad, half_window=None):
    start = time.perf_counter()
    h, w = image.shape[:2]
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    q = order_corners(quad).astype(np.float64)
    center = q.mean(axis=0)
    half = min(48., max(12., .012*np.hypot(w, h)))
    if half_window is not None:
        if not np.isfinite(half_window) or not 3<=half_window<=48:raise ValueError('half_window must be 3..48 pixels')
        half=float(half_window)
    offsets = np.linspace(-half, half, 65)
    fractions = np.linspace(.06, .94, 64)
    lines = []
    evidence = []
    for i in range(4):
        a, b = q[i], q[(i+1) % 4]
        edge = b-a
        normal = np.array([-edge[1], edge[0]]) / max(np.linalg.norm(edge), 1e-9)
        if np.dot(center-(a+b)/2., normal) < 0:
            normal = -normal
        base = a[None, :] + fractions[:, None]*edge
        coords = base[:, None, :] + offsets[None, :, None]*normal
        profiles = cv2.remap(gray, coords[..., 0].astype(np.float32),
                             coords[..., 1].astype(np.float32), cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE).astype(np.float64)
        outer = np.median(profiles[:, :8], axis=1)
        inner = np.median(profiles[:, -8:], axis=1)
        contrast = inner-outer
        level = (inner+outer)/2.
        signed = (profiles-level[:, None])*np.where(contrast >= 0, 1., -1.)[:, None]
        # A monotone threshold crossing, for either light or dark target edges.
        crossings = (signed[:, :-1] <= 0) & (signed[:, 1:] > 0)
        # Choose the crossing closest to the contour, not a distant table texture.
        scores = np.where(crossings, abs((offsets[:-1]+offsets[1:])/2.), np.inf)
        index = np.argmin(scores, axis=1)
        rows = np.arange(len(base))
        before, after = signed[rows, index], signed[rows, index+1]
        alpha = np.clip(-before/np.maximum(after-before, 1e-9), 0., 1.)
        shift = offsets[index]+alpha*(offsets[index+1]-offsets[index])
        points = base+shift[:, None]*normal
        good = ((abs(contrast) >= 12) & np.any(crossings, axis=1)
                & (points[:, 0] >= 1) & (points[:, 0] < w-1)
                & (points[:, 1] >= 1) & (points[:, 1] < h-1))
        info = dict(edge=i, profiles=64, supported=int(good.sum()), accepted=False)
        line = None
        if good.sum() >= 20:
            line, rms, count = _tls__v10_quad(points[good])
            support_span = float(np.ptp(fractions[good]))
            # A highly curved boundary must not be forced to be a straight line.
            info.update(tls_rms=rms, retained=count, coverage=support_span)
            if rms <= max(1.5, .06*half) and support_span >= .60:
                info['accepted'] = True
            else:
                line = None
        lines.append(line)
        evidence.append(info)
    refined = q.copy()
    refined_count = 0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:
            continue
        crossing = np.cross(lines[i-1], lines[i])
        if abs(crossing[2]) < .08:  # ill-conditioned corner intersection
            continue
        point = crossing[:2]/crossing[2]
        if (np.linalg.norm(point-q[i]) <= 3*half and
                0 <= point[0] <= w-1 and 0 <= point[1] <= h-1):
            refined[i] = point
            refined_count += 1
    try:
        candidate = order_corners(refined)
        area_ratio = abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85 <= area_ratio <= 1.15:
            raise ValueError('refined area changed too much')
        # Order must still identify the same four vertices (no corner relabel).
        if np.max(np.linalg.norm(candidate-q, axis=1)) > 3*half:
            raise ValueError('corner order or displacement changed too much')
    except (ValueError, cv2.error):
        candidate = q.astype(np.float32)
        refined_count = 0
    return candidate, dict(method='p1_pyramid_subpixel_profiles_tls',
        state='refined' if refined_count else 'coarse_retained',
        refined_corners=refined_count, edges=evidence, half_window_pixels=float(half),
        corner_displacements=np.linalg.norm(candidate-q, axis=1).tolist(),
        refinement_s=time.perf_counter()-start)


def detect_refined(image, limit=640, refine=True):
    start = time.perf_counter()
    # Same P1 idea: small contour search, narrow original/work-resolution profiles.
    coarse_limit = min(limit, max(160, int(round(max(image.shape[:2])/3.))))
    try:
        quad, info = detect_quad(image, coarse_limit)
        fallback = False
    except ValueError:
        if coarse_limit == limit:
            raise
        quad, info = detect_quad(image, limit)
        fallback = True
    contour_s = time.perf_counter()-start
    if refine:
        quad, edge_info = refine_edges(image, quad)
    else:
        edge_info = dict(method='disabled', state='coarse_retained', refinement_s=0.)
    info = dict(info, coarse_limit=coarse_limit, detection_limit=limit,
                coarse_fallback=fallback, contour_s=contour_s, edge_refinement=edge_info,
                detection_s=time.perf_counter()-start)
    return quad, info


# ======================================================================
# ===== [09/22] v14_planner =====
# ======================================================================


"""Bounded split search with a per-photo coordinate atlas; hardware ABI9.

Atlas values rank candidates only. make_tile remains the authority for crop,
quantization, the 0.65-source-pixel guard and the exact PL suffix-row proof.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def plan_tiles_fast(model,image_shape,tile_size=1280,max_tiles=512,validator=None):
    if not 64<=tile_size<=1280:raise ValueError('tile_size须为64..1280')
    if validator is None:raise RuntimeError('需要PL精确规划器，不能用坐标预览认证行缓存安全')
    budget=48;hints={};atlas=None;atlas_attempted=False
    reasons={};events=[];fallback=None
    counters=dict(full_validation_attempts=0,predictive_splits=0,hint_evaluations=0,
        hint_s=0.,full_validation_s=0.,atlas_build_s=0.,atlas_builds=0,
        hint_batches=0,direct_hint_fallbacks=0,direct_prediction_evaluations=0,split_candidates=0,
        early_axis_accepts=0,hint_budget_exhaustions=0)
    wo,ho=model['width'],model['height'];ih,iw=image_shape[:2]

    def ensure_atlas():
        nonlocal atlas,atlas_attempted
        if atlas_attempted:return
        atlas_attempted=True;t=time.perf_counter();counters['atlas_builds']+=1
        try:
            # At most 129x129x2 float32, about 130KB. Never a full-image map.
            aw=min(129,max(17,(wo-1+15)//16+1))
            ah=min(129,max(17,(ho-1+15)//16+1))
            u,v=np.meshgrid(np.linspace(0,wo-1,aw),np.linspace(0,ho-1,ah))
            x,y=map_points(model,u,v)
            if np.all(np.isfinite(x)) and np.all(np.isfinite(y)):
                atlas=np.stack((x,y),axis=-1).astype(np.float32)
        except (ValueError,OverflowError,FloatingPointError):
            atlas=None
        finally:counters['atlas_build_s']+=time.perf_counter()-t

    def summarize(box,xx,yy):
        if not np.all(np.isfinite(xx)) or not np.all(np.isfinite(yy)):return None
        left=max(0,min(iw-2,int(np.floor(xx.min()))-3))
        right=min(iw,max(left+2,int(np.ceil(xx.max()))+4))
        top=max(0,min(ih-2,int(np.floor(yy.min()))-3))
        bottom=min(ih,max(top+2,int(np.ceil(yy.max()))+4))
        wi,hi=right-left,bottom-top
        #   ⚠️ 2026-10-27（800x600 实测）：这里原来是写死的
        #      `512 if wi<=320 else 256 if wi<=640 else 128`。
        #      硬件已经改成 ROWS=384，但 256 这一档没跟着改 —— 于是 crop 宽 306~404
        #      （落在 321..640 档）时预算被压到 256，而 peak_rows 实测 223~314，
        #      **每帧都被切成 2 块**，帧率从 15 掉到 1.5~3.5 fps。
        #      ⇒ 统一用硬件真实容量 `LINE_BUF_ROWS`；真正的安全仍由
        #        `peak_rows` 的 PL 证明把关（见 make_tile / validator）。
        from core import LINE_BUF_ROWS as _LBR
        rows=_LBR if wi<=640 else 128
        low=np.clip(np.floor(yy.min(axis=1)),0,ih-2)
        high=np.clip(np.floor(yy.max(axis=1)),0,ih-2)+1
        future=np.minimum.accumulate(low[::-1])[::-1]
        peak=float(np.max(high-future+1))+4
        single=float(np.max(high-low+1))+4
        axis='x' if single>rows else 'y'
        if wi>512 or hi>1280:axis='x' if wi>=hi else 'y'
        return dict(width=wi,height=hi,rows=rows,peak=peak,axis=axis,
            overload=max(wi/512.,hi/1280.,peak/rows),traffic=wi*hi,crop=(left,top,right,bottom),
            obvious=(wi>1296 or hi>1296 or peak>rows*1.18+8))

    def hint_many(boxes,direct=False):
        missing=list(dict.fromkeys(tuple(b) for b in boxes if tuple(b) not in hints))
        remaining=max(0,budget-counters['hint_evaluations'])
        if len(missing)>remaining:counters['hint_budget_exhaustions']+=1
        missing=missing[:remaining]
        if missing:
            started=time.perf_counter()
            counters['hint_evaluations']+=len(missing);counters['hint_batches']+=1
            try:
                if not direct:ensure_atlas()
                if atlas is not None and not direct:
                    # Batch all siblings/cuts into a single small native remap.
                    uu=[];vv=[]
                    for x0,y0,x1,y1 in missing:
                        u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
                        uu.append(u);vv.append(v)
                    mx=(np.concatenate(uu,axis=1)*(atlas.shape[1]-1)/(wo-1)).astype(np.float32)
                    my=(np.concatenate(vv,axis=1)*(atlas.shape[0]-1)/(ho-1)).astype(np.float32)
                    samples=cv2.remap(atlas,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
                    for i,box in enumerate(missing):
                        sample=samples[:,i*9:(i+1)*9]
                        hints[box]=summarize(box,sample[:,:,0],sample[:,:,1])
                else:
                    for box in missing:
                        counters['direct_prediction_evaluations' if direct else 'direct_hint_fallbacks']+=1
                        x0,y0,x1,y1=box
                        try:
                            u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
                            x,y=map_points(model,u,v);hints[box]=summarize(box,x,y)
                        except (ValueError,OverflowError,FloatingPointError):hints[box]=None
            finally:counters['hint_s']+=time.perf_counter()-started
        return [hints.get(tuple(box)) for box in boxes]

    def children(box,axis,cut):
        x0,y0,x1,y1=box
        if axis=='x':return (x0,y0,cut,y1),(cut,y0,x1,y1)
        return (x0,y0,x1,cut),(x0,cut,x1,y1)

    def choose_split(box,preferred,depth):
        x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
        if (preferred=='x' and w<4) or (preferred=='y' and h<4):
            preferred='y' if preferred=='x' else 'x'
        start,size=(x0,w) if preferred=='x' else (y0,h)
        selected=(preferred,start+size//2)
        if depth>=5 or counters['hint_evaluations']>=budget:return selected
        parent=hint_many([box])[0];best=None
        # Search two cuts on the indicated axis. Only inspect the other axis
        # when neither indicated-axis pair looks feasible. These are hints.
        for axis in (preferred,'y' if preferred=='x' else 'x'):
            start,size=(x0,w) if axis=='x' else (y0,h)
            if size<128:continue
            fractions=[.5]
            if parent is not None:
                boundary=(640 if parent['width']>640 else 320) if axis=='x' else 1280
                extent=parent['width'] if axis=='x' else parent['height']
                fraction=(boundary-12)/max(extent,1)
                if .25<fraction<.75:fractions.append(fraction)
            if len(fractions)==1:fractions.append(.375)
            candidates=[];boxes=[];seen=set()
            for fraction in fractions:
                cut=start+int(round(size*fraction))
                if cut in seen or min(cut-start,start+size-cut)<64:continue
                seen.add(cut);a,b=children(box,axis,cut)
                candidates.append((axis,cut,fraction));boxes.extend((a,b))
            predictions=hint_many(boxes);axis_fits=False;axis_overlap=1.
            counters['split_candidates']+=len(candidates)
            for i,(candidate_axis,cut,fraction) in enumerate(candidates):
                ha,hb=predictions[2*i:2*i+2]
                if ha is None or hb is None:continue
                overloads=(ha['overload'],hb['overload'])
                failed=sum(o>1 for o in overloads)
                ca,cb=ha['crop'],hb['crop']
                overlap=max(0,min(ca[2],cb[2])-max(ca[0],cb[0]))*max(0,min(ca[3],cb[3])-max(ca[1],cb[1]))
                traffic=ha['traffic']+hb['traffic']
                axis_overlap=min(axis_overlap,overlap/max(1,traffic))
                score=(failed,sum(max(0,o-1) for o in overloads),
                       (traffic+.5*overlap)/(w*h)+.05*abs(fraction-.5))
                if best is None or score<best:best=score;selected=(candidate_axis,cut)
                axis_fits|=failed==0
            if axis_fits and axis_overlap<=.12:
                if axis==preferred:counters['early_axis_accepts']+=1
                break
        return selected

    def plan_once():
        plans=[]
        def split(box,depth=0):
            x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
            # Do not build an atlas for the common one-tile case. Its first
            # direct hint costs the same as v11; build only when cuts are needed.
            prediction=hint_many([box],direct=atlas is None)[0] if depth<3 and min(w,h)>=128 else None
            predicted=(prediction is not None and prediction['obvious'] and counters['predictive_splits']<8)
            if predicted:
                counters['predictive_splits']+=1
                error=None;reason='共享坐标预览预测超限，提前切分（不是安全证明）'
                preferred=prediction['axis']
            else:
                started=time.perf_counter();counters['full_validation_attempts']+=1
                try:tile=make_tile(model,box,image_shape,validator)
                except (ValueError,cv2.error) as e:
                    error=e;reason=str(e);preferred=getattr(e,'split_axis','x' if w>=h else 'y')
                else:
                    plans.append(tile)
                    if len(plans)>max_tiles:raise ValueError('分块数超过上限，请设置较小max_dim')
                    return
                finally:counters['full_validation_s']+=time.perf_counter()-started
            reasons[reason]=reasons.get(reason,0)+1
            if isinstance(error,TileGeometryError) and min(w,h)<=128:
                raise GeometryPlanFallback(reason+'；停止把局部曲率误差细分成微小块') from error
            if depth>=14 or max(w,h)<4:raise ValueError('无法安全分块: '+reason) from error
            axis,cut=choose_split(box,preferred,depth)
            events.append(dict(box=list(box),reason=reason,depth=depth,split_axis=axis,
                               split_coordinate=cut,predictive=bool(predicted)))
            a,b=children(box,axis,cut);split(a,depth+1);split(b,depth+1)
        xs=np.linspace(0,wo,int(np.ceil(wo/tile_size))+1).astype(int)
        ys=np.linspace(0,ho,int(np.ceil(ho/tile_size))+1).astype(int)
        for ya,yb in zip(ys[:-1],ys[1:]):
            for xa,xb in zip(xs[:-1],xs[1:]):split((int(xa),int(ya),int(xb),int(yb)))
        return plans

    try:plans=plan_once()
    except GeometryPlanFallback as e:
        if not (np.any(model['bend_x']) or np.any(model['bend_y'])):raise
        fallback=str(e);hints.clear();atlas=None;atlas_attempted=False
        # All model-dependent hint data is discarded before the retry.
        model['bend_x']=np.zeros((NY,NX));model['bend_y']=np.zeros((NY,NX))
        model['mesh_x']=np.zeros((33,33));model['mesh_y']=np.zeros((33,33))
        model['dewarp'].update(state='perspective_fallback',strength=0.,fallback_reason=fallback)
        plans=plan_once()
    model['plan_stats']=dict(initial_tile_size=tile_size,tile_count=len(plans),planner='adaptive',
        search_backend='v14_shared_atlas_overlap_cost',hint_source='interpolated_preview_only',
        atlas_shape=None if atlas is None else list(atlas.shape[:2]),
        min_tile_width=min(p['width'] for p in plans),min_tile_height=min(p['height'] for p in plans),
        split_reason_counts=reasons,split_events=events,geometry_fallback=fallback,
        geometry_guard_sample_step=16,geometry_guard_threshold=.65,hint_budget=budget,
        max_cut_candidates_per_split=4,
        timing_note='atlas_build_s is included in hint_s; full_validation_s includes nested lighting/control work',
        **counters)
    return plans


# ======================================================================
# ===== [10/22] v41_quad =====
# ======================================================================


"""Bounded multicolor rectangle proposals and coherent exterior profiles.

No target hue, brightness polarity, grid, focal length or fixed aspect ratio.
Proposals are never trusted without four same-frame measured exterior lines.
YUYV color fallback converts sampled normal bands, not a full RGB frame.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sample_profiles(image,x,y):
    """Sample BGR/gray or paired YUYV with explicit CSC/color-range contract."""
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if image.ndim==2:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[...,None].astype(np.float32)
    if image.shape[2]==3:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
    # Chroma belongs to a Y0/Y1 pair centered at x=.5,2.5,... . Do not resize
    # the interleaved U/V byte plane as though each byte were the same channel.
    uvx=np.ascontiguousarray((mx-.5)*.5,np.float32)
    Y=cv2.remap(image[:,:,0],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    U=cv2.remap(pairs[:,:,1],uvx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
    V=cv2.remap(pairs[:,:,3],uvx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
    mode=color_mode();cy,rv,gu,gv,bu=((298,409,100,208,516),(256,359,88,183,454),
                                  (298,459,55,136,541),(256,403,48,120,475))[mode]
    C=Y if mode&1 else np.maximum(Y-16.,0.)
    return np.clip(np.stack((cy*C+bu*U,cy*C-gu*U-gv*V,cy*C+rv*V),axis=-1)/256.,0,255)


def _tls__v41_quad(points):
    """Analytic 2D TLS; residual trim cannot accept an unsupported second edge."""
    selected=np.asarray(points,np.float64)
    for _ in range(3):
        center=selected.mean(axis=0);d=selected-center
        xx=float(np.sum(d[:,0]**2));yy=float(np.sum(d[:,1]**2));xy=float(np.sum(d[:,0]*d[:,1]))
        if np.hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1):return None,None,None
        angle=.5*np.arctan2(2*xy,xx-yy);normal=np.array([-np.sin(angle),np.cos(angle)])
        residual=np.abs(d@normal);threshold=min(1.25,max(.55,2.5*float(np.median(residual))))
        keep=residual<=threshold
        if keep.all() or int(keep.sum())<12:break
        selected=selected[keep]
    center=selected.mean(axis=0);d=selected-center
    angle=.5*np.arctan2(2*float(np.sum(d[:,0]*d[:,1])),float(np.sum(d[:,0]**2)-np.sum(d[:,1]**2)))
    normal=np.array([-np.sin(angle),np.cos(angle)])
    return np.r_[normal,-normal@center],float(np.sqrt(np.mean((d@normal)**2))),selected


def _coherent_offsets(samples,offsets,t,minimum_contrast,boundary_prior=None,line_lock_radius=None):
    """Three peak hypotheses/profile; bounded joint line consensus, not nearest crossing."""
    sm=samples.copy();sm[:,1:-1]=(samples[:,:-2]+2*samples[:,1:-1]+samples[:,2:])*.25
    gradient=np.zeros(samples.shape[:2],np.float32)
    # A wider difference measures a real contrast across blur, not one noisy sample.
    gradient[:,4:-4]=np.max(np.abs(sm[:,8:]-sm[:,:-8]),axis=2)
    noise=np.median(np.max(np.abs(samples[:,1:]-samples[:,:-1]),axis=2),axis=1)
    threshold=np.maximum(float(minimum_contrast),4*noise)
    positions=np.zeros((len(t),3),np.float32);strengths=np.zeros_like(positions)
    work=gradient/(1+.35*np.abs(offsets)[None,:]/max(1.,float(abs(offsets[-1]))))
    if line_lock_radius is not None:work[:,np.abs(offsets)>line_lock_radius]=0.
    affinity=np.zeros_like(positions);signed=boundary_prior is not None and samples.shape[2]==3 and np.linalg.norm(boundary_prior)>=16.
    row=np.arange(len(t))
    for k in range(3):
        col=np.argmax(work,axis=1)
        left=gradient[row,np.maximum(col-1,0)];mid=gradient[row,col];right=gradient[row,np.minimum(col+1,len(offsets)-1)]
        den=left-2*mid+right
        alpha=np.where(np.abs(den)>1e-5,np.clip(.5*(left-right)/np.where(np.abs(den)>1e-5,den,1.),-.5,.5),0.)
        positions[:,k]=offsets[col]+alpha*(offsets[1]-offsets[0])
        strengths[:,k]=mid
        if signed:
            vector=sm[row,np.minimum(col+4,len(offsets)-1)]-sm[row,np.maximum(col-4,0)]
            affinity[:,k]=(vector@boundary_prior)/np.maximum(np.linalg.norm(vector,axis=1)*np.linalg.norm(boundary_prior),1e-9)
        for shift in range(-4,5):work[row,np.clip(col+shift,0,len(offsets)-1)]=0
    eligible=(strengths>=threshold[:,None])&(np.abs(positions)<abs(offsets[-1])*.9)
    if line_lock_radius is not None:
        eligible&=np.abs(positions)<=line_lock_radius
        if signed:eligible&=affinity>=.25
    # P1 batches normal-profile geometry; batch the bounded hypothesis grid too.
    # Same ordered anchor pairs/three peaks, eligibility and endpoint constraints.
    anchors=np.linspace(0,len(t)-1,8).astype(int)
    ai,bi,ki,kj=np.indices((8,8,3,3))
    ia,ib=anchors[ai.ravel()],anchors[bi.ravel()]
    ka,kb=ki.ravel(),kj.ravel();dt=t[ib]-t[ia]
    good=(dt>=.4)&eligible[ia,ka]&eligible[ib,kb]
    if not good.any():return None
    ia,ib,ka,kb=ia[good],ib[good],ka[good],kb[good]
    slope=(positions[ib,kb]-positions[ia,ka])/(t[ib]-t[ia])
    intercept=positions[ia,ka]-slope*t[ia]
    endpoint_limit=abs(offsets[-1]) if line_lock_radius is None else line_lock_radius
    good=np.maximum(np.abs(intercept+slope*t[0]),np.abs(intercept+slope*t[-1]))<=endpoint_limit
    if not good.any():return None
    models=np.stack((intercept[good],slope[good]),axis=1).astype(np.float32)
    predicted=models[:,0,None,None]+models[:,1,None,None]*t[None,:,None]
    distance=np.where(eligible[None,:,:],np.abs(positions[None,:,:]-predicted),np.inf)
    peak=np.argmin(distance,axis=2);res=np.take_along_axis(distance,peak[:,:,None],axis=2)[:,:,0]
    inlier=res<=.85
    g=np.take_along_axis(np.broadcast_to(strengths,(len(models),)+strengths.shape),peak[:,:,None],axis=2)[:,:,0]
    score=inlier.sum(axis=1)+.08*np.sum(np.minimum(g,64)*inlier,axis=1)/64.-.08*np.abs(models[:,0]+models[:,1]*.5)
    best=int(np.argmax(score));chosen=peak[best];keep=inlier[best]
    return positions[row,chosen],strengths[row,chosen],keep


def refine_boundary(image,quad,half_window=6.,profiles=64,min_support=.60,max_rms=1.5,
                    minimum_contrast=12.,fraction_limits=(.10,.90),deadline=None,boundary_prior=None,line_lock_radius=None):
    """Independent 4xN exterior gradient bands; all four lines must be accepted."""
    begin=time.perf_counter();cpu=time.thread_time();h,w=image.shape[:2]
    if profiles not in (24,64) or not 2.5<=half_window<=24:raise ValueError('Invalid bounded exterior profile layout')
    if line_lock_radius is not None and (not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window):raise ValueError('Physical peak corridor invalid')
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Physical boundary side prior invalid')
    q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Exterior profiles require cyclic convex current corners')
    from tracking import fused_yuyv_exterior__v87_v74_native as fused_yuyv_exterior
    native=fused_yuyv_exterior(image,q,half_window,profiles,min_support,max_rms,minimum_contrast,fraction_limits,deadline,boundary_prior,line_lock_radius)
    if native is not None:return native
    center=q.mean(axis=0)
    t=np.linspace(*fraction_limits,profiles);offsets=np.linspace(-half_window,half_window,65)
    bases=[];normals=[];coords=[]
    for i in range(4):
        a,b=q[i],q[(i+1)%4];edge=b-a;normal=np.array([-edge[1],edge[0]])/max(1e-9,np.linalg.norm(edge))
        if np.dot(center-(a+b)*.5,normal)<0:normal=-normal
        base=a+t[:,None]*edge;bases.append(base);normals.append(normal)
        coords.append(base[:,None,:]+offsets[None,:,None]*normal)
    xy=np.asarray(coords);bands=vector_profiles(image,xy[...,0].reshape(4*profiles,65),xy[...,1].reshape(4*profiles,65))
    bands=bands.reshape(4,profiles,65,-1);lines=[];reports=[];polarities=[];supports=[];rms_values=[]
    from tracking import coherent_profiles__v87_v74_native as coherent_profiles; from tracking import native_status__v87_v74_native as native_status
    consensus=coherent_profiles(bands,half_window,fraction_limits,minimum_contrast,boundary_prior,line_lock_radius)
    consensus_detail={} if consensus is None else consensus[1]
    for i in range(4):
        data=bands[i]
        if consensus is None:selection=_coherent_offsets(data,offsets,t,minimum_contrast,None if prior is None else prior[i],line_lock_radius)
        else:
            selected=consensus[0][i]
            selection=(selected[:,0],selected[:,1],selected[:,2]>.5)
        luminance=data[:,:,0]
        contrast=float(np.median(np.median(luminance[:,-8:],axis=1)-np.median(luminance[:,:8],axis=1)))
        raw_polarity=int(np.sign(contrast)) if abs(contrast)>=8 else 0
        # Mixed-color exterior may reverse Y polarity along one real line.
        # A vector proof has four spatial lines, not a common brightness sign.
        polarities.append(raw_polarity if data.shape[2]==1 else 0)
        report=dict(edge=i,profiles=profiles,supported=0,retained=0,coverage=0.,accepted=False,
                    polarity=polarities[-1],Y_polarity=raw_polarity,contrast_backend='Y_gradient' if data.shape[2]==1 else 'unclipped_YUV_vector_gradient')
        line=None;rms=1e30;retained=0
        if selection is not None:
            shifts,strength,keep=selection
            points=bases[i]+shifts[:,None]*normals[i]
            keep&=(points[:,0]>=1)&(points[:,0]<w-1)&(points[:,1]>=1)&(points[:,1]<h-1)
            report['supported']=int(keep.sum())
            if int(keep.sum())>=int(np.ceil(profiles*min_support)):
                line,rms,selected=_tls__v41_quad(points[keep])
                if line is not None:
                    retained=len(selected)
                    tangent=(q[(i+1)%4]-q[i]);length=float(np.linalg.norm(tangent))
                    along=(selected-q[i])@tangent/max(1e-9,length*length)
                    coverage=float(np.ptp(along));report.update(retained=retained,coverage=coverage,tls_rms=rms)
                    report['accepted']=bool(retained>=int(np.ceil(profiles*min_support)) and coverage>=.60 and rms<=max_rms)
                    if not report['accepted']:line=None
        lines.append(line);reports.append(report);supports.append(retained/float(profiles) if line is not None else 0.)
        rms_values.append(float(rms))
    result=q.copy();refined=0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:continue
        cross=np.cross(lines[i-1],lines[i])
        if abs(cross[2])<.08:continue
        p=cross[:2]/cross[2]
        if np.isfinite(p).all() and np.linalg.norm(p-q[i])<=3*half_window and np.all(p>=1) and p[0]<w-1 and p[1]<h-1:
            result[i]=p;refined+=1
    valid=refined==4 and all(r['accepted'] for r in reports)
    if valid:
        try:
            ordered=result.astype(np.float32);ratio=abs(cv2.contourArea(ordered))/max(1.,abs(cv2.contourArea(q.astype(np.float32))))
            valid=cv2.isContourConvex(ordered) and .85<=ratio<=1.15 and np.max(np.linalg.norm(ordered-q,axis=1))<=3*half_window
            if valid:result=ordered
        except (ValueError,cv2.error):valid=False
    deadline_hit=deadline is not None and time.perf_counter()>=deadline
    if deadline_hit:valid=False
    if not valid:result=q;refined=0
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if valid else 'rejected',
        valid=bool(valid),supported_edges=sum(s>=min_support for s in supports),refined_corners=refined,
        edges=reports,edge_support=supports,edge_rms=rms_values,edge_polarity=polarities,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(result-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-begin,refinement_thread_cpu_s=time.thread_time()-cpu,
        backend='bounded_coherent_gradient_profiles',profiles_per_edge=profiles,fraction_limits=list(fraction_limits),
        vector_sample_backend=(native_status().get('packed_exterior_backend','opencv_remap_scalar_planes')
            if image.ndim==3 and image.shape[2]==2 and max(image.shape[:2])<=1280 else 'opencv_remap_scalar_planes'),
        consensus_backend=consensus_detail.get('backend','numpy_three_peak_consensus'),
        consensus_native_wall_s=consensus_detail.get('native_wall_s',0.),
        consensus_native_thread_cpu_s=consensus_detail.get('native_thread_cpu_s',0.),
        same_frame_color_bands_only=bool(image.ndim==3 and image.shape[2]==2),gradient_consensus_required=True,
        color_vector_proof=bool(image.ndim==3),brightness_polarity_required=image.ndim==2,
        same_frame_source=True,current_source_key=array_key(image),
        source_proof_kind='raw_YUV_profiles' if image.ndim==3 and image.shape[2]==2 else 'source_color_profiles' if image.ndim==3 else 'source_Y_profiles',
        deadline_hit=deadline_hit,corner_order_preserved=True,boundary_prior_used=prior is not None and line_lock_radius is not None,
        physical_peak_lock=line_lock_radius is not None,peak_lock_radius_source=line_lock_radius,
        signed_peak_lock=bool(line_lock_radius is not None and prior is not None))
    return np.asarray(result,np.float32),evidence


def original_y_boundary(image,scale,quad,offset=(0,0),radius=3.,source_gray=None):
    """P1 native original-Y64 proof of a CURRENT tracking-space proposal.

    Independent source-resolution profiles; never relabel previous-frame points.
    RMS is conservatively rescaled; supports use retained, not pre-trim points.
    This supplies evidence only. The caller still applies its polarity/motion gate.
    """
    from tracking import refine_original_y64__v87_v74_native as refine_original_y64
    from core import luminance as luminance
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);origin=np.asarray(offset,np.float64)
    q=np.asarray(quad,np.float32).reshape(4,2)
    if scale.shape!=(2,) or np.any(scale<=0) or not np.isfinite(scale).all():raise ValueError('Source proof scale invalid')
    local=(q+.5)*scale-.5-origin
    h,w=image.shape[:2]
    if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
            or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):return None
    half=min(24.,max(3.,float(radius)*float(scale.max())))
    raw=image.ndim==3 and image.shape[2]==2
    y=source_gray;proof=None
    if raw and y is None:
        from tracking import refine_original_yuyv64__v87_v74_native as refine_original_yuyv64
        proof=refine_original_yuyv64(image,local,half)
    if proof is None:
        if y is None:y=luminance(image) if raw else image if image.ndim==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        if y.shape!=(h,w) or y.dtype!=np.uint8:raise ValueError('Source proof gray layout mismatch')
        proof=refine_original_y64(y,local,half)
    if proof is None:return None
    result,detail=proof;edges=detail.get('edges',[])
    accepted=len(edges)==4 and detail.get('refined_corners')==4 and all(e.get('accepted',False) for e in edges)
    support=[e.get('retained',0)/64. if e.get('accepted',False) else 0. for e in edges]
    rms=[float(e.get('tls_rms',1e30))/float(scale.min()) for e in edges]
    observed=((result+origin+.5)/scale-.5).astype(np.float32)
    # Preserve inward/outward contrast signs without assuming white foreground.
    # Sample source-Y endpoints at the fitted exterior, not an older frame.
    ordered=np.asarray(result,np.float64);D=np.roll(ordered,-1,axis=0)-ordered
    length=np.linalg.norm(D,axis=1);normal=np.stack((-D[:,1],D[:,0]),axis=1)/np.maximum(length[:,None],1e-9)
    normal*=np.where(np.sum((ordered.mean(axis=0)-ordered-D*.5)*normal,axis=1)<0,-1.,1.)[:,None]
    fractions=np.linspace(.06,.94,64);base=ordered[:,None,:]+fractions[None,:,None]*D[:,None,:]
    ends=base[:,:,None,:]+np.array([-half,half])[None,None,:,None]*normal[:,None,None,:]
    if y is None:
        # Packed native proof reports normalized source-profile polarity itself.
        contrast=np.array([e.get('profile_contrast',0.) for e in edges],np.float64)
    else:
        bands=sample_profiles(y,ends[...,0].reshape(256,2),ends[...,1].reshape(256,2)).reshape(4,64,2)
        contrast=np.median(bands[:,:,1]-bands[:,:,0],axis=1)
    polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist()
    valid=bool(accepted and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
    evidence=dict(valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(s>=.60 for s in support),
        edge_support=support,edge_rms=rms,edge_polarity=polarity,edge_backend='cpp_current_source_Y64',
        method='p1_original_resolution_normal_profiles_TLS',source_proof=detail,
        tracking_roi_offset=origin.tolist(),same_frame_source=True,profiles_per_edge=64,
        current_source_key=array_key(image),source_proof_kind='source_Y_profiles',fraction_limits=[.06,.94],
        boundary_fallback_s=time.perf_counter()-begin,boundary_fallback_thread_cpu_s=time.thread_time()-cpu)
    return observed,evidence


def rectangle_proposals__v41_quad(color,source_shape,checkpoint=lambda stage:None,max_candidates=12,include_lines=True):
    return rectangle_proposals__v45_color(color,source_shape,checkpoint,max_candidates,include_lines)


# ======================================================================
# ===== [11/22] v45_color =====
# ======================================================================


"""Bounded color exterior proposals / raw chroma observations; no device access.

YUYV U/V coordinates use pair centers. No fixed hue, white foreground or RGB
clipping is used to prove an exterior. Every proposal still needs four lines.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def vector_profiles(image,x,y):
    """Return [Y, 1.75 U, 1.75 V] differences without CSC clipping."""
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if image.ndim==2:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[...,None].astype(np.float32)
    if image.shape[2]==2:
        from core import require_yuyv as require_yuyv
        require_yuyv(image)
        from tracking import packed_vector_profiles__v87_v74_native as packed_vector_profiles
        direct=packed_vector_profiles(image,mx,my)
        if direct is not None:return direct
        h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
        ux=np.ascontiguousarray((mx-.5)*.5,np.float32)
        yv=cv2.remap(image[:,:,0],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        u=cv2.remap(pairs[:,:,1],ux,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
        v=cv2.remap(pairs[:,:,3],ux,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
        return np.stack((yv,1.75*u,1.75*v),axis=-1)
    bgr=cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    yv=.114*bgr[:,:,0]+.587*bgr[:,:,1]+.299*bgr[:,:,2]
    return np.stack((yv,1.75*.564*(bgr[:,:,0]-yv),1.75*.713*(bgr[:,:,2]-yv)),axis=-1)


def chroma_gray(image,shape,channel,out):
    """Only an optional LK scalar observation; source lease stays owned by caller."""
    from core import require_yuyv as require_yuyv
    require_yuyv(image)
    if channel not in ('U','V') or out.dtype!=np.uint8 or out.shape!=tuple(shape):
        raise ValueError('Invalid chroma LK workspace')
    h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
    plane=pairs[:,:,1 if channel=='U' else 3]
    cv2.resize(plane,(shape[1],shape[0]),dst=out,interpolation=cv2.INTER_LINEAR)
    # OpenCV supports in-place GaussianBlur; one small scalar plane, no RGB frame.
    cv2.GaussianBlur(out,(3,3),0,dst=out)
    return out


def _candidate(q,shape):
    h,w=shape;q=order_corners(q)
    if np.any(q<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3):return None
    area=abs(cv2.contourArea(q));edges=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edges,axis=1)
    if area<.035*w*h or min(length)<max(8.,.04*min(h,w)):return None
    sine=np.abs(np.cross(edges,np.roll(edges,1,axis=0)))/(length*np.roll(length,1))
    if min(sine)<.20:return None
    return q


def _mask_candidates(lab,checkpoint):
    """Contrast to a robust frame border, including mixed ink + white cover."""
    h,w=lab.shape[:2];band=max(3,min(h,w)//25)
    border=np.concatenate((lab[:band].reshape(-1,3),lab[-band:].reshape(-1,3),
                           lab[band:-band,:band].reshape(-1,3),lab[band:-band,-band:].reshape(-1,3)))
    center=np.median(border,axis=0);spread=np.maximum(8.,np.median(np.abs(border-center),axis=0)*1.4826)
    weight=np.clip(12./spread,.35,1.5);weight[0]*=.65
    delta=(lab.astype(np.float32)-center)*weight
    distance=np.clip(np.sqrt(np.sum(delta*delta,axis=2)),0,255).astype(np.uint8)
    checkpoint('color_border_distance')
    otsu,_=cv2.threshold(distance,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    masks=[]
    for threshold in (max(12.,otsu),max(10.,otsu*.65)):
        mask=(distance>threshold).astype(np.uint8)*255
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
        masks.append(mask)
    candidates=[]
    for mask in masks:
        checkpoint('color_mask_contours')
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:8]:
            hull=cv2.convexHull(contour);area=abs(cv2.contourArea(hull))
            if area<.035*w*h:continue
            # Hull can bridge ink/color breaks; this is never a final admission.
            for eps in (.012,.022,.04,.065):
                poly=cv2.approxPolyDP(hull,eps*cv2.arcLength(hull,True),True)
                if len(poly)!=4:continue
                try:q=_candidate(poly,(h,w))
                except ValueError:continue
                if q is not None and abs(cv2.contourArea(q))/area>=.82:candidates.append(q);break
    return candidates


def _line_candidates(edges,checkpoint):
    """Combine bounded opposite line pairs when an exterior contour is broken."""
    h,w=edges.shape;checkpoint('color_hough_segments')
    segments=cv2.HoughLinesP(edges,1,np.pi/180.,max(18,min(h,w)//10),
                            minLineLength=max(16,min(h,w)//6),maxLineGap=max(6,min(h,w)//14))
    checkpoint('color_hough_segments_done')
    if segments is None:return []
    lines=[]
    raw=segments.reshape(-1,4).astype(np.float64)
    order=np.argsort(np.linalg.norm(raw[:,2:]-raw[:,:2],axis=1))[::-1][:64]
    for i in order:
        a,b=raw[i,:2],raw[i,2:];d=b-a;length=float(np.linalg.norm(d))
        normal=np.array([-d[1],d[0]])/length;rho=float(normal@a)
        if rho<0:normal=-normal;rho=-rho
        if any(abs(float(normal@n))>.992 and abs(rho-(r if normal@n>0 else -r))<3. for n,r,_,_ in lines):continue
        lines.append((normal,rho,length,np.stack((a,b))))
        if len(lines)==24:break
    if len(lines)<4:return []
    # Opposite sides may converge; no right-angle or fixed aspect assumption.
    pairs=[]
    for a,b in itertools.combinations(range(len(lines)),2):
        n1,r1,l1,_=lines[a];n2,r2,l2,_=lines[b];dot=float(n1@n2)
        if abs(dot)<.75:continue
        if abs(r1-(r2 if dot>0 else -r2))<max(10.,.06*min(h,w)):continue
        pairs.append((a,b,l1+l2))
    pairs=sorted(pairs,key=lambda p:p[2],reverse=True)[:48]
    candidates=[]
    for first,second in itertools.combinations(pairs,2):
        if len({first[0],first[1],second[0],second[1]})!=4:continue
        if abs(float(lines[first[0]][0]@lines[second[0]][0]))>.85:continue
        checkpoint('color_line_quad')
        a,b=first[:2];c,d=second[:2];corners=[]
        for i,j in ((a,c),(a,d),(b,d),(b,c)):
            n1,r1=lines[i][:2];n2,r2=lines[j][:2];den=n1[0]*n2[1]-n1[1]*n2[0]
            if abs(den)<.20:break
            corners.append([(r1*n2[1]-n1[1]*r2)/den,(n1[0]*r2-r1*n2[0])/den])
        if len(corners)!=4:continue
        try:q=_candidate(np.asarray(corners,np.float32),(h,w))
        except ValueError:continue
        if q is None:continue
        # Every proposed side must have an actual segment spanning its interior.
        good=True
        for i in (a,b,c,d):
            normal,rho,_,segment=lines[i];distance=np.abs(q@normal-rho)
            ids=np.argsort(distance)[:2];p1,p2=q[ids];vector=p2-p1;length=float(np.linalg.norm(vector))
            t=(segment-p1)@vector/max(1e-9,length*length)
            overlap=max(0.,min(1.,float(max(t)))-max(0.,float(min(t))))
            if overlap<.40:good=False;break
        if good and not any(np.max(np.linalg.norm(q-old,axis=1))<3. for old in candidates):candidates.append(q)
        if len(candidates)>=32:break
    return candidates


def rectangle_proposals__v45_color(color,source_shape,checkpoint=lambda stage:None,max_candidates=12,include_lines=True):
    """Candidate union only; closed gradients, border contrast and long line pairs."""
    begin=time.perf_counter();h,w=color.shape[:2];H,W=source_shape[:2]
    if color.dtype!=np.uint8 or color.ndim!=3 or color.shape[2]!=3:raise ValueError('Expected small BGR proposal image')
    checkpoint('multicolor_gradient_prepare')
    smooth=cv2.GaussianBlur(color,(3,3),0);lab=cv2.cvtColor(smooth,cv2.COLOR_BGR2LAB)
    channels=(lab[:,:,0],lab[:,:,1],lab[:,:,2]);union=np.zeros((h,w),np.uint8)
    for plane in channels:
        checkpoint('multicolor_channel_edges');union|=cv2.Canny(plane,12,40)
    candidates=_mask_candidates(lab,checkpoint)
    # Closed contours and convex hulls are proposals, not 75% filled-color masks.
    for kernel in (3,5):
        checkpoint('multicolor_contours')
        edges=cv2.morphologyEx(union,cv2.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:20]:
            hull=cv2.convexHull(contour);area=abs(cv2.contourArea(hull))
            if area<.035*w*h:continue
            for epsilon in (.012,.025,.045,.065):
                poly=cv2.approxPolyDP(hull,epsilon*cv2.arcLength(hull,True),True)
                if len(poly)!=4:continue
                try:q=_candidate(poly,(h,w))
                except ValueError:continue
                if q is not None and abs(cv2.contourArea(q))/area>.85:candidates.append(q);break
    if include_lines:candidates.extend(_line_candidates(union,checkpoint))
    unique=[]
    for q in sorted(candidates,key=lambda q:abs(cv2.contourArea(q)),reverse=True):
        q=(q+.5)*[W/w,H/h]-.5
        if not any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in unique):unique.append(q.astype(np.float32))
        if len(unique)>=max_candidates:break
    return unique


def iter_recovery_rectangles(color,source_shape,checkpoint,allow_lines,max_candidates=8):
    """Yield cheap proposals for immediate admission BEFORE bounded line fallback.

    Only budgeted recovery uses this scheduler. Startup and final source64/current24
    validation keep their existing path. Coarse lines never constitute a proof.
    """
    seen=[]
    for q in rectangle_proposals__v45_color(color,source_shape,checkpoint,max_candidates,include_lines=False):
        seen.append(q);yield q
    if len(seen)>=max_candidates or not allow_lines():return
    checkpoint('bounded_color_line_prepare')
    h,w=color.shape[:2];scale=min(1.,160./max(h,w))
    small=cv2.resize(color,(max(2,round(w*scale)),max(2,round(h*scale))),interpolation=cv2.INTER_LINEAR) if scale<1. else color
    lab=cv2.cvtColor(cv2.GaussianBlur(small,(3,3),0),cv2.COLOR_BGR2LAB)
    union=np.zeros(small.shape[:2],np.uint8)
    for k in range(3):
        checkpoint('bounded_color_line_channel');union|=cv2.Canny(lab[:,:,k],12,40)
    # Recheck immediately before the non-preemptible OpenCV call.
    if not allow_lines():return
    H,W=source_shape[:2];lh,lw=union.shape
    for local in _line_candidates(union,checkpoint):
        q=((local+.5)*[W/lw,H/lh]-.5).astype(np.float32)
        if any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in seen):continue
        seen.append(q);yield q
        if len(seen)>=max_candidates:return


# ======================================================================
# ===== [12/22] v48_candidates =====
# ======================================================================


"""Streaming low-resolution exterior proposals; each still needs source proof."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def exterior_candidates(image,check,limit=192):
    """Rank bounded outer/enclosed hypotheses; all still need source proof."""
    yield from ranked_exterior_candidates(image,check,limit)


# ======================================================================
# ===== [13/22] v49_boundary =====
# ======================================================================


"""Current-frame exterior agreement and ephemeral detector receipts; CPU only."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def array_key(a):
    return (int(a.ctypes.data),tuple(a.shape),tuple(a.strides),a.dtype.str)

def actual_source64(evidence,source_key):
    return bool(source_key is not None and evidence.get('same_frame_source')
        and evidence.get('profiles_per_edge')==64 and evidence.get('current_source_key')==source_key
        and evidence.get('source_proof_kind') in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles')
        and len(evidence.get('fraction_limits',()))==2 and not evidence.get('deadline_hit'))

def exterior_agreement(first,second,first_e,second_e,scale,source_key=None):
    """Line-normal disagreement avoids amplifying tiny errors at intersections.

    Independent CURRENT source64 proof remains mandatory for wider searches.
    Supports/RMS, polarity, convexity and temporal geometry are checked by caller.
    Both the fit-derived normal allowance and absolute corner cap are bounded.
    """
    from tracking import pair_geometry as pair_geometry
    error,line_error,corner_error=pair_geometry(first,second)
    if error is not None:
        return dict(verified=False,reason='invalid_current_quad' if error=='invalid' else 'degenerate_current_edges')
    rms_a=float(max(first_e.get('edge_rms',[1e30]*4)))
    rms_b=float(max(second_e.get('edge_rms',[1e30]*4)))
    support=min(tuple(first_e.get('edge_support',[0.]*4))+tuple(second_e.get('edge_support',[0.]*4)))
    normal_limit=float(np.clip(.30+.5*(rms_a+rms_b)+.125*float(np.min(scale)),.55,.90))
    provenance=actual_source64(second_e,source_key)
    independent=not (actual_source64(first_e,source_key)
        and first_e.get('source_proof_kind')==second_e.get('source_proof_kind')
        and first_e.get('fraction_limits')==second_e.get('fraction_limits'))
    verified=(provenance and independent and first_e.get('valid',False) and second_e.get('valid',False)
        and first_e.get('supported_edges')==4 and second_e.get('supported_edges')==4
        and first_e.get('refined_corners')==4 and second_e.get('refined_corners')==4
        and support>=.80 and max(rms_a,rms_b)<=.65
        and line_error<=normal_limit and corner_error<=1.5)
    return dict(verified=bool(verified),line_normal_difference=line_error,
        normal_limit=normal_limit,corner_difference=corner_error,corner_limit=1.5,
        min_support=float(support),max_rms=max(rms_a,rms_b),units='tracking_pixels',
        proof='same_frame_independent_source64',source64_provenance_verified=bool(provenance),independent_sampling_verified=bool(independent),
        profiles_per_edge=second_e.get('profiles_per_edge'),source_backend=second_e.get('edge_backend'),old_H_not_used=True)

def outer_features(points,quad):
    """Keep real features in a narrow exterior band, not playing screen content."""
    p=np.asarray(points,np.float32).reshape(-1,2);q=np.asarray(quad,np.float32)
    if not len(p):return p
    edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
    if np.min(length)<4:return np.empty((0,2),np.float32)
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    center=q.mean(axis=0)
    normal*=np.where(np.sum((center-q)*normal,axis=1)>=0,1.,-1.)[:,None]
    d=np.sum((p[:,None,:]-q[None,:,:])*normal[None,:,:],axis=2)
    # Allow a little exterior/case texture; exclude the deep interior. The width
    # is bounded in observation pixels and scales with the shortest side.
    # Only the rim/exterior carries camera/object motion. Screen pixels must
    # not dominate FB/RANSAC even when the content inside the case is moving.
    width=float(np.clip(.02*float(np.min(length)),1.25,2.0))
    keep=np.isfinite(p).all(axis=1)&(np.min(d,axis=1)>=-3.)&(np.min(d,axis=1)<=width)
    return np.ascontiguousarray(p[keep],np.float32)

def issue_receipt(observation,source_corners,evidence,gate,original_edges,scale):
    # Only synchronous recovery has a caller-owned frame index and source key.
    # Startup/external supplied corners cannot get a reusable receipt.
    if observation is None or 'frame_index' not in observation or 'source_key' not in observation:return None
    return dict(frame_index=int(observation['frame_index']),source_key=observation['source_key'],
        gray_key=array_key(observation['gray']),scale=tuple(float(v) for v in scale),
        source_corners=np.asarray(source_corners,np.float32).tolist(),
        evidence=copy.deepcopy(evidence),gate=copy.deepcopy(gate),
        original_all_four=bool(original_edges.get('refined_corners')==4 and
            len(original_edges.get('edges',[]))==4 and all(e.get('accepted',False) for e in original_edges['edges'])))

def read_receipt(info,image,gray,scale,index,full):
    """A receipt proves only this call's frame/gray/layout/returned four corners.

    Plain CPU metadata; never caches H or owns source/MMAP arrays. A mismatch
    falls back to full current validation rather than accepting a stale receipt.
    """
    r=info.get('_current_boundary_receipt')
    if not isinstance(r,dict):return None
    if (r.get('frame_index')!=index or r.get('source_key')!=array_key(image)
        or r.get('gray_key')!=array_key(gray) or r.get('scale')!=tuple(float(v) for v in scale)
        or not r.get('original_all_four') or not r.get('gate',{}).get('reliable')):return None
    source=np.asarray(r['source_corners'],np.float32);q=np.asarray(full,np.float32)
    if source.shape!=(4,2) or q.shape!=(4,2) or not np.isfinite(source).all() or not np.isfinite(q).all() or np.max(np.abs(source-q))>1e-3:return None
    e=copy.deepcopy(r['evidence'])
    if (not e.get('valid',False) or e.get('supported_edges')!=4 or e.get('refined_corners')!=4
        or min(e.get('edge_support',[0.]*4))<.60 or max(e.get('edge_rms',[1e30]*4))>1.):return None
    candidate=((source+.5)/scale-.5).astype(np.float32)
    g=dict(r['gate'],same_frame_receipt_reused=True,repeated_border_selection_skipped=True)
    return candidate,e,g


# ======================================================================
# ===== [14/22] v50_orientation =====
# ======================================================================


"""Two layouts with time-bounded evidence and transactional H commit."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

@dataclass(frozen=True)
class OrientationProposal:
    quad:object
    size:object
    detail:dict
    state:dict
    base_revision:int

class DualOrientation:
    __slots__=('__dict__','_draft')
    def __init__(self,mode,size,confirm_frames=2):
        if mode not in ('fixed','auto_two'):raise ValueError('output_orientation must be fixed/auto_two')
        if isinstance(confirm_frames,bool) or not isinstance(confirm_frames,int) or not 2<=confirm_frames<=8:
            raise ValueError('orientation_confirm_frames must be2..8')
        if mode=='auto_two':
            if size is None or len(size)!=2:raise ValueError('auto_two requires output_size=(short,long)')
            if any(isinstance(v,bool) or not isinstance(v,(int,np.integer)) for v in size):raise ValueError('Dual output dimensions must be integers')
            a,b=sorted(map(int,size))
            if not 16<=a<b<=1280:raise ValueError('Dual output requires16<=short<long<=1280')
            self.sizes={'portrait':(a,b),'landscape':(b,a)}
        else:self.sizes={}
        self.mode=mode;self.confirm_frames=confirm_frames;self.orientation=None
        self.long_family=1;self.shift=0;self.generation=0;self.metric={}
        self.pending=None;self.count=0;self.pending_at=0.;self.last_vote_at=0.
        self.flip_count=0;self.flip_at=0.;self.last_switch_at=-1e9
        self.evidence_window_s=.5;self.cooldown_s=.2;self.revision=0

    def lost(self,timestamp=None):
        # HELD/LOST are not votes. Expire by elapsed time, not processed index.
        now=time.perf_counter() if timestamp is None else float(timestamp)
        if now-self.last_vote_at>self.evidence_window_s:self.pending=None;self.count=0
        if now-self.flip_at>self.evidence_window_s:self.flip_count=0

    def propose(self,q,image_shape,index,new_target=False,confidence=1.,timestamp=None,strong_verified=False):
        draft=getattr(self,'_draft',None)
        if draft is None:
            draft=object.__new__(DualOrientation);self._draft=draft
        draft.__dict__.clear();draft.__dict__.update(self.__dict__)
        quad,size,detail=draft._observe(q,image_shape,index,new_target,confidence,timestamp,strong_verified)
        return OrientationProposal(quad,size,detail,dict(draft.__dict__),self.revision)

    def commit(self,proposal):
        if proposal.base_revision!=self.revision:raise ValueError('Stale orientation proposal')
        self.__dict__.update(proposal.state);self.revision+=1
        return dict(proposal.detail,orientation_committed=True,layout_generation=self.generation)

    def observe(self,q,image_shape,index,new_target=False,confidence=1.,**kwargs):
        p=self.propose(q,image_shape,index,new_target,confidence,**kwargs)
        return p.quad,p.size,self.commit(p)

    def _observe(self,q,image_shape,index,new_target,confidence,timestamp,strong_verified):
        began=time.perf_counter();now=began if timestamp is None else float(timestamp)
        q=np.asarray(q,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Orientation requires finite current four corners')
        if self.mode=='fixed':return q,None,dict(policy='fixed',changed=False,layout_generation=0,orientation_s=time.perf_counter()-began)
        first=self.orientation is None;old=self.orientation;old_shift=self.shift
        reinitialized=False;family=self.long_family
        if first or new_target:
            ratio,metric=aspect_ratio(q,image_shape)
            # Ambiguous aspect never vetoes orientation. Do not rename an
            # established physical edge family on a near-equal estimate.
            if first or ratio<.85 or ratio>1.15:family=0 if ratio>1 else 1
            self.metric=metric
            if new_target:self.pending=None;self.count=0;self.flip_count=0
        edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
        if np.min(length)<4:raise ValueError('Degenerate orientation edges')
        unit=edge/length[:,None];ids=(family,family+2)
        axis_ratio=float(sum(abs(unit[i,0]) for i in ids))/max(float(sum(abs(unit[i,1]) for i in ids)),1e-6)
        angle=float(np.degrees(np.arctan2(1.,axis_ratio)))
        desired='landscape' if axis_ratio>1.15 else 'portrait' if axis_ratio<1/1.15 else None
        changed=False;reorder=False;decision='retain_in_angle_deadband';switch_requested_at=None
        if first:
            self.orientation=desired or ('landscape' if axis_ratio>1 else 'portrait')
            self.long_family=family;reorder=True;decision='initial_current_layout'
        else:
            self.lost(now)
            target=desired or self.orientation;family_changed=family!=self.long_family
            proposal=(target,family)
            if confidence<.75:decision='weak_current_direction_no_vote'
            elif target==self.orientation and not family_changed:
                self.pending=None;self.count=0;decision='current_layout_confirmed'
            else:
                if self.pending!=proposal or now-self.last_vote_at>self.evidence_window_s:
                    self.pending=proposal;self.count=1;self.pending_at=now
                else:self.count+=1
                self.last_vote_at=now
                strong=bool(strong_verified and confidence>=.90 and desired is not None
                    and (axis_ratio>=1.7 or axis_ratio<=1/1.7))
                enough=strong or self.count>=self.confirm_frames
                if enough and (strong or now-self.last_switch_at>=self.cooldown_s):
                    switch_requested_at=self.pending_at
                    self.orientation=target;self.long_family=family
                    changed=target!=old;reinitialized=family_changed;reorder=changed or family_changed
                    self.pending=None;self.count=0;self.last_switch_at=now
                    decision='strong_current_proof_fast_switch' if strong else 'time_window_votes_confirmed'
                else:decision='pending_current_direction'
        # Half-turn geometry is independent of semantic text/video direction.
        if not first and not reorder:
            top=float((q[self.shift,1]+q[(self.shift+1)%4,1])*.5)
            bottom=float((q[(self.shift+2)%4,1]+q[(self.shift+3)%4,1])*.5)
            if top-bottom>.10*float(np.min(length)) and confidence>=.75:
                if now-self.flip_at>self.evidence_window_s:self.flip_count=0
                self.flip_count+=1;self.flip_at=now
                strong_flip=bool(strong_verified and confidence>=.90 and top-bottom>.35*float(np.min(length)))
                if (strong_flip or self.flip_count>=self.confirm_frames) and (strong_flip or now-self.last_switch_at>=self.cooldown_s):
                    reorder=True;self.flip_count=0;self.last_switch_at=now
                    decision='current_half_turn_reorder';switch_requested_at=now
            else:self.flip_count=0
        if first or reorder:
            top_family=self.long_family if self.orientation=='landscape' else 1-self.long_family
            self.shift=min((top_family,top_family+2),key=lambda i:float((q[i,1]+q[(i+1)%4,1])*.5))
            self.generation+=1
        result=np.ascontiguousarray(np.roll(q,-self.shift,axis=0),np.float32)
        detail=dict(policy='auto_two_time_window',orientation=self.orientation,changed=changed,
            mapping_reoriented=bool(not first and self.shift!=old_shift),reinitialized=reinitialized,
            target_change_proposed=bool(new_target),output_size=list(self.sizes[self.orientation]),
            output_corner_shift=self.shift,layout_generation=self.generation,long_edge_family=self.long_family,
            long_axis_ratio=axis_ratio,long_axis_angle_degrees=angle,square_switch_veto=False,
            pending_orientation=None if self.pending is None else self.pending[0],confirmation_count=self.count,
            required_confirmations=self.confirm_frames,evidence_window_s=self.evidence_window_s,
            minimum_switch_interval_s=self.cooldown_s,decision=decision,orientation_committed=False,
            switch_requested_at=switch_requested_at,switch_decided_at=now if reorder and not first else None,
            aspect_method=self.metric.get('method'),aspect_confidence=self.metric.get('confidence'),
            orientation_s=time.perf_counter()-began,semantic_text_orientation=False)
        return result,self.sizes[self.orientation],detail


# ======================================================================
# ===== [15/22] v51_target =====
# ======================================================================


"""Bounded CPU target/corner continuity; no cached H, image leases or device IO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def align_current(candidate,evidence,reference):
    """Match cyclic numbering only; never move/smooth the measured corners."""
    q=np.asarray(candidate,np.float32);r=np.asarray(reference,np.float32)
    distances=[float(np.max(np.linalg.norm(np.roll(q,-i,axis=0)-r,axis=1))) for i in range(4)]
    shift=int(np.argmin(distances));e=dict(evidence)
    if shift:
        for name in ('edge_support','edge_rms','edge_polarity','border_colors','corner_displacements'):
            if name in e and len(e[name])==4:e[name]=list(e[name][shift:])+list(e[name][:shift])
        if len(e.get('edges',()))==4:
            reports=e['edges'][shift:]+e['edges'][:shift]
            e['edges']=[dict(item,edge=i) for i,item in enumerate(reports)]
    e['corner_correspondence_shift']=shift
    return np.ascontiguousarray(np.roll(q,-shift,axis=0),np.float32),e

def border_signature(evidence):
    colors=np.asarray(evidence.get('border_colors',()),np.float32)
    if colors.shape!=(4,6) or not np.isfinite(colors).all() or not evidence.get('valid'):return None
    # Difference across the physical exterior is less sensitive to a uniform
    # exposure/color cast than the absolute cover or playing screen content.
    delta=colors[:,3:]-colors[:,:3]
    return np.clip(delta/np.array([255.,224.,224.],np.float32),-1.5,1.5)

def target_relation(previous,candidate,evidence,signature):
    current=border_signature(evidence)
    diagonal=max(8.,float(np.linalg.norm(np.asarray(previous)[2]-np.asarray(previous)[0])))
    travel=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))/diagonal
    difference=None if current is None or signature is None else float(np.mean(np.abs(current-signature)))
    same=difference is not None and difference<=.15 and travel<=.20
    changed=difference is not None and difference>.25
    label='same_target' if same else 'new_target' if changed else 'unproven_reacquisition'
    return dict(state=label,same_target=bool(same),target_changed=not same,
        boundary_signature_difference=difference,normalized_corner_travel=travel,
        semantic_identity_proven=False),current


# ======================================================================
# ===== [16/22] v62_boundary =====
# ======================================================================


"""Current physical-line lock and single-use startup evidence; CPU metadata only."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def peak_radius(scale,evidence,half):
    """A peak corridor in SOURCE pixels, independent of object motion."""
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):
        raise ValueError('Physical peak lock requires positive source scale')
    values=evidence.get('edge_rms',[]) if evidence else []
    noise=max(values)*float(scale.min()) if len(values)==4 and all(np.isfinite(v) and 0<=v<=2 for v in values) else 0.
    return float(min(.70*half,np.clip(1.25+.75*noise,1.25,2.0)))


def layer_continuity(previous,evidence):
    """Check signed sides on strong edges, not the colour of playing content."""
    current=border_signature(evidence)
    if previous is None or current is None:
        return dict(verified=True,measured=False,reason='no_signed_vector_prior')
    a=np.asarray(previous,np.float64);b=np.asarray(current,np.float64)
    if a.shape!=(4,3) or b.shape!=(4,3) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return dict(verified=False,measured=False,reason='invalid_signed_layer_prior')
    weights=np.array([255.,224.,224.]);a=a*weights;b=b*weights
    na=np.linalg.norm(a,axis=1);nb=np.linalg.norm(b,axis=1)
    strong=(na>=16.)&(nb>=16.)
    cosine=np.sum(a*b,axis=1)/np.maximum(na*nb,1e-9)
    failed=strong&(cosine<.25)
    return dict(verified=not bool(failed.any()),measured=bool(strong.any()),
        strong_edges=int(strong.sum()),opposite_edges=int(failed.sum()),
        edge_cosine=cosine.tolist(),minimum_cosine=.25,
        reason='same_signed_physical_side' if not failed.any() else 'parallel_layer_side_changed')


def issue_startup_receipt(image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate):
    """Bind actual primary64 and independent24 to THIS caller-held source array.

    No arrays, image leases or hardware pointers are owned by this record.
    Startup alone consumes it synchronously before the source lease is returned.
    Background proposals must still be sampled on their currently leased frame.
    """
    key=array_key(image)
    if (not agreement.get('verified') or not gate.get('reliable') or not actual_source64(primary,key)
        or secondary.get('profiles_per_edge')!=24 or not secondary.get('same_frame_source')
        or secondary.get('current_source_key')!=key or secondary.get('deadline_hit')):
        return None
    return dict(source_instance_id=id(image),source_key=array_key(image),
        source_corners=np.asarray(source_quad,np.float32).tolist(),
        scale=tuple(float(v) for v in scale),primary=copy.deepcopy(primary),
        secondary=copy.deepcopy(secondary),secondary_corners=np.asarray(secondary_quad,np.float32).tolist(),
        gate=dict(gate),agreement=dict(agreement),consumed=False,
        kind='same_live_source_primary64_independent24')


def consume_startup_receipt(info,image,source_quad,scale):
    """Recheck geometry/provenance without rerunning any border search."""
    if not isinstance(info,dict):return None
    receipt=info.pop('_initial_boundary_receipt',None)
    if not isinstance(receipt,dict) or receipt.get('consumed'):return None
    receipt['consumed']=True
    source=np.asarray(source_quad,np.float32);bound=np.asarray(receipt.get('source_corners'),np.float32)
    scale=np.asarray(scale,np.float64)
    if (receipt.get('kind')!='same_live_source_primary64_independent24'
        or receipt.get('source_instance_id')!=id(image) or receipt.get('source_key')!=array_key(image)
        or receipt.get('scale')!=tuple(float(v) for v in scale)
        or source.shape!=(4,2) or bound.shape!=(4,2) or not np.isfinite(bound).all()
        or np.max(np.abs(source-bound))>1e-3):return None
    primary=receipt.get('primary',{});secondary=receipt.get('secondary',{})
    if (not actual_source64(primary,array_key(image)) or secondary.get('profiles_per_edge')!=24
        or not secondary.get('same_frame_source') or secondary.get('current_source_key')!=array_key(image)
        or secondary.get('deadline_hit')):return None
    q=((source+.5)/scale-.5).astype(np.float32)
    other=np.asarray(receipt.get('secondary_corners'),np.float32)
    agreement=current_agreement(other,q,secondary,primary,scale,array_key(image))
    lock=line_lock(q,other)
    if not agreement.get('verified') or not lock.get('verified') or not receipt.get('gate',{}).get('reliable'):return None
    agreement.update(startup_same_frame_proof_reused=True,repeated_border_search_skipped=True,
        source_instance_bound=True,receipt_single_use=True,line_lock=lock)
    return q,copy.deepcopy(primary),dict(receipt['gate'],same_frame_proof_reused=True),agreement


# ======================================================================
# ===== [17/22] v62_exterior =====
# ======================================================================


"""Bounded coarse outer-frame hypotheses. CPU RAM only, never an admission."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def enclosure(parent,child,margin=0.):
    """A larger aligned current quadrilateral may enclose a printed/video inset.

    Containment alone is insufficient: retain three matching side directions
    and bound the area ratio. No expected hue, brightness or portrait is used.
    """
    a=np.asarray(parent,np.float32);b=np.asarray(child,np.float32)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():return False
    aa=abs(cv2.contourArea(a));ab=abs(cv2.contourArea(b))
    if ab<=1 or not 1.12<=aa/ab<=6.:return False
    if any(cv2.pointPolygonTest(a,tuple(float(v) for v in p),True)<-margin for p in b):return False
    da=np.roll(a,-1,axis=0)-a;db=np.roll(b,-1,axis=0)-b
    na=np.linalg.norm(da,axis=1);nb=np.linalg.norm(db,axis=1)
    if min(na.min(),nb.min())<4:return False
    ua=da/na[:,None];ub=db/nb[:,None]
    return any(np.count_nonzero(np.abs(np.sum(ua*np.roll(ub,k,axis=0),axis=1))>=.94)>=3 for k in range(4))

def coarse_support(magnitude,quad,cutoff):
    """Cheap current 20-position perimeter evidence for ranking, not proof."""
    q=np.asarray(quad,np.float64);edge=np.roll(q,-1,axis=0)-q
    length=np.linalg.norm(edge,axis=1)
    if length.min()<4:return np.zeros(4,np.float64)
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    base=q[:,None,:]+np.linspace(.08,.92,20)[None,:,None]*edge[:,None,:]
    xy=base[:,:,None,:]+np.linspace(-1.5,1.5,5)[None,None,:,None]*normal[:,None,None,:]
    h,w=magnitude.shape
    x=np.clip(np.rint(xy[...,0]).astype(np.int32),0,w-1)
    y=np.clip(np.rint(xy[...,1]).astype(np.int32),0,h-1)
    peaks=np.max(magnitude[y,x],axis=2)
    return np.mean(peaks>=max(6.,cutoff*.8),axis=1)

def rank_pool(pool,magnitude,cutoff,check):
    if not pool:return []
    entries=[];h,w=magnitude.shape
    for q,source in pool:
        check('outer_hypothesis_perimeter')
        support=coarse_support(magnitude,q,cutoff)
        area=abs(cv2.contourArea(q))/float(w*h)
        entries.append(dict(quad=q,source=source,support=support,
            score=float(support.min()+.35*support.mean()+.12*np.sqrt(area)),parents=[]))
    for i,e in enumerate(entries):
        for j,p in enumerate(entries):
            if i==j or p['support'].min()<.55:continue
            if enclosure(p['quad'],e['quad'],margin=1.5):e['parents'].append(j)
    # Test plausible enclosures first; tiny insets cannot win merely because
    # playing content has a very sharp gradient. Every result still needs real
    # source-resolution four-edge refinement in the detector.
    order=sorted(range(len(entries)),key=lambda i:(bool(entries[i]['parents']),-entries[i]['score']))
    return [entries[i] for i in order]

def ranked_exterior_candidates(image,check,limit=192):
    """At most 12 coarse hypotheses/pass before any expensive admission.

    Reuses the original Y/U/V downsample and gradient front end. Pooling only
    low-resolution polygons permits containment-aware selection without a
    second full-frame color conversion or source-sized mask.
    """
    h,w=image.shape[:2];ow=min(w,int(limit));oh=max(16,round(h*ow/w))
    if image.ndim==3 and image.shape[2]==2:
        from core import require_yuyv as require_yuyv
        require_yuyv(image);check('fast_YUV_downsample')
        planes=[cv2.resize(image[:,:,0],(ow,oh),interpolation=cv2.INTER_LINEAR),
                cv2.resize(image[:,0::2,1],(ow,oh),interpolation=cv2.INTER_LINEAR),
                cv2.resize(image[:,1::2,1],(ow,oh),interpolation=cv2.INTER_LINEAR)]
    elif image.ndim==3:
        check('fast_color_downsample')
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=list(cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb)))
    else:
        check('fast_Y_downsample')
        planes=[cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)]
    check('fast_YUV_gradients');magnitude=np.zeros((oh,ow),np.uint8)
    for i,plane in enumerate(planes):
        smooth=cv2.GaussianBlur(plane,(3,3),0)
        dx=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,1,0,ksize=3),alpha=.25 if i==0 else .4375)
        dy=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,0,1,ksize=3),alpha=.25 if i==0 else .4375)
        np.maximum(magnitude,cv2.max(dx,dy),out=magnitude)
    threshold,_=cv2.threshold(magnitude,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    kernel=np.ones((3,3),np.uint8);seen=[]
    from tracking import _visible_quad as _visible_quad
    scale=np.array([w/ow,h/oh],np.float64)
    for cutoff in dict.fromkeys((max(8,int(threshold)),max(6,int(threshold*.65)))):
        check('fast_YUV_closed_edges')
        edges=cv2.morphologyEx((magnitude>=cutoff).astype(np.uint8)*255,cv2.MORPH_CLOSE,kernel)
        check('fast_YUV_contours')
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        pool=[]
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:16]:
            check('fast_YUV_polygon')
            if abs(cv2.contourArea(contour))<.035*ow*oh:continue
            hull=cv2.convexHull(contour);perimeter=cv2.arcLength(hull,True)
            coarse=None
            for eps in (.012,.022,.04,.065):
                polygon=cv2.approxPolyDP(hull,eps*perimeter,True)
                if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
                try:q=_visible_quad((polygon.reshape(4,2)+.5)*scale-.5,image.shape)
                except ValueError:continue
                coarse=q;break
            if coarse is None:continue
            if any(np.max(np.linalg.norm(coarse-old,axis=1))<3. for old in seen):continue
            if any(np.max(np.linalg.norm(coarse-old[1],axis=1))<3. for old in pool):continue
            low=((coarse+.5)/scale-.5).astype(np.float32)
            pool.append((low,coarse))
            if len(pool)>=12:break
        for entry in rank_pool(pool,magnitude,cutoff,check):
            q=entry['source'];seen.append(q.copy());yield q

def proven_outer_parent(candidate,proven):
    """Reject an inset only when a larger CURRENT source four-edge fit exists."""
    for q in proven:
        if enclosure(q,candidate,margin=2.):
            return dict(enclosed=True,outer_corners=np.asarray(q).tolist(),
                reason='larger_source_primary_outer_blocks_inset',coarse_rank_is_not_proof=True,independent_CURRENT_proof_not_claimed=True)
    return None


# ======================================================================
# ===== [18/22] v62_policy =====
# ======================================================================


"""V61 bounded current-edge policies; owns no frame leases or device IO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class LKWorkBudgetExceeded(ValueError):
    """A completed failed FB attempt cannot retry within its compute window."""

class LKPhaseBudget:
    """Budget whole attempts, never half of a forward/backward transaction."""
    def __init__(self,cpu_s=.12,wall_s=.40):
        self.begin=time.perf_counter();self.cpu=time.thread_time()
        self.cpu_s=float(cpu_s);self.wall_s=float(wall_s)
        self.deadline=self.begin+self.wall_s
    def retry_allowed(self):
        return time.thread_time()-self.cpu<self.cpu_s and time.perf_counter()<self.deadline
    def summary(self):
        wall=time.perf_counter()-self.begin;cpu=time.thread_time()-self.cpu
        return dict(budget_basis='thread_CPU_with_separate_wall_guard',cpu_budget_s=self.cpu_s,
            wall_guard_s=self.wall_s,wall_s=wall,thread_cpu_s=cpu,
            wall_minus_thread_cpu_s=max(0.,wall-cpu),cpu_budget_hit=cpu>=self.cpu_s,
            wall_guard_hit=wall>=self.wall_s,cpu_overshoot_s=max(0.,cpu-self.cpu_s),
            wall_overshoot_s=max(0.,wall-self.wall_s),complete_FB_attempt_reserved=True,
            old_prepare_wall_deadline_used=False,scope='cooperative; complete checks never split')

def proof_band(scale,evidence=None):
    """A source-pixel proof band independent of the motion search radius."""
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):
        raise ValueError('Current proof requires positive finite 2D scale')
    rms=[] if evidence is None else evidence.get('edge_rms',[])
    noise=max(rms)*float(np.min(scale)) if len(rms)==4 and all(np.isfinite(v) and 0<=v<=2. for v in rms) else 0.
    # Current fit noise widens only the sampling band, never the line lock.
    half=float(np.clip(max(3.,1.5*float(np.min(scale)))+1.25*noise,3.,6.))
    return half/float(np.max(scale)),half

def sample_locked_color(image,scale,quad,profiles,deadline,boundary_prior=None,half_source=None,offset=(0,0),lock_physical=True,lock_evidence=None):
    """Use existing packed native sampling without another gray edge search.

    Sampling width and the caller's geometric tolerance are separate. Source
    provenance/line fits are real, supplied by the existing refine_boundary.
    No source arrays or pointers escape this synchronous CPU transaction.
    """
    from tracking import _visible_quad as _visible_quad
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);_,default_half=proof_band(scale)
    half=default_half if half_source is None else float(half_source)
    if not np.isfinite(half) or not 2.5<=half<=24.:raise ValueError('Current sample half-window must be2.5..24 source pixels')
    origin=np.asarray(offset,np.float64)
    if origin.shape!=(2,) or not np.isfinite(origin).all():raise ValueError('Current sample offset invalid')
    q=np.asarray(quad,np.float32)
    local=_visible_quad((q+.5)*scale-.5-origin,image.shape,preserve_order=True)
    peak=peak_radius(scale,lock_evidence or {},half) if lock_physical else None
    candidate,evidence=refine_boundary(image,local,half,profiles=profiles,
        max_rms=float(scale.min()),minimum_contrast=8.,
        fraction_limits=(.12,.88) if profiles==24 else (.10,.90),
        deadline=deadline,boundary_prior=boundary_prior,line_lock_radius=peak)
    observed=((candidate+origin+.5)/scale-.5).astype(np.float32)
    evidence=dict(evidence,edge_rms=[float(v)/float(scale.min()) for v in evidence['edge_rms']],
        edge_backend='locked_current_YUV'+str(profiles),tracking_roi_offset=origin.tolist(),
        boundary_fallback_s=time.perf_counter()-begin,
        boundary_fallback_thread_cpu_s=time.thread_time()-cpu,
        direct_locked_band=True,repeated_gray_edge_search=False)
    return observed,evidence

def line_lock(reference,candidate):
    """Check both quads' lines, not just potentially sensitive intersections."""
    from tracking import pair_geometry as pair_geometry
    error,normal,corner=pair_geometry(reference,candidate)
    if error is not None:
        return dict(verified=False,reason='invalid_line_lock' if error=='invalid' else 'degenerate_line_lock')
    return dict(verified=bool(normal<=.75 and corner<=1.5),line_normal_difference=normal,
        normal_limit=.75,corner_difference=corner,corner_limit=1.5,units='tracking_pixels',
        lock='one_current_primary_edge_reference',old_H_not_used=True)

def stable_current(evidence,gate,candidate,previous,age,max_gap,scheduled=False,lost=False):
    """Fresh strong Y uses the original normal path; maximum FB age remains."""
    shift=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))
    supports=evidence.get('edge_support',[0.]*4);rms=evidence.get('edge_rms',[1e30]*4)
    okay=(not lost and not scheduled and 0<=age<max_gap and gate.get('reliable',False)
        and evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and not evidence.get('color_vector_proof',False)
        and len(supports)==4 and len(rms)==4 and min(supports)>=.75 and max(rms)<=.50
        and gate.get('polarity_flips',1)==0 and gate.get('prediction_correction',1e30)<=1.
        and shift<=1.5)
    return dict(eligible=bool(okay),policy='V58_normal_current_Y_four_edges',corner_shift=shift,
        max_shift=1.5,min_support=.75,max_rms=.50,anchor_age=int(age),max_anchor_age=int(max_gap),
        current_four_edges_required=True,scheduled_FB_not_skipped=True,reacquisition=False)

def stable_fb_context(detail,travel,correction,lost,elapsed,processing_gap=False):
    """Bounded same-target tolerance only AFTER complete current FB/four-edge fit.

    A proven latest-slot processing skip may use up to .75s elapsed, with tighter
    motion/FB/inlier bounds. A genuine/stale/invalid capture gap is not eligible.
    New-target admission and LOST remain strict; current independent proof stays.
    """
    if lost or elapsed is None or not np.isfinite(elapsed) or not np.isfinite(travel):return False
    common=(0<float(elapsed)<=.75 and travel<=6. and correction<=2.5
        and detail.get('good_features',0)>=4 and detail.get('inlier_fraction',0.)>=.85
        and detail.get('fb_median',1e30)<.7)
    if not common:return False
    if float(elapsed)<=.35:return True
    return bool(processing_gap and travel<=3. and correction<=1.5
        and detail.get('good_features',0)>=6 and detail.get('inlier_fraction',0.)>=.90
        and detail.get('fb_median',1e30)<.35)


def declare_current_y24(evidence):
    # These helpers really sample 24 positions .055..945; this is NOT source64.
    if evidence.get('profiles_per_edge') is None and evidence.get('edge_backend') in (
            'cpp_analytic_tls','cpp_edges_gate_motion_context','numpy_analytic_tls'):
        return dict(evidence,profiles_per_edge=24,fraction_limits=[.055,.945],
            sampling_metadata='fixed_current_tracking_Y24_grid')
    return evidence

def stable_rms_limit(scale):
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Current RMS scale invalid')
    # Source-pixel precision floor: 1.5 source pixels, <=.85 observation pixels.
    return float(np.clip(1.5/float(np.min(scale)),.65,.85))

def detector_source64(image,scale,edges,derived_gray=None):
    """Bind the already executed original64 fit to its current detector input.

    This adapter is called synchronously immediately after the original
    refinement. It rejects unknown grids/backends and never accepts an old
    receipt. P1 native and Python profiles really use .06..94 and64 positions.
    Vector evidence must carry the key of this input or its same-call derived Y.
    """
    reports=edges.get('edges',[]);key=array_key(image)
    p1=edges.get('method')=='p1_pyramid_subpixel_profiles_tls'
    if p1:
        if len(reports)!=4 or any(r.get('profiles')!=64 for r in reports):
            raise ValueError('Original P1 source64 grid missing')
        kind='source_Y_profiles';fractions=[.06,.94]
    else:
        keys=[key]
        if derived_gray is not None:keys.append(array_key(derived_gray))
        if (not edges.get('same_frame_source') or edges.get('profiles_per_edge')!=64
                or edges.get('current_source_key') not in keys or edges.get('deadline_hit')
                or edges.get('source_proof_kind') not in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles')):
            raise ValueError('Original source64 provenance missing')
        kind=edges['source_proof_kind'];fractions=edges.get('fraction_limits',[])
        if len(fractions)!=2:raise ValueError('Original source64 sampling limits missing')
    if len(reports)!=4 or edges.get('refined_corners')!=4 or any(not r.get('accepted') for r in reports):
        raise ValueError('Original source64 does not contain four fitted lines')
    supports=[float(r.get('retained',0))/64. for r in reports]
    rms=[float(r.get('tls_rms',1e30))/float(np.min(scale)) for r in reports]
    polarities=edges.get('edge_polarity')
    if polarities is None:
        polarities=[int(np.sign(r.get('profile_contrast',0.))) if abs(r.get('profile_contrast',0.))>=8 else 0 for r in reports]
    valid=bool(min(supports)>=.60 and all(r.get('coverage',0.)>=.60 for r in reports))
    return dict(edges,valid=valid,supported_edges=sum(v>=.60 for v in supports),
        refined_corners=4 if valid else 0,edge_support=supports,edge_rms=rms,edge_polarity=polarities,
        profiles_per_edge=64,fraction_limits=list(fractions),same_frame_source=True,
        current_source_key=key,source_proof_kind=kind,edge_backend='detector_original_source64',
        evidence_adapter='synchronous_original_fit_grid_and_source_key_checked',deadline_hit=False)

def current_agreement(first,second,first_e,second_e,scale,source_key,stable_fb=False):
    """Strict new-target proof; bounded noise tolerance after complete current FB.

    No tolerance for LOST/new admission. Both independently measured current
    fits must still contain all four physical lines and actual source64 data.
    """
    result=exterior_agreement(first,second,first_e,second_e,scale,source_key=source_key)
    limit=stable_rms_limit(scale)
    result.update(admission_policy='strict_current_reacquisition',stable_FB_support_tolerance=False,
        strict_new_candidate_support=.80,strict_new_candidate_rms=.65,stable_FB_rms_limit=limit,admission_grade='new_or_current_strict')
    if result.get('verified') or not stable_fb:return result
    a=first_e.get('edge_support',[0.]*4);b=second_e.get('edge_support',[0.]*4)
    eligible=(first_e.get('profiles_per_edge')==24 and len(a)==4 and len(b)==4
        and min(a)>=.75 and min(b)>=.75 and result.get('source64_provenance_verified',False)
        and result.get('independent_sampling_verified',False) and first_e.get('valid',False)
        and second_e.get('valid',False) and first_e.get('supported_edges')==4
        and second_e.get('supported_edges')==4 and first_e.get('refined_corners')==4
        and second_e.get('refined_corners')==4 and result.get('max_rms',1e30)<=limit
        and result.get('line_normal_difference',1e30)<=min(.75,result.get('normal_limit',0.))
        and result.get('corner_difference',1e30)<=1.)
    result.update(verified=bool(eligible),stable_FB_support_tolerance=bool(eligible),
        complete_current_FB_required=True,strict_new_candidate_threshold_unchanged=True,
        admission_policy='stable_current_FB_independent_edges' if eligible else 'strict_current_reacquisition',
        admission_grade='stable_FB_bounded_noise' if eligible else 'weak_current_hold_and_remeasure_required')
    return result

def search_gate(evidence,candidate,proposal,radius):
    """Bound a coarse/transported search separately from CURRENT proof agreement.

    Corner intersection sensitivity must not be treated as disagreement between
    the independent source64 and24 fits. Bounded line drift, area and corners
    still restrict this proposal-to-primary search; strict admission follows.
    """
    from tracking import exterior_gate as exterior_gate
    import cv2
    a=np.asarray(proposal,np.float32);b=np.asarray(candidate,np.float32)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return dict(reliable=False,reason='invalid_search_quad')
    g=exterior_gate(evidence,b,a,radius)
    d=line_lock(a,b)
    area=abs(cv2.contourArea(a));ratio=abs(cv2.contourArea(b))/max(area,1.)
    normal_limit=min(6.,.95*float(radius));corner_limit=min(9.,1.30*float(radius))
    valid=(evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and g['min_support']>=.60 and g['max_rms']<=1.
        and cv2.isContourConvex(b) and .80<=ratio<=1.25
        and d.get('line_normal_difference',1e30)<=normal_limit
        and g['prediction_correction']<=corner_limit)
    return dict(g,reliable=bool(valid),gate_kind='bounded_search_before_strict_current_proof',
        line_normal_difference=d.get('line_normal_difference'),normal_limit=normal_limit,
        corner_limit=corner_limit,area_ratio=ratio,independent_proof_not_granted=True)



def sample_locked_pair(image,scale,quad,deadline,evidence,half,cpu_budget_s=.12):
    """Optional native fusion for an already trusted same-target locked line."""
    from tracking import _visible_quad as _visible_quad
    from tracking import fused_locked_pair__v87_v74_native as fused_locked_pair
    scale=np.asarray(scale,np.float64);q=np.asarray(quad,np.float32)
    local=_visible_quad((q+.5)*scale-.5,image.shape,preserve_order=True)
    result=fused_locked_pair(image,local,half,peak_radius(scale,evidence,half),float(scale.min()),
        deadline,border_signature(evidence),cpu_budget_s)
    if result is None:return None
    primary,secondary,detail=result;converted=[]
    for observed,source in (primary,secondary):
        observed=((observed+.5)/scale-.5).astype(np.float32)
        source=dict(source,edge_rms=[float(v)/float(scale.min()) for v in source['edge_rms']],
            edge_backend='locked_current_YUV'+str(source['profiles_per_edge']),tracking_roi_offset=[0.,0.],
            direct_locked_band=True,repeated_gray_edge_search=False,paired_native_transaction=True)
        converted.append((observed,source))
    return converted[0],converted[1],detail


# ======================================================================
# ===== [19/22] v84_color =====
# ======================================================================


"""Cold CV preparation outside acquisition; bounded reusable color work images."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_READY=threading.Event();_LOCK=threading.Lock();_LOCAL__v84_color=threading.local();_DETAIL={}


def prepare_color_runtime(cancel=None):
    """One small Lab call initializes CV tables before any recovery budget starts."""
    from tracking import check_cancel as check_cancel
    if _READY.is_set():return dict(_DETAIL,already_ready=True)
    with _LOCK:
        if _READY.is_set():return dict(_DETAIL,already_ready=True)
        check_cancel(cancel);began=time.perf_counter();cpu=time.thread_time()
        checkpoint('CV_COLOR_WARMUP_BEGIN',hardware_access=False,scope='CPU setup; outside frame measurement')
        # Exercise the actual uchar conversion with a small varied image.
        image=np.arange(8*8*3,dtype=np.uint8).reshape(8,8,3)
        blurred=cv2.GaussianBlur(image,(3,3),0)
        cv2.cvtColor(blurred,cv2.COLOR_BGR2LAB)
        check_cancel(cancel)
        _DETAIL.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
            work_shape=[8,8,3],backend='opencv_uint8_Lab_initialized',hardware_access=False)
        _READY.set();checkpoint('CV_COLOR_WARMUP_END',**_DETAIL)
        return dict(_DETAIL,already_ready=False)


def color_runtime_ready():return _READY.is_set()


def small_lab(color,check,max_dim=192):
    """No lazy Lab initialization in a timed recovery. Source proof remains full resolution."""
    if not _READY.is_set():
        # Public direct detection without NativeSetup can use earlier Y/YUV
        # paths; never start an uninitialized heavyweight call in its budget.
        raise ValueError('Color runtime not prepared; defer Lab proposal stage')
    if color.dtype!=np.uint8 or color.ndim!=3 or color.shape[2]!=3:raise ValueError('Expected BGR color proposal image')
    check('multicolor_work_resize_begin')
    h,w=color.shape[:2];scale=min(1.,float(max_dim)/max(h,w))
    shape=(max(2,round(h*scale)),max(2,round(w*scale)),3)
    if getattr(_LOCAL__v84_color,'shape',None)!=shape:
        _LOCAL__v84_color.shape=shape;_LOCAL__v84_color.work=np.empty(shape,np.uint8)
        _LOCAL__v84_color.smooth=np.empty(shape,np.uint8);_LOCAL__v84_color.lab=np.empty(shape,np.uint8)
    if shape[:2]!=color.shape[:2]:
        cv2.resize(color,(shape[1],shape[0]),dst=_LOCAL__v84_color.work,interpolation=cv2.INTER_LINEAR)
        source=_LOCAL__v84_color.work
    else:source=color
    check('multicolor_work_resize_end')
    check('multicolor_gaussian_begin');cv2.GaussianBlur(source,(3,3),0,dst=_LOCAL__v84_color.smooth)
    check('multicolor_gaussian_end')
    check('multicolor_Lab_begin');cv2.cvtColor(_LOCAL__v84_color.smooth,cv2.COLOR_BGR2LAB,dst=_LOCAL__v84_color.lab)
    check('multicolor_Lab_end')
    return _LOCAL__v84_color.lab


# ======================================================================
# ===== [20/22] v85_boundary =====
# ======================================================================


"""Failure-only current bands: retain fitted lines, repair one side, no IO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCAL__v85_boundary=threading.local()


def _workspace():
    if not hasattr(_LOCAL__v85_boundary,'work'):
        _LOCAL__v85_boundary.work=dict(t=np.linspace(.10,.90,64),offset=np.linspace(-1.,1.,65),
            bands=np.zeros((4,64,65,3),np.float32))
    return _LOCAL__v85_boundary.work


def _selection(data,half,minimum_contrast=12.,line_lock_radius=None):
    from tracking import coherent_profiles__v31_native as coherent_profiles
    # The old ABI accepts four bands. Zero dummy sides have no hypotheses;
    # only the requested side is sampled or fitted during a single-side repair.
    work=_workspace();work['bands'].fill(0);work['bands'][:len(data)]=data
    result=coherent_profiles(work['bands'],half,(.10,.90),minimum_contrast,line_lock_radius=line_lock_radius)
    if result is not None:return result[0][:len(data)].copy()
    values=[]
    for band in data:
        selected=_coherent_offsets(band,work['offset']*half,work['t'],minimum_contrast,
            line_lock_radius=line_lock_radius)
        values.append(np.zeros((64,3),np.float32) if selected is None else
            np.stack((selected[0],selected[1],selected[2]),axis=1))
    return np.asarray(values)


def _sample(image,q,normal,edges,half):
    t=_workspace()['t'];offset=_workspace()['offset']*half
    edge=np.roll(q,-1,axis=0)-q
    base=q[edges,None,:]+t[None,:,None]*edge[edges,None,:]
    xy=base[:,:,None,:]+offset[None,None,:,None]*normal[edges,None,None,:]
    values=vector_profiles(image,xy[...,0].reshape(-1,65),xy[...,1].reshape(-1,65))
    return base,values.reshape(len(edges),64,65,3)


def _fit(q,normal,base,selected,index,shape,data=None,half=None):
    h,w=shape[:2];keep=selected[:,2]>.5
    points=base+selected[:,0,None]*normal
    keep&=(points[:,0]>=1)&(points[:,0]<w-1)&(points[:,1]>=1)&(points[:,1]<h-1)
    n=len(selected);needed=int(np.ceil(.60*n))
    report=dict(edge=index,profiles=n,supported=int(keep.sum()),retained=0,coverage=0.,
        accepted=False,tls_rms=1e30,polarity=0,Y_polarity=0,
        contrast_backend='unclipped_YUV_vector_gradient')
    if data is not None and half is not None:
        col=int(np.clip(round(32.+96./half),0,64));near=data[:,col,0]
        report.update(highlight_fraction=float(np.mean(near>=250.)),dark_clip_fraction=float(np.mean(near<=4.)),
            clip_probe_scope='current candidate inward3px; possible clipping, not a glare diagnosis')
    if keep.sum()<needed:return None,report
    line,rms,retained=_tls__v41_quad(points[keep])
    if line is None:return None,report
    tangent=q[(index+1)%4]-q[index]
    along=(retained-q[index])@tangent/max(1e-9,float(tangent@tangent))
    span=float(np.ptp(along));count=len(retained)
    okay=count>=needed and span>=.60 and rms<=1.5
    report.update(retained=count,coverage=span,tls_rms=float(rms),accepted=bool(okay))
    if okay:report['fitted_line_source']=line.tolist()
    return line if okay else None,report


def candidate_color_refine(image,quad,half_window,check,deadline=None):
    """One four-side fit, then at most one fresh weak-side sample.

    Three accepted CURRENT line coefficients are retained exactly. The extra
    band widens only the fourth side around the immutable original proposal.
    No source pointer, old frame or historical edge is cached.
    """
    if image.ndim!=3 or image.shape[2] not in (2,3):raise ValueError('Color band source required')
    q=np.asarray(quad,np.float64);begin=time.perf_counter();cpu=time.thread_time()
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Current color candidate must be cyclic convex')
    edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
    if min(length)<4:raise ValueError('Degenerate current candidate')
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    normal*=np.where(np.sum((q.mean(axis=0)-q-edge*.5)*normal,axis=1)<0,-1.,1.)[:,None]
    check('v85_current_color_bands')
    bases,bands=_sample(image,q,normal,np.arange(4),float(half_window))
    selection=_selection(bands,float(half_window));lines=[];reports=[]
    for i in range(4):
        check('v85_current_color_fit')
        line,report=_fit(q,normal[i],bases[i],selection[i],i,image.shape,bands[i],float(half_window))
        lines.append(line);reports.append(report)
    repair=dict(attempted=False,retained_current_lines=0)
    good=[i for i,r in enumerate(reports) if r['accepted'] and r['retained']>=52
        and r['coverage']>=.62 and r['tls_rms']<=1.]
    weak=[i for i,r in enumerate(reports) if not r['accepted'] or r['retained']<52]
    if len(good)==3 and len(weak)==1 and (deadline is None or deadline-time.perf_counter()>=.025):
        # Bounded failure-only work. This is a new current measurement, never
        # lowering the final source64 / independent24 admission thresholds.
        check('v85_single_weak_edge_repair');i=weak[0]
        repair_q=q.copy();repair_normal=normal.copy();peak_lock=None
        wider=min(12.,max(8.,1.6*float(half_window)))
        if lines[i] is not None:
            # A fitted but sparse edge is already a physical-line reference.
            # Recenter its band and keep a narrow peak corridor, instead of
            # widening into a neighboring page or printed rectangle.
            old_line=lines[i]
            for corner in (i,(i+1)%4):
                repair_q[corner]-=(old_line[:2]@repair_q[corner]+old_line[2])*old_line[:2]
            repair_normal[i]=old_line[:2]*(1. if old_line[:2]@normal[i]>=0 else -1.)
            wider=min(6.,max(3.,.75*float(half_window)));peak_lock=min(1.5,.70*wider)
        started=time.perf_counter();used=time.thread_time()
        base,band=_sample(image,repair_q,repair_normal,np.array([i]),wider)
        chosen=_selection(band,wider,8.,peak_lock)[0]
        line,report=_fit(q,repair_normal[i],base[0],chosen,i,image.shape,band[0],wider)
        if line is not None and report['tls_rms']>1.:
            line=None;report['accepted']=False
        old=reports[i]
        improved=bool(line is not None and (not old['accepted'] or
            (report['retained']>old['retained'] and report['coverage']>=old['coverage']-.05)))
        repair=dict(attempted=True,edge=i,half_source_pixels=wider,retained_current_lines=3,
            successful=improved,wall_s=time.perf_counter()-started,
            thread_cpu_s=time.thread_time()-used,minimum_contrast=8.,
            physical_peak_lock_source=peak_lock,seed='current_weak_line' if peak_lock is not None else 'original_candidate',
            other_current_line_coefficients_unchanged=True)
        if improved:lines[i]=line;reports[i]=report
    result=q.copy();valid=all(line is not None for line in lines)
    if valid:
        for i in range(4):
            cross=np.cross(lines[i-1],lines[i])
            if abs(cross[2])<.08:valid=False;break
            result[i]=cross[:2]/cross[2]
        h,w=image.shape[:2]
        ratio=abs(cv2.contourArea(result.astype(np.float32)))/max(1.,abs(cv2.contourArea(q.astype(np.float32))))
        valid=bool(valid and np.isfinite(result).all() and cv2.isContourConvex(result.astype(np.float32))
            and .85<=ratio<=1.15 and np.max(np.linalg.norm(result-q,axis=1))<=3*float(half_window)
            and np.all(result>=1) and np.all(result[:,0]<w-1) and np.all(result[:,1]<h-1))
    expired=deadline is not None and time.perf_counter()>=deadline
    valid=bool(valid and not expired);colors=[]
    if valid:
        # Match native YUYV pair centers and fitted-line +/-3px signatures.
        # The independent24 caller receives these actual same-layer sides.
        t=_workspace()['t'];centers=result[:,None,:]+t[None,:,None]*(np.roll(result,-1,axis=0)-result)[:,None,:]
        direction=np.stack((np.roll(result,-1,axis=0)[:,1]-result[:,1],
            result[:,0]-np.roll(result,-1,axis=0)[:,0]),axis=1)
        direction/=np.linalg.norm(direction,axis=1)[:,None]
        direction*=np.where(np.sum((result.mean(axis=0)-result)*direction,axis=1)<0,-1.,1.)[:,None]
        xy=centers[:,:,None,:]+np.array([-3.,3.])[None,None,:,None]*direction[:,None,None,:]
        side=vector_profiles(image,xy[...,0].reshape(256,2),xy[...,1].reshape(256,2)).reshape(4,64,2,3)
        colors=np.concatenate((np.median(side[:,:,0],axis=1),np.median(side[:,:,1],axis=1)),axis=1).tolist()
    expired=deadline is not None and time.perf_counter()>=deadline
    valid=bool(valid and not expired)
    if not valid:result=q.copy()
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if valid else 'rejected',
        valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(r['accepted'] for r in reports),
        edges=reports,edge_support=[r['retained']/64. if r['accepted'] else 0. for r in reports],
        edge_rms=[r['tls_rms'] for r in reports],edge_polarity=[0]*4,half_window_pixels=float(half_window),
        corner_displacements=np.linalg.norm(result-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-begin,refinement_thread_cpu_s=time.thread_time()-cpu,
        backend='v85_packed_bands_native_consensus_retained_lines',profiles_per_edge=64,
        fraction_limits=[.10,.90],same_frame_source=True,current_source_key=array_key(image),
        source_proof_kind='raw_YUV_profiles' if image.shape[2]==2 else 'source_color_profiles',
        color_vector_proof=True,brightness_polarity_required=False,gradient_consensus_required=True,
        physical_source_corners=result.astype(np.float32).tolist(),border_colors=colors,
        corner_order_preserved=True,deadline_hit=expired,single_edge_repair=repair,
        vector_sample_backend='existing_packed_YUYV_or_color_sampler',full_plane_CSC_used=False)
    return result.astype(np.float32),evidence


def stable_weak_edge_grade(first,second,agreement,source_key):
    """One weak side in ONE independent layout, after complete same-target FB."""
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or first.get('profiles_per_edge')!=24 or second.get('profiles_per_edge')!=64):return None
    groups=[]
    for e,n in ((first,24),(second,64)):
        if (not e.get('valid') or e.get('refined_corners')!=4 or e.get('supported_edges')!=4
            or e.get('deadline_hit') or not e.get('same_frame_source') or e.get('current_source_key')!=source_key):return None
        counts=e.get('edge_support',[])
        reports=e.get('edges') or e.get('source_proof',{}).get('edges',[])
        if len(counts)!=4 or not np.isfinite(counts).all():return None
        # The original native tracking-Y counter precedes TLS trimming and
        # does not export retained span. Do not invent that missing report;
        # the caller can obtain one fresh source24 layout against its Y64.
        if len(reports)!=4:return None
        if any(not r.get('accepted') or r.get('profiles')!=n or r.get('coverage',0)<.62
            or abs(float(r.get('retained',0))/n-float(v))>1e-5 for r,v in zip(reports,counts)):return None
        groups.append(np.asarray(counts,np.float64))
    a,b=groups;weak=np.flatnonzero(np.minimum(a,b)<.80)
    if len(weak)!=1:return None
    i=int(weak[0])
    if min(a[i],b[i])<.70 or max(a[i],b[i])<.80:return None
    if (agreement.get('max_rms',1e30)>.65
        or agreement.get('line_normal_difference',1e30)>min(.75,agreement.get('normal_limit',0.))
        or agreement.get('corner_difference',1e30)>1.):return None
    return dict(verified=True,admission_grade='stable_FB_single_weak_edge_070',
        admission_policy='same_target_current_four_edges_complete_FB',weak_edge=i,
        weak_support_floor=.70,other_three_support_floor=.80,independent_weak_side_support=max(a[i],b[i]),
        stable_FB_support_tolerance=True,complete_current_FB_required=True,
        strict_new_candidate_threshold_unchanged=True,all_four_current_fitted_lines_required=True,
        zero_support_edge_allowed=False,original_support_values_preserved=True)


def line_quantization_grade(first,second,agreement,scale,source_key):
    """At most two 1/32-source-pixel interpolation steps, with strong evidence.

    This never reduces support or accepts a missing line. Absolute .75tracking
    line lock and tighter corner/RMS checks still bound the physical layer.
    """
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or agreement.get('min_support',0)<.80 or agreement.get('max_rms',1e30)>.35
        or agreement.get('corner_difference',1e30)>1.
        or first.get('profiles_per_edge')!=24 or second.get('profiles_per_edge')!=64):return None
    for e,n in ((first,24),(second,64)):
        if (not e.get('valid') or e.get('refined_corners')!=4 or e.get('supported_edges')!=4
            or not e.get('same_frame_source') or e.get('current_source_key')!=source_key
            or e.get('deadline_hit')):return None
        reports=e.get('edges') or e.get('source_proof',{}).get('edges',[])
        if not reports and n==24 and e.get('edge_backend') in (
            'cpp_analytic_tls','cpp_edges_gate_motion_context','numpy_analytic_tls'):
            if min(e.get('edge_support',[0]*4))<.80:return None
        elif len(reports)!=4 or any(not r.get('accepted') or r.get('profiles')!=n
            or r.get('coverage',0)<.62 for r in reports):return None
    step=.0625/float(np.min(scale));old=agreement.get('normal_limit',0.)
    limit=min(.75,old+step);error=agreement.get('line_normal_difference',1e30)
    if not old<error<=limit:return None
    return dict(verified=True,admission_grade='current_line_interpolation_quantization',
        admission_policy='strong_current_independent_edges_quantized_line',
        original_normal_limit=old,normal_limit=limit,quantization_allowance_source_pixels=.0625,
        strict_new_candidate_support=.80,all_four_current_fitted_lines_required=True,
        zero_support_edge_allowed=False,old_H_not_used=True)


def repair_independent24(image,scale,primary,source,observed,current,half,deadline,offset=(0,0)):
    """Fresh single-side CURRENT sample for a marginal strict admission.

    The other three lines come from the actual current24 fit. No cached old
    frame or primary64 point is counted in this shifted independent24 grid.
    """
    key=array_key(image);scale=np.asarray(scale,np.float64)
    if (not actual_source64(source,key) or not source.get('valid')
        or min(source.get('edge_support',[0.]*4))<.80
        or not current.get('valid') or current.get('profiles_per_edge')!=24
        or current.get('current_source_key')!=key or current.get('deadline_hit')
        or current.get('weak24_repair_attempted')):return None
    support=np.asarray(current.get('edge_support',[]),np.float64)
    if support.shape!=(4,) or not np.isfinite(support).all():return None
    weak=np.flatnonzero(support<.80)
    if len(weak)!=1 or min(support)<.70:return None
    if len(current.get('edges',[]))!=4 or max(current.get('edge_rms',[1e30]*4))>.65:return None
    if deadline is not None and deadline-time.perf_counter()<.030:return None
    begin=time.perf_counter();cpu=time.thread_time();i=int(weak[0])
    origin=np.asarray(offset,np.float64)
    q=(np.asarray(primary,np.float64)+.5)*scale-.5-origin
    old=np.asarray(current.get('physical_source_corners'),np.float64)
    if q.shape!=(4,2) or old.shape!=(4,2) or not np.isfinite(old).all():return None
    edge=q[(i+1)%4]-q[i];normal=np.array([-edge[1],edge[0]])/max(1e-9,np.linalg.norm(edge))
    if normal@(q.mean(axis=0)-(q[i]+q[(i+1)%4])*.5)<0:normal=-normal
    t=np.linspace(.135,.865,24);offset=np.linspace(-half,half,65)
    base=q[i]+t[:,None]*edge;xy=base[:,None,:]+offset[None,:,None]*normal
    data=vector_profiles(image,xy[...,0],xy[...,1])
    sides=base[:,None,:]+np.array([-3.,3.])[None,:,None]*normal
    side=vector_profiles(image,sides[...,0],sides[...,1]);prior=side[:,1]-side[:,0]
    selected=_coherent_offsets(data,offset,t,8.,prior,peak_radius(scale,source,half))
    if selected is None:return None
    fit=np.stack((selected[0],selected[1],selected[2]),axis=1)
    line,report=_fit(q,normal,base,fit,i,image.shape,data,half)
    if line is None or report['retained']<20 or report['coverage']<.62:return None
    lines=[]
    for k in range(4):
        v=np.cross(np.r_[old[k],1.],np.r_[old[(k+1)%4],1.]);v/=max(1e-9,np.linalg.norm(v[:2]));lines.append(v)
    lines[i]=line;result=old.copy()
    for k in range(4):
        cross=np.cross(lines[k-1],lines[k])
        if abs(cross[2])<.08:return None
        result[k]=cross[:2]/cross[2]
    h,w=image.shape[:2]
    if (not np.isfinite(result).all() or not cv2.isContourConvex(result.astype(np.float32))
        or np.any(result<1) or np.any(result[:,0]>=w-1) or np.any(result[:,1]>=h-1)
        or np.max(np.linalg.norm(result-old,axis=1))>2.
        or time.thread_time()-cpu>.040 or (deadline is not None and time.perf_counter()>=deadline)):return None
    evidence=dict(current);reports=[dict(r) for r in current['edges']];reports[i]=report
    supports=list(current['edge_support']);supports[i]=report['retained']/24.
    rms=list(current['edge_rms']);rms[i]=report['tls_rms']/float(np.min(scale))
    layout=[list(current.get('fraction_limits',[.12,.88])) for _ in range(4)];layout[i]=[.135,.865]
    evidence.update(edges=reports,edge_support=supports,edge_rms=rms,
        physical_source_corners=result.astype(np.float32).tolist(),fraction_limits_per_edge=layout,
        weak24_repair_attempted=True,weak24_repair=dict(edge=i,wall_s=time.perf_counter()-begin,
            thread_cpu_s=time.thread_time()-cpu,grid=[24,.135,.865],
            retained_other_current_lines=3,old_frame_used=False,primary_points_relabelled=False))
    return ((result+origin+.5)/scale-.5).astype(np.float32),evidence


def compact_evidence(evidence):
    """Own only scalar/list proof fields used by same-frame consumers."""
    import copy
    fields=('method','valid','state','refined_corners','supported_edges','edges','edge_support','edge_rms',
        'edge_polarity','edge_backend','profiles_per_edge','fraction_limits','same_frame_source',
        'current_source_key','source_proof_kind','physical_source_corners','color_vector_proof',
        'deadline_hit','border_colors','corner_order_preserved','half_window_pixels',
        'gradient_consensus_required','brightness_polarity_required','boundary_prior_used',
        'physical_peak_lock','peak_lock_radius_source','signed_peak_lock','signed_reference',
        'fraction_limits_per_edge','weak24_repair_attempted','weak24_repair','sampling_metadata')
    result={k:copy.deepcopy(evidence[k]) for k in fields if k in evidence}
    if 'source_proof' in evidence:
        source=evidence['source_proof'];result['source_proof']={k:copy.deepcopy(source[k])
            for k in ('method','edges','refined_corners','backend') if k in source}
    return result


# ======================================================================
# ===== [21/22] v85_candidates =====
# ======================================================================


"""Failure-only small YUV line hypotheses; no full-color preparation or IO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCAL__v85_candidates=threading.local()


def line_candidates(image,check):
    h,w=image.shape[:2];ow=min(w,160);oh=max(16,round(h*ow/w))
    shape=(oh,ow)
    if getattr(_LOCAL__v85_candidates,'shape',None)!=shape:
        _LOCAL__v85_candidates.shape=shape;_LOCAL__v85_candidates.plane=np.empty(shape,np.uint8)
        _LOCAL__v85_candidates.smooth=np.empty(shape,np.uint8);_LOCAL__v85_candidates.magnitude=np.empty(shape,np.uint8)
    mag=_LOCAL__v85_candidates.magnitude;mag.fill(0)
    if image.ndim==3 and image.shape[2]==2:
        planes=(image[:,:,0],image[:,0::2,1],image[:,1::2,1])
    elif image.ndim==2:planes=(image,)
    else:
        check('v85_small_line_color')
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb))
    for plane in planes:
        check('v85_small_line_gradient')
        cv2.resize(plane,(ow,oh),dst=_LOCAL__v85_candidates.plane,interpolation=cv2.INTER_LINEAR)
        cv2.GaussianBlur(_LOCAL__v85_candidates.plane,(3,3),0,dst=_LOCAL__v85_candidates.smooth)
        dx=cv2.convertScaleAbs(cv2.Sobel(_LOCAL__v85_candidates.smooth,cv2.CV_16S,1,0,ksize=3),alpha=.35)
        dy=cv2.convertScaleAbs(cv2.Sobel(_LOCAL__v85_candidates.smooth,cv2.CV_16S,0,1,ksize=3),alpha=.35)
        np.maximum(mag,cv2.max(dx,dy),out=mag)
    check('v85_small_line_threshold')
    threshold,_=cv2.threshold(mag,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    edges=(mag>=max(8.,threshold*.65)).astype(np.uint8)*255
    proposals=_line_candidates(edges,check)
    # Existing opposite-side geometry rejects arbitrary wood-grain crossings;
    # all proposals still require actual full-source64/independent24 admission.
    pool=[(q,q) for q in proposals[:12]]
    scale=np.array([w/ow,h/oh],np.float64)
    for entry in rank_pool(pool,mag,threshold,check)[:2]:
        yield ((entry['quad']+.5)*scale-.5).astype(np.float32)


# ======================================================================
# ===== [22/22] v86_candidates =====
# ======================================================================


"""Bounded mixed-cover candidates. Coarse ranking is never source-edge admission."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _gradient(planes,check):
    mag=np.zeros(planes[0].shape,np.uint8)
    for plane in planes:
        check('v86_coarse_gradient')
        smooth=cv2.GaussianBlur(plane,(3,3),0)
        dx=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,1,0),alpha=.35)
        dy=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,0,1),alpha=.35)
        np.maximum(mag,cv2.max(dx,dy),out=mag)
    return mag


def _shared_sides(parent,child):
    """A book band shares actual side lines, unlike a separate surrounding mat."""
    p=np.asarray(parent,np.float64);c=np.asarray(child,np.float64)
    e=np.roll(p,-1,axis=0)-p;n=np.stack((-e[:,1],e[:,0]),axis=1)
    n/=np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-9)
    mids=.5*(c+np.roll(c,-1,axis=0));ce=np.roll(c,-1,axis=0)-c
    cn=np.stack((-ce[:,1],ce[:,0]),axis=1);cn/=np.maximum(np.linalg.norm(cn,axis=1)[:,None],1e-9)
    return sum(any(abs(float(n[j]@cn[i]))>.97 and
        abs(float((mids[i]-p[j])@n[j]))<=2. for j in range(4)) for i in range(4))


def _perimeter(mag,q,cutoff):
    # Four longitudinal sections: interrupted ink/glare does not need a closed mask.
    support=coarse_support(mag,q,cutoff)
    return support


def ranked_candidates(image,check,limit=192):
    from tracking import _visible_quad as _visible_quad
    from tracking import policy as policy
    settings=policy();h,w=image.shape[:2];ow=min(w,int(limit));oh=max(16,round(h*ow/w))
    check('v86_candidate_downsample')
    if image.ndim==3 and image.shape[2]==2:
        planes=[cv2.resize(a,(ow,oh),interpolation=cv2.INTER_LINEAR) for a in
            (image[:,:,0],image[:,0::2,1],image[:,1::2,1])]
    elif image.ndim==3:
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=list(cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb)))
    else:planes=[cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)]
    scale=np.array([w/ow,h/oh]);raw_mag=_gradient(planes,check)
    threshold,_=cv2.threshold(raw_mag,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    pool=[];kernel=np.ones((3,3),np.uint8)
    def add(low,kind):
        try:q=_visible_quad((np.asarray(low)+.5)*scale-.5,image.shape)
        except ValueError:return
        q=((q+.5)/scale-.5).astype(np.float32)
        if any(np.max(np.linalg.norm(q-e['q'],axis=1))<1.5 for e in pool):return
        if len(pool)<20:pool.append(dict(q=q,kind=kind))
    def contours(mag,cutoff,kind,capacity=12):
        check('v86_coarse_contours')
        edge=cv2.morphologyEx((mag>=cutoff).astype(np.uint8)*255,cv2.MORPH_CLOSE,kernel)
        cs,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cs,key=cv2.contourArea,reverse=True)[:14]:
            if len(pool)>=capacity:return
            check('v86_coarse_polygon')
            if abs(cv2.contourArea(c))<.035*ow*oh:continue
            hull=cv2.convexHull(c);length=cv2.arcLength(hull,True)
            for eps in (.012,.022,.04,.065):
                p=cv2.approxPolyDP(hull,eps*length,True)
                if len(p)==4 and cv2.isContourConvex(p):add(p.reshape(4,2),kind);break
    for cutoff in dict.fromkeys((max(8.,threshold),max(6.,threshold*.65))):contours(raw_mag,cutoff,'raw_YUV')
    def rank_entries():
        for e in pool:
            check('v86_full_cover_rank')
            support=_perimeter(raw_mag,e['q'],threshold);e['support']=support
            area=abs(cv2.contourArea(e['q']))/(ow*oh)
            e['score']=float(support.min()+.35*support.mean()+.08*np.sqrt(area))
        for child in pool:
            for parent in pool:
                if parent is child:continue
                ratio=abs(cv2.contourArea(parent['q']))/max(1.,abs(cv2.contourArea(child['q'])))
                if not 1.12<=ratio<=2.8 or min(parent['support'])<.35:continue
                if enclosure(parent['q'],child['q'],margin=1.) and _shared_sides(parent['q'],child['q'])>=3:
                    # Coarse evidence may change order, never remove an unproved child.
                    child['score']-=.12;parent['score']+=.25
        return sorted(pool,key=lambda e:e['score'],reverse=True)
    yielded=[]
    # Yield cheap contours BEFORE starting Hough/contrast work. A caller can
    # accept candidate0 immediately and never resume this generator's fallback.
    for e in rank_entries()[:4]:
        yielded.append(e['q'].copy())
        yield ((e['q']+.5)*scale-.5).astype(np.float32)
    from tracking import _RECOVERY_BUDGET as _RECOVERY_BUDGET
    budget=_RECOVERY_BUDGET.get();permit=getattr(budget,'can_start_stage',None)
    lines_allowed=permit is None or permit('v86_pooled_segments',.10,.16,admission_cpu_s=.12,admission_wall_s=.18)
    if lines_allowed:
        class LineWorkStop(Exception):pass
        began=time.perf_counter();cpu=time.thread_time();combinations=0
        def bounded_check(stage):
            nonlocal combinations
            check(stage)
            if stage=='color_line_quad':combinations+=1
            if combinations>64 or time.thread_time()-cpu>.10 or time.perf_counter()-began>.16:
                raise LineWorkStop()
        try:lines=_line_candidates((raw_mag>=max(6.,threshold*.65)).astype(np.uint8)*255,bounded_check)
        except LineWorkStop:lines=[]
        for q in lines[:6]:add(q,'raw_segments')
    contrast_allowed=permit is None or permit('v86_small_contrast',.015,.030,admission_cpu_s=.12,admission_wall_s=.18)
    if settings['detection_contrast_fallback'] and contrast_allowed and not any(
            _perimeter(raw_mag,e['q'],threshold).min()>=.65 for e in pool):
        check('v86_failure_only_small_contrast')
        enhanced=cv2.createCLAHE(clipLimit=1.6,tileGridSize=(4,4)).apply(planes[0])
        em=_gradient([enhanced]+planes[1:],check)
        t,_=cv2.threshold(em,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
        contours(em,max(6.,t*.65),'small_contrast_proposal_only',20)
    count=0
    for e in rank_entries():
        if any(np.max(np.linalg.norm(e['q']-old,axis=1))<1.5 for old in yielded):continue
        yield ((e['q']+.5)*scale-.5).astype(np.float32)
        count+=1
        if count>=2:return
