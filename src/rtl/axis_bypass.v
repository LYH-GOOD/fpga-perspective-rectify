//=============================================================================
// axis_bypass.v —— 在 AXI-Stream 流里给 axis_sharp 加一条**真正的**旁路
//
//   原拓扑（S3b）：
//       fifo.M_AXIS ──► axis_sharp_0 ──► dma.S_AXIS_S2MM
//       ⇒ 即使 ENABLE=0，每个像素仍要 s.read()/m.write() 穿过核（逐位直通），
//         核**一直在流里**，关不掉。
//
//   新拓扑（本模块）：
//       fifo.M_AXIS ──► [axis_bypass] ──► dma.S_AXIS_S2MM
//                            ▲    │
//                            │    └──► axis_sharp_0.s_axis
//                            └─────── axis_sharp_0.m_axis
//       SHARP_EN=0 ⇒ 上游直接接到下游，axis_sharp 收不到一个字节、也不启动
//                    ⇒ 核在物理上不工作（不是"算了但丢弃"）。
//
//   ★★ 极性：SHARP_EN 复位值 = 0 = **直通**。
//      这是故意的 —— 上电 / 重载位流 / 软件崩了，流永远走得通，不可能死锁。
//      要锐化必须软件显式置 1（并且必须同时置 ap_start，否则会反压住流）。
//
//   ★ 切换只在**包边界**生效：只有当「上游这一包已收完」且「下游这一包已送完」
//      时才允许改 sel。否则一包会被拆成两段走不同路径，DMA 收到的顺序就乱了。
//
//   信号集（取自 rectify_bd_stream 生成的 system.v，不是猜的）：
//       fifo.M_AXIS   : TDATA[31:0], TLAST, TVALID, TREADY        （无 TKEEP）
//       sharp.s_axis  : TDATA[31:0], TKEEP[3:0], TSTRB[3:0], TLAST（TKEEP/TSTRB 外部绑 4'hF）
//       sharp.m_axis  : TDATA[31:0], TKEEP[3:0], TLAST, TVALID, TREADY
//       dma.S_AXIS_S2MM: TDATA[31:0], TKEEP[3:0], TLAST, TVALID, TREADY
//   ⇒ 直通那条路必须**自己造 TKEEP=4'hF**（原拓扑里是 sharp 给的）。
//
//   寄存器（AXI4-Lite，32 位，地址 0x40040000）：
//       0x00  SHARP_EN   [0]  读写。0=直通(复位值) 1=走核
//       0x04  VERSION         只读 = 0x5342_0001（'S''B' v0.1）
//       0x08  S_BEATS         只读 上游已收拍数（32 位回绕）
//       0x0C  M_BEATS         只读 下游已送拍数（32 位回绕）
//       0x10  PKT_CNT         只读 下游已送包数（按 TLAST 计）
//       0x14  SEL_NOW   [0]   只读 当前**实际生效**的选择（位对齐用）
//
//   ⚠️ 本模块**不**产生 TLAST、**不**改数据，只做路由。
//      TLAST 由上游（remap）或 axis_sharp（它自己重算）给出。
//=============================================================================
`timescale 1ns / 1ps

module axis_bypass #(
    parameter integer TDATA_W = 32
) (
    input  wire               aclk,
    input  wire               aresetn,

    // ---------------- 上游：axis_data_fifo_0 / M_AXIS ----------------
    input  wire [TDATA_W-1:0] s_tdata,
    input  wire               s_tlast,
    input  wire               s_tvalid,
    output wire               s_tready,

    // ---------------- 下游：axi_dma_0 / S_AXIS_S2MM ----------------
    output wire [TDATA_W-1:0] m_tdata,
    output wire [3:0]         m_tkeep,
    output wire               m_tlast,
    output wire               m_tvalid,
    input  wire               m_tready,

    // ---------------- 侧路出：axis_sharp_0 / s_axis ----------------
    output wire [TDATA_W-1:0] sh_tdata,
    output wire [3:0]         sh_tkeep,
    output wire [3:0]         sh_tstrb,
    output wire               sh_tlast,
    output wire               sh_tvalid,
    input  wire               sh_tready,

    // ---------------- 侧路回：axis_sharp_0 / m_axis ----------------
    input  wire [TDATA_W-1:0] fs_tdata,
    input  wire [3:0]         fs_tkeep,
    input  wire               fs_tlast,
    input  wire               fs_tvalid,
    output wire               fs_tready,

    // ---------------- 控制：AXI4-Lite 从机 ----------------
    input  wire [5:0]         s_axi_awaddr,
    input  wire [2:0]         s_axi_awprot,
    input  wire               s_axi_awvalid,
    output wire               s_axi_awready,
    input  wire [31:0]        s_axi_wdata,
    input  wire [3:0]         s_axi_wstrb,
    input  wire               s_axi_wvalid,
    output wire               s_axi_wready,
    output wire [1:0]         s_axi_bresp,
    output wire               s_axi_bvalid,
    input  wire               s_axi_bready,
    input  wire [5:0]         s_axi_araddr,
    input  wire [2:0]         s_axi_arprot,
    input  wire               s_axi_arvalid,
    output wire               s_axi_arready,
    output wire [31:0]        s_axi_rdata,
    output wire [1:0]         s_axi_rresp,
    output wire               s_axi_rvalid,
    input  wire               s_axi_rready
);

    //=====================================================================
    // 0. 选择寄存器（包边界对齐）
    //=====================================================================
    reg  sharp_en;          // 软件意图：1 = 想走核
    reg  sel_sharp;         // 实际生效：1 = 走核（只在包边界更新）
    reg  in_busy;           // 上游：本包还没收完
    reg  out_busy;          // 下游：本包还没送完

    // ★ 这里必须用「上游口」的握手，不能用 sh_*：
    //   直通档下 sh_tvalid 恒 0，用 sh_hs 会在直通时一个拍都数不到。
    wire s_hs    = s_tvalid  & s_tready;
    wire m_hs    = m_tvalid  & m_tready;

    always @(posedge aclk) begin
        if (!aresetn) begin
            sel_sharp <= 1'b0;      // ★ 复位 = 直通
            in_busy   <= 1'b0;
            out_busy  <= 1'b0;
        end else begin
            // 只有「两头都没包在飞」时才允许改选择；并且
            // ★ 切到「走核」还要求 sh_tready 已经拉高（核已经在等数据）。
            //   否则一切过去 s_tready 立刻变 0，整条流当场卡死。
            //   加了这条互锁后，软件忘了 ap_start 的后果是「锐化静默不生效」
            //   （可从 SEL_NOW 读出来），而不是黑屏卡死。
            if (!in_busy && !out_busy &&
                ((sharp_en == sel_sharp) ? 1'b0
                 : (sharp_en ? sh_tready : 1'b1))) begin
                sel_sharp <= sharp_en;
            end
            if (s_hs)      in_busy  <= ~s_tlast;
            if (m_hs)      out_busy <= ~m_tlast;
        end
    end

    //=====================================================================
    // 1. 数据通路
    //=====================================================================
    // ---- 上游口的 ready：走哪条路由哪个下游给 ----
    assign s_tready = sel_sharp ? sh_tready : m_tready;

    // ---- 到 axis_sharp ----
    assign sh_tvalid = sel_sharp ? s_tvalid : 1'b0;
    assign sh_tdata  = s_tdata;
    assign sh_tkeep  = 4'hF;
    assign sh_tstrb  = 4'hF;
    assign sh_tlast  = s_tlast;

    // ---- 到 DMA ----
    assign m_tvalid  = sel_sharp ? fs_tvalid : s_tvalid;
    assign m_tdata   = sel_sharp ? fs_tdata  : s_tdata;
    assign m_tkeep   = sel_sharp ? fs_tkeep  : 4'hF;   // ★ 直通路自己造 TKEEP
    assign m_tlast   = sel_sharp ? fs_tlast  : s_tlast;

    // ---- axis_sharp 出来的 ready ----
    assign fs_tready = m_tready;   // 非选中时 fs_tvalid 恒 0，拉扯不到谁

    //=====================================================================
    // 2. 统计计数器（板上验收用：直通档下 S_BEATS 应 == M_BEATS == w*h）
    //=====================================================================
    reg [31:0] s_beats, m_beats, pkt_cnt;

    always @(posedge aclk) begin
        if (!aresetn) begin
            s_beats <= 32'd0;
            m_beats <= 32'd0;
            pkt_cnt <= 32'd0;
        end else begin
            if (s_hs)       s_beats <= s_beats + 32'd1;
            if (m_hs) begin
                m_beats <= m_beats + 32'd1;
                if (m_tlast) pkt_cnt <= pkt_cnt + 32'd1;
            end
        end
    end

    //=====================================================================
    // 3. AXI4-Lite 从机
    //=====================================================================
    localparam [31:0] VERSION = 32'h5342_0001;

    reg        aw_got, w_got, bvalid_r;
    reg [5:0]  awaddr_q;
    reg [31:0] wdata_q;
    reg [3:0]  wstrb_q;

    reg        rvalid_r;
    reg [31:0] rdata_q;

    assign s_axi_awready = ~aw_got & ~bvalid_r;
    assign s_axi_wready  = ~w_got  & ~bvalid_r;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_arready = ~rvalid_r;
    assign s_axi_rvalid  = rvalid_r;
    assign s_axi_rdata   = rdata_q;
    assign s_axi_rresp   = 2'b00;

    always @(posedge aclk) begin
        if (!aresetn) begin
            aw_got   <= 1'b0;
            w_got    <= 1'b0;
            bvalid_r <= 1'b0;
            awaddr_q <= 6'd0;
            wdata_q  <= 32'd0;
            wstrb_q  <= 4'd0;
            sharp_en <= 1'b0;          // ★ 复位 = 直通
            rvalid_r <= 1'b0;
            rdata_q  <= 32'd0;
        end else begin
            // ---- 写地址 ----
            if (s_axi_awvalid && s_axi_awready) begin
                awaddr_q <= s_axi_awaddr;
                aw_got   <= 1'b1;
            end
            // ---- 写数据 ----
            if (s_axi_wvalid && s_axi_wready) begin
                wdata_q <= s_axi_wdata;
                wstrb_q <= s_axi_wstrb;
                w_got   <= 1'b1;
            end
            // ---- 提交（两半都到齐）----
            if (aw_got && w_got && !bvalid_r) begin
                if (awaddr_q[5:2] == 4'h0) begin      // 0x00 = SHARP_EN
                    if (wstrb_q[0]) sharp_en <= wdata_q[0];
                end
                aw_got   <= 1'b0;
                w_got    <= 1'b0;
                bvalid_r <= 1'b1;
            end
            if (bvalid_r && s_axi_bready) bvalid_r <= 1'b0;

            // ---- 读 ----
            if (s_axi_arvalid && s_axi_arready) begin
                case (s_axi_araddr[5:2])
                    4'h0:    rdata_q <= {31'd0, sharp_en};
                    4'h1:    rdata_q <= VERSION;
                    4'h2:    rdata_q <= s_beats;
                    4'h3:    rdata_q <= m_beats;
                    4'h4:    rdata_q <= pkt_cnt;
                    4'h5:    rdata_q <= {31'd0, sel_sharp};
                    default: rdata_q <= 32'hDEAD_BEEF;
                endcase
                rvalid_r <= 1'b1;
            end else if (rvalid_r && s_axi_rready) begin
                rvalid_r <= 1'b0;
            end
        end
    end

endmodule
