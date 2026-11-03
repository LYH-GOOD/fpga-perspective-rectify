
wire kernel_monitor_reset;
wire kernel_monitor_clock;
wire kernel_monitor_report;
assign kernel_monitor_reset = ~ap_rst_n;
assign kernel_monitor_clock = ap_clk;
assign kernel_monitor_report = 1'b0;
wire [1:0] axis_block_sigs;
wire [3:0] inst_idle_sigs;
wire [0:0] inst_block_sigs;
wire kernel_block;

assign axis_block_sigs[0] = ~grp_load_and_hsum_fu_224.grp_load_and_hsum_Pipeline_VITIS_LOOP_50_1_fu_132.s_axis_TDATA_blk_n;
assign axis_block_sigs[1] = ~grp_axis_sharp_Pipeline_VITIS_LOOP_123_3_fu_302.m_axis_TDATA_blk_n;

assign inst_block_sigs[0] = 1'b0;

assign inst_idle_sigs[0] = 1'b0;
assign inst_idle_sigs[1] = grp_load_and_hsum_fu_224.ap_idle;
assign inst_idle_sigs[2] = grp_load_and_hsum_fu_224.grp_load_and_hsum_Pipeline_VITIS_LOOP_50_1_fu_132.ap_idle;
assign inst_idle_sigs[3] = grp_axis_sharp_Pipeline_VITIS_LOOP_123_3_fu_302.ap_idle;

axis_sharp_hls_deadlock_idx0_monitor axis_sharp_hls_deadlock_idx0_monitor_U (
    .clock(kernel_monitor_clock),
    .reset(kernel_monitor_reset),
    .axis_block_sigs(axis_block_sigs),
    .inst_idle_sigs(inst_idle_sigs),
    .inst_block_sigs(inst_block_sigs),
    .block(kernel_block)
);


always @ (kernel_block or kernel_monitor_reset) begin
    if (kernel_block == 1'b1 && kernel_monitor_reset == 1'b0) begin
        find_kernel_block = 1'b1;
    end
    else begin
        find_kernel_block = 1'b0;
    end
end
