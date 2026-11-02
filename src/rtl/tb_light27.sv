`timescale 1ns/1ps
module tb_light27;
 reg clk=0;always #6 clk=~clk;
 reg rst=0;
 reg [31:0] din=0;reg vin=0,lin=0;wire rin;
 wire [31:0] dout;wire vout,lout;reg rout=1;
 reg [5:0] aw=0,ar=0;reg av=0,wv=0,br=1,rv=0,rr=1;
 reg [31:0] wd=0;reg [3:0] ws=15;wire ard,wrd,bv,arr,rrv;wire [1:0] bp,rp;wire [31:0] rd;
 axis_light27 dut(.aclk(clk),.aresetn(rst),.s_axis_tdata(din),.s_axis_tvalid(vin),.s_axis_tready(rin),.s_axis_tlast(lin),
  .m_axis_tdata(dout),.m_axis_tvalid(vout),.m_axis_tready(rout),.m_axis_tlast(lout),
  .s_axi_awaddr(aw),.s_axi_awvalid(av),.s_axi_awready(ard),.s_axi_wdata(wd),.s_axi_wstrb(ws),.s_axi_wvalid(wv),.s_axi_wready(wrd),
  .s_axi_bresp(bp),.s_axi_bvalid(bv),.s_axi_bready(br),.s_axi_araddr(ar),.s_axi_arvalid(rv),.s_axi_arready(arr),
  .s_axi_rdata(rd),.s_axi_rresp(rp),.s_axi_rvalid(rrv),.s_axi_rready(rr));
 reg [32:0] expected[0:20000];integer head=0,tail=0;
 integer strength=0,requested=0;reg in_packet=0;
 integer sent=0,received=0,cycles=0;
 reg [32:0] stalled;reg was_stalled=0;reg random_stalls=0;
 reg [31:0] rng=32'h52617603;
 function automatic [31:0] golden(input [31:0] x,input integer amount);
  integer r,g,b,y,k,top,d;
  begin
   r=(x>>16)&255;g=(x>>8)&255;b=x&255;y=(r+2*g+b)/4;
   // Independent integer model of knots (16,0),(48,32),(112,32),(240,0).
   if(y<=16||y>=240)k=0;else if(y<=48)k=y-16;else if(y<=112)k=32;else k=(240-y)/4;
   d=(k*amount+128)/256;top=r;if(g>top)top=g;if(b>top)top=b;if(d>255-top)d=255-top;
   golden={x[31:24],8'(r+d),8'(g+d),8'(b+d)};
  end
 endfunction
 always @(posedge clk) begin
  if(rst)begin
   cycles=cycles+1;
   if(was_stalled&&(!vout||{lout,dout}!==stalled))$fatal(1,"changed stalled output");
   was_stalled=vout&&!rout;stalled={lout,dout};
   if(vin&&rin)begin
    if(!in_packet)strength=requested;
    expected[tail]={lin,golden(din,strength)};tail=tail+1;sent=sent+1;in_packet=!lin;
   end
   if(vout&&rout)begin
    if(head>=tail||{lout,dout}!==expected[head])$fatal(1,"pixel mismatch head=%0d got=%h expected=%h",head,{lout,dout},expected[head]);
    head=head+1;received=received+1;
   end
  end else begin head=0;tail=0;in_packet=0;was_stalled=0;end
 end
 always @(negedge clk)begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};rout=!random_stalls||(|rng[2:1]);
 end
 task automatic write_strength(input integer value,input integer skew);
  begin
   // Both AW-before-W and W-before-AW, and simultaneous channels.
   fork
    begin repeat(skew>0?skew:0)@(negedge clk);aw=0;av=1;do @(posedge clk);while(!ard);@(negedge clk);av=0;end
    begin repeat(skew<0?-skew:0)@(negedge clk);wd=value;wv=1;do @(posedge clk);while(!wrd);@(negedge clk);wv=0;end
   join
   wait(bv);@(posedge clk);@(negedge clk);requested=value>256?256:value;
  end
 endtask
 task automatic read_reg(input [5:0] addr,input [31:0] value);
  begin
   @(negedge clk);ar=addr;rv=1;do @(posedge clk);while(!arr);
   @(negedge clk);rv=0;wait(rrv);if(rd!==value)$fatal(1,"register %h got %h expected %h",addr,rd,value);
   @(posedge clk);@(negedge clk);
  end
 endtask
 task automatic pixel(input [31:0] data,input last);
  begin
   @(negedge clk);din=data;vin=1;lin=last;
   do @(posedge clk);while(!rin);
   @(negedge clk);vin=0;
  end
 endtask
 task automatic drain;
  begin wait(head==tail);repeat(5)@(negedge clk);end
 endtask
 integer i,s,begin_cycles,begin_received;
 initial begin
  repeat(5)@(negedge clk);rst=1;read_reg(4,32'h4c540001);
  for(s=0;s<5;s=s+1)begin
   write_strength(s*64,s%3-1);random_stalls=1;
   for(i=0;i<256;i=i+1)pixel({8'ha5,8'(i),8'(i),8'(i)},i==255);
   drain();read_reg(8,s*64);
  end
  write_strength(64,2);pixel(32'h7f204060,0);write_strength(256,-3);
  pixel(32'h7f204060,1);pixel(32'h7f204060,1);drain();
  for(i=0;i<3000;i=i+1)begin
   if(i%97==0)write_strength((i*13)%257,i%3-1);
   pixel(rng,i%31==30||i==2999);
  end
  drain();random_stalls=0;write_strength(128,0);
  @(negedge clk);begin_received=received;begin_cycles=cycles;vin=1;lin=0;
  for(i=0;i<1024;i=i+1)begin
   din=32'h11203040+i;lin=i==1023;
   @(posedge clk);if(!rin)$fatal(1,"not II=1 during ready output");@(negedge clk);
  end
  vin=0;drain();if(received-begin_received!=1024)$fatal(1,"throughput count");
  write_strength(0,0);pixel(32'hff000000,0);pixel(32'hff123456,0);pixel(32'hffffffff,1);drain();
  // Reset during a partial packet, including all held pipeline/parameter state.
  random_stalls=1;pixel(32'h00203040,0);@(negedge clk);rst=0;vin=0;
  repeat(4)@(negedge clk);requested=0;rst=1;random_stalls=0;
  read_reg(0,0);read_reg(8,0);pixel(32'hab123456,1);drain();
  $display("LIGHT27_PASS pixels=%0d cycles=%0d, grayscale/colors/stalls/midpacket/reset/II1",received,cycles);$finish;
 end
 initial begin #10000000;$fatal(1,"timeout");end
endmodule
