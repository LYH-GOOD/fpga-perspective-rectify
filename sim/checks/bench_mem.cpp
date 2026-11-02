//=============================================================================
// bench_mem.cpp —— B1 实验：零访存（流式）vs 落 DDR（随机取 4 邻域）
//
// 目的：把"架构差别"从"CPU 快慢"里剥离出来 —— 同样的字节数、同一块内存，
//       只改**访问模式**，看差多少。
//
// 三条测量（取多次最小值，避开调度抖动）：
//   A  顺序读 IN_B   —— 我们的 PL 核输入就是这么取的（每个字节读一次）
//   A' 顺序读 OUT_B  —— 与 B 的**逻辑字节数**相同，作为公平基准
//   B  双线性取数     —— "落 DDR" 的做法：每个输出像素取 4 个邻居
//   C  顺序写        —— 我们的输出路径
//
// 地形：梯形（keystone）局部线性化，模拟"斜着拍一张纸"；
// 坐标用 Q16.16 增量递推（和 coord_gen 一样），**不把坐标计算当成本体**。
//
// 编译： g++ -O3 -std=c++11 -o bench_mem bench_mem.cpp
// 运行： ./bench_mem [重复次数，默认 7]
//
// ⚠️ 读数注意：
//   · B 的 MB/s 按【逻辑字节】算（4 B × 输出像素）；真实 DRAM 事务是 cache line，
//     所以另报一列 **估算的 cache line 流量**。
//   · 这里的内存是 malloc（可缓存），而 PL 走 DMA 是 uncached ——
//     所以这里的数对"落 DDR"是**偏乐观**的（CPU 有缓存帮忙，PL 没有）。
//   · ⚠️ 这个基准在桌面 x86 上**没有意义**（全在 cache 里，17 GB/s），
//     只在 PYNQ 的 Cortex-A9 + DDR 上才有参考价值。
//=============================================================================
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>

static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+1e-9*t.tv_nsec; }

int main(int argc,char** argv){
    const int IW=640, IH=480;            // 输入帧（YUYV）
    const int OW=362, OH=512;            // 输出（与上板日志一致）
    const int IN_B = IW*IH*2;            // 614,400
    const int OUT_B= OW*OH*4;            // 741,376
    const int REP  = argc>1?atoi(argv[1]):7;

    uint8_t* buf=(uint8_t*)malloc(OUT_B);          // A/A'/B 共用
    uint8_t* out=(uint8_t*)malloc(OUT_B);
    if(!buf||!out){printf("malloc failed\n");return 1;}
    for(int i=0;i<OUT_B;i++) buf[i]=(uint8_t)(i*31+7);
    memset(out,0,OUT_B);
    volatile long sink=0;

    printf("输入 %dx%d (%d B)   输出 %dx%d (%d B)   重复 %d 次\n",IW,IH,IN_B,OW,OH,OUT_B,REP);
    printf("------------------------------------------------------------------\n");

    // ---------- A 顺序读（IN_B）----------
    double best=1e9;
    for(int r=0;r<REP;r++){
        double t=now(); long s=0;
        for(int i=0;i<IN_B;i++) s+=buf[i];
        sink+=s; t=now()-t; if(t<best)best=t;
    }
    const double a_ms=best*1000;
    printf("A  顺序读    %8.2f ms   %8.1f MB/s   (%d B)\n",a_ms,IN_B/best/1e6,IN_B);

    // ---------- A' 顺序读（OUT_B，与 B 同逻辑字节数）----------
    best=1e9;
    for(int r=0;r<REP;r++){
        double t=now(); long s=0;
        for(int i=0;i<OUT_B;i++) s+=buf[i];
        sink+=s; t=now()-t; if(t<best)best=t;
    }
    const double a2_ms=best*1000;
    printf("A' 顺序读    %8.2f ms   %8.1f MB/s   (%d B，与 B 同字节数)\n",a2_ms,OUT_B/best/1e6,OUT_B);

    // ---------- B 双线性取数（4 邻域）----------
    best=1e9;
    for(int r=0;r<REP;r++){
        double t=now(); long s=0;
        for(int v=0;v<OH;v++){
            // 逐行重置，行内增量递推（Q16.16）
            int64_t ux=(int64_t)((30.0+0.06*v)*65536.0);
            int64_t vy=(int64_t)((40.0+1.06*v)*65536.0);
            const int64_t dx=(int64_t)(1.05*65536.0);
            for(int u=0;u<OW;u++){
                int x=(int)(ux>>16); int y=(int)(vy>>16);
                if(x<0)x=0; if(x>IW-2)x=IW-2;
                if(y<0)y=0; if(y>IH-2)y=IH-2;
                const uint8_t* p=buf+(size_t)y*IW*2+(size_t)x*2;
                s+=p[0]+p[2]+p[IW*2]+p[IW*2+2];
                ux+=dx;
            }
        }
        sink+=s; t=now()-t; if(t<best)best=t;
    }
    const double g_ms=best*1000;
    //   每个输出像素跨两行、每行 2 个相邻像素 ⇒ 通常落在 2 条 64 B cache line 内
    const double lines=(double)OW*OH*2.0;
    printf("B  双线性    %8.2f ms   %8.1f MB/s   (%d B 逻辑)\n",g_ms,OUT_B/best/1e6,OUT_B);
    printf("             估算 cache line 流量 ≈ %.1f MB（按 2 条/Px 估）\n",lines*64/1e6);
    printf("             ⇒ 同样字节数下，随机取数比顺序读慢 %.2f 倍\n",g_ms/a2_ms);

    // ---------- C 顺序写 ----------
    best=1e9;
    for(int r=0;r<REP;r++){
        double t=now();
        memset(out,0xA5,OUT_B);
        t=now()-t; if(t<best)best=t;
    }
    printf("C  顺序写    %8.2f ms   %8.1f MB/s   (%d B)\n",best*1000,OUT_B/best/1e6,OUT_B);

    printf("------------------------------------------------------------------\n");
    printf("参考：本项目的 PL 流式核整帧 dma_wait p50 ≈ 21.9 ms\n");
    printf("      （顺序读输入 + 顺序写输出 + 插值算术，全在片上行缓存里完成）\n");
    (void)sink;
    free(buf);free(out);
    return 0;
}
