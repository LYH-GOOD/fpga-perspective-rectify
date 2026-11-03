//=============================================================================
// axis_remap_top.v
//   PL 侧顶层 —— AXI4-Lite 配置 + AXI-Stream 进出，包住 remap_core
//
//   ┌──────────────┐  AXI4-Lite   ┌───────────────┐
//   │  PS (ARM)    │─────────────►│ axi_lite_regs │──► 尺寸 / 8 参数 / 控制
//   │  PYNQ Python │◄─────────────│               │◄── 状态
//   └──────────────┘              └───────────────┘
//   ┌──────────────┐  AXI-Stream  ┌───────────────┐  AXI-Stream  ┌──────────────┐
//   │ AXI DMA 或   │─────────────►│               │─────────────►│ AXI DMA 或   │
//   │ HDMI RX      │  (8bit 灰度) │  remap_core   │  (8bit 灰度) │ HDMI TX      │
//   └──────────────┘              └───────────────┘              └──────────────┘
//
//   视频阶段把两头的 DMA 换成 HDMI RX/TX 即可，**本模块和 remap_core 都不用改**。
//
//---------------------------------------------------------------------------
//   ⚠️ 接入 AXI DMA 时的注意点
//---------------------------------------------------------------------------
//   · 本设计的流位宽是 **8 bit**（灰度）。AXI DMA 的流接口位宽必须在 IP 配置里
//     设成 8 bit；若用的是 32 bit 的 DMA，需要插入一个 AXI4-Stream Data Width
//     Converter（4 像素打包成 1 拍）。
//   · tlast 用来标记帧末像素；帧首由内部计数器推导（不依赖 tuser），
//     因为 AXI DMA 默认没有 tuser 通道。
//
//---------------------------------------------------------------------------
//   ⚠️ 行缓存深度仍未解决的老约束
//---------------------------------------------------------------------------
//   `ROWS` 必须大于输出单行源区间的垂直跨度（≈ W_out × tan θ，θ 是文档在
//   画面里的旋转角），否则核会死锁。详见 remap_core.v 文件头与
//   docs/pl_remap_interface.md §6.2。stuck 状态位可用于检出。
//=============================================================================
`timescale 1ns / 1ps

module axis_remap_top #(
    //---- 颜色（2026-09-30 彩色步 C3b）---------------------------------------
    //   NCH = 1：灰度；PIX_W = 8，DW = 8
    //   NCH = 3：彩色；PIX_W = 24（RGB888），DW = 32
    //   ⚠️ 为什么彩色要用 32 位的流、而不是 24 位：
    //      AXI DMA 的 tdata 只支持 8/16/32/64/... **没有 24**。
    //      所以流上是"一个像素一拍、低 3 字节有效、第 4 字节补 0"。
    //      ⚠️ 代价是 DMA 多搬 1/3 的字节 —— 但**实测这笔开销是免费的**：
    //         瓶颈是核（538,896 px × 7.16 拍 ÷ 83.333 MHz = 46.3 ms），
    //         而输出侧 DMA 只要 538,896 拍 = 6.5 ms，比核快 7 倍。
    //      ⚠️ 换来的好处：**完全不需要 tkeep**，PS 侧就是简单地按 4 字节读、
    //         丢掉第 4 个 —— 少一整类"字节对齐"的坑。
    parameter integer NCH        = 1,
    parameter integer DW         = 8,       // AXI-Stream 位宽（灰度 8 / 彩色 32）
    parameter integer PIX_W      = 8,       // 核的像素位宽 = NCH*8（灰度 8 / 彩色 24）
    parameter integer ROW_AW     = 12,
    // ROWS：行缓存深度。必须 > 输出单行源区间的最大垂直跨度，
    //       否则会死锁（画面冻结）。跨度 ≈ W_out × tan(θ)，θ = 文档在画面里的旋转角。
    //       ⚠️ 必须是 2 的幂（line_buf 用位切片做环形取模）。
    //       实测：普通倾斜照片 7~8 行足够；**强旋转的照片要 166 行**。
    //       256 行覆盖到约 11° 旋转，配合下面 MAX_W=1280 时 BRAM 占约 55%。
    parameter integer ROWS       = 256,
    parameter integer FRAC_BITS  = 16,
    parameter integer NORM_SCALE = 2048,
    parameter integer ACC_W      = 56,
    // MAX_W：支持的最大输入图像宽度。PS 侧 load_image() 已限制输入 ≤1280。
    //        行缓存开销 = ROWS × MAX_W 字节 —— 这是本项目 BRAM 的唯一大用户。
    parameter integer MAX_W      = 1280,
    parameter integer ADDR_AW    = 6
)(
    input  wire                 aclk,
    input  wire                 aresetn,     // 低电平有效

    // ---------------- AXI4-Lite 从机（PS 配置）----------------
    input  wire [ADDR_AW-1:0]   s_axi_awaddr,
    input  wire                 s_axi_awvalid,
    output wire                 s_axi_awready,
    input  wire [31:0]          s_axi_wdata,
    input  wire [3:0]           s_axi_wstrb,
    input  wire                 s_axi_wvalid,
    output wire                 s_axi_wready,
    output wire [1:0]           s_axi_bresp,
    output wire                 s_axi_bvalid,
    input  wire                 s_axi_bready,
    input  wire [ADDR_AW-1:0]   s_axi_araddr,
    input  wire                 s_axi_arvalid,
    output wire                 s_axi_arready,
    output wire [31:0]          s_axi_rdata,
    output wire [1:0]           s_axi_rresp,
    output wire                 s_axi_rvalid,
    input  wire                 s_axi_rready,

    // ---------------- AXI-Stream 从机（输入像素流）----------------
    input  wire [DW-1:0]        s_axis_tdata,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,
    input  wire                 s_axis_tlast,   // 帧末像素

    // ---------------- AXI-Stream 主机（输出像素流）----------------
    output wire [DW-1:0]        m_axis_tdata,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire                 m_axis_tlast
);

    //========================================================================
    // 0. 流位宽 DW ↔ 核像素位宽 PIX_W（彩色 32 ↔ 24，多出来的字节补 0）
    //------------------------------------------------------------------------
    //   ⚠️ 输入方向不需要 generate：`s_axis_tdata[PIX_W-1:0]` 在 DW==PIX_W 时
    //      就是整字，切片合法。
    //   ⚠️ 输出方向的补零**必须**用 generate 分支写 —— 直接写
    //      `{{(DW-PIX_W){1'b0}}, ...}` 在 DW==PIX_W 时是零宽复制，
    //      某些工具会报错。
    //========================================================================
    wire [PIX_W-1:0] core_in_data = s_axis_tdata[PIX_W-1:0];
    wire [PIX_W-1:0] core_out_data;

    generate
    if (DW == PIX_W) begin : g_pad_none
        assign m_axis_tdata = core_out_data;
    end else begin : g_pad_zero
        assign m_axis_tdata = {{(DW-PIX_W){1'b0}}, core_out_data};
    end
    endgenerate

    //========================================================================
    // 1. 配置寄存器
    //========================================================================
    wire [15:0]        cfg_w_in, cfg_h_in, cfg_w_out, cfg_h_out;
    wire signed [31:0] a11, a12, a13, a21, a22, a23, a31, a32;
    wire               cfg_we, cfg_loaded;
    wire               ctrl_start, ctrl_soft_rst;
    //   调试总线：从核引到寄存器块（0x38 / 0x3C，只读）
    //   ⚠️ 必须声明在 u_regs 实例【之前】—— 这个文件踩过四次
    //      "declaration after use"（iverilog: Unable to bind wire/reg/memory）
    wire [31:0]        core_dbg0, core_dbg1;

    //========================================================================
    // 2. remap_core 接口信号（提前声明：例化要用）
    //========================================================================
    wire               core_rst_n;
    wire               core_in_ready;       // remap_core 的反压输出
    wire               in_fire;
    wire               in_sof;
    wire               frame_done;
    wire               stuck;

    // 状态
    reg                busy_r;
    reg  [15:0]        frame_cnt;
    reg                frame_active;

    //========================================================================
    // 3. 配置寄存器例化
    //========================================================================
    axi_lite_regs #(
        .ADDR_AW(ADDR_AW)
    ) u_regs (
        .clk(aclk), .rst_n(aresetn),

        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),

        .cfg_w_in(cfg_w_in), .cfg_h_in(cfg_h_in),
        .cfg_w_out(cfg_w_out), .cfg_h_out(cfg_h_out),
        .a11(a11), .a12(a12), .a13(a13),
        .a21(a21), .a22(a22), .a23(a23),
        .a31(a31), .a32(a32),
        .cfg_we(cfg_we), .cfg_loaded(cfg_loaded),
        .ctrl_start(ctrl_start), .ctrl_soft_rst(ctrl_soft_rst),
        .dbg0(core_dbg0), .dbg1(core_dbg1),

        .st_busy(busy_r), .st_frame_done(frame_done),
        .st_stuck(stuck), .st_frame_cnt(frame_cnt)
    );

    //========================================================================
    // 4. 输入侧帧边界推导
    //------------------------------------------------------------------------
    //   tlast 标记帧末；tuser 不用（AXI DMA 默认没有该通道），
    //   帧首由 frame_active 推导：一帧结束后收到的第一个像素即 SOF。
    //========================================================================
    assign core_rst_n      = aresetn && !ctrl_soft_rst;

    assign s_axis_tready   = core_in_ready;     // remap_core 的反压直连到 AXI-Stream
    assign in_fire         = s_axis_tvalid && core_in_ready;
    assign in_sof          = in_fire && !frame_active;

    always @(posedge aclk) begin
        if (!core_rst_n) begin
            frame_active <= 1'b0;
        end else if (in_fire) begin
            frame_active <= ~s_axis_tlast;      // 收到 tlast → 本帧结束
        end
    end

    //========================================================================
    // 5. 重映射核
    //========================================================================
    remap_core #(
        .NCH(NCH), .PIX_W(PIX_W), .ROW_AW(ROW_AW), .ROWS(ROWS),
        .FRAC_BITS(FRAC_BITS), .NORM_SCALE(NORM_SCALE),
        .ACC_W(ACC_W), .MAX_W(MAX_W)
    ) u_core (
        .clk(aclk), .rst_n(core_rst_n),

        .cfg_w_in(cfg_w_in), .cfg_h_in(cfg_h_in),
        .cfg_w_out(cfg_w_out), .cfg_h_out(cfg_h_out),
        .a11(a11), .a12(a12), .a13(a13),
        .a21(a21), .a22(a22), .a23(a23),
        .a31(a31), .a32(a32),

        .in_valid(s_axis_tvalid), .in_data(core_in_data),
        .in_sof(in_sof), .in_ready(core_in_ready),
        .in_eof(s_axis_tlast),

        .out_valid(m_axis_tvalid), .out_data(core_out_data),
        .out_ready(m_axis_tready),
        .out_sof(),                    // 未对外暴露（AXI-Stream 无 tuser）
        .out_last(m_axis_tlast),

        .frame_done(frame_done), .stuck(stuck),
        .dbg0(core_dbg0), .dbg1(core_dbg1)     // 调试只读（转给寄存器块）
    );

    //========================================================================
    // 6. 状态统计
    //------------------------------------------------------------------------
    //   ⚠️ frame_cnt 必须数 frame_done 的【上升沿】，不能数电平。
    //      核里 frame_done 会保持 2 拍（S_OUT 置位 → S_DONE 不倒 → S_IDLE 才清零），
    //      按电平数会每帧 +2（实测上板跑一帧读出 FRAME_CNT = 2）。
    //========================================================================
    //   ⚠️⚠️ 复位条件必须是 `core_rst_n`，**不是** `aresetn` —— 2026-09-28 踩过：
    //      上一版写的是 `if (!aresetn)`，于是【写过 CTRL[1] 软复位之后 busy_r 不会清零】，
    //      它一直保持旧值 1。PS 侧超时诊断看到 busy=1 就报"核还在算，只是慢"，
    //      而实际上 30 秒里核一帧都没产出（FRAME_CNT=0）——
    //      **一个陈旧的 status 位把排查方向整个带偏了。**
    //      （仿真里看不出来：那边从来没查过软复位后的 STATUS。）
    //      core_rst_n = aresetn && !ctrl_soft_rst，所以硬复位照样生效 ✓
    reg frame_done_d;
    always @(posedge aclk) begin
        if (!core_rst_n) begin
            busy_r       <= 1'b0;
            frame_cnt    <= 16'd0;
            frame_done_d <= 1'b0;
        end else begin
            frame_done_d <= frame_done;

            if (in_sof)                     busy_r <= 1'b1;
            else if (frame_done)            busy_r <= 1'b0;

            //   frame_cnt 已经在上面被 core_rst_n 的手里清零了，
            //   这里不用再判 ctrl_soft_rst（保留原注释以便对照历史）
            if (frame_done & ~frame_done_d) frame_cnt <= frame_cnt + 16'd1;
        end
    end

endmodule
