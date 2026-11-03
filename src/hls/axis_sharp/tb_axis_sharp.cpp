//=============================================================================
// tb_axis_sharp.cpp —— axis_sharp 的 C 仿真测试台（本机 g++ 直接跑，不开 Vitis）
//
//   用法： tb_axis_sharp <in.raw> <out.raw> <w> <h> <a8> <enable>
//          in/out.raw = 紧排 BGR24（每像素 3 字节，行间无填充）
//
//   判据（先写死）：输出与 C 版 p11_unsharp2 逐字节相同（max abs diff = 0）。
//   本 TB 自己只检查「输出个数对、tlast 在最后一个像素」，逐字节比对另做。
//=============================================================================
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "axis_sharp.cpp"

int main(int argc, char** argv) {
    if (argc < 7) {
        printf("usage: %s <in.raw> <out.raw> <w> <h> <a8> <enable>\n", argv[0]);
        return 2;
    }
    const char* fin  = argv[1];
    const char* fout = argv[2];
    int w  = atoi(argv[3]);
    int h  = atoi(argv[4]);
    int a8 = atoi(argv[5]);
    int en = atoi(argv[6]);

    const size_t n = (size_t)w * (size_t)h * 3;
    std::vector<unsigned char> src(n), dst(n, 0);

    FILE* f = fopen(fin, "rb");
    if (!f) { printf("ERR: cannot open %s\n", fin); return 2; }
    if (fread(src.data(), 1, n, f) != n) {
        printf("ERR: short read (need %zu bytes)\n", n);
        fclose(f); return 2;
    }
    fclose(f);

    hls::stream<axis_pkt> s_in, s_out;

    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            size_t i = ((size_t)y * w + x) * 3;
            axis_pkt p;
            p.data.range(7,  0) = (ap_uint<8>)src[i + 0];
            p.data.range(15, 8) = (ap_uint<8>)src[i + 1];
            p.data.range(23, 16)= (ap_uint<8>)src[i + 2];
            p.data.range(31, 24)= 0;
            p.keep = 0xF;
            p.strb = 0xF;
            p.last = (y == h - 1 && x == w - 1) ? 1 : 0;
            s_in.write(p);
        }
    }

    axis_sharp(s_in, s_out, (ap_uint<16>)w, (ap_uint<16>)h,
               (ap_int<32>)a8, (ap_uint<1>)en);

    int got = 0, tlast_at_end = 0, tlast_count = 0;
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            if (s_out.empty()) {
                printf("ERR: output stream underflow at y=%d x=%d (got %d of %d)\n",
                       y, x, got, w * h);
                return 3;
            }
            axis_pkt p = s_out.read();
            size_t i = ((size_t)y * w + x) * 3;
            dst[i + 0] = (unsigned char)p.data.range(7,  0);
            dst[i + 1] = (unsigned char)p.data.range(15, 8);
            dst[i + 2] = (unsigned char)p.data.range(23, 16);
            if (p.last) {
                ++tlast_count;
                if (y == h - 1 && x == w - 1) tlast_at_end = 1;
                else printf("ERR: tlast at wrong place y=%d x=%d\n", y, x);
            }
            ++got;
        }
    }
    if (!s_out.empty()) printf("WARN: extra pixels left in output stream\n");

    f = fopen(fout, "wb");
    if (!f) { printf("ERR: cannot write %s\n", fout); return 2; }
    fwrite(dst.data(), 1, n, f);
    fclose(f);

    printf("OK w=%d h=%d a8=%d enable=%d out_pixels=%d tlast_count=%d tlast_at_end=%d\n",
           w, h, a8, en, got, tlast_count, tlast_at_end);
    return (got == w * h && tlast_count == 1 && tlast_at_end) ? 0 : 4;
}
