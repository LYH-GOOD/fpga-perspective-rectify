"""P11 PS corner detection and inverse homography; copied from ../P1/board.
This project uses this local copy; register normalization remains unchanged.
"""

from p11_contract import RELEASE_ID, cache_profile
import hashlib as _hashlib
from pathlib import Path as _SourcePath
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

import sys

import numpy as np
import cv2

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
