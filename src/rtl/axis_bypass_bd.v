//=============================================================================
// axis_bypass_bd.v —— 只给 Block Design 用的**接口包装层**
//
//   本文件里**没有任何逻辑**，只有：
//     ① 把 axis_bypass 的散装端口改名为 <接口名>_<信号名>
//     ② 挂上 X_INTERFACE_INFO / X_INTERFACE_PARAMETER，让 Vivado 在
//        create_bd_cell -type module -reference 时把它们聚成 5 个接口
//     ③ 例化 axis_bypass
//
//   ★ 为什么单独一层：axis_bypass.v 还要被 xsim 自检台用（那里是散装端口，
//     直连最省事）。包装层把「BD 接口标注」和「逻辑」彻底分开 ——
//     逻辑只此一份，自检台测的就是进 BD 的那一份。
//
//   接口对应关系（全部来自 rectify_bd_stream 生成的 system.v，不是猜的）：
//     S_AXIS   ← axis_data_fifo_0/M_AXIS        TDATA32 + TLAST（无 TKEEP/TSTRB）
//     M_AXIS   → axi_dma_0/S_AXIS_S2MM          TDATA32 + TKEEP + TLAST
//     SH_AXIS  → axis_sharp_0/s_axis            TDATA32 + TKEEP + TSTRB + TLAST
//     FS_AXIS  ← axis_sharp_0/m_axis            TDATA32 + TKEEP + TLAST
//     S_AXI    ↔ sc_lite/M05_AXI                AXI4-Lite，6 位地址（64 B）
//=============================================================================
`timescale 1ns / 1ps

module axis_bypass_bd (
    // ---------------- 时钟 / 复位（全部挂在 ps7 FCLK_CLK0 域）----------------
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF S_AXIS:M_AXIS:SH_AXIS:FS_AXIS:S_AXI, ASSOCIATED_RESET aresetn, PHASE 0.0, INSERT_VIP 0" *)
    input  wire        aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW, INSERT_VIP 0" *)
    input  wire        aresetn,

    // ---------------- S_AXIS：来自 axis_data_fifo_0（无 TKEEP/TSTRB）--------
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *)
    input  wire [31:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *)
    input  wire        s_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXIS, TDATA_NUM_BYTES 4, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, HAS_TKEEP 0, HAS_TSTRB 0, HAS_TLAST 1, PHASE 0.0, LAYERED_METADATA undef, INSERT_VIP 0" *)
    input  wire        s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *)
    output wire        s_axis_tready,

    // ---------------- M_AXIS：去 axi_dma_0 S2MM（要 TKEEP）-----------------
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *)
    output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *)
    output wire [3:0]  m_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *)
    output wire        m_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME M_AXIS, TDATA_NUM_BYTES 4, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, HAS_TKEEP 1, HAS_TSTRB 0, HAS_TLAST 1, PHASE 0.0, LAYERED_METADATA undef, INSERT_VIP 0" *)
    output wire        m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *)
    input  wire        m_axis_tready,

    // ---------------- SH_AXIS：去 axis_sharp_0 s_axis（要 TKEEP/TSTRB）------
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TDATA" *)
    output wire [31:0] sh_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TKEEP" *)
    output wire [3:0]  sh_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TSTRB" *)
    output wire [3:0]  sh_axis_tstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TLAST" *)
    output wire        sh_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TVALID" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME SH_AXIS, TDATA_NUM_BYTES 4, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, HAS_TKEEP 1, HAS_TSTRB 1, HAS_TLAST 1, PHASE 0.0, LAYERED_METADATA undef, INSERT_VIP 0" *)
    output wire        sh_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 SH_AXIS TREADY" *)
    input  wire        sh_axis_tready,

    // ---------------- FS_AXIS：来自 axis_sharp_0 m_axis（带 TKEEP）----------
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 FS_AXIS TDATA" *)
    input  wire [31:0] fs_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 FS_AXIS TKEEP" *)
    input  wire [3:0]  fs_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 FS_AXIS TLAST" *)
    input  wire        fs_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 FS_AXIS TVALID" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME FS_AXIS, TDATA_NUM_BYTES 4, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, HAS_TKEEP 1, HAS_TSTRB 0, HAS_TLAST 1, PHASE 0.0, LAYERED_METADATA undef, INSERT_VIP 0" *)
    input  wire        fs_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 FS_AXIS TREADY" *)
    output wire        fs_axis_tready,

    // ---------------- S_AXI：AXI4-Lite 从机（64 B 地址空间）-----------------
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, DATA_WIDTH 32, PROTOCOL AXI4LITE, ADDR_WIDTH 6, ID_WIDTH 0, AWUSER_WIDTH 0, ARUSER_WIDTH 0, WUSER_WIDTH 0, RUSER_WIDTH 0, BUSER_WIDTH 0, READ_WRITE_MODE READ_WRITE, HAS_BURST 0, HAS_LOCK 0, HAS_PROT 1, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, SUPPORTS_NARROW_BURST 0, MAX_BURST_LENGTH 1, NUM_READ_OUTSTANDING 2, NUM_WRITE_OUTSTANDING 2, MAX_READ_BURST_LENGTH 1, MAX_WRITE_BURST_LENGTH 1, INSERT_VIP 0" *)
    input  wire [5:0]  s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *)
    input  wire [2:0]  s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *)
    input  wire        s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *)
    output wire        s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *)
    input  wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *)
    input  wire [3:0]  s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *)
    input  wire        s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *)
    output wire        s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *)
    output wire [1:0]  s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *)
    output wire        s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *)
    input  wire        s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *)
    input  wire [5:0]  s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *)
    input  wire [2:0]  s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *)
    input  wire        s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *)
    output wire        s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *)
    output wire [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *)
    output wire [1:0]  s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *)
    output wire        s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *)
    input  wire        s_axi_rready
);

    axis_bypass #(.TDATA_W(32)) u_core (
        .aclk    (aclk),
        .aresetn (aresetn),

        .s_tdata (s_axis_tdata),
        .s_tlast (s_axis_tlast),
        .s_tvalid(s_axis_tvalid),
        .s_tready(s_axis_tready),

        .m_tdata (m_axis_tdata),
        .m_tkeep (m_axis_tkeep),
        .m_tlast (m_axis_tlast),
        .m_tvalid(m_axis_tvalid),
        .m_tready(m_axis_tready),

        .sh_tdata (sh_axis_tdata),
        .sh_tkeep (sh_axis_tkeep),
        .sh_tstrb (sh_axis_tstrb),
        .sh_tlast (sh_axis_tlast),
        .sh_tvalid(sh_axis_tvalid),
        .sh_tready(sh_axis_tready),

        .fs_tdata (fs_axis_tdata),
        .fs_tkeep (fs_axis_tkeep),
        .fs_tlast (fs_axis_tlast),
        .fs_tvalid(fs_axis_tvalid),
        .fs_tready(fs_axis_tready),

        .s_axi_awaddr (s_axi_awaddr),
        .s_axi_awprot (s_axi_awprot),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata  (s_axi_wdata),
        .s_axi_wstrb  (s_axi_wstrb),
        .s_axi_wvalid (s_axi_wvalid),
        .s_axi_wready (s_axi_wready),
        .s_axi_bresp  (s_axi_bresp),
        .s_axi_bvalid (s_axi_bvalid),
        .s_axi_bready (s_axi_bready),
        .s_axi_araddr (s_axi_araddr),
        .s_axi_arprot (s_axi_arprot),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata  (s_axi_rdata),
        .s_axi_rresp  (s_axi_rresp),
        .s_axi_rvalid (s_axi_rvalid),
        .s_axi_rready (s_axi_rready)
    );

endmodule
