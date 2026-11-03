//=============================================================================
// remap_core.v
//   流式重映射核 —— 行缓存 + 坐标递推 + 双线性插值
//
//   数据通路（全程片上，不落 DDR —— 铁律 1）：
//
//     输入像素流 ──► 行缓存 ──► 4 邻域 ──► 双线性 ──► 输出像素流
//                      ▲
//        8 个 H⁻¹ 参数 ─┴─► 坐标递推（每像素 3 次加法）
//
//   输入、输出都是"1 像素/时钟 + valid 握手"的简单流接口，
//   外面套一层 AXI-Stream 即可对接 DMA（视频阶段换成 HDMI RX/TX，本模块不改）。
//
//---------------------------------------------------------------------------
//   ⚠️⚠️ 行缓存深度 ROWS 的硬约束（决定本模块能否不死锁）
//---------------------------------------------------------------------------
//   记输出第 v 行所需输入行的区间为 [y_min(v), y_max(v)]，跨度 span = y_max-y_min+1。
//
//        不死锁条件：   ROWS > span
//
//   理由（流控的两条边界必须同时成立）：
//     · 要能产出第 v 行，输入必须已写到 y_max(v)  →  rows_written > y_max
//     · 不能覆盖还要用的行 y_min(v)                →  rows_written < y_min + ROWS
//   两式并存 ⟺ y_max < y_min + ROWS - 1 ⟺ ROWS > span
//
//   span 的实测规律（sim/golden/analyze_band.py，已实测非推算）：
//         span ≈ W_out × tan(θ)，θ = 文档在【图像里】的旋转角
//   ⚠️ 是【旋转】决定深度，不是倾角：
//         纯倾斜（θ=0）只要 2 行；旋转 3° 要 61 行；旋转 10° 要 196 行。
//   演示时必须让文档在画面里接近"正"的（相机端平），否则 span 超限
//   → 表现为画面冻结（可用 stuck 信号检出）。
//
//---------------------------------------------------------------------------
//   吞吐（2026-09-27 提速① 后更新）
//---------------------------------------------------------------------------
//   提速前：每像素约 60 拍 = 等除法器 49 拍 + 其余 11 拍 → 720p 约 1.5 fps。
//   提速①（coord_gen 里 8 路并行除法器 + 结果 FIFO 解耦）后：
//         每像素约 12 拍（实测 11.99：76800 px / 920519 拍）→ 720p ≈ 7.5 fps。
//   ⚠️ 瓶颈已经【不是除法器】，而是本模块 FSM 每像素串行的 ~11 拍
//      （取 4 邻域 4 拍 + 双线性 2 拍 + 钳位/输出等）。下一步②对它做流水线化，
//      让相邻像素同时处于不同阶段 → 目标 ~6 拍。
//
//   ⭐ 多帧（视频）：2026-09-30 已支持，并【上板实测】——
//      批量 4 帧 × 4 组不同 H、全程不复位、逐字节一致（run_result(16).log）。
//      靠两处【相扣】的机制，不需要"帧基准偏移"（那是当时设想的另一条路）：
//        · line_buf 在【帧首】把 rows_written 归零
//          ⇒ 语义从"上电至今写了多少行"变成"本帧写了多少行"
//          （否则 ROW_AW=12 撑不了几帧就回绕）
//        · A_IDLE 的开工条件带上 frame_started
//          ⇒ 挡住"帧末 A 多跑一行、用上一帧参数锁存下一帧第 0 行"
//      详见 §7b 与 line_buf.v 的 rows_written 段。
//=============================================================================
`timescale 1ns / 1ps

module remap_core #(
    //---- 颜色（2026-09-30 彩色步 C3）----------------------------------------
    //   NCH = 1：灰度，PIX_W=8（每像素 8 位）
    //   NCH = 3：彩色，PIX_W=24（RGB888，接口字宽）
    //   ⚠️ 行缓存里【不】存 24 位 —— 见下面的 LB_PIX_W。
    parameter integer NCH        = 1,       // 通道数：1 = 灰度，3 = 彩色 RGB
    parameter integer PIX_W      = 8,       // 接口像素位宽 = NCH*8
    //---- 其它 --------------------------------------------------------------
    parameter integer ROW_AW     = 12,      // 行号位宽
    // ⚠️ ROWS 必须 > 输出单行源区间的最大垂直跨度，否则死锁（画面冻结）；
    //    ⚠️⚠️ 原来写"必须是 2 的幂"，2026-09-29 已解除：line_buf 的 row_to_slot
    //        支持非 2 的幂（彩色要 192 —— 见那里的推导）。2 的幂走位切片（最快）。
    //    强旋转的真实照片实测需要 166 行 → 灰度 256 / 彩色 192。
    parameter integer ROWS       = 256,     // 行缓存深度（见上面硬约束）
    parameter integer FRAC_BITS  = 16,
    parameter integer NORM_SCALE = 2048,
    parameter integer ACC_W      = 56,
    parameter integer MAX_W      = 1280     // 支持的最大图像宽（PS 侧已限 ≤1280）
)(
    input  wire                 clk,
    input  wire                 rst_n,

    // ---------------- 配置（运行中保持不变）----------------
    input  wire [15:0]          cfg_w_in, cfg_h_in,
    input  wire [15:0]          cfg_w_out, cfg_h_out,
    input  wire signed [31:0]   a11, a12, a13, a21, a22, a23, a31, a32,

    // ---------------- 输入像素流 ----------------
    input  wire                 in_valid,
    input  wire [PIX_W-1:0]     in_data,
    input  wire                 in_sof,      // 帧首像素
    output wire                 in_ready,    // 反压
    input  wire                 in_eof,      // 帧末像素（该像素仍有效）

    // ---------------- 输出像素流（标准 valid/ready 握手）----------------
    //   ⚠️ out_valid/out_data 是【组合】输出（由 S_OUT 状态直接决定），
    //      这是 AXI-Stream 的标准做法：tvalid 拉高后保持数据不变，
    //      直到 tready 到来才推进。若做成寄存输出，下游会在 tvalid 尚未
    //      拉高时就"接收"一拍，属于协议违例。
    input  wire                 out_ready,   // 下游能否接收（= AXI-Stream 的 tready）
    output wire                 out_valid,
    output wire [PIX_W-1:0]     out_data,
    output wire                 out_sof,
    output wire                 out_last,

    // ---------------- 状态 ----------------
    output reg                  frame_done,
    output reg                  stuck,       // 等所需输入行超时（多半是 ROWS 配小了）

    // ---------------- 调试（2026-09-29 加）----------------
    //   ⭐ 上板失败时"卡在输入侧还是卡在核里"靠猜了两轮板子。
    //      把活状态直接引出来，配合 axi_lite_regs 的 DBG0/DBG1 只读寄存器，
    //      一次就能问到答案 —— **DBG0[24] 的 in_ready 一个 bit 就能定案**：
    //        卡住时 in_ready=0 ⇒ 核在反压输入（DMA 当然发不出去）
    //        卡住时 in_ready=1 ⇒ 核没反压，问题在 DMA/外部
    //   ⚠️ 纯观测，不参与任何逻辑、不进关键路径。
    output wire [31:0]          dbg0,
    output wire [31:0]          dbg1
);

    localparam integer COL_AW = $clog2(MAX_W);
    localparam [ROW_AW-1:0] ROWS_C  = ROWS[ROW_AW-1:0];
    localparam [ROW_AW:0]   ROWS_EXT = ROWS;          // 加宽一比特，供流控比较用
    localparam [ROW_AW-1:0] ROW0    = {ROW_AW{1'b0}};

    //========================================================================
    // 0. ⭐ 颜色格式：行缓存里存什么（2026-09-30 彩色步 C3）
    //========================================================================
    //   ⚠️ 接口是 RGB888（PIX_W=24），**但行缓存里存 RGB565（16 位）** ——
    //      这是整个彩色方案里最贵的一个取舍，理由如下（全是实测，不是估算）。
    //
    //   【为什么不能存 888】行缓存开销 = ROWS × 行距 × 位宽：
    //
    //       格式        位宽   RAMB36（行距 1024 / ROWS 192）  占比
    //       RGB888      24     144                             ✗ 超过芯片的 140
    //       RGB666      18     108                             77%（偏满）
    //       RGB565      16      96                             69%
    //      （实测：build/probe_linebuf_bram.tcl 单独综合 line_buf；
    //        自检：它测出的灰度现状 80 块 = 整工程实测 82 块 ⇒ 数字可信）
    //
    //   【为什么是 565 而不是 666】18 位理论上"白捡"（BRAM 字宽本来就是 18），
    //      但实测量出来是 108 块、不是 96 —— Vivado 没按 2K×18 铺满。
    //      60 → 108 块要多占 12 块（+12.5%），而本项目 **在 80 块时就因布线拥塞
    //      把时钟从 100 MHz 压到了 83.33 MHz**（见 create_bd.tcl）。
    //      ⇒ 按"速度优先"：**把余量留给时序，选 96 块的 RGB565。**
    //
    //   【代价是什么】输入先量化到 5/6/5（红蓝 32 级、绿 64 级）再插值。
    //      对"拍摄文档"这个场景可接受（文档以低饱和度为主），
    //      而且输出仍是 888（插值在 8 位域做，比在 5 位域做更细腻）。
    //      ⚠️ **PS 侧的逐位定点模型必须做同样的量化**，否则逐字节一致的判据会失效。
    //
    //   ⚠️ 展开用的是**位复制**（`{r5, r5[4:2]}` 而不是 `{r5, 3'b0}`）：
    //      位复制让 63→255、0→0 线性铺满，而补零只能到 248（最大值变暗）。
    //      两者都是纯位拼接，**综合后是 0 个 LUT**（只是重新接线）。
    //========================================================================
    localparam integer LB_PIX_W = (NCH == 1) ? 8 : 16;   // 行缓存里每像素的位宽

    // ---- 行缓存像素（RGB565）→ 插值用的 NCH×8 位 ----
    function [NCH*8-1:0] lb_to_ch;
        input [LB_PIX_W-1:0] w;
        reg   [4:0] r5;
        reg   [5:0] g6;
        reg   [4:0] b5;
        begin
            if (NCH == 1) begin
                lb_to_ch = w;                       // 灰度：直通
            end else begin
                {r5, g6, b5} = w;
                lb_to_ch = {r5, r5[4:2], g6, g6[5:4], b5, b5[4:2]};
            end
        end
    endfunction

    // ---- 接口像素（NCH×8 位）→ 行缓存像素（RGB565）----
    //   ⚠️ 用【截断】而不是四舍五入：截断没有进位边界（255+2 会溢出成 64），
    //      PS 侧复刻也只是 `>> 2`。⚠️ 但截断有 -0.5 LSB 的系统偏差，要在文档里写明。
    function [LB_PIX_W-1:0] ch_to_lb;
        input [NCH*8-1:0] c;
        begin
            if (NCH == 1) begin
                ch_to_lb = c;                       // 灰度：直通
            end else begin
                ch_to_lb = {c[23:19], c[15:10], c[7:3]};   // R[7:3] G[7:2] B[7:3]
            end
        end
    endfunction

    //------------------------------------------------------------------------
    // 6. 三级流水线（2026-09-28 ② 流水线化）
    //------------------------------------------------------------------------
    //   目标：把每像素从 11.99 拍降到 ~4 拍。
    //   ⭐ 账怎么算的：拆开原来的串行状态表发现 —— BRAM 读口只用满 10 拍里的 4 拍，
    //      其余 6 拍（取坐标/钳位/插值/输出）根本不碰读口却串行占着整条通路。
    //
    //        A 坐标+钳位 ──► B 读 4 邻域 ──► C 插值+输出 ──► 像素
    //          ~2 拍            4 拍            ~4 拍
    //
    //   稳态吞吐 = max(2, 4, 4) = **4 拍**（受单读口 BRAM 限制，是硬下限）。
    //
    //   ⚠️⚠️ 三个 stall 源（风险全在这里）：
    //     · coord_valid 低（坐标 FIFO 空）→ 只挡 A
    //     · rows_written 不够（要读的行还没写完）→ 挡 B（A 可以继续）
    //     · out_ready 低（DMA 没接收）→ 挡 C → 反压 B → 反压 A
    //   ⚠️ 每级都必须【先把自己的输入锁存下来】再干活，否则下一级会踩上一级 ✗
    //      —— 具体就是 B 要 latch 一份 b_* 地址/权重，C 要等 B 读完才允许 B 重写 4 元组。
    //
    //   ⚠️ 流控 y_lo_cur 仍按【A 级自己维护的输出位置计数 av_u/av_v】更新，
    //      与原来在 S_CLAMP 里用 out_u/out_v 更新**语义完全一致**
    //      （原来也是"提前 8 拍算"，现在提前 ~4 拍，只会更保守）。
    //------------------------------------------------------------------------

    // ---- A 级：取坐标 + 钳位 ----
    localparam [1:0] A_IDLE = 2'd0, A_RL = 2'd1, A_WAIT = 2'd2, A_CLAMP = 2'd3;
    reg  [1:0]          a_state;
    reg                 a_valid;        // A 的结果（y0_r..fy_r）待 B 取
    reg  [15:0]         av_u;           // A 级维护的输出位置（= coord_gen.row_v 与 sof/last 的口径）
    reg  [ROW_AW-1:0]   av_v;

    // ---- B 级：读 4 邻域 ----
    localparam [2:0] B_IDLE = 3'd0,
                     B_RD0 = 3'd1, B_RD1 = 3'd2, B_RD2 = 3'd3, B_RD3 = 3'd4,
                     B_HOLD = 3'd5;     // 4 元组已备好，等 C 取（或等 C 空出来）
    reg  [2:0]          b_state;
    reg  [ROW_AW-1:0]   b_y0, b_y1;     // ⚠️ B 自己锁一份地址/权重：
    reg  [COL_AW-1:0]   b_x0, b_x1;     //    不锁的话 A 下一拍就把 y0_r.. 覆盖了 ✗
    reg  [15:0]         b_fx, b_fy;
    //   ⭐ 2 体分体：在 b_latch 那一拍就把"偶数列的那个"和"奇数列的那个"选好，
    //      寄存器输出直接进 BRAM 地址口 —— 地址路上没有任何 mux/比较器。
    reg  [COL_AW-1:0]   b_col_even, b_col_odd;

    // ---- C 级：插值 + 输出 ----
    localparam [2:0] C_IDLE = 3'd0, C_FEED = 3'd1, C_W1 = 3'd2, C_W2 = 3'd3, C_OUT = 3'd4;
    reg  [2:0]          c_state;
    //   ⭐ 2026-10-22：C 不再自己锁一份 4 元组 —— 改成在 c_take 那一拍就把
    //      B 的 p00_r.. 直接喂给双线性（双线性自己在同一个沿抓进第 1 级）。
    //      原来的"混了下一个像素的邻居"风险由双线性的输入寄存器挡掉。

    reg  [ROW_AW-1:0]   out_v;          // 输出位置（sof/last 与 C 级口径）
    reg  [15:0]         out_u;
    reg                 b_rdy;          // B 的 4 元组就绪、待 C 取

    //   ⚠️ 下面这条是老状态机的残留说明，保留以解释为什么 A 要等 coord_valid：
    //      coord_gen 的输出比 row_load 晚 2 拍（累加器 1 拍 + 输出寄存 1 拍）。


    //========================================================================
    // 1. 输入侧：写行缓存
    //========================================================================
    reg  [ROW_AW-1:0]   wr_row;
    reg  [15:0]         wr_col;
    reg                 in_eof_r;

    reg  [ROW_AW-1:0]   y_lo_cur;       // 当前输出行仍需的最小输入行（流控用）
    reg  [ROW_AW-1:0]   y_row_last;     // 上一输出行【最后一个像素】的 y0_w（行首保守下界用）
    reg                 y_row_last_v;   // 是否已有"上一行"（第 0 行没有）
    reg                 frame_seen;     // 本帧已产出完毕 → 输入要能继续排空（见 §7）
    reg                 frame_req;      // ⭐ 帧门：本帧输出还没做完（见 §7b）
    //   ⭐ frame_started：从最近一次【帧首】以来，A 还没开过工。
    //      帧首置 1、A 一开工清 0 —— 帧末那段窗口里恒为 0，于是 A 不会
    //      "跑过帧末再多锁存一行"（见 A_IDLE 里的长注释）。
    //   ⚠️ 声明必须在这里（A_IDLE 用到它）—— 本项目已踩过 6 次
    //      "declaration after use"（iverilog: Unable to bind wire/reg/memory）。
    reg                 frame_started;

    //   ⭐ fs_set = "本帧输出的最后一个像素被收下了" —— 帧门的关闸条件
    //   ⚠️ 必须声明在 A/B/C 三个块【之前】（本项目第六次踩 declaration after use）
    wire fs_set = (c_state == C_OUT) && out_ready
                  && (out_u == cfg_w_out - 16'd1)
                  && (out_v == cfg_h_out - 16'd1);
    wire [ROW_AW-1:0]   rows_written;
    //   ⚠️ 必须声明在 rows_written 之后（本项目第七次踩 declaration after use）
    wire                arow_go = (a_state == A_IDLE) && !a_valid && frame_req
                                  && frame_started && (rows_written > ROW0);

    // 行缓存读口（提前声明：u_lb 例化与 §3 组合块要用）
    //   ⭐ 2026-10-22：改成 2 个体口（偶数列 / 奇数列），一行两列一拍读完
    reg                 rd_en;
    reg  [ROW_AW-1:0]   rd_row_e, rd_row_o;
    reg  [15:0]         rd_col_e, rd_col_o;
    wire [LB_PIX_W-1:0] rd_data_e, rd_data_o;
    wire                rd_valid;

    // 锁存并钳位后的四邻域地址与权重（提前声明：§3 读口组合块要用）
    reg  [ROW_AW-1:0]   y0_r, y1_r;
    reg  [COL_AW-1:0]   x0_r, x1_r;
    reg  [15:0]         fx_r, fy_r;

    wire                wr_fire = in_valid & in_ready;

    // ⭐ 本拍写的是本行最后一列 —— 行缓存靠它把"整行写完"记进 rows_written。
    //    ⚠️ 不能省：少了它行缓存会在本行【第一个】像素就把行数 +1，
    //       上层提前以为该行到齐 → 读到只写了一半的行。
    //       现象 = 只有第 0 行部分像素错（板上实测最大 57 灰阶）。详见 line_buf.v。
    wire                wr_last = (wr_col == cfg_w_in - 16'd1);

    line_buf #(
        //   ⚠️ 行缓存里是 LB_PIX_W（灰度 8 / 彩色 16=RGB565），不是接口的 PIX_W
        .PIX_W(LB_PIX_W), .W_ACTIVE(MAX_W), .ROWS(ROWS), .ROW_AW(ROW_AW)
    ) u_lb (
        .clk(clk), .rst_n(rst_n),
        .wr_en(wr_fire),
        .wr_row(wr_row), .wr_col(wr_col), .wr_data(ch_to_lb(in_data)),
        .wr_last(wr_last),
        .frame_start(wr_fire & in_sof),   // ⭐ 帧首脉冲（帧门的一部分）
        .rd_en(rd_en),
        .rd_row_e(rd_row_e), .rd_row_o(rd_row_o),
        .rd_col_e(rd_col_e), .rd_col_o(rd_col_o),
        .rd_data_e(rd_data_e), .rd_data_o(rd_data_o),
        .rd_valid(rd_valid),
        .rows_written(rows_written)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            wr_row   <= ROW0;
            wr_col   <= 16'd0;
            in_eof_r <= 1'b0;
        end else if (wr_fire) begin
            in_eof_r <= in_eof;
            if (in_sof) begin
                wr_row <= ROW0;
                wr_col <= 16'd1;
            end else if (wr_col == cfg_w_in - 16'd1) begin
                wr_col <= 16'd0;
                wr_row <= wr_row + 1'b1;
            end else begin
                wr_col <= wr_col + 1'b1;
            end
        end
    end

    //========================================================================
    // 2. 坐标发生器
    //------------------------------------------------------------------------
    //   ⚠️ row_load / advance 必须【组合】驱动（由 state 直接决定），
    //      不能用寄存输出！寄存会让它们比状态晚一拍，坐标整体滞后一个像素
    //      （踩过的坑：表现为输出图与黄金参考整体错位一格）。
    //========================================================================
    wire                cg_row_load;
    wire                cg_advance;
    wire signed [31:0]  x_q, y_q, d_q;
    wire                cg_divz, cg_ovf;
    // ⚠️ coord_valid 现在是【电平】（coord_gen 内部结果 FIFO 非空），
    //    要配 coord_ready 握手，否则 FIFO 会每拍弹出、远快于本 FSM 消耗。
    wire                coord_valid;
    wire                coord_ready;

    coord_gen #(
        .NDIV(16), .FIFO_DEPTH(32),
        .FRAC_BITS(FRAC_BITS), .NORM_SCALE(NORM_SCALE), .ACC_W(ACC_W)
    ) u_cg (
        .clk(clk), .rst_n(rst_n),
        .a11(a11), .a12(a12), .a13(a13), .a21(a21), .a22(a22), .a23(a23),
        .a31(a31), .a32(a32),
        .row_load(cg_row_load), .row_v(av_v),   // ⚠️ 必须是【A 级】的行号！
                                               //    原来接 out_v（C 级）在流水化后是错的：
                                               //    A 超前 C 好几个像素，行首 row_load 会用错行播种 ✗
        .cfg_w_out(cfg_w_out),          // ⭐ 递推不能越过行尾
        .coord_ready(coord_ready),      // ⭐ 握手：本 FSM 在 S_PREP 时才是"要取"
        .x_q(x_q), .y_q(y_q), .d_q(d_q),
        .coord_valid(coord_valid),
        .div_by_zero(cg_divz), .out_overflow(cg_ovf)
    );

    //========================================================================
    // 3. 行缓存读口
    //========================================================================
    //   ---- 级间握手（⚠️ 必须声明在下面两个 always 块【之前】----
    //        踩过两次 "declaration after use"：iverilog 报
    //        "Unable to bind wire/reg/memory ... Check for declaration after use"）
    //   b_take : B 把 A 的结果（y0_r..fy_r）取走 → A 的寄存器即刻可用
    //   c_take : C 把 B 的 4 元组（p00_r..p11_r）取走 → b_rdy 清掉
    //   ⚠️ 两个条件缺一个都会错像素：
    //        · B 取走前 A 不能覆盖（否则 B 读到错地址）
    //        · C 取走前 B 不能重写 4 元组（否则 C 插值用的是下一个像素的邻居）
    wire b_rows_ok = (rows_written > y1_r);   // = 老版本 S_CLAMP 里的 row_ok
    //   ⚠️⚠️ frame_req 必须并进 b_start（2026-09-29 帧门第三半，上板+仿真都验到）：
    //      只把 A 停在 A_IDLE 是【不够】的 —— A 已经产出的结果还在流水线里，
    //      B/C 会继续把它们吐出去。而 out_v/out_u 停在帧末不归零 ⇒
    //      **往后每一个吐出去的像素都被判成"帧末"** ⇒ 带着 tlast 的多余 beat。
    //      实测：仿真里有 54 个、板上有 5 个（S2MM 的输入 FIFO 吞几个就停了）。
    //      这些 beat 落到下一个传输上，S2MM 收到第一个就判"包结束" ⇒ 挂死。
    //      ⇒ 帧门必须同时管住 A / B / C 三级。
    wire b_start   = a_valid && b_rows_ok && frame_req;
    //   ⚠️ 同上：C 也要受帧门管 —— 帧末关闸后不再取新的 4 元组
    wire c_take    = b_rdy && (c_state == C_IDLE) && frame_req;
    //   ⚠️⚠️ b_rows_ok 必须并进"能不能开读"里 —— 否则会【吞像素】：
    //      行没到齐时 B 不启动，但清除 a_valid 的那句照样执行
    //      ⇒ 这个像素被丢掉、而 B 从来没读过它 ⇒ 输出错位 + A 一路跑飞
    //      （实测：A 已到 av_u=25 时 C 才 u=5）
    wire b_take = b_start && !b_rdy && (b_state == B_IDLE);
    //   ⭐ b_chain：C 取走 4 元组的【同一拍】顺手把下一个像素的地址锁进来，
    //      省掉"回 B_IDLE 再出发"那一拍。没有它 B 每像素要 7 拍而不是 6 拍。
    wire b_chain = b_start && b_rdy && (b_state == B_HOLD) && c_take;
    wire b_latch = b_take || b_chain;         // 本拍把 A 的结果锁进 b_*
    //   ⚠️⚠️ a_free 也必须带 frame_req（2026-09-29 帧门第四半，仿真里挂死才发现）：
    //      只挡 b_start/c_take 是【不够】的 —— 帧末 a_valid 被丢掉后，
    //      `a_free = !a_valid || b_latch` 里的 `!a_valid` 又成立 ⇒
    //      **A 会再跑一次 A_CLAMP，产出一个永远没人取的结果** ⇒ a_valid 恒 1
    //      ⇒ pipe_busy 恒真 ⇒ in_ready 恒 0 ⇒ 下一帧的输入根本进不来（死锁）。
    //      带上 frame_req 之后，关闸期间 A 既不去 A_CLAMP、也不弹坐标 ✓
    wire a_free  = (!a_valid || b_latch) && frame_req;

    //   ⚠️ 必须【组合】驱动：BRAM 在时钟沿采样 rd_en/rd_addr，数据下一拍才有效。
    //      若把 rd_en/地址做成寄存输出，地址会比预期晚一拍呈现，
    //      四个邻域就会整体错位（踩过的坑：表现为插值结果取到隔壁像素）。
    //
    //   ⚠️⚠️ 两个坑叠在这一个 always 块里，都要守着：
    //
    //   ① 【相位】地址给出的那拍 ≠ 抓数据的那拍，必须错开整整一个状态。
    //      第一版把"在 B_RDk 给地址"和"在 B_RDk 抓数据"写进了同一个状态，
    //      结果四个槽位整体平移一格（p10_r←真p00、p01_r←真p10、p11_r←真p01，
    //      而 p00_r←上一像素的 p11）。**实测混淆矩阵 76800/76800 全中** ——
    //      是 100% 确定性的平移，不是随机错。
    //      （首像素读到 0 就是线索：那是 rd_data 的复位值，还没有"上一个像素"）
    //      ⇒ 正确相位 = 老串行版 S_RD0→S_RD1→S_RD2→S_RD3→S_BIL 那套：
    //            第 k 拍给地址，第 k+1 拍抓数据。
    //
    //   ② 【时序】地址通路里**不许有比较器**。
    //      第二版改成"在 B_IDLE 用 A 的活输出 y0_r/x0_r 给地址"，相位对了，
    //      但把 b_rows_ok（12 位比较器 = 两级 CARRY4 ≈ 1.4 ns）串进了
    //      读口地址通路 —— 那条路本身要过 DSP 乘法器（rd_slot×W_ACTIVE）
    //      再到 BRAM 的 ENBWREN，本来就紧。
    //      实测 WNS 从 +0.601 掉到 **-0.222**，TNS -0.460，
    //      最差的 12 条路径【全部】落在 `u_lb/mem_reg_*/ENBWREN` 上 ⇒ 直接不出比特流。
    //      ⇒ 所以：**"能不能开读"只在状态转移/锁存 b_* 那一步用，地址永远由
    //        已经寄存好的 b_* 给出。** 比较器的结果进的是寄存器，不进地址。
    //========================================================================
    always @(*) begin
        //   rd_en=0 时地址无所谓，给个默认值（保持四个都不悬空）
        rd_en    = 1'b0;
        rd_row_e = b_y0; rd_col_e = {16'd0} | b_col_even;
        rd_row_o = b_y0; rd_col_o = {16'd0} | b_col_odd;
        //   ⭐ 地址【只依赖寄存值】(b_state / b_*)。别在这里引入任何比较器。
        //   2 体：每拍两个体各读一个 ⇒ 一行两列 1 拍、两行 2 拍。
        case (b_state)
        B_RD0: begin
            rd_en = 1'b1;
            rd_row_e = b_y0; rd_col_e = {16'd0} | b_col_even;
            rd_row_o = b_y0; rd_col_o = {16'd0} | b_col_odd;
        end
        B_RD1: begin
            rd_en = 1'b1;
            rd_row_e = b_y1; rd_col_e = {16'd0} | b_col_even;
            rd_row_o = b_y1; rd_col_o = {16'd0} | b_col_odd;
        end
        default: ;
        endcase
    end

    //========================================================================
    // 4. 坐标 → 钳位四邻域
    //------------------------------------------------------------------------
    //   整数部分 xf = x_q >>> 16
    //       x_q < 0         → x0 = 0,       fx = 0   （左越界钳位）
    //       xf >= W_in-1    → x0 = W_in-2,  fx = 0   （右越界钳位）
    //       否则             → x0 = xf,      fx = x_q[15:0]
    //   y 同理。x1 = x0+1，y1 = y0+1 恒成立。
    //
    //   ⚠️ 实测表明大量输出行的源会落在输入图外（tilt60 有 357/720 行），
    //      所以钳位不是可选项，是必需的。
    //========================================================================
    reg  signed [31:0]  lat_x, lat_y;          // 锁存的坐标
    wire signed [31:0]  wid_m1 = cfg_w_in - 32'sd1;
    wire signed [31:0]  hei_m1 = cfg_h_in - 32'sd1;
    wire signed [31:0]  wid_m2 = cfg_w_in - 32'sd2;
    wire signed [31:0]  hei_m2 = cfg_h_in - 32'sd2;

    wire signed [31:0]  xf_i = lat_x >>> FRAC_BITS;
    wire signed [31:0]  yf_i = lat_y >>> FRAC_BITS;

    // ⚠️ 越界判据是 xf >= W_in-1（不是 W_in-2）：
    //    当 xf = W_in-2 且小数非零时（如 x=62.5），像素 62 和 63 都有效，
    //    必须正常插值。只有 xf >= W_in-1 时 x1 才会越界。
    wire x_neg  = (lat_x < 32'sd0);
    wire y_neg  = (lat_y < 32'sd0);
    wire x_high = (xf_i >= wid_m1);
    wire y_high = (yf_i >= hei_m1);

    wire [COL_AW-1:0] x0_w = x_neg  ? {COL_AW{1'b0}}
                            : x_high ? wid_m2[COL_AW-1:0]
                            :          xf_i[COL_AW-1:0];
    wire [ROW_AW-1:0] y0_w = y_neg  ? ROW0
                            : y_high ? hei_m2[ROW_AW-1:0]
                            :          yf_i[ROW_AW-1:0];

    // 钳位时权重取"最靠近边界那一个像素"：
    //   左越界 → fx=0      （采 x=0）
    //   右越界 → fx=65535  （采 x=W_in-1）
    wire [15:0] fx_w = x_neg  ? 16'd0
                     : x_high ? 16'hFFFF
                     :          lat_x[15:0];
    wire [15:0] fy_w = y_neg  ? 16'd0
                     : y_high ? 16'hFFFF
                     :          lat_y[15:0];

    wire [ROW_AW-1:0] y1_w = y0_w + 1'b1;

    // 这一像素用到的最大输入行是否已到齐
    wire row_ok = (rows_written > y1_w);

    //========================================================================
    // 5. 双线性插值
    //========================================================================
    reg  [LB_PIX_W-1:0] p00_r, p10_r, p01_r, p11_r;
    //   ⭐ 2026-10-22：bil_valid 改成【组合】= c_take，省掉 C_IDLE/C_FEED 两级中的一级
    wire                bil_valid = c_take;
    wire [PIX_W-1:0]    bil_pixel;
    wire                bil_valid_out;

    //   ⭐ 彩色时每通道 8 位、三通道并行（bilinear 内部 generate 复制三套通路，
    //      **不增加流水级数** —— 延迟仍是 2 拍，见 bilinear.v 文件头的取舍论证）。
    //   ⚠️ 喂进去的是【展开后】的 NCH×8 位，不是行缓存里的 RGB565 ——
    //      插值必须在 8 位域做，否则 5 位域的舍入误差会被放大成色带。
    //   ⚠️ lb_to_ch 是纯位拼接 ⇒ 0 个 LUT、0 级逻辑 ⇒ **不进关键路径**。
    bilinear #(.PIX_W(8), .NCH(NCH)) u_bil (
        .clk(clk), .rst_n(rst_n),
        //   ⭐ 2026-10-22 C 级合并：直接吃 B 级的 p00_r.. / b_fx，在 c_take 那一拍喂。
        //      双线性在 valid_in 那一拍的时钟沿把输入抓进自己的第 1 级寄存器，
        //      而 B 是在【同一个沿】才更新 p00_r（非阻塞）⇒ 抓到的正是本像素 ✓
        .p00(lb_to_ch(p00_r)), .p10(lb_to_ch(p10_r)),
        .p01(lb_to_ch(p01_r)), .p11(lb_to_ch(p11_r)),
        .fx(b_fx), .fy(b_fy),
        .valid_in(bil_valid),
        .pixel(bil_pixel), .valid_out(bil_valid_out)
    );

    //========================================================================
    // 6. 状态机（状态编码与变量声明已在文件开头集中给出）
    //========================================================================

    // ---- 坐标发生器的控制（改由 A 级驱动）----
    //   ⚠️ 老版本 row_load 在 S_RINIT 发、coord_ready 在 S_PREP 拉高；
    //      流水化后这两件事都归 A 级 —— 语义不变，只是换了个"人"来举手：
    //        · row_load  = A 级走到 A_RL 那一拍（1 拍脉冲）
    //        · coord_ready = A 级停在 A_WAIT（= 我真的要取坐标）
    // ---- 级间握手（⚠️ 声明见文件上方 §3 之前 —— 读口组合块要用 b_take）----
    assign cg_row_load = (a_state == A_RL);
    //   ⚠️⚠️ 必须带 a_free！只写 (a_state == A_WAIT) 是错的：
    //      A_WAIT **可能停多拍**（等 B 把上一个结果取走），而 coord_gen 只要看到
    //      coord_valid && coord_ready 就弹出队首 —— 停几拍就弹几个 ⇒ **坐标被沿途丢弃** ✗
    //      症状：①输出值错位 ②行内需要的 W 个坐标凑不齐 → A 永远等 coord_valid → 死锁。
    //      带上 a_free 后，只在"这一拍确定会锁存"时弹出 ✓
    assign coord_ready = (a_state == A_WAIT) && a_free;

    // ---- 输出握手（组合，AXI-Stream 语义，与老版本一致）----
    assign out_valid = (c_state == C_OUT);
    assign out_data  = bil_pixel;
    assign out_sof   = (c_state == C_OUT) && (out_v == ROW0) && (out_u == 16'd0);
    assign out_last  = (c_state == C_OUT) && (out_v == cfg_h_out - 16'd1)
                                         && (out_u == cfg_w_out - 16'd1);

    //========================================================================
    // 6b. 级间握手
    //------------------------------------------------------------------------
    //   b_take : B 把 A 的结果（y0_r..fy_r）取走 → A 的寄存器即刻可用
    //   c_take : C 把 B 的 4 元组（p00_r..p11_r）取走 → b_rdy 清掉
    //   ⚠️ 两个条件缺一个都会错像素：
    //        · B 取走前 A 不能覆盖（否则 B 读到错地址）
    //        · C 取走前 B 不能重写 4 元组（否则 C 插值用的是下一个像素的邻居）
    //========================================================================
    //========================================================================
    // 6c. A 级：取坐标 + 钳位（每像素 ~2 拍）
    //========================================================================
    always @(posedge clk) begin
        if (!rst_n) begin
            a_state <= A_IDLE;
            a_valid <= 1'b0;
            av_u    <= 16'd0;
            av_v    <= ROW0;
            lat_x   <= 32'sd0;
            lat_y   <= 32'sd0;
            //   ⚠️⚠️ 这三条【必须】在复位里初始化！
            //      漏掉时它们保持 X → lim_ext 变 X → in_ready 变 X
            //      → 输入握手永远完不成 → rows_written 恒 0 → 整机死锁。
            //      （老版本这些是在 FSM 的复位分支里初始化的，流水化搬过来时漏了）
            y_lo_cur     <= ROW0;
            y_row_last   <= ROW0;
            y_row_last_v <= 1'b0;
            //   ⚠️ frame_seen 不在这里清！它的复位在 §7 的专属 always 块里 ——
            //      原因见那里：它被 A 级和 C 级【两边】写，写进两个块就是多驱动。
        end else begin
            case (a_state)
            A_IDLE: begin
                //   ⭐ A_IDLE 停在【帧与帧之间】，所以这里的清零就是"每帧状态清零"。
                //   ⚠️⚠️ 全部清零都必须在 `!a_valid` 之后 —— 帧末 A 是先回 A_IDLE、
                //      再由 B 把最后一个结果取走的（b_latch 那条通路清 a_valid）。
                //      抢在它前面清 av_u/av_v 会让"最后那个像素"算错位置，
                //      整帧就整体错位（实测：帧1 vs 帧2 全错）。
                if (!a_valid) begin
                    av_u    <= 16'd0;
                    av_v    <= ROW0;
                    y_row_last_v <= 1'b0;   // 新的一帧：还没有上一行
                    y_lo_cur     <= ROW0;   // 流控下界回到 0（否则放输入跑过头）
                    y_row_last   <= ROW0;
                    //   ⚠️⚠️ 必须等 frame_req —— 这就是"帧门"：
                    //      光看 rows_written>0 的话，帧末行缓存里还留着上一帧的行，
                    //      核会不等新输入就自己重跑一遍（多发 beat + 过期 tlast）。
                    //   ⚠️⚠️⚠️ 必须带 `frame_started`（2026-09-30 修）——
                    //      不加的话，帧末 A 会**多跑一行**，用【旧参数】锁存
                    //      下一帧第 0 行的行初值 ⇒ 下一帧第 0 行全错。
                    //
                    //   机制（本地 TB 逐次打印 row_load 定案的）：
                    //      A 判"帧末"比 C 级收下最后像素**早好几拍**（A 领先 C），
                    //      A 一回 A_IDLE 就满足 `frame_req && rows_written > ROW0`
                    //      ⇒ **立刻又跳 A_RL，多一次 `row_load`**
                    //      ⇒ 用当时的 a13/a23（**上一帧的参数**）锁存 XN0。
                    //
                    //   ⚠️ 试过用 `!frame_seen` —— **无效**：`frame_seen` 是在
                    //      `fs_set`（C 级收下最后像素）时置位的，而那时 A 早就
                    //      进了 A_IDLE ✗。**要挡的是"A 跑在 C 前面"这件事本身。**
                    //   ⚠️ 也试过把开闸（frame_req）推迟一拍 —— 同样无效，
                    //      因为这里卡的不是"开闸时刻"，是"A 已经跑到帧末了"。
                    //
                    //   为什么以前发现不了：
                    //     · 多出来的那一行**不产出任何 beat**（闸关着）——
                    //       所以 `axis_soft_reset_tb` 的"帧间零多余 beat"检查抓不到；
                    //     · 单张模式每张图重载 overlay ⇒ 顺带硬复位 ⇒ 更碰不上；
                    //     · 上一张与下一张**配置相同**时，这次多余的锁存用的是
                    //       **相同参数** ⇒ 完全无害（TB 里帧 3 就是这样，全对）。
                    //
                    //   `frame_started` 的语义：**"从最近一次帧首以来，A 还没开过工"**。
                    //     帧首置 1、A 一开工就清 0 ⇒ 帧末那段窗口里它恒为 0
                    //     ⇒ A 老实停在 A_IDLE，等下一帧的帧首 ✓
                    //   实测（multiframe_cfg_tb）：加之前 54/2240 错，加之后 0。
                    if (frame_req && frame_started && rows_written > ROW0) a_state <= A_RL;
                end
                //   ⚠️ 这里不写 a_valid <= 0：它的清理由 b_latch 统一负责，
                //      否则会清掉"还没被 B 取走"的那一个结果。
            end
            A_RL: a_state <= A_WAIT;        // row_load 由上面的组合 assign 给出
            A_WAIT: begin
                //   ⚠️ 必须等 coord_valid（顺序除法器要几十拍才出结果），
                //      且要等自己的输出寄存器空出来
                if (coord_valid && a_free) begin
                    lat_x   <= x_q;
                    lat_y   <= y_q;
                    a_state <= A_CLAMP;
                end
            end
            A_CLAMP: begin
                // 钳位结果进 A 的输出寄存器（B 会原样取走）
                x0_r <= x0_w;
                x1_r <= x0_w + 1'b1;
                y0_r <= y0_w;
                y1_r <= y1_w;
                fx_r <= fx_w;
                fy_r <= fy_w;
                a_valid <= 1'b1;

                //------------------------------------------------------------
                // 流控下界（与老版本 S_CLAMP 里那段语义完全一致，
                //   只是位置计数改用 A 级自己的 av_u/av_v）
                //   规则：行首取 min(y(u=0), 上一行末像素的 y)；行内继续取 min
                //   见 §4/§7 与 report/llm_log 里的两次踩坑记录
                //------------------------------------------------------------
                if (av_u == 16'd0)
                    y_lo_cur <= (!y_row_last_v || (y0_w < y_row_last))
                                ? y0_w : y_row_last;
                else if (y0_w < y_lo_cur)
                    y_lo_cur <= y0_w;

                if (av_u == cfg_w_out - 16'd1) begin
                    y_row_last   <= y0_w;
                    y_row_last_v <= 1'b1;
                end

                // 推进 A 的位置计数
                //   ⚠️⚠️ 2026-09-29 帧门配套修：**整帧跑完必须回 A_IDLE**。
                //      原来行末一律跳 A_RL（开始下一行），跑完最后一行又跳 A_RL
                //      从头再来 ⇒ **A 永远进不了 A_IDLE** ⇒ 于是
                //        · A_IDLE 里那套"每帧状态清零"从来没执行过
                //        · frame_req 这道门也从来没关上（核一直自己重跑）
                //      实测（two_frame_tb 探针）：帧2 的帧首时刻 a_state=2(A_WAIT)、
                //      rows_written=40、out_v/out_u 还停在帧末 ⇒ 整帧错位。
                if (av_u == cfg_w_out - 16'd1) begin
                    av_u <= 16'd0;
                    if (av_v == cfg_h_out - 16'd1) begin
                        // 最后一行也跑完了 ⇒ 回 A_IDLE 停下，等下一帧的 frame_req
                        //   ⚠️ 这里【不能】清 a_valid —— 最后这个像素的结果刚在上一句
                        //      置 1，此时清掉就是把整帧最后一个像素丢了（而且后面会
                        //      整体错位一格）。它的清理由 b_latch 那条通路负责。
                        a_state <= A_IDLE;
                    end else begin
                        av_v    <= av_v + 1'b1;
                        a_state <= A_RL;        // 行末 → 下一行要先重新 row_load
                    end
                end else begin
                    av_u    <= av_u + 1'b1;
                    a_state <= A_WAIT;
                end
            end
            default: a_state <= A_IDLE;
            endcase

            //   A 的结果被 B 取走 → 清 a_valid。
            //   ⚠️ 放在 case 之后：同一拍 A_CLAMP 新产出的值不能被清掉
            //     （A_CLAMP 那拍 a_valid 本来是 0，b_latch 不可能同时为真）
            //   ⚠️ 用 b_latch 而不是 b_take：B_HOLD 交接时（b_chain）也算取走，
            //      漏了它 A 会以为结果没被取走而卡在 A_WAIT ⇒ 死锁。
            if (b_latch) a_valid <= 1'b0;

            //   ⭐⭐ 帧末把【多余的残留结果】直接丢掉（2026-09-29 帧门第三半）
            //   ⚠️ 为什么必须丢、而且必须在这里丢：
            //      帧门关闸后 b_latch 不再发生 ⇒ a_valid 会【永远保持 1】
            //      ⇒ pipe_busy 恒真 ⇒ in_ready 恒 0 ⇒ **下一帧的输入根本进不来，死锁**
            //      （实测：加了 C 的帧门之后仿真直接挂死）
            //      而这个结果本来就是对"帧末之后的像素"算的，本来就该丢 ✓
            //   ⚠️ 放在最后：与 A_CLAMP 同拍时以这条为准（帧末优先）。
            if (fs_set) a_valid <= 1'b0;
        end
    end

    //========================================================================
    // 6d. B 级：读 4 邻域（每像素 4 拍，是整条流水线的瓶颈）
    //========================================================================
    always @(posedge clk) begin
        if (!rst_n) begin
            b_state <= B_IDLE;
            b_rdy   <= 1'b0;
            b_y0 <= ROW0; b_y1 <= ROW0;
            b_x0 <= {COL_AW{1'b0}}; b_x1 <= {COL_AW{1'b0}};
            b_fx <= 16'd0; b_fy <= 16'd0;
            p00_r <= {LB_PIX_W{1'b0}}; p10_r <= {LB_PIX_W{1'b0}};
            p01_r <= {LB_PIX_W{1'b0}}; p11_r <= {LB_PIX_W{1'b0}};
        end else begin
            if (c_take) b_rdy <= 1'b0;
            //   ⭐ 帧末丢掉多余的 4 元组（与 A 的 a_valid 同理）——
            //      它属于"帧末之后的像素"，不丢会一直占着 b_rdy ⇒ 同样卡住下一帧。
            if (fs_set) b_rdy <= 1'b0;

            //   ⭐ 把 A 的结果锁一份到 b_*（【两个入口】：B_IDLE 空闲时开新像素、
            //      B_HOLD 交接时续上下一个）。
            //      一定要锁：否则 A 下一拍就去算下一个像素、把 y0_r.. 覆盖掉。
            //      而且【只能在这里用比较器 b_rows_ok】—— 见 §3 的时序说明。
            if (b_latch) begin
                b_y0 <= y0_r; b_y1 <= y1_r;
                b_x0 <= x0_r; b_x1 <= x1_r;
                b_fx <= fx_r; b_fy <= fy_r;
                //   ⭐ 2 体：把偶数列 / 奇数列各选出来（此时选，不进地址路）
                b_col_even <= x0_r[0] ? x1_r : x0_r;
                b_col_odd  <= x0_r[0] ? x0_r : x1_r;
            end

            case (b_state)
            B_IDLE: begin
                //   ⚠️ 必须同时满足两条才开工：
                //        ① 有活干（a_valid）② 要读的行已写好（b_rows_ok）
                //      只满足①就开工 → 读到没写完的行（老版本 S_CLAMP 的 row_ok 就是防这个）
                if (b_take) b_state <= B_RD0;
            end
            //   ⚠️⚠️ 抓数据比给地址【晚一个状态】（BRAM 同步读）：
            //        第 k 拍给地址 → 第 k+1 拍数据才有效 ⇒ 在第 k+1 拍抓。
            //      别写成"同一个状态里既给地址又抓数据"——那样四个槽位会整体平移一格。
            //   ⭐ 2026-10-22：2 体 ⇒ 一行两列同一拍读出，原来 RD0..RD3 四个状态只剩两个。
            //      B_RD0 给 (y0,偶) 和 (y0,奇) 的地址；B_RD1 抓它们、同时给 y1 的地址；
            //      B_HOLD 抓 y1 那一对。
            B_RD0: b_state <= B_RD1;                                    // 地址 y0 那一对
            B_RD1: begin                                                // 抓 y0 那一对；地址 y1 那一对
                       if (b_x0[0]) begin p10_r <= rd_data_e; p00_r <= rd_data_o; end
                       else         begin p00_r <= rd_data_e; p10_r <= rd_data_o; end
                       b_state <= B_HOLD;
                   end
            B_HOLD: begin
                if (!b_rdy) begin
                    // 抓 y1 那一对 → 4 元组齐 → 交给 C
                    if (b_x0[0]) begin p11_r <= rd_data_e; p01_r <= rd_data_o; end
                    else         begin p01_r <= rd_data_e; p11_r <= rd_data_o; end
                    b_rdy <= 1'b1;
                end else if (c_take) begin
                    // 交接完 —— 下一个能开就直接续上，否则回 B_IDLE 等
                    b_state <= b_chain ? B_RD0 : B_IDLE;
                end
            end
            default: b_state <= B_IDLE;
            endcase
        end
    end

    //========================================================================
    // 6e. C 级：插值 + 输出（每像素 ~4 拍）
    //------------------------------------------------------------------------
    //   ⚠️ 双线性是两级流水：bil_pixel 比 bil_valid 晚 2 拍
    //      ⇒ C_W1→C_OUT（2026-10-22 合并后只需等 1 拍）。改插值器级数必须同步改
    //========================================================================
    localparam [1:0] CD_IDLE = 2'd0, CD_DONE = 2'd1;   // 帧末多停一拍（匹配老版本 frame_done 宽度）
    reg  [1:0] c_done_state;

    always @(posedge clk) begin
        if (!rst_n) begin
            c_state <= C_IDLE;
            c_done_state <= CD_IDLE;
            out_v <= ROW0;
            out_u <= 16'd0;
            frame_done <= 1'b0;
        end else begin
            //   ⭐ 2026-10-22 C 级合并：c_take 那一拍就把 p00_r.. 喂给双线性
            //      （bil_valid = c_take，见上面的 wire），所以不再需要
            //      c_p*/c_fx 这套锁存，也不需要 C_FEED 这一拍。
            //      延迟链：c_take(N) → 双线性 2 级 → N+2 出结果 ⇒ C_W1 等 1 拍。
            case (c_state)
            C_IDLE:  if (c_take) c_state <= C_W1;
            C_W1:    c_state <= C_OUT;
            C_OUT: begin
                if (out_ready) begin
                    if (out_u == cfg_w_out - 16'd1) begin
                        if (out_v == cfg_h_out - 16'd1) begin
                            frame_done   <= 1'b1;
                            //   ⚠️ frame_seen 不在这里置位！见 §7 的专属 always 块 ——
                            //      它与 A 级的复位清 0 分属两块就是多驱动。
                            c_state      <= C_IDLE;
                            c_done_state <= CD_DONE;
                        end else begin
                            out_v   <= out_v + 1'b1;
                            out_u   <= 16'd0;
                            c_state <= C_IDLE;
                        end
                    end else begin
                        out_u   <= out_u + 1'b1;
                        c_state <= C_IDLE;
                    end
                end
            end
            default: c_state <= C_IDLE;
            endcase

            // 帧末清 frame_done（与老版本 S_OUT 置 1 → S_DONE → S_IDLE 清 0 等效）
            if (c_done_state == CD_DONE) begin
                frame_done   <= 1'b0;
                c_done_state <= CD_IDLE;
            end

            //   ⭐ 帧首把输出位置归零（帧门的一部分，2026-09-29）
            //   ⚠️ 为什么必须在这里清：帧末 out_v/out_u 停在 (H_out-1, W_out-1)，
            //      不清的话下一帧第一个像素就被判成"帧末 ⇒ tlast=1" ⇒ 输出流里
            //      到处是 tlast（这正是上板"多发 beat + 过期 tlast"的来源之一）。
            //   ⚠️ 放在最后：与上面 case 的赋值同拍时以这句为准（帧首优先）。
            if (wr_fire && in_sof) begin
                out_v <= ROW0;
                out_u <= 16'd0;
            end
        end
    end


    //========================================================================
    // 7. 流控：输入侧反压
    //------------------------------------------------------------------------
    //   写第 rows_written 行会覆盖第 (rows_written - ROWS) 行，
    //   所以必须保证  rows_written < y_lo_cur + ROWS。
    //
    //   ⚠️ 必须用加宽比较！直接写 (rows_written - y_lo_cur) < ROWS 会在
    //      y_lo_cur > rows_written 时回绕成大正数 —— 输入被永久堵死，
    //      而它正等着的那一行永远到不了 → 死锁。这是踩过的坑。
    //
    //   行首（S_RINIT）暂停输入，避免 y_lo_cur 还没更新就冲过头。
    //
    //------------------------------------------------------------------------
    //   ⚠️⚠️ 帧末必须让输入【排空】，否则上游 DMA 永久挂起（2026-09-27 上板踩的坑）
    //------------------------------------------------------------------------
    //   帧产出完毕后 FSM 回到 S_IDLE，而 S_IDLE 把 y_lo_cur 清零了 →
    //   in_ready 立刻变假 → **输入流被掐断**。
    //   如果此时输入图还没送完（rows_written < H_IN），上游永远等不到 tready：
    //     · 上板表现：DMA 挂死，而核的 STATUS 却是 busy=0 / stuck=0 / 帧计数=1
    //       （核早算完了，纯粹是"吃不进剩余的输入"）
    //     · 什么时候会踩：**最后一输出行的最小 y + ROWS < H_IN**
    //       实测 4 张样图：test-6/8/9 恰好能吃完 → 过；
    //       **test-7 差 10 行** → 挂。唯一吃不掉的那张就是唯一失败的那张。
    //   ⚠️ 这不只是某张图的问题：**视频阶段输入是连续流，必然踩**。
    //      流式架构的核必须能一直吃掉输入，否则上游必堵。
    //
    //   修法：加一个粘滞位 frame_seen。帧末置位后 in_ready 恒真（只吃不保护，
    //   因为此时没有任何行还需要保护）；下一帧的【第一个像素】(in_sof) 或复位时清零，
    //   流控随即恢复。
    //========================================================================
    wire [ROW_AW:0] wr_ext  = {1'b0, rows_written};
    wire [ROW_AW:0] lim_ext = {1'b0, y_lo_cur} + ROWS_EXT;

    //------------------------------------------------------------------------
    //   ⚠️⚠️ frame_seen 必须【独占一个 always 块】
    //------------------------------------------------------------------------
    //   它天然被两边写：复位清 0（原在 A 级块里）+ 帧末置 1（原在 C 级块里）。
    //   流水化把 FSM 拆成 A/B/C 三块后，这两个赋值落进了【两个不同的 always 块】
    //   ⇒ 综合报：
    //       CRITICAL WARNING: [Synth 8-6859] multi-driven net on pin Q
    //          1st driver 'frame_seen_reg__0/Q'   2nd driver 'GND'
    //       CRITICAL WARNING: [Synth 8-6858] ... constant driver has been
    //          preserved, other driver is ignored
    //   ⚠️ 保留的是 **GND 那一份** ⇒ frame_seen 被钉死在 0 ⇒ 帧末"输入排空"失效
    //      ⇒ 上游 DMA 拿不到 tready 而挂死（就是 test-7 那种挂法）。
    //
    //   ⚠️⚠️ 这个坑【仿真完全看不出来】：iverilog 对"两个块写同一个 reg"不报错，
    //      而两处的触发条件（复位 / 帧末）互斥、行为上永远不冲突 ⇒ 仿真一直"过"。
    //      只有综合日志会说话 —— **所以上板前必须扫一遍综合日志里的 multi-driven。**
    //
    //   修法：把全部赋值收进这一个块。优先级按原单块版本的语义：
    //        复位 > 帧末置位 > 下一帧首像素清零
    //        （原版本里 in_sof 那句写在 case 之前、帧末那句在 case 里，
    //          同拍时后者胜 —— 这里用 if-else 顺序显式表达）
    //------------------------------------------------------------------------

    always @(posedge clk) begin
        if (!rst_n)                 frame_seen <= 1'b0;
        else if (fs_set)            frame_seen <= 1'b1;   // 帧末（优先级高于下面）
        else if (wr_fire && in_sof) frame_seen <= 1'b0;   // 新一帧的第一个像素
    end

    //========================================================================
    // 7b. ⭐ 帧门（frame_req）—— 一帧输入只出一帧（2026-09-29）
    //---------------------------------------------------------------------------
    //   ⚠️⚠️ 修的是什么：**输入送完之后，核会自己空转重跑帧**。
    //      因为 A_IDLE 只看 `rows_written > 0`，帧末它在行缓存里看到"行早到齐了"
    //      → 不等新输入直接再跑一遍 ⇒ 往外发【超出 W_out×H_out 的额外像素】，
    //      而且这些额外像素带着过期的 tlast（out_v/out_u 停在帧末不动）。
    //
    //   上板实测的两种后果（同一个根因，两种表现）：
    //     · 不复位连跑：悬着的额外 beat 被【下一个传输】当成第一个字节吃掉
    //       ⇒ 传输能走完，但整条流被挪了 1 个像素（实测"1 / 538896 不一致"）
    //     · 帧间软复位：复位把 tvalid 从 1 直接撤到 0、**没有任何握手**
    //       ⇒ AXI-Stream 协议违例 ⇒ 互联里的 beat 状态被破坏
    //       ⇒ 新传输收到第 1 个字节就判"包结束"（S2MM Idle=1）⇒ 核永远等不到
    //         ready ⇒ **挂死**（MM2S transferred=0，帧计数=0）
    //
    //   ⭐ 修法：分开"输出侧的帧"和"输入侧的帧"
    //     · frame_req = 【输出侧】本帧还没产出完 —— 置位 in_sof、清除 fs_set
    //       ⇒ 输出一完 A 就停在 A_IDLE ⇒ **不再空转、不再多发一个 beat** ✓
    //     · 输入侧维持原样：frame_seen 让输入在输出完成后继续排空
    //       （2026-09-27 踩过的坑：不排空 ⇒ 上游 DMA 拿不到 tready ⇒ 挂死）
    //     ⇒ 两边都满足：不多发 beat，也不掐断输入 ✓
    //
    //   ⚠️ 为什么【不能】用复位来实现这件事（本项目的教训）：
    //      复位会撤销"已断言但未握手"的 tvalid —— 那是 AXI-Stream 协议违例，
    //      正是上面那条挂死的成因。**流式系统里状态清零要靠数据流自然驱动。**
    //========================================================================
    //   ⚠️⚠️⚠️ 帧首开闸必须【比 rows_written 清零晚一拍】（2026-09-30 修）
    //   ------------------------------------------------------------------
    //   现象（板上批量模式实测）：**第 2 张图起，输出的【第 0 行】全错** ——
    //     本地复现后 dump 出来，第 2 帧的第 0 行与【第 1 帧的第 0 行】逐字节相同。
    //     ⇒ 它读的是行缓存里**上一帧还没被覆盖的残留**。
    //
    //   根因：帧首那一拍，两件事【同时】生效 ——
    //       · `line_buf` 按 frame_start 清 `rows_written`
    //       · 这里把 `frame_req` 置 1（开闸）
    //     于是 A 级在 A_IDLE 里判 `frame_req && rows_written > ROW0` 时，
    //     看到的 `rows_written` **还是上一帧的值** ⇒ 以为"行早到齐了" ⇒
    //     不等新输入、直接开算 ⇒ 第 0 行用残留数据。
    //
    //   ⚠️ 为什么以前一直没暴露：**单张模式每张图重载 overlay = 顺带硬复位**，
    //      `rows_written` 从 0 开始 ⇒ 这个 race 从来碰不上。
    //      ⇒ **批量（overlay 只加载一次）和视频（连续帧）都会踩。**
    //
    //   ⚠️ 为什么现有 TB 也测不出来：`axis_soft_reset_tb` 连喂 3 帧但
    //     **配置与输入完全相同** ⇒ 残留"恰好就是该有的数据" ⇒ 每帧都巧合正确。
    //     复现需要用【不同的配置】跑第 2 帧 —— 见 `multiframe_cfg_tb.v`。
    //
    //   修法：把开闸推迟一拍（`sof_d`），那时 `rows_written` 已经是 0 ✓
    //        A 就会老老实实等新输入把行喂够，再开算。
    //========================================================================
    //   ⚠️ 2026-09-30 试过"把开闸推迟一拍（sof_d）"—— **验证无效**，已撤回。
    //      复现仍在（multiframe_cfg_tb 报 REPRODUCED，54/2240，只错第 0 行）。
    //      那次实验的副产品：确认了 `FS_SET` 每帧都正常触发、`rows_written`
    //      与 `av_v` 在帧首都已归零 —— 所以"开闸早一拍"不是本 bug 的成因。
    always @(posedge clk) begin
        if (!rst_n)                 frame_req <= 1'b0;
        else if (wr_fire && in_sof) frame_req <= 1'b1;   // 帧首：开闸
        else if (fs_set)            frame_req <= 1'b0;   // 输出完成：关闸
    end

    //   同上：帧首置 1、A 一开工清 0（两条都是非阻塞，语义清楚）
    always @(posedge clk) begin
        if (!rst_n)                 frame_started <= 1'b0;
        else if (wr_fire && in_sof) frame_started <= 1'b1;
        else if (arow_go)           frame_started <= 1'b0;
    end

    //   ⚠️ 流水化后"要暂停输入"的时刻 = A 级在发 row_load（a_state == A_RL），
    //      与老版本的 (state != S_RINIT) 等价
    //   ⚠️ 这里【不】用 frame_req 去挡输入 —— 挡了会在"输出已完成、输入还没吃完"
    //      时掐断上游（正是 2026-09-27 那个挂死）。输入侧只受 frame_seen + 流控管。
    //
    //---------------------------------------------------------------------------
    //   ⭐ 帧间"等排空"（2026-09-29，帧门第二半）
    //---------------------------------------------------------------------------
    //   帧 N 的输入收完（见过 tlast）之后，**下一个像素就是帧 N+1 的第一个**。
    //   但此时帧 N 的流水线（A/B/C）可能还在往外排最后几个像素 ——
    //   如果现在就把帧 N+1 的帧首放进来，帧首那套"位置清零"会打断正在排出的像素
    //   ⇒ 帧末几个像素算错（实测：帧1 vs 帧2 差 4 / 3072）。
    //   ⇒ 所以：**输入已收完 且 流水线非空 时，把输入按住**，等排空再放下一帧进来。
    //   ⚠️ 按住是安全的：此刻【本帧已经没有待收的输入了】（tlast 已见），
    //      上游本来就没东西可发 —— 不会像 2026-09-27 那次把上游掐死。
    //---------------------------------------------------------------------------
    wire in_frame_done = in_eof_r;                            // 本帧输入已收完
    wire pipe_busy     = a_valid || b_rdy || (c_state != C_IDLE);
    wire hold_next     = in_frame_done && pipe_busy;          // 等排空

    assign in_ready = !hold_next &&
                      (frame_seen || ((a_state != A_RL) && (wr_ext < lim_ext)));

    //========================================================================
    // 8. 死锁检测：等所需输入行超过 65535 拍，基本可以断定 ROWS 配小了
    //------------------------------------------------------------------------
    //   ⚠️ "在等输入行"的新判据 = B 级空闲、手里有活、但要读的行还没写完。
    //      （老版本是停在 S_CLAMP 等 row_ok）
    //========================================================================
    wire waiting_rows = (b_state == B_IDLE) && a_valid && !b_rows_ok;

    reg [15:0] wait_cnt;
    always @(posedge clk) begin
        if (!rst_n)                    wait_cnt <= 16'd0;
        else if (!waiting_rows)        wait_cnt <= 16'd0;
        else if (wait_cnt != 16'hFFFF) wait_cnt <= wait_cnt + 16'd1;
    end
    always @(posedge clk) begin
        if (!rst_n) stuck <= 1'b0;
        else        stuck <= (wait_cnt == 16'hFFFF) && waiting_rows;
    end

    //   ⭐ 这里原来有一条 `TODO(video)`："多帧需要给 rows_written 加帧基准偏移"。
    //      2026-09-30 已解决，但【没走基准偏移这条路】—— 用的是
    //      「line_buf 帧首归零 rows_written」+「A_IDLE 带 frame_started」两处相扣。
    //      已上板实测（批量 4 帧 × 4 组不同 H、不复位、逐字节一致）。详见文件头。

    //========================================================================
    // 9. 吞吐计数（片上性能计量，不是临时探针）
    //------------------------------------------------------------------------
    //   ⭐ 为什么把调试计数器留下来当正式逻辑：
    //      "拍/像素"这一个总数**不足以定位瓶颈**——8.46 拍里到底谁在等谁，
    //      只有分门别类数出来才知道该改哪一级。2026-09-28 就是靠这组数
    //      把"以为 B 是瓶颈"纠正成"coord_gen 的除法器环才是"的。
    //      视频阶段每帧的吞吐会随 H 变化，这组计数是现场诊断的唯一手段。
    //
    //   读法（上层经 AXI4-Lite 或 ILA 取，或 TB 层次引用）：
    //      pf_starve 大 → coord_gen 供不上坐标（要动除法器并行度/算法）
    //      pf_waitb  大 → B 或 C 是瓶颈（要动读口相位/输出握手）
    //      pf_rows   大 → 在等输入行（流控太紧，或行缓存 ROWS 太小）
    //      pf_chold  ≈ 每像素 1 拍 → 握手固有开销，正常
    //
    //   ⚠️ 第一版把 pf_starve 和 pf_waitb 混成一个计数器，读出来是错的 ——
    //      两者的修法完全不同（前者动 coord_gen、后者动 B），必须分开。
    //   ⚠️ 纯计数器，不参与任何数据通路，不进关键路径（时序无影响）。
    //========================================================================
    reg [31:0] pf_cyc    = 0;   // 总拍数（rst 释放后开始计）
    reg [31:0] pf_starve = 0;   // A 能取（a_free=1）但坐标还没出来
    reg [31:0] pf_waitb  = 0;   // A 攥着结果没被 B 取走（a_free=0）
    reg [31:0] pf_bnoa   = 0;   // B 空转、A 还没算出下一个
    reg [31:0] pf_rows   = 0;   // B 有活、但要读的行还没写完（等输入）
    reg [31:0] pf_chold  = 0;   // B 的 4 元组就绪、等 C 取

    always @(posedge clk) begin
        if (rst_n) begin
            pf_cyc <= pf_cyc + 1'b1;
            if (a_state == A_WAIT &&  a_free && !coord_valid) pf_starve <= pf_starve + 1'b1;
            if (a_state == A_WAIT && !a_free)                 pf_waitb  <= pf_waitb  + 1'b1;
            if (b_state == B_IDLE && !a_valid && !b_rdy)      pf_bnoa   <= pf_bnoa   + 1'b1;
            if (b_state == B_IDLE && a_valid && !b_rows_ok)   pf_rows   <= pf_rows   + 1'b1;
            if (b_state == B_HOLD)                            pf_chold  <= pf_chold  + 1'b1;
        end
    end

    //========================================================================
    // 10. 调试只读总线（观测用，不参与逻辑）
    //========================================================================
    //   DBG0 —— 流控 / 输入侧（**卡住时先看这个**）
    //     [11:0]  rows_written   已写完的输入行数（=0 ⇒ 输入压根没进来）
    //     [23:12] y_lo_cur       流控下界（行缓存还需保护的最小行）
    //     [24]    in_ready       ⭐ 核是否在收输入。0 ⇒ 核在反压输入
    //     [25]    frame_seen     帧末"输入排空"粘滞位
    //     [26]    b_rows_ok      要读的行到齐没有
    //     [27]    a_valid        A 级手上有结果
    //     [29:28] a_state        0=IDLE 1=RL(行首) 2=WAIT(等坐标) 3=CLAMP
    //     [31:30] 保留
    assign dbg0 = { 2'b0, a_state, a_valid, b_rows_ok, frame_seen, in_ready,
                    y_lo_cur, rows_written };

    //   DBG1 —— B/C 级、输出握手与坐标发生器
    //     [2:0]   b_state        0=IDLE 1..4=RD0..RD3 5=HOLD
    //     [5:3]   c_state        0=IDLE 1=FEED 2=W1 3=W2 4=OUT
    //     [6]     b_rdy          B 的 4 元组就绪
    //     [7]     coord_valid    坐标 FIFO 非空
    //     [8]     coord_ready    本拍在取坐标
    //     [20:9]  out_v          当前输出行
    //     [21]    out_ready      ⭐ 下游(DMA)收不收 —— C 卡在 OUT 时就等它
    //     [22]    out_valid      核正在往外送（tvalid）
    //     [23]    out_last       核认为这是帧末（tlast）
    //     [29:24] out_u[5:0]     当前输出列（低 6 位）
    //     [31:30] 保留
    //   ⭐ [21]~[23] 是 2026-09-29 加的：死锁链已经定位到"C 级卡在 C_OUT
    //      等 out_ready"，这三个位直接把"到底在等 DMA、还是核自己卡住"闭环。
    assign dbg1 = { 2'b0, out_u[5:0], out_last, out_valid, out_ready,
                    out_v, coord_ready, coord_valid, b_rdy, c_state, b_state };

endmodule
