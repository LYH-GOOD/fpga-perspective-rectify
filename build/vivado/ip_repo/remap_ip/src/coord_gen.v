//=============================================================================
// coord_gen.v
//   单应变换的坐标发生器 —— 行初始化 + 沿行递推
//
//   这是 01 蓝图 §2.2「沿行递推，每像素 3 次加法」的实现：
//   沿输出行向右走一个像素，三个累加器各自只增加一个【常量】，
//   不需要每个像素重算 6 次乘法 + 3 次加法。
//
//---------------------------------------------------------------------------
//   ⭐ 设计一：递推在【精确整数域】做，不在定点域做
//---------------------------------------------------------------------------
//   朴素递推的问题是：每步增量要先截断再累加，误差会【累积】。
//   例如把 xn（Q16.16）直接累加 (a11*su)>>16，每步丢 0.5 LSB，
//   1280 步就是 640 LSB ≈ 0.01 px —— 白白吃掉精度预算。
//
//   本模块改为累加【未移位的精确量】：
//
//       XN = a11·su + a12·sv + (a13 << 16)        ← 完全精确，无截断
//       YN = a21·su + a22·sv + (a23 << 16)
//       DD = a31·su + a32·sv + (65536 << 16)
//
//   沿 u 递推： XN += a11·32     （a11·32 是精确整数）
//   沿 v 递推： sv += 32，XN 初值 = a12·sv + (a13<<16)
//   最后一次性移位： xn = XN >> 16,  d = DD >> 16
//
//   ⚠️ 与直算版（homography_calc.v）的差别：直算版把三项【各自】右移再相加，
//      本模块把三项【先相加再】右移。实测本模块精度反而高 1.8 倍
//      （实测误差 0.0186 px vs 0.0329 px），因为只在最后舍入一次。
//
//=============================================================================
//   ⭐⭐ 设计二（2026-09-27 提速第一步）：把递推与除法【解耦】，N 路并行
//=============================================================================
//   改动前的问题：
//       递推每算出一个像素的坐标，就【停下来等】除法器 49 拍。
//       于是每个像素 ~60 拍里，49 拍(82%) 在干等 —— 除法器算完就闲置。
//
//   改动后的结构：
//
//       递推（1 拍/次）──┬──► 除法器 0 ──┐
//                       ├──► 除法器 1 ──┤
//                       ├──► ...        ├──► 结果 FIFO ──► 上层
//                       └──► 除法器 N-1 ┘
//
//   ⭐ 关键洞察：**不需要操作数队列**。
//      让 N 个除法器【按轮转顺序启动】，且它们的延迟完全相同 →
//      完成顺序 == 启动顺序 → 结果天然有序，直接进 FIFO 即可。
//
//   ⚠️⚠️ 更正一个一度写在这里的【错误结论】（2026-09-27 踩到，代价很大）：
//      原文写的是"div_seq 一个字都没改 → 逐字节一致【结构上成立】"。
//      **错。** div_seq 当时并不是一个 (a,b) 的纯函数：
//        · q_neg 在 done 那拍才从【活输入】取 → 符号跑到别的像素上
//        · b_ext = {1'b0, b_abs} 组合进【每一次迭代】 → 除数在运行中被改掉
//      它只在 N=1 时侥幸正确（上游会等 done，操作数总线 49 拍不动）。
//      N=8 时总线每几拍换一次 → 同一组 (a,b) 算出的商就偏了。
//      ⇒ "用同一个子模块"只保证【算法一样】，不保证【接口时序无关】。
//        并行化一定会让子模块的输入总线变得不安分，凡是内部用了活输入的地方
//        都会在那里露馅。判据不能靠推理，只能靠【跨并行度逐字节 diff】。
//      （对比方案"倒数查表+牛顿"是近似算法，必须精确校正——
//        风险和验证成本更高，这一点原文的判断仍然成立。）
//
//   节流：某个除法器忙 / 结果 FIFO 满 / 本行像素已发完 → 递推暂停。
//        除法器产得快（49/N 拍一个），上层吃得慢（~11 拍一个），
//        所以 FIFO 会填满、生产被节流 —— **上层永远不用等**。
//
//   ⚠️ N=1 时行为与改动前【逐字节相同】，可用来单独验证"解耦"这一步改对了。
//=============================================================================
`timescale 1ns / 1ps

module coord_gen #(
    parameter integer FRAC_BITS  = 16,      // Q16.16
    parameter integer NORM_SCALE = 2048,    // 坐标归一化尺度（必须是 2 的幂）
    parameter integer ACC_W      = 56,      // 累加器位宽
    parameter integer DIV_AW     = 48,      // 除法器被除数位宽
    parameter integer DIV_BW     = 32,      // 除法器除数位宽
    parameter integer DIV_WQ     = 48,      // 除法器商位宽
    parameter integer NDIV       = 8,       // ⭐ 除法器并行度（每个含 x/y 两个 div_seq）
    //   结果 FIFO 深度。
    //   ⚠️ 不再是"必须 ≥ NDIV"那么简单：发射门控会预留 NDIV 个槽位给在飞结果，
    //      所以实际可排队数 = FIFO_DEPTH - NDIV。取 16 是给上层留 8 格缓冲
    //      （"除法器产得快、FIFO 填满、上层永远不用等"这个解耦效果靠它）。
    parameter integer FIFO_DEPTH = 16
)(
    input  wire                 clk,
    input  wire                 rst_n,       // 同步低电平复位

    // ---------------- 单应逆矩阵参数（Q16.16，已预乘 NORM_SCALE）----------------
    input  wire signed [31:0]   a11, a12, a13,
    input  wire signed [31:0]   a21, a22, a23,
    input  wire signed [31:0]   a31, a32,

    // ---------------- 控制 ----------------
    //   ⚠️ 接口变化（提速第一步）：删掉了 advance —— 递推不再由上层一拍一拍喂，
    //      而是本模块自己按"除法器空闲"的节奏跑。上层只管消耗结果。
    input  wire                 row_load,    // 1 拍脉冲：载入第 row_v 行的初值，并清空队列
    input  wire [11:0]          row_v,       // 输出行号
    input  wire [15:0]          cfg_w_out,   // 本行有多少个像素（递推不能越过行尾）
    //   ⚠️ coord_valid 现在是【电平】（= FIFO 非空），不是脉冲。
    //      所以必须配一个 ready 做握手，否则 FIFO 会每拍都弹出、远快于上层消耗。
    //      上层在 S_PREP 里"准备取"时把 coord_ready 拉高即可。
    input  wire                 coord_ready,

    // ---------------- 结果（从 FIFO 队首【组合】读出）----------------
    //   ⚠️ 必须组合读：如果做成寄存输出，弹出后它会【滞后一拍】——
    //      下一拍 x_q 还停在"已经被弹走的那个值"上，而 coord_valid 已经指向新队首
    //      → 上层会取到错位的数据。（写第一版时踩到的）
    output wire signed [31:0]   x_q,         // 输入图像列坐标，Q16.16
    output wire signed [31:0]   y_q,         // 输入图像行坐标，Q16.16
    output wire signed [31:0]   d_q,         // 分母（调试用，非 FIFO 数据）
    output wire                 coord_valid, // 有结果可取（电平，配 coord_ready 握手）
    output wire                 div_by_zero,
    output wire                 out_overflow
);

    localparam integer NORM_SHIFT = FRAC_BITS - $clog2(NORM_SCALE);   // 16-11 = 5
    localparam integer RR_AW      = (NDIV <= 1) ? 1 : $clog2(NDIV);
    localparam integer FIFO_AW    = (FIFO_DEPTH <= 1) ? 1 : $clog2(FIFO_DEPTH);

    //========================================================================
    // 1. 沿 v 方向的归一化坐标（纯移位）
    //========================================================================
    wire [16:0] sv = {5'd0, row_v} <<< NORM_SHIFT;

    //========================================================================
    // 2. 参数加宽到累加器位宽
    //========================================================================
    wire signed [ACC_W-1:0] a11_e = {{(ACC_W-32){a11[31]}}, a11};
    wire signed [ACC_W-1:0] a12_e = {{(ACC_W-32){a12[31]}}, a12};
    wire signed [ACC_W-1:0] a13_e = {{(ACC_W-32){a13[31]}}, a13};
    wire signed [ACC_W-1:0] a21_e = {{(ACC_W-32){a21[31]}}, a21};
    wire signed [ACC_W-1:0] a22_e = {{(ACC_W-32){a22[31]}}, a22};
    wire signed [ACC_W-1:0] a23_e = {{(ACC_W-32){a23[31]}}, a23};
    wire signed [ACC_W-1:0] a31_e = {{(ACC_W-32){a31[31]}}, a31};
    wire signed [ACC_W-1:0] a32_e = {{(ACC_W-32){a32[31]}}, a32};

    wire signed [ACC_W-1:0] sv_e = {{(ACC_W-17){1'b0}}, sv};

    // 每步增量：a11·32（= a11 << 5，精确，纯移位不占乘法器）
    wire signed [ACC_W-1:0] dXN = a11_e <<< NORM_SHIFT;
    wire signed [ACC_W-1:0] dYN = a21_e <<< NORM_SHIFT;
    wire signed [ACC_W-1:0] dDD = a31_e <<< NORM_SHIFT;

    //========================================================================
    // 3. 行初值（u = 0）
    //    XN0 = a12·sv + (a13 << 16)
    //    乘法先算在双倍位宽，避免 Verilog 静默截断
    //========================================================================
    wire signed [2*ACC_W-1:0] p12 = a12_e * sv_e;
    wire signed [2*ACC_W-1:0] p22 = a22_e * sv_e;
    wire signed [2*ACC_W-1:0] p32 = a32_e * sv_e;

    wire signed [ACC_W-1:0] XN0 = p12[ACC_W-1:0] + (a13_e <<< FRAC_BITS);
    wire signed [ACC_W-1:0] YN0 = p22[ACC_W-1:0] + (a23_e <<< FRAC_BITS);
    wire signed [ACC_W-1:0] DD0 = p32[ACC_W-1:0] + (56'sd1 <<< (FRAC_BITS*2));

    //========================================================================
    // 4. 操作数（来自累加器）
    //------------------------------------------------------------------------
    //   x_q = (xn << 16) / d，xn / d 都是 Q16.16。
    //   ⚠️ 有效范围：|xn| < 2^(DIV_AW-FRAC_BITS) = 2^32，即坐标 < 65536 像素。
    //      实测 7 张图 350 万像素：被除数 ≤ 2^43、除数 ∈ [42824, 90807] 且恒正。
    //========================================================================
    reg signed [ACC_W-1:0] XN, YN, DD;         // 累加器

    wire signed [ACC_W-1:0] xn = XN >>> FRAC_BITS;
    wire signed [ACC_W-1:0] yn = YN >>> FRAC_BITS;
    wire signed [ACC_W-1:0] dd = DD >>> FRAC_BITS;

    wire signed [DIV_AW-1:0] div_a_x = xn <<< FRAC_BITS;   // 左移 16 位，截到 DIV_AW
    wire signed [DIV_AW-1:0] div_a_y = yn <<< FRAC_BITS;
    wire signed [DIV_BW-1:0] div_b   = dd[DIV_BW-1:0];

    //========================================================================
    // 5. 发射节拍：本行还有像素没发 && 轮到的除法器空闲 && FIFO 没满
    //========================================================================
    //   ⚠️ 结果 FIFO 的信号必须【先声明】—— 下面发射逻辑要用 fifo_cnt / fifo_room。
    //      （Verilog 要求声明先于使用；踩过一次）
    localparam integer PKW = 32 + 32 + 3;              // qx + qy + (dz | x_ovf | y_ovf)
    reg [PKW-1:0]              fifo [0:FIFO_DEPTH-1];
    reg [FIFO_AW:0]            fifo_cnt;
    reg [FIFO_AW-1:0]          wr_ptr, rd_ptr;

    reg [15:0]          issued;          // 本行已发射的操作数个数
    reg [RR_AW-1:0]     rr;              // 轮转指针
    reg [NDIV-1:0]      busy;            // 各除法器忙标志

    reg signed [DIV_AW-1:0] a_x_l, a_y_l;
    reg signed [DIV_BW-1:0] b_l;
    reg [RR_AW-1:0]         rr_l;
    reg                     step_d;
    reg                     step_d2;
    integer                 z;
    reg [NDIV-1:0]          start_oh;

    //   ⚠️ 行代号（generation）：行首 +1，每个除法器记下自己是哪一代启动的。
    //      只有"本代"完成的除法器才允许把结果推进 FIFO —— 否则上一行还在算的
    //      除法器会把残留结果塞进新一行的队列。
    //      ⚠️ 不能靠 busy 做这件事：行首 busy 被清零后马上又被新一行预定置位，
    //         旧除法器完成时 busy 已经是 1 了，门控失效。（踩过的坑）
    localparam integer GEN_W = 3;
    reg  [GEN_W-1:0]            gen;
    reg  [GEN_W-1:0]            div_gen [0:NDIV-1];

    wire [NDIV-1:0]              pair_done;
    wire [NDIV-1:0]              pair_dz;
    wire signed [DIV_WQ-1:0]     pair_qx [0:NDIV-1];
    wire signed [DIV_WQ-1:0]     pair_qy [0:NDIV-1];

    //   ⚠️ 这里【故意不再有】fifo_full：光判"满"会让在飞结果把计数顶过深度，
    //      发射判据改用下面的 fifo_room（预留槽位）。要看"满没满"直接看 fifo_cnt。
    wire cur_free  = ~busy[rr];

    //------------------------------------------------------------------------
    // ⭐ 结果 FIFO 背压：必须给【在飞结果】预留槽位 —— 2026-09-27 修第二处死锁级 bug
    //------------------------------------------------------------------------
    //   ⚠️ 原写法只挡 fifo_cnt >= FIFO_DEPTH，但 any_done（除法器完成）是
    //      **不受发射门控**地写 FIFO 的。于是"已经发出去、还没算完"的那些
    //      会一起落进 FIFO：
    //          fifo_cnt = 7 时仍允许发射 → 最多再 8 个在飞 → fifo_cnt 冲到 15
    //      计数超过深度 → wr_ptr 回卷 → **压掉还没被读走的坐标**。
    //      实测（慢消费者，POPGAP=40，模拟上层 11 拍/像素跟不上）：
    //          [FIFO-OVER] fifo_cnt=9 > 深度 8
    //          逐像素 dump 与基准差 6200 行 —— 就是板上"行撕裂/错位"的典型成因。
    //
    //   ⭐ 判据：发射后"未读 + 在飞"不能超过深度。在飞数量上界就是 NDIV，
    //      所以直接从阈值里【预留 NDIV 个槽位】即可 —— 代价只有一次常量比较，
    //      不往 do_step 的关键路径上堆加法器（时序已只剩 +0.6 ns，不能再加）。
    //      证明：记 Φ = fifo_cnt + 在飞数。发射是唯一让 Φ 增大的事件，
    //            门控保证发射后 Φ ≤ (DEPTH-NDIV) + NDIV = DEPTH；
    //            完成/弹出只让 Φ 持平或减小 → 恒有 fifo_cnt ≤ Φ ≤ DEPTH ✓
    //------------------------------------------------------------------------
    localparam [FIFO_AW:0] FIFO_HIWAT = (FIFO_DEPTH > NDIV) ? (FIFO_DEPTH - NDIV) : 0;
    wire fifo_room = (fifo_cnt <= FIFO_HIWAT);

    //------------------------------------------------------------------------
    // ⭐ 在飞门控（inflight gate）—— 2026-09-27 修死锁
    //------------------------------------------------------------------------
    //   一笔发射要经过 3 拍才落到除法器上：
    //        do_step(T) → step_d(T+1) → start_oh(T+2) → 除法器在 T+2 末尾采样
    //
    //   因此 do_step 必须挡住 T+1 / T+2 两拍：
    //     · T+1：不挡的话 a_x_l 会在 T+1 末尾被新操作数覆盖，
    //            而除法器要到 T+2 末尾才采样 → 算的是"未来的像素"（跳点）
    //     · T+2：同上（T+2 末尾的覆盖与采样同沿，虽然非阻塞赋值下侥幸安全，
    //            但 row_load 此刻会把脉冲吃掉 → 就是下面那个死锁）
    //
    //   ⚠️ 旧代码在这里用的是 busy 预定：do_step 那拍就把 busy 置 1。
    //      那样虽然也挡住了 T+1/T+2，但 row_load 落在窗口内时
    //      `if (step_d)` 被跳过 → 脉冲永不发出 → busy 置了却没人清
    //      → pair_done 永不到来 → **永久死锁**（幽灵除法器）。
    //      现在改成"只挡发射、不置 busy"，busy 一律由 start_oh 置位，
    //      于是 busy==1 ⟺ 除法器真的在跑，结构上不可能出现幽灵。
    //------------------------------------------------------------------------
    wire inflight  = step_d | step_d2;
    wire do_step   = (issued < cfg_w_out) && cur_free && fifo_room && ~inflight;

    //------------------------------------------------------------------------
    // ⚠️⚠️ 操作数必须【锁存】，不能在除法器启动时才从活累加器取
    //------------------------------------------------------------------------
    //   踩过的坑：累加器在 do_step 那拍就往前走了，而 start_oh 要再过两拍才到
    //   除法器 —— 到时 XN 已经是 u_{k+2} 了，除法器算的是"未来的像素"。
    //   现象：坐标整体偏一个固定量、且只在某些行露馅。
    //
    //   所以在 do_step 那一拍把 {操作数, 目标除法器号} 一起锁进寄存器，
    //   启动脉冲只认锁存值。
    //------------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            XN <= {ACC_W{1'b0}};
            YN <= {ACC_W{1'b0}};
            DD <= {ACC_W{1'b0}};
            a_x_l <= {DIV_AW{1'b0}};
            a_y_l <= {DIV_AW{1'b0}};
            b_l   <= {DIV_BW{1'b0}};
            rr_l  <= {RR_AW{1'b0}};
            issued <= 16'd0;
            rr     <= {RR_AW{1'b0}};
            step_d  <= 1'b0;
            step_d2 <= 1'b0;
            start_oh <= {NDIV{1'b0}};
            busy     <= {NDIV{1'b0}};
            gen      <= {GEN_W{1'b0}};
            for (z = 0; z < NDIV; z = z + 1) div_gen[z] <= {GEN_W{1'b0}};
        end else begin
            start_oh <= {NDIV{1'b0}};

            //   ⚠️⚠️ 行首必须把 step_d / step_d2 都清掉！
            //      只写 `if (step_d && !row_load)` 是不够的 —— 那只挡住 row_load
            //      【那一拍】，挡不住【下一拍】：上一行遗留的 step_d 会在行首之后
            //      一拍照样发启动脉冲，而且用的是遗留的 rr_l / 操作数。
            //      后果：FIFO 里多一个残留条目，整个坐标序列错位一格。
            //      （诊断 TB 上是"u=1 那格又输出了 u=0 的值"）
            //
            //   ⭐ 行首吃掉一个在飞脉冲是【安全】的：脉冲没发 → busy 没置（新规则）
            //      → 不留幽灵；本行 issued 已归零、FIFO 已清空，本来就要重来。
            if (row_load) begin
                step_d  <= 1'b0;               // ⭐ 断掉遗留脉冲的源头
                step_d2 <= 1'b0;
                XN <= XN0;
                YN <= YN0;
                DD <= DD0;
                issued   <= 16'd0;
                rr       <= {RR_AW{1'b0}};
                gen      <= gen + 1'b1;        // ⭐ 换代号 → 旧除法器的完成作废
            end else begin
                step_d  <= do_step;
                step_d2 <= step_d;             // ⭐ 在飞门控的第 2 拍
                if (step_d) begin
                    start_oh[rr_l] <= 1'b1;
                    div_gen[rr_l]  <= gen;     // ⭐ 记下"哪一代启动的"
                end
                if (do_step) begin
                    XN <= XN + dXN;
                    YN <= YN + dYN;
                    DD <= DD + dDD;
                    // ⭐ 这一拍的 XN/YN/DD 正是"本次要算的那个 u" → 锁下来
                    a_x_l  <= div_a_x;
                    a_y_l  <= div_a_y;
                    b_l    <= div_b;
                    rr_l   <= rr;
                    issued <= issued + 16'd1;
                    rr     <= (rr == NDIV[RR_AW-1:0] - 1'b1) ? {RR_AW{1'b0}} : rr + 1'b1;
                end
            end

            //   ⚠️⚠️ busy 必须【不受 row_load 影响】地更新！
            //      一开始我在 row_load 里写了 busy<=0，结果新行立刻重启了
            //      【还在算】的除法器；旧除法器的 done 稍后到达时，div_gen[i]
            //      已被新行覆盖 → 代号门控失效 → 上一行的残留结果被推进 FIFO。
            //      （现象：换行后前几个坐标是上一行的延续）
            //      正确做法：让在飞的除法器【自然完成】（代号会自动丢弃它的结果），
            //      期间轮转指针 cur_free 自然跳过它。
            //
            //   ⭐⭐ 2026-09-27 修死锁：busy 【只在 start_oh 真正发出时】置位。
            //      "do_step 就预定 busy"会把 busy 和除法器的真实状态解耦 ——
            //      row_load 吃掉脉冲后 busy 留在 1，没人清 → 永久死锁。
            //      现在 busy==1 ⟺ 这个除法器真的在跑，是一条【结构不变量】，
            //      由 tb/coord_gen_deadlock_tb.v 的不变量 A/B 逐拍检查。
            busy <= (busy | start_oh) & ~pair_done;
        end
    end

    //========================================================================
    // 6. N 组除法器（每组含 x / y 两个 div_seq）
    //    ⚠️ 按轮转顺序启动、延迟相同 → 完成顺序 == 启动顺序 → 结果天然有序
    //========================================================================
    genvar gi;
    generate
        for (gi = 0; gi < NDIV; gi = gi + 1) begin : g_div
            wire done_x, done_y, dz_x, dz_y;
            div_seq #(.WA(DIV_AW), .WB(DIV_BW), .WQ(DIV_WQ)) u_div_x (
                .clk(clk), .rst_n(rst_n),
                .start(start_oh[gi]), .a(a_x_l), .b(b_l),
                .q(pair_qx[gi]), .done(done_x), .div_zero(dz_x)
            );
            div_seq #(.WA(DIV_AW), .WB(DIV_BW), .WQ(DIV_WQ)) u_div_y (
                .clk(clk), .rst_n(rst_n),
                .start(start_oh[gi]), .a(a_y_l), .b(b_l),
                .q(pair_qy[gi]), .done(done_y), .div_zero(dz_y)
            );
            assign pair_done[gi] = done_x & done_y;   // 两个同拍完成（同参数、同启动）
            assign pair_dz[gi]   = dz_x | dz_y;
        end
    endgenerate



    //========================================================================
    // 7. 结果 FIFO
    //------------------------------------------------------------------------
    //   完成顺序 == 启动顺序，所以"哪个除法器完成"不影响顺序，直接入队即可。
    //========================================================================
    // ⭐ 按【行代号】过滤：只有本代启动的除法器完成才作数
    wire [NDIV-1:0] done_oh;
    genvar gg;
    generate
        for (gg = 0; gg < NDIV; gg = gg + 1) begin : g_gen_gate
            assign done_oh[gg] = pair_done[gg] & (div_gen[gg] == gen);
        end
    endgenerate
    wire any_done = |done_oh;                          // 同一拍最多一个（等延迟）

    // 从 one-hot 的完成信号里选出是哪一个
    reg [RR_AW-1:0] done_idx;
    integer k;
    always @(*) begin
        done_idx = {RR_AW{1'b0}};
        for (k = NDIV - 1; k >= 0; k = k - 1)
            if (done_oh[k]) done_idx = k[RR_AW-1:0];
    end

    wire signed [DIV_WQ-1:0] qx_sel = pair_qx[done_idx];
    wire signed [DIV_WQ-1:0] qy_sel = pair_qy[done_idx];
    wire                     dz_sel = pair_dz[done_idx];

    wire x_ovf = (qx_sel > 48'sd2147483647) || (qx_sel < -48'sd2147483648);
    wire y_ovf = (qy_sel > 48'sd2147483647) || (qy_sel < -48'sd2147483648);

    wire [PKW-1:0] pack_in = {dz_sel, x_ovf, y_ovf, qx_sel[31:0], qy_sel[31:0]};

    // 消费：必须是【握手】—— 有数据 且 上层说"我要取"
    wire pop = coord_valid & coord_ready;
    wire pop_any = pop;   // 仅供 TB 探针

    always @(posedge clk) begin
        if (!rst_n) begin
            fifo_cnt <= {(FIFO_AW+1){1'b0}};
            wr_ptr   <= {FIFO_AW{1'b0}};
            rd_ptr   <= {FIFO_AW{1'b0}};
        end else if (row_load) begin
            fifo_cnt <= {(FIFO_AW+1){1'b0}};           // 行首清队
            wr_ptr   <= {FIFO_AW{1'b0}};
            rd_ptr   <= {FIFO_AW{1'b0}};
        end else begin
            case ({any_done, pop})
                2'b10: begin fifo[wr_ptr] <= pack_in; wr_ptr <= wr_ptr + 1'b1;
                             fifo_cnt <= fifo_cnt + 1'b1; end
                2'b01: begin rd_ptr <= rd_ptr + 1'b1;
                             fifo_cnt <= fifo_cnt - 1'b1; end
                2'b11: begin fifo[wr_ptr] <= pack_in; wr_ptr <= wr_ptr + 1'b1;
                             rd_ptr <= rd_ptr + 1'b1; end       // 同时读写，计数不变
                default: ;
            endcase
        end
    end

    //========================================================================
    // 8. 输出（从 FIFO 弹出）
    //========================================================================
    //   ⚠️⚠️ 位序：Verilog 拼接 {a,b,c,d} 是【高位在前】，所以 pack_in 里
    //        qx 落在 [63:32]、qy 落在 [31:0] —— 别按"先后顺序"去想。
    //        （写第一版时读反了，x/y 整整对调，TB 一看就露馅）
    //        [66]=dz  [65]=x_ovf  [64]=y_ovf  [63:32]=qx  [31:0]=qy
    wire [PKW-1:0] head = fifo[rd_ptr];

    assign coord_valid  = (fifo_cnt != 0);          // 电平：队里有货

    //========================================================================
    // 9. 吞吐计数（片上性能计量，与 remap_core 的 pf_* 配套）
    //------------------------------------------------------------------------
    //   回答"坐标为什么供不上"：是除法器环满了，还是结果 FIFO 满了。
    //     · pf_nofree 大 → 8 路除法器是瓶颈（要加并行度，或换算法）
    //     · pf_noroom 大 → 上层吃得慢（FIFO 满是被动现象，不是本模块的锅）
    //   这两个的修法完全相反，混在一起看会得出错误结论。
    //   ⚠️ 纯计数器，不参与数据通路；同一拍里 noroom 优先计数（互斥）。
    //   ⚠️ 必须定义在文件【末尾】—— do_step / any_done / fifo_room 都在上面才定义
    //      （否则报 "Unable to bind ... Check for declaration after use"）
    //========================================================================
    reg [31:0] pf_step   = 0;     // 发射次数（= 本模块实际吞吐）
    reg [31:0] pf_nofree = 0;     // 卡：轮到的那路除法器还忙
    reg [31:0] pf_noroom = 0;     // 卡：结果 FIFO 满
    always @(posedge clk) begin
        if (rst_n) begin
            if (do_step) pf_step <= pf_step + 1'b1;
            if      ((issued < cfg_w_out) && ~inflight && !fifo_room)
                pf_noroom <= pf_noroom + 1'b1;
            else if ((issued < cfg_w_out) && ~inflight && fifo_room && !cur_free)
                pf_nofree <= pf_nofree + 1'b1;
        end
    end

    assign x_q          = head[63:32];
    assign y_q          = head[31:0];
    assign div_by_zero  = head[PKW-1];              // [66]
    assign out_overflow = head[PKW-2] | head[PKW-3];
    assign d_q          = dd[31:0];                 // 调试用，非按像素对齐

endmodule
