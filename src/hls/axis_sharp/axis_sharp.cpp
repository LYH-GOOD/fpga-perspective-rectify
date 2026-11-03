//=============================================================================
// axis_sharp.cpp —— PL 内部流式反锐化掩模（box unsharp），AXI-Stream 进/出
//
//   位置： remap/m_axis ──► [axis_data_fifo] ──► 本核 ──► axi_dma_0/S_AXIS_S2MM
//
//   算法【逐位照抄】v110_autosharpen.py 的 C 版 p11_unsharp2
//   （权威源：_pl_unsharp_2026-10-28/_ref_unsharp_kernel.cpp）：
//
//       recip = 65536 / (k*k)                  ← 整数除法，k=5 → 2621
//       a8    = (int)(amount*256 + 0.5)         ← Q8，四舍五入
//       blur8 = (sum_kxk * recip) >> 8          ← Q8 的模糊值
//       v     = orig + ((a8 * ((orig<<8) - blur8)) >> 16)
//       out   = clamp(v, 0, 255)
//
//   边界：replicate（左右 + 上下），与 C 版 p11_hrow 的 clamp 一致。
//
//   ⚠️ 与 C 版的唯一差别：C 版用 k+1 个 slot 且 `% slots` 取模；本核用 8 个
//      slot（2 的幂，& 7）省掉除法器。**存的数据内容完全相同** ⇒ 结果逐位相同。
//
//   ⚠️ k 第一版硬编码 5（K_FIXED）。要支持 3 需重综合。
//
//   ⚠️ tlast 必须自己生成：本核比 remap 晚 R 行输出，流的 tlast 不能透传。
//      帧末 = (out_row == h-1) && (out_col == w-1)。
//=============================================================================
#include <hls_stream.h>
#include <ap_axi_sdata.h>
#include <ap_int.h>

#define MAX_W   512
#define K_FIXED 5
#define R_FIXED (K_FIXED >> 1)      // = 2
#define SLOTS   8                    // 2 的幂，必须 > K_FIXED + 1

typedef ap_axiu<32, 0, 0, 0> axis_pkt;
typedef ap_uint<24>          pix24;
typedef ap_int<16>           hsum_t;

static inline int clampi(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// 读一行（w 个像素）+ 算水平滑动和，写进 slot
static void load_and_hsum(hls::stream<axis_pkt>& s,
                          pix24  (&raw)[SLOTS][MAX_W],
                          hsum_t (&h0)[SLOTS][MAX_W],
                          hsum_t (&h1)[SLOTS][MAX_W],
                          hsum_t (&h2)[SLOTS][MAX_W],
                          int w, int sl)
{
    for (int x = 0; x < w; ++x) {
#pragma HLS PIPELINE II=1
        axis_pkt p = s.read();
        raw[sl][x] = p.data.range(23, 0);        // bit[31:24] 填充位，丢弃
    }

    // 初始窗口：x=0 的 k 邻域（左侧 replicate）
    int s0 = 0, s1 = 0, s2 = 0;
    for (int i = 0; i < K_FIXED; ++i) {
        int sx = clampi(i - R_FIXED, 0, w - 1);
        pix24 v = raw[sl][sx];
        s0 += (int)v.range(7, 0);
        s1 += (int)v.range(15, 8);
        s2 += (int)v.range(23, 16);
    }

    for (int x = 0; x < w; ++x) {
#pragma HLS PIPELINE II=1
        h0[sl][x] = (hsum_t)s0;
        h1[sl][x] = (hsum_t)s1;
        h2[sl][x] = (hsum_t)s2;

        int add = clampi(x + R_FIXED + 1, 0, w - 1);   // 右端 replicate
        int rem = clampi(x - R_FIXED,     0, w - 1);   // 左端 replicate
        pix24 va = raw[sl][add];
        pix24 vr = raw[sl][rem];
        s0 += (int)va.range(7, 0)  - (int)vr.range(7, 0);
        s1 += (int)va.range(15, 8) - (int)vr.range(15, 8);
        s2 += (int)va.range(23, 16) - (int)vr.range(23, 16);
    }
}

void axis_sharp(hls::stream<axis_pkt>& s_axis,
                hls::stream<axis_pkt>& m_axis,
                ap_uint<16> w_out,
                ap_uint<16> h_out,
                ap_int<32>  a8,
                ap_uint<1>  enable)
{
#pragma HLS INTERFACE axis      port=s_axis
#pragma HLS INTERFACE axis      port=m_axis
#pragma HLS INTERFACE s_axilite port=w_out  bundle=control
#pragma HLS INTERFACE s_axilite port=h_out  bundle=control
#pragma HLS INTERFACE s_axilite port=a8     bundle=control
#pragma HLS INTERFACE s_axilite port=enable bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    static pix24  raw[SLOTS][MAX_W];
    static hsum_t h0 [SLOTS][MAX_W];
    static hsum_t h1 [SLOTS][MAX_W];
    static hsum_t h2 [SLOTS][MAX_W];
#pragma HLS ARRAY_PARTITION variable=raw complete dim=1
#pragma HLS ARRAY_PARTITION variable=h0  complete dim=1
#pragma HLS ARRAY_PARTITION variable=h1  complete dim=1
#pragma HLS ARRAY_PARTITION variable=h2  complete dim=1

    const int w  = (int)w_out;
    const int h  = (int)h_out;
    const int A8 = (int)a8;
    const int recip = 65536 / (K_FIXED * K_FIXED);   // = 2621
    const bool en = (enable != 0);
    const int MASK = SLOTS - 1;

    if (w <= 0 || h <= 0 || w > MAX_W) return;

    // ---------- 预读第 0..R 行 ----------
    for (int yy = 0; yy <= R_FIXED; ++yy) {
        load_and_hsum(s_axis, raw, h0, h1, h2, w,
                      (yy < h ? yy : h - 1) & MASK);
    }

    // ---------- 主循环：输出 h 行 ----------
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
#pragma HLS PIPELINE II=1
            // 垂直求和：k 行 hsum 相加（边界 replicate）
            int v0 = 0, v1 = 0, v2 = 0;
            for (int i = 0; i < K_FIXED; ++i) {
                int sl = clampi(y - R_FIXED + i, 0, h - 1) & MASK;
                v0 += (int)h0[sl][x];
                v1 += (int)h1[sl][x];
                v2 += (int)h2[sl][x];
            }

            pix24 o = raw[y & MASK][x];

            ap_uint<32> od;
            if (en && A8 > 0) {
                // ---- 逐位复现 C 版定点 ----
                int b0 = (v0 * recip) >> 8;
                int b1 = (v1 * recip) >> 8;
                int b2 = (v2 * recip) >> 8;

                int p0 = (int)o.range(7, 0);
                int p1 = (int)o.range(15, 8);
                int p2 = (int)o.range(23, 16);

                int r0 = p0 + ((A8 * ((p0 << 8) - b0)) >> 16);
                int r1 = p1 + ((A8 * ((p1 << 8) - b1)) >> 16);
                int r2 = p2 + ((A8 * ((p2 << 8) - b2)) >> 16);

                od.range(7, 0)   = (ap_uint<8>)clampi(r0, 0, 255);
                od.range(15, 8)  = (ap_uint<8>)clampi(r1, 0, 255);
                od.range(23, 16) = (ap_uint<8>)clampi(r2, 0, 255);
            } else {
                od.range(23, 0) = o;          // bypass：原样直通（延迟照旧）
            }
            od.range(31, 24) = 0;

            axis_pkt op;
            op.data = od;
            op.keep = 0xF;
            op.strb = 0xF;
            op.last = (y == h - 1 && x == w - 1) ? 1 : 0;
            m_axis.write(op);
        }

        // 读下一行：y + R + 1（超出则不复用，边界靠 clamp 读最后一行）
        if (y + R_FIXED + 1 < h) {
            load_and_hsum(s_axis, raw, h0, h1, h2, w,
                          (y + R_FIXED + 1) & MASK);
        }
    }
}
