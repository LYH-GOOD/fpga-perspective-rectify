"""P1-style pyramid contour + subpixel edge profiles on the working image.

No fixed paper aspect, grid spacing, camera focal length or lens coefficients.
Manual points are kept as supplied by the caller. TLS is for approximately
straight document boundaries; individual unsupported edges keep coarse corners.
"""
from pathlib import Path
import hashlib, time
import cv2
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _tls(points):
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
    from v8_geometry import order_corners
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
            line, rms, count = _tls(points[good])
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
    from v8_geometry import detect_quad
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
