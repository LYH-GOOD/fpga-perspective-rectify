//=============================================================================
// axi_lite_regs.v
//   AXI4-Lite 从机 —— 配置寄存器组
//
//   PS 侧（PYNQ 的 Python）通过它下发图像尺寸、8 个单应参数，并读回状态。
//   PYNQ 里用 pynq.Overlay + MMIO 直接读写，不需要写驱动。
//
//---------------------------------------------------------------------------
//   寄存器映射（地址空间 64 字节，字对齐）
//---------------------------------------------------------------------------
//   偏移    名称        属性   内容
//   --------------------------------------------------------------------
//   0x00   CTRL        W      [0] start：写 1 启动一帧处理（1 拍脉冲）
//                             [1] soft_reset：写 1 复位（1 拍脉冲）
//   0x04   STATUS      R      [0] busy        正在处理
//                             [1] frame_done  已完成一帧
//                             [2] stuck       等输入行超时（ROWS 配小了）
//                             [3] cfg_loaded  参数已写入（写 A32 时置位）
//   0x08   SIZE_IN     RW     [15:0] H_IN   [31:16] W_IN
//   0x0C   SIZE_OUT    RW     [15:0] H_OUT  [31:16] W_OUT
//   0x10   A11         RW     Q16.16
//   0x14   A12         RW
//   0x18   A13         RW     注意：a13 / a23 **不乘** NORM_SCALE
//   0x1C   A21         RW
//   0x20   A22         RW
//   0x24   A23         RW
//   0x28   A31         RW
//   0x2C   A32         RW     写完这条会拉高 cfg_we 一拍 + 置位 cfg_loaded
//   0x30   VERSION     R      [15:0] minor  [31:16] major
//   0x38   DBG0        R      调试：流控/输入侧（见下面 DBG0 位定义）
//   0x3C   DBG1        R      调试：A/B/C 各级状态
//   0x34   FRAME_CNT   R      已完成的帧数（PS 可轮询它判断进度）
//
//   ⚠️ 参数换算公式见 docs/pl_remap_interface.md §二（PS 侧必读）：
//      只有 a13 / a23 不乘 NORM_SCALE，其余 6 个都要乘。
//
//---------------------------------------------------------------------------
//   协议实现说明
//---------------------------------------------------------------------------
//   · 写通道：等 AW 和 W 都有效 → 同拍断言 awready/wready → 下一拍回 B。
//     不做 outstanding，一次一笔，最简单且不会错。
//   · 读通道：AR 有效 → 断言 arready + 寄存地址 → 下一拍给 R。
//   · wstrb 只支持全字写（4'hF）。PYNQ 的 MMIO 就是全字访问，够用。
//=============================================================================
`timescale 1ns / 1ps

module axi_lite_regs #(
    parameter integer ADDR_AW = 6,
    parameter integer VERSION_MAJOR = 1,
    //   ⭐ 每次改动会体现在上板行为上的 RTL 就 +1 —— 日志里的 VERSION 就成了
    //      "这一版 RTL 到底上没上板"的凭证（配合 notebook 步骤 0 的文件指纹）。
    //   1.4 = 彩色（2026-09-30 C3）：行缓存存 RGB565、三通道插值、
    //         AXI-Stream 8→32 位（低 3 字节）、ROWS 256→192、MAX_W 1280→1024。
    //   1.5 = 多帧修复（2026-09-30）：**帧末 A 会多跑一行**，用【上一帧的参数】
    //         锁存下一帧第 0 行的行初值 ⇒ 换配置/批量/视频时第 0 行全错。
    //         修法：A_IDLE 的开工条件加 `frame_started`（见 remap_core.v）。
    //         ⚠️ 读 0x30 若仍是 0x00010004 ⇒ **板上是修之前的比特流**。
    parameter integer VERSION_MINOR = 5
)(
    input  wire                 clk,
    input  wire                 rst_n,          // 同步低电平复位

    // ---------------- AXI4-Lite 从机接口 ----------------
    input  wire [ADDR_AW-1:0]   s_axi_awaddr,
    input  wire                 s_axi_awvalid,
    output reg                  s_axi_awready,

    input  wire [31:0]          s_axi_wdata,
    input  wire [3:0]           s_axi_wstrb,
    input  wire                 s_axi_wvalid,
    output reg                  s_axi_wready,

    output reg  [1:0]           s_axi_bresp,
    output reg                  s_axi_bvalid,
    input  wire                 s_axi_bready,

    input  wire [ADDR_AW-1:0]   s_axi_araddr,
    input  wire                 s_axi_arvalid,
    output reg                  s_axi_arready,

    output reg  [31:0]          s_axi_rdata,
    output reg  [1:0]           s_axi_rresp,
    output reg                  s_axi_rvalid,
    input  wire                 s_axi_rready,

    // ---------------- 配置输出（给 remap_core）----------------
    output reg  [15:0]          cfg_w_in,
    output reg  [15:0]          cfg_h_in,
    output reg  [15:0]          cfg_w_out,
    output reg  [15:0]          cfg_h_out,
    output reg  signed [31:0]   a11, a12, a13,
    output reg  signed [31:0]   a21, a22, a23,
    output reg  signed [31:0]   a31, a32,
    output reg                  cfg_we,         // 参数写完脉冲（1 拍）
    output reg                  cfg_loaded,     // 参数已写入标志
    output reg                  ctrl_start,     // 启动脉冲（1 拍）
    output reg                  ctrl_soft_rst,  // 软复位脉冲（1 拍）

    // ---------------- 状态输入（从 remap_core）----------------
    input  wire                 st_busy,
    input  wire                 st_frame_done,
    input  wire                 st_stuck,
    input  wire [15:0]          st_frame_cnt,

    // ---------------- 调试寄存器输入（从 remap_core 的活状态）----------------
    //   ⭐ 2026-09-29 加：上板失败时"卡在输入侧还是卡在核里"靠猜了两轮，
    //      把核内部状态暴露成两个只读寄存器后，一次就能问到答案。
    //      **一个 bit（DBG0[24] = in_ready）就能定案**。
    input  wire [31:0]          dbg0,
    input  wire [31:0]          dbg1
);

    //========================================================================
    // 寄存器地址（字偏移，低 2 位忽略）
    //========================================================================
    localparam [5:0] R_CTRL      = 6'h00;
    localparam [5:0] R_STATUS    = 6'h04;
    localparam [5:0] R_SIZE_IN   = 6'h08;
    localparam [5:0] R_SIZE_OUT  = 6'h0C;
    localparam [5:0] R_A11       = 6'h10;
    localparam [5:0] R_A12       = 6'h14;
    localparam [5:0] R_A13       = 6'h18;
    localparam [5:0] R_A21       = 6'h1C;
    localparam [5:0] R_A22       = 6'h20;
    localparam [5:0] R_A23       = 6'h24;
    localparam [5:0] R_A31       = 6'h28;
    localparam [5:0] R_A32       = 6'h2C;
    localparam [5:0] R_VERSION   = 6'h30;
    localparam [5:0] R_DBG0      = 6'h38;      // 调试：流控/输入侧
    localparam [5:0] R_DBG1      = 6'h3C;      // 调试：A/B/C 各级状态
    localparam [5:0] R_FRAME_CNT = 6'h34;

    // 注意：这里刻意不用 SystemVerilog 的强制转换语法 16'(x)，
    //       保持源码是纯 Verilog（Vivado / iverilog 都通吃）
    localparam [31:0] VERSION = (VERSION_MAJOR[15:0] << 16) | (VERSION_MINOR[15:0]);

    //========================================================================
    // 1. 写通道 FSM
    //========================================================================
    localparam W_IDLE = 1'b0, W_RESP = 1'b1;
    reg wstate;

    wire wr_fire = (wstate == W_IDLE) && s_axi_awvalid && s_axi_wvalid;
    wire [5:0] waddr = s_axi_awaddr[ADDR_AW-1:0];

    //========================================================================
    // ⚠️⚠️ 软复位必须【保持多拍】—— 2026-09-28 上板踩的坑，代价是两轮板子
    //------------------------------------------------------------------------
    //   原来写的是"1 拍脉冲"（默认 ctrl_soft_rst <= 0，只在写 CTRL 那拍置 1）。
    //   上板表现（run_result(9).log，--repeat 1 的第 2 帧）：
    //       DMA 超时 30 秒，MM2S(发) 一个字节都没发出去（in_ready 一直是 0）
    //       而 FRAME_CNT 被清成了 0
    //   ⇒ **复位"部分生效"了**：數 frame_cnt 的那一支到了，数 FSM 状态的那一支没到，
    //     核停在"半复位"的不一致状态里（a_state 卡在 A_RL ⇒ in_ready 恒 0）。
    //
    //   ⭐ 为什么仿真永远发现不了：
    //      仿真里 `core_rst_n` 到所有触发器的延迟都是 0，1 拍脉冲人人收得到。
    //      真芯片上它要扇出到**上万**个触发器，时钟偏斜 + 长线延迟会让一部分
    //      触发器在那一拍根本采不到 ⇒ 半个核被复位、半个没被复位。
    //      （判据：如果 1 拍脉冲真的"完全没生效"，核会保持上一帧状态 →
    //        行为应当和"不复位"一样，而 --no-frame-reset 那组是能跑完的。
    //        它却挂了 ⇒ 只能是"部分生效"。）
    //
    //   修法：把脉冲拉成 64 拍（≈770 ns @83.3 MHz）。对复位这种低频动作，
    //         多花 64 拍毫无代价，换来的是"所有触发器都一定采到"。
    //   ⚠️ 判据没有变 —— 修完必须重跑 axis_soft_reset_tb（它复现的是【时序】，
    //      但skew 它在仿真里也造不出来；所以这一条**只能靠上板验证**）。
    //========================================================================
    localparam [7:0] SOFT_RST_HOLD = 8'd63;    // 保持 64 拍（+1 拍由默认分支给出）
    reg [7:0] soft_rst_cnt;

    always @(posedge clk) begin
        if (!rst_n) begin
            wstate        <= W_IDLE;
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_bvalid  <= 1'b0;
            s_axi_bresp   <= 2'b00;

            cfg_w_in   <= 16'd1280;
            cfg_h_in   <= 16'd720;
            cfg_w_out  <= 16'd1280;
            cfg_h_out  <= 16'd720;
            a11 <= 32'sd0; a12 <= 32'sd0; a13 <= 32'sd0;
            a21 <= 32'sd0; a22 <= 32'sd0; a23 <= 32'sd0;
            a31 <= 32'sd0; a32 <= 32'sd0;
            cfg_we      <= 1'b0;
            cfg_loaded  <= 1'b0;
            ctrl_start  <= 1'b0;
            ctrl_soft_rst <= 1'b0;
            soft_rst_cnt  <= 8'd0;
        end else begin
            // 默认拉低单拍脉冲
            cfg_we        <= 1'b0;
            ctrl_start    <= 1'b0;
            //   ⭐ 软复位不是单拍，而是"计数到 0 为止"（见上面的说明）
            ctrl_soft_rst <= (soft_rst_cnt != 8'd0);
            if (soft_rst_cnt != 8'd0) soft_rst_cnt <= soft_rst_cnt - 8'd1;

            case (wstate)
            //------------------------------------------------------------
            W_IDLE: begin
                if (wr_fire) begin
                    s_axi_awready <= 1'b1;
                    s_axi_wready  <= 1'b1;
                    s_axi_bresp   <= 2'b00;      // OKAY

                    // ---- 写寄存器 ----
                    case (waddr)
                    R_CTRL: begin
                        if (s_axi_wdata[0]) ctrl_start    <= 1'b1;
                        if (s_axi_wdata[1]) begin
                            ctrl_soft_rst <= 1'b1;
                            soft_rst_cnt  <= SOFT_RST_HOLD;   // ⭐ 装载保持计数
                        end
                    end
                    R_SIZE_IN:  begin cfg_w_in  <= s_axi_wdata[31:16];
                                       cfg_h_in  <= s_axi_wdata[15:0];  end
                    R_SIZE_OUT: begin cfg_w_out <= s_axi_wdata[31:16];
                                       cfg_h_out <= s_axi_wdata[15:0];  end
                    R_A11: a11 <= s_axi_wdata;
                    R_A12: a12 <= s_axi_wdata;
                    R_A13: a13 <= s_axi_wdata;
                    R_A21: a21 <= s_axi_wdata;
                    R_A22: a22 <= s_axi_wdata;
                    R_A23: a23 <= s_axi_wdata;
                    R_A31: a31 <= s_axi_wdata;
                    R_A32: begin
                        a32        <= s_axi_wdata;
                        cfg_we     <= 1'b1;       // 最后一条 → 参数就绪脉冲
                        cfg_loaded <= 1'b1;
                    end
                    default: ;                    // 只读寄存器写入被忽略
                    endcase

                    wstate <= W_RESP;
                end
            end
            //------------------------------------------------------------
            W_RESP: begin
                s_axi_awready <= 1'b0;
                s_axi_wready  <= 1'b0;
                s_axi_bvalid  <= 1'b1;
                // ⚠️ 结束条件是 bvalid【已经拉高一拍】且 bready 也高，
                //    不能只判 bready —— 否则 bready 提前拉高时，
                //    同一拍内 bvalid 先置 1 又被置 0，握手永远完不成。
                if (s_axi_bvalid && s_axi_bready) begin
                    s_axi_bvalid <= 1'b0;
                    wstate       <= W_IDLE;
                end
            end
            endcase
        end
    end

    //========================================================================
    // 2. 读通道 FSM
    //========================================================================
    localparam R_IDLE = 1'b0, R_DATA = 1'b1;
    reg rstate;
    reg [5:0] raddr_r;

    always @(posedge clk) begin
        if (!rst_n) begin
            rstate        <= R_IDLE;
            s_axi_arready <= 1'b0;
            s_axi_rvalid  <= 1'b0;
            s_axi_rdata   <= 32'd0;
            s_axi_rresp   <= 2'b00;
            raddr_r       <= 6'd0;
        end else begin
            case (rstate)
            //------------------------------------------------------------
            R_IDLE: begin
                if (s_axi_arvalid) begin
                    s_axi_arready <= 1'b1;
                    raddr_r       <= s_axi_araddr[ADDR_AW-1:0];
                    rstate        <= R_DATA;
                end
            end
            //------------------------------------------------------------
            R_DATA: begin
                s_axi_arready <= 1'b0;
                s_axi_rvalid  <= 1'b1;
                s_axi_rresp   <= 2'b00;

                // ---- 读多路选择 ----
                case (raddr_r)
                R_CTRL:      s_axi_rdata <= 32'd0;          // CTRL 是只写的
                R_STATUS:    s_axi_rdata <= {28'd0, cfg_loaded, st_stuck,
                                              st_frame_done, st_busy};
                R_SIZE_IN:   s_axi_rdata <= {cfg_w_in,  cfg_h_in};
                R_SIZE_OUT:  s_axi_rdata <= {cfg_w_out, cfg_h_out};
                R_A11:       s_axi_rdata <= a11;
                R_A12:       s_axi_rdata <= a12;
                R_A13:       s_axi_rdata <= a13;
                R_A21:       s_axi_rdata <= a21;
                R_A22:       s_axi_rdata <= a22;
                R_A23:       s_axi_rdata <= a23;
                R_A31:       s_axi_rdata <= a31;
                R_A32:       s_axi_rdata <= a32;
                R_VERSION:   s_axi_rdata <= VERSION;
                R_FRAME_CNT: s_axi_rdata <= {16'd0, st_frame_cnt};
                R_DBG0:      s_axi_rdata <= dbg0;
                R_DBG1:      s_axi_rdata <= dbg1;
                default:     s_axi_rdata <= 32'hDEAD_BEEF;  // 越界地址，便于调试
                endcase

                // ⚠️ 同上：必须 rvalid 已经拉高一拍且 rready 也高才结束。
                //    只判 rready 会让 rvalid 永远为 0（踩过的坑）。
                if (s_axi_rvalid && s_axi_rready) begin
                    s_axi_rvalid <= 1'b0;
                    rstate       <= R_IDLE;
                end
            end
            endcase
        end
    end

    // wstrb 未使用（只支持全字写）。PYNQ 的 MMIO 就是 32 位访问，够用。
    wire _unused_wstrb = |s_axi_wstrb;

endmodule
