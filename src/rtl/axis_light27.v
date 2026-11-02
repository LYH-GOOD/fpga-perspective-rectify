`timescale 1ns/1ps
// Single-pass RGB888 PWL shadow lift, 32-bit AXIS carrier; no image RAM.
// Q8 strength 0..256, sampled at packet first input handshake. PS keeps it
// unchanged across ALL packets/tiles of one rectified frame. TLAST=packet end.
module axis_light27 (
 (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXIS:M_AXIS:S_AXI, ASSOCIATED_RESET aresetn" *)
 (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
 (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
 (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [31:0] s_axis_tdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [31:0] m_axis_tdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_axis_tvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_axis_tlast,
 (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 6" *)
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *) input wire [5:0] s_axi_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output wire [1:0] s_axi_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [5:0] s_axi_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output wire [1:0] s_axi_rresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready
);
 localparam [31:0] VERSION=32'h4c540001;
 reg [8:0] configured,active_strength;
 reg packet_open;
 reg [31:0] packet_count;
 reg aw_seen,w_seen;
 reg [5:0] aw_addr;
 reg [31:0] w_data;
 reg [3:0] w_strb;
 wire [8:0] masked_config={w_strb[1]?w_data[8]:configured[8],w_strb[0]?w_data[7:0]:configured[7:0]};
 assign s_axi_awready=!aw_seen&&!s_axi_bvalid;
 assign s_axi_wready=!w_seen&&!s_axi_bvalid;
 assign s_axi_bresp=2'b00;
 assign s_axi_arready=!s_axi_rvalid;
 assign s_axi_rresp=2'b00;
 reg v0,v1,v2,last0,last1,last2;
 reg [31:0] data0,data1,data2;
 reg [5:0] base0;
 reg [8:0] strength0;
 reg [7:0] room0,room1;
 reg [14:0] product1;
 wire ready2=!v2||m_axis_tready;
 wire ready1=!v1||ready2;
 wire ready0=!v0||ready1;
 assign s_axis_tready=ready0;
 assign m_axis_tvalid=v2;
 assign m_axis_tdata=data2;
 assign m_axis_tlast=last2;
 wire input_fire=s_axis_tvalid&&s_axis_tready;
 wire [7:0] r=s_axis_tdata[23:16],g=s_axis_tdata[15:8],b=s_axis_tdata[7:0];
 wire [9:0] weighted={2'b0,r}+{1'b0,g,1'b0}+{2'b0,b};
 wire [7:0] y=weighted[9:2];
 wire [7:0] maximum=(r>g)?((r>b)?r:b):((g>b)?g:b);
 wire [7:0] shadow_ramp=y-8'd16;
 wire [7:0] highlight_ramp=8'd240-y;
 wire [5:0] lift_base=(y<=16||y>=240)?6'd0:
                         (y<48)?shadow_ramp[5:0]:(y<112)?6'd32:{2'b0,highlight_ramp[7:2]};
 (* use_dsp="yes" *) wire [14:0] scaled=base0*strength0;
 wire [15:0] rounded={1'b0,product1}+16'd128;
 wire [7:0] requested_delta=rounded[15:8];
 wire [7:0] delta=(requested_delta>room1)?room1:requested_delta;

 always @(posedge aclk) begin
  if (!aresetn) begin
   configured<=0;aw_seen<=0;w_seen<=0;aw_addr<=0;w_data<=0;w_strb<=0;
   s_axi_bvalid<=0;s_axi_rvalid<=0;s_axi_rdata<=0;
  end else begin
   if (s_axi_awvalid&&s_axi_awready) begin aw_seen<=1;aw_addr<=s_axi_awaddr;end
   if (s_axi_wvalid&&s_axi_wready) begin w_seen<=1;w_data<=s_axi_wdata;w_strb<=s_axi_wstrb;end
   if (aw_seen&&w_seen&&!s_axi_bvalid) begin
    if (aw_addr[5:2]==0) configured<=(masked_config>256)?9'd256:masked_config;
    aw_seen<=0;w_seen<=0;s_axi_bvalid<=1;
   end
   if (s_axi_bvalid&&s_axi_bready) s_axi_bvalid<=0;
   if (s_axi_arvalid&&s_axi_arready) begin
    s_axi_rvalid<=1;
    case (s_axi_araddr[5:2])
     0:s_axi_rdata<={23'd0,configured};
     1:s_axi_rdata<=VERSION;
     2:s_axi_rdata<={23'd0,active_strength};
     3:s_axi_rdata<={30'd0,(v0||v1||v2),packet_open};
     4:s_axi_rdata<=packet_count;
     default:s_axi_rdata<=0;
    endcase
   end
   if (s_axi_rvalid&&s_axi_rready) s_axi_rvalid<=0;
  end
 end

 always @(posedge aclk) begin
  if (!aresetn) begin
   v0<=0;v1<=0;v2<=0;last0<=0;last1<=0;last2<=0;
   data0<=0;data1<=0;data2<=0;base0<=0;strength0<=0;room0<=0;room1<=0;product1<=0;
   packet_open<=0;active_strength<=0;packet_count<=0;
  end else begin
   if (input_fire) begin
    if (!packet_open) active_strength<=configured;
    packet_open<=!s_axis_tlast;
   end
   if (m_axis_tvalid&&m_axis_tready&&m_axis_tlast) packet_count<=packet_count+1;
   if (ready0) begin
    v0<=s_axis_tvalid;
    if (s_axis_tvalid) begin
     data0<=s_axis_tdata;last0<=s_axis_tlast;base0<=lift_base;
     strength0<=packet_open?active_strength:configured;room0<=8'd255-maximum;
    end
   end
   if (ready1) begin
    v1<=v0;
    if (v0) begin data1<=data0;last1<=last0;product1<=scaled;room1<=room0;end
   end
   if (ready2) begin
    v2<=v1;
    if (v1) begin
     data2<={data1[31:24],(data1[23:16]+delta),(data1[15:8]+delta),(data1[7:0]+delta)};
     last2<=last1;
    end
   end
  end
 end
endmodule
