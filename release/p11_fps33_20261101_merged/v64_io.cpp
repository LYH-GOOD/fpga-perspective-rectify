// CPU-only P1 adapter. Never writes an FPGA register from a worker thread.
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <initializer_list>
#include <time.h>
#include <stdlib.h>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif
extern "C" int p11_v64_abi(){return 6601;}
static uint8_t sat(int v){return uint8_t(std::max(0,std::min(255,v)));}

static const int rgb_coeff[4][5]={{298,409,100,208,516},{256,359,88,183,454},
                               {298,459,55,136,541},{256,403,48,120,475}};
#ifdef __ARM_NEON
static uint8x8_t rgb_byte(int32x4_t lo,int32x4_t hi){
 lo=vshrq_n_s32(vaddq_s32(lo,vdupq_n_s32(128)),8);
 hi=vshrq_n_s32(vaddq_s32(hi,vdupq_n_s32(128)),8);
 return vqmovn_u16(vcombine_u16(vqmovun_s32(lo),vqmovun_s32(hi)));
}
#endif
template<int channels> static void pack_row(const uint8_t* s,int x0,int w,int mode,uint8_t* d){
 const int* c=rgb_coeff[mode];int x=0;
 auto scalar=[&](int i){int sx=x0+i,p=sx&~1;
  int y=int(s[sx*2])-((mode&1)?0:16),u=int(s[p*2+1])-128,v=int(s[p*2+3])-128;
  d[i*channels]=sat((c[0]*y+c[4]*u+128)>>8);
  d[i*channels+1]=sat((c[0]*y-c[2]*u-c[3]*v+128)>>8);
  d[i*channels+2]=sat((c[0]*y+c[1]*v+128)>>8);
  if(channels==4)d[i*channels+3]=255;
 };
 // An odd crop begins with the second Y of a shared UV pair. Consume that
 // pixel scalarly before the even-aligned eight-pixel vector groups.
 if(x0&1){scalar(x);++x;}
#ifdef __ARM_NEON
 for(;x+8<=w;x+=8){
  uint8x8x2_t z=vld2_u8(s+(x0+x)*2);
  uint8x8x2_t uv=vuzp_u8(z.val[1],z.val[1]);
  uint8x8_t uu=vzip_u8(uv.val[0],uv.val[0]).val[0];
  uint8x8_t vv=vzip_u8(uv.val[1],uv.val[1]).val[0];
  int16x8_t y=vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(z.val[0])),vdupq_n_s16((mode&1)?0:16));
  int16x8_t u=vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(uu)),vdupq_n_s16(128));
  int16x8_t v=vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(vv)),vdupq_n_s16(128));
  int32x4_t yl=vmull_n_s16(vget_low_s16(y),c[0]),yh=vmull_n_s16(vget_high_s16(y),c[0]);
  uint8x8_t blue=rgb_byte(vmlal_n_s16(yl,vget_low_s16(u),c[4]),vmlal_n_s16(yh,vget_high_s16(u),c[4]));
  uint8x8_t red=rgb_byte(vmlal_n_s16(yl,vget_low_s16(v),c[1]),vmlal_n_s16(yh,vget_high_s16(v),c[1]));
  uint8x8_t green=rgb_byte(vmlsl_n_s16(vmlsl_n_s16(yl,vget_low_s16(u),c[2]),vget_low_s16(v),c[3]),
                          vmlsl_n_s16(vmlsl_n_s16(yh,vget_high_s16(u),c[2]),vget_high_s16(v),c[3]));
  if(channels==4){uint8x8x4_t out;out.val[0]=blue;out.val[1]=green;out.val[2]=red;out.val[3]=vdup_n_u8(255);vst4_u8(d+x*4,out);}
  else{uint8x8x3_t out;out.val[0]=blue;out.val[1]=green;out.val[2]=red;vst3_u8(d+x*3,out);}
 }
#endif
 for(;x<w;++x)scalar(x);
}
// 2026-10-24 C2：YUYV 原样搬运（**不做颜色转换**，那步已挪进 PL）。
// 每行一次 memcpy —— 这是整个 C2 的关键：
//   原来是 Python/numpy 的 `dst3[h,w,2][:] = src3[h,w,2]`，numpy 对 3 维跨步
//   赋值**不会**把最后两维合并成"一行拷贝"，退化成逐 2 字节，
//   实测 51,000 px × 95 ns ≈ 4.85 ms（正好等于测到的 4.88 ms）。
//   换成每行 memcpy 后，同样的数据量应在毫秒以下。
// 契约：x0/w 必须为偶数（YUYV 的 U/V 是一对像素共享的，奇数会让整行配对错开）。
extern "C" int p11_v64_copy_rows(const uint8_t* src,int ss,int sw,int sh,
 int x0,int y0,int w,int h,int ds,uint8_t* dst,size_t bytes){
 if(!src||!dst||ss<sw*2||sw<2||sh<2||x0<0||y0<0||w<2||h<1||
    x0+w>sw||y0+h>sh||ds<w*2||(x0&1)||(w&1)||bytes<size_t(ds)*size_t(h-1)+size_t(w)*2)return -1;
 for(int y=0;y<h;++y)
  std::memcpy(dst+size_t(y)*size_t(ds),src+size_t(y+y0)*size_t(ss)+size_t(x0)*2,size_t(w)*2);
 return 0;
}
extern "C" int p11_v64_pack(const uint8_t* src,int stride,int sw,int sh,
 int x0,int y0,int w,int h,int mode,uint8_t* dst,size_t bytes){
 if(!src||!dst||sw<2||sh<2||stride<sw*2||sw%2||x0<0||y0<0||w<2||h<2||
    x0+w>sw||y0+h>sh||mode<0||mode>3||bytes<size_t(w)*h*4)return -1;
 for(int y=0;y<h;++y)pack_row<4>(src+(y+y0)*size_t(stride),x0,w,mode,dst+y*size_t(w)*4);
 return 0;
}
extern "C" int p11_v66_caps(){
#ifdef __ARM_NEON
 return 1;
#else
 return 0;
#endif
}
extern "C" int p11_v66_yuyv_bgr(const uint8_t* src,int stride,int w,int h,int mode,
 uint8_t* dst,int dst_stride,size_t bytes){
 if(!src||!dst||w<2||h<2||(w&1)||stride<w*2||dst_stride<w*3||mode<0||mode>3||
    bytes<size_t(h-1)*dst_stride+size_t(w)*3)return -1;
 for(int y=0;y<h;++y)pack_row<3>(src+y*size_t(stride),0,w,mode,dst+y*size_t(dst_stride));return 0;
}
static void bgra_row(const uint8_t* s,uint8_t* d,int w){
 int x=0;
#ifdef __ARM_NEON
 for(;x+8<=w;x+=8){uint8x8x4_t z=vld4_u8(s+x*4);uint8x8x3_t o;
  o.val[0]=z.val[0];o.val[1]=z.val[1];o.val[2]=z.val[2];vst3_u8(d+x*3,o);}
#endif
 for(;x<w;++x){d[x*3]=s[x*4];d[x*3+1]=s[x*4+1];d[x*3+2]=s[x*4+2];}
}
extern "C" int p11_v66_bgra_bgr(const uint8_t* src,int stride,int w,int h,
 uint8_t* dst,int dst_stride,size_t bytes){
 if(!src||!dst||w<2||h<2||stride<w*4||dst_stride<w*3||
    bytes<size_t(h-1)*dst_stride+size_t(w)*3)return -1;
 for(int y=0;y<h;++y)bgra_row(src+y*size_t(stride),dst+y*size_t(dst_stride),w);return 0;
}

// Current H only: build the local crop, fixed coefficients and immutable
// ten-word packet in one CPU call. This is not a cached H or a safety receipt.
extern "C" int p11_v66_mapping(const double* h,const int32_t* box,int iw,int ih,
 int32_t* out,uint32_t* packet){
 if(!h||!box||!out||!packet||iw<2||ih<2)return -1;
 int x0=box[0],y0=box[1],tw=box[2]-x0,th=box[3]-y0;
 if(x0<0||y0<0||tw<2||th<2||box[2]>4095||box[3]>4095)return -1;
 double local[9];
 for(int r=0;r<3;++r){
  local[r*3]=h[r*3];local[r*3+1]=h[r*3+1];
  local[r*3+2]=h[r*3]*x0+h[r*3+1]*y0+h[r*3+2];
 }
 double xmin=1e100,xmax=-1e100,ymin=1e100,ymax=-1e100;
 for(int y:{0,th-1})for(int x:{0,tw-1}){
  double den=local[6]*x+local[7]*y+local[8];
  if(!std::isfinite(den)||den<=1e-5)return -2;
  double xx=(local[0]*x+local[1]*y+local[2])/den;
  double yy=(local[3]*x+local[4]*y+local[5])/den;
  if(!std::isfinite(xx)||!std::isfinite(yy)||std::abs(xx)>1e8||std::abs(yy)>1e8)return -2;
  xmin=std::min(xmin,xx);xmax=std::max(xmax,xx);ymin=std::min(ymin,yy);ymax=std::max(ymax,yy);
 }
 int cx=std::max(0,int(std::floor(xmin))-3),cy=std::max(0,int(std::floor(ymin))-3);
 int ex=std::min(iw,int(std::ceil(xmax))+4),ey=std::min(ih,int(std::ceil(ymax))+4);
 // 2026-10-24 C2：YUYV 的 U/V 是**一对像素共享**的，行内配对按 x 的奇偶走。
 // 裁剪左边界或宽度为奇数 ⇒ 下一行的配对整体错开 2 字节（整帧颜色错乱）。
 // ⇒ x 方向统一取偶（左边向下、右边向上），最多多 2 列。
 //   高度不用管。iw 是输入宽度，YUYV 下必为偶数。
 if(cx&1)--cx;
 if(ex&1)ex=(ex<iw)?ex+1:ex-1;
 int cw=ex-cx,ch=ey-cy;
 if(cw<2||ch<2)return -3;
 // 2026-10-25：行缓存 MAX_W=640（原 1024）。超了就回绕 —— 必须在这里挡住。
 if(cw>512||ch>4095||uint64_t(cw)*ch*4>=(1u<<23)||uint64_t(tw)*th*4>=(1u<<23))return -4;
 for(int c=0;c<3;++c){local[c]-=cx*local[6+c];local[3+c]-=cy*local[6+c];}
 if(!std::isfinite(local[8])||local[8]<=1e-5)return -2;
 out[0]=cx;out[1]=cy;out[2]=cw;out[3]=ch;
 packet[0]=(uint32_t(cw)<<16)|uint32_t(ch);packet[1]=(uint32_t(tw)<<16)|uint32_t(th);
 for(int k=0;k<8;++k){
  // nearbyint retains the baseline round-to-nearest-even coefficient rule.
  double value=std::nearbyint((local[k]/local[8])*((k==2||k==5)?65536.:134217728.));
  if(!std::isfinite(value)||std::abs(value)>2147483647.)return -5;
  out[4+k]=int32_t(value);packet[2+k]=uint32_t(out[4+k]);
 }
 return 0;
}

static int64_t floor16(int64_t a){return a>=0?a/65536:-((-a+65535)/65536);}
static bool coord(const int32_t* a,int u,int v,int64_t& x,int64_t& y){
 const int64_t xn=floor16(int64_t(a[0])*u*32+int64_t(a[1])*v*32+int64_t(a[2])*65536);
 const int64_t yn=floor16(int64_t(a[3])*u*32+int64_t(a[4])*v*32+int64_t(a[5])*65536);
 const int64_t den=floor16(int64_t(a[6])*u*32+int64_t(a[7])*v*32+(int64_t(1)<<32));
 // Match signed 48-bit operands / signed32 denominator and output, reject truncation.
 if(den<=0||den>INT32_MAX||xn<-(int64_t(1)<<31)||xn>=(int64_t(1)<<31)||
    yn<-(int64_t(1)<<31)||yn>=(int64_t(1)<<31))return false;
 x=(xn*65536)/den;y=(yn*65536)/den;
 return x>=INT32_MIN&&x<=INT32_MAX&&y>=INT32_MIN&&y<=INT32_MAX;
}
extern "C" int p11_v64_guard(const int32_t* a,int iw,int ih,int ow,int oh,int rows,int* out){
 if(!a||!out||iw<2||iw>512||ih<2||ih>4095||ow<2||ow>4095||oh<2||oh>4095||rows!=384)return -1;
 if(ih<=rows){
  // Entire source crop fits: no row can ever be overwritten. Affine operands
  // have extrema at rectangle corners; a positive affine denominator makes
  // the unrounded quotient extrema occur there too. Bound floor/division
  // error over the entire rectangle, rather than sampling interior pixels.
  double min_den=1e100,max_ratio=0.;
  for(int v: {0,oh-1})for(int u: {0,ow-1}){
   int64_t xn=floor16(int64_t(a[0])*u*32+int64_t(a[1])*v*32+int64_t(a[2])*65536);
   int64_t yn=floor16(int64_t(a[3])*u*32+int64_t(a[4])*v*32+int64_t(a[5])*65536);
   int64_t dd=floor16(int64_t(a[6])*u*32+int64_t(a[7])*v*32+(int64_t(1)<<32));
   int64_t x,y;if(!coord(a,u,v,x,y)||dd<1024)return -2;
   min_den=std::min(min_den,double(dd));
   double xr=(double(int64_t(a[0])*u*32+int64_t(a[1])*v*32+int64_t(a[2])*65536))/65536.;
   double yr=(double(int64_t(a[3])*u*32+int64_t(a[4])*v*32+int64_t(a[5])*65536))/65536.;
   double dr=(double(int64_t(a[6])*u*32+int64_t(a[7])*v*32+(int64_t(1)<<32)))/65536.;
   max_ratio=std::max(max_ratio,std::max(std::abs(xr/dr),std::abs(yr/dr)));
   if(xn<-(int64_t(1)<<31)||xn>=(int64_t(1)<<31)||yn<-(int64_t(1)<<31)||yn>=(int64_t(1)<<31))return -2;
  }
  double bound=max_ratio+(max_ratio+1.)/min_den+1./65536.+.0001;
  if(bound>=32767.)return -2;
  out[0]=ih;out[1]=4;return 0;
 }
 // Deterministic fixed-point dry run. Input may run to the current flow limit
 // immediately; this deliberately rejects timing-dependent retention cases.
 int lo=0,last=0,written=std::min(ih,rows),peak=0,prev0=0,prev1=0;
 for(int v=0;v<oh;++v){for(int u=0;u<ow;++u){int64_t x,y;
   if(!coord(a,u,v,x,y)){out[0]=v;out[1]=u;return -2;}
   int y0=int(std::max(int64_t(0),std::min(int64_t(ih-2),floor16(y))));
   int next=(u==0)?((v==0)?y0:std::min(y0,last)):std::min(lo,y0);
   int retained=std::min(y0,std::min(prev0,prev1));
   // The first two samples have no earlier B/C pixels from this frame.
   if(v==0&&u==0)retained=y0;else if(v==0&&u==1)retained=std::min(y0,prev0);
   written=std::max(written,std::min(ih,next+rows));
   if(written>retained+rows){out[0]=v;out[1]=u;return -3;}
   int need=y0+2-next;peak=std::max(peak,need);
   if(need>rows){out[0]=v;out[1]=u;return -4;}
   prev1=prev0;prev0=y0;lo=next;if(u==ow-1)last=y0;
 }}out[0]=peak;out[1]=ow*oh;return 0;
}

// V65 sufficient interval certificate. The exact legacy scanner above is kept
// only as an explicitly selected reference, never as the fast planner fallback.
// An unproved interval is subdivided or rejected; a prefix is never a receipt.
static double guard_clock(clockid_t which){
 timespec t;clock_gettime(which,&t);return t.tv_sec+t.tv_nsec*1e-9;
}
struct GuardState {
 int lo_low,lo_high,last,written_high,prev0,prev1,peak;
 GuardState(int ih,int rows):lo_low(0),lo_high(0),last(0),
  written_high(std::min(ih,rows)),prev0(0),prev1(0),peak(0){}
};
struct IntervalGuard {
 const int32_t* a;int iw,ih,ow,oh,rows,block_width,max_nodes;
 int samples=0,accepted=0,subdivided=0,nodes=0,fail_v=-1,fail_u=-1,code=0;
 double begin_cpu,begin_wall,cpu_limit;
 IntervalGuard(const int32_t* aa,int wi,int hi,int wo,int ho,int rr,
               int bw,int mn,double budget):a(aa),iw(wi),ih(hi),ow(wo),oh(ho),rows(rr),
  block_width(bw),max_nodes(mn),begin_cpu(guard_clock(CLOCK_THREAD_CPUTIME_ID)),
  begin_wall(guard_clock(CLOCK_MONOTONIC)),cpu_limit(budget){}
 bool fail(int c,int u,int v){code=c;fail_u=u;fail_v=v;return false;}
 bool tick(int u,int v){
  if(++nodes>max_nodes)return fail(-5,u,v);
  if(nodes==1||(nodes&31)==0){
   if(guard_clock(CLOCK_THREAD_CPUTIME_ID)-begin_cpu>=cpu_limit ||
      guard_clock(CLOCK_MONOTONIC)-begin_wall>=.20)return fail(-5,u,v);
  }return true;
 }
 bool point(int u,int v,int& yy){
  int64_t x,y;++samples;
  if(!coord(a,u,v,x,y))return fail(-2,u,v);
  yy=int(std::max(int64_t(0),std::min(int64_t(ih-2),floor16(y))));return true;
 }
 bool exact_step(int u,int v,GuardState& st){
  int y;if(!point(u,v,y))return false;
  int low,high;
  if(u==0){low=high=(v==0?y:std::min(y,st.last));}
  else{low=std::min(st.lo_low,y);high=std::min(st.lo_high,y);}
  int retained=std::min(y,std::min(st.prev0,st.prev1));
  if(v==0&&u==0)retained=y;
  else if(v==0&&u==1)retained=std::min(y,st.prev0);
  st.written_high=std::max(st.written_high,std::min(ih,high+rows));
  if(st.written_high>retained+rows)return fail(-3,u,v);
  int need=y+2-low;if(need>rows)return fail(-4,u,v);
  st.peak=std::max(st.peak,need);st.lo_low=low;st.lo_high=high;
  st.prev1=st.prev0;st.prev0=y;return true;
 }
 bool bounds(int u0,int u1,int v,int& ymin,int& ymax){
  // Raw affine operands have extrema at interval endpoints. With positive
  // denominator, each continuous linear-fractional quotient is monotonic.
  // Flooring numerator/denominator changes a ratio by <=(1+|ratio|)/min(d').
  // Quotient truncation adds <=1/65536 pixel. .0001 exceeds rounding error for
  // the admitted |ratio|<32767, |raw|<2^47, d'>=1024 domain (no fast-math).
  double ylo=1e100,yhi=-1e100,max_ratio=0.;int64_t min_den=INT64_MAX;
  for(int u:{u0,u1}){
   int64_t nrx=int64_t(a[0])*u*32+int64_t(a[1])*v*32+int64_t(a[2])*65536;
   int64_t nry=int64_t(a[3])*u*32+int64_t(a[4])*v*32+int64_t(a[5])*65536;
   int64_t dr=int64_t(a[6])*u*32+int64_t(a[7])*v*32+(int64_t(1)<<32);
   int64_t nx=floor16(nrx),ny=floor16(nry),dd=floor16(dr);
   if(dd<1024||dd>INT32_MAX||nx<INT32_MIN||nx>INT32_MAX||ny<INT32_MIN||ny>INT32_MAX)
    return fail(-2,u,v);
   min_den=std::min(min_den,dd);
   double x=double(nrx)/double(dr),y=double(nry)/double(dr);
   ylo=std::min(ylo,y);yhi=std::max(yhi,y);
   max_ratio=std::max(max_ratio,std::max(std::abs(x),std::abs(y)));
  }
  double error=(max_ratio+1.)/double(min_den)+1./65536.+.0001;
  if(!std::isfinite(error)||max_ratio+error>=32767.)return fail(-2,u0,v);
  ymin=int(std::max(0.,std::min(double(ih-2),std::floor(ylo-error))));
  ymax=int(std::max(0.,std::min(double(ih-2),std::floor(yhi+error))));
  // A denominator and source-y numerator constant along u give exactly the
  // same clamped source row, including both fixed-point truncations.
  if(a[3]==0&&a[6]==0){int yy;if(!point(u0,v,yy))return false;ymin=ymax=yy;}
  return true;
 }
 bool block(int u0,int u1,int v,GuardState& st){
  if(!tick(u0,v))return false;
  GuardState original=st;
  // At the first pixel, row-start flow and the two delayed B/C samples are
  // evaluated exactly. Afterwards prefix minima cannot increase within a row.
  if(!exact_step(u0,v,st))return false;
  if(u0==u1)return true;
  int ymin,ymax;if(!bounds(u0+1,u1,v,ymin,ymax))return false;
  int next_low=std::min(st.lo_low,ymin);
  int retained_low=std::min(ymin,std::min(st.prev0,st.prev1));
  int need_high=ymax+2-next_low;
  if(st.written_high<=retained_low+rows&&need_high<=rows){
   int tail0,tail1;
   if(!point(u1,v,tail0))return false;
   if(u1==u0+1)tail1=st.prev0;
   else if(!point(u1-1,v,tail1))return false;
   st.lo_low=next_low;st.lo_high=std::min(st.lo_high,std::min(tail0,tail1));
   st.prev0=tail0;st.prev1=tail1;st.peak=std::max(st.peak,need_high);++accepted;
   return true;
  }
  // Keep the pre-block bounds: an unsuccessful broad interval must not update
  // state. Exact leaf steps remain subject to the same two safety inequalities.
  st=original;++subdivided;int mid=(u0+u1)/2;
  return block(u0,mid,v,st)&&block(mid+1,u1,v,st);
 }
 int run(int* out){
  GuardState st(ih,rows);
  bool okay=true;
  for(int v=0;v<oh&&okay;++v){
   for(int u=0;u<ow;u+=block_width){
    if(!block(u,std::min(ow-1,u+block_width-1),v,st)){okay=false;break;}
   }
   if(okay)st.last=st.prev0;
  }
  out[0]=st.peak;out[1]=samples;out[2]=accepted;out[3]=subdivided;
  out[4]=fail_v;out[5]=fail_u;out[6]=nodes;out[7]=1;
  return okay?0:(code?code:-5);
 }
};
extern "C" int p11_v65_guard_interval(const int32_t* a,int iw,int ih,int ow,int oh,
 int rows,int block_width,int max_nodes,double cpu_budget,int* out){
 if(!a||!out||iw<2||iw>512||ih<2||ih>4095||ow<2||ow>4095||oh<2||oh>4095||
    rows!=384||block_width<8||block_width>128||max_nodes<1||max_nodes>65536||
    !std::isfinite(cpu_budget)||cpu_budget<=0.||cpu_budget>.05)return -1;
 std::fill(out,out+8,0);out[4]=out[5]=-1;
 if(ih<=rows){
  int tmp[2]={0,0};int rc=p11_v64_guard(a,iw,ih,ow,oh,rows,tmp);
  out[0]=tmp[0];out[1]=tmp[1];out[7]=0;return rc;
 }
 IntervalGuard g(a,iw,ih,ow,oh,rows,block_width,max_nodes,cpu_budget);return g.run(out);
}

static double now(){timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
extern "C" int p11_v64_parameters(volatile uint32_t* regs,const uint32_t* packet,uint32_t* out){
 if(!regs||!packet||!out)return -1;
 if(regs[1]&1)return -2;
 for(int i=0;i<10;++i)regs[2+i]=packet[i]; // A32 is deliberately last.
 __sync_synchronize();
 for(int i=0;i<10;++i)if(regs[2+i]!=packet[i]){out[0]=i;return -3;}
 out[0]=regs[1];out[1]=regs[0x34/4]&65535;
 if(!(out[0]&8)||out[0]&1)return -4;return 0;
}
extern "C" int p11_v64_arm(volatile uint32_t* dma,uint32_t receive,uint32_t send,uint32_t nout,uint32_t nin){
 if(!dma||!receive||!send||(receive&3)||(send&3)||!nout||!nin||nout>=(1u<<23)||nin>=(1u<<23))return -1;
 if((dma[1]|dma[0x34/4])&0x71)return -2;
 dma[0x34/4]=0x7000;dma[1]=0x7000;
 dma[0x48/4]=receive;dma[0x4c/4]=0;
 __sync_synchronize();dma[0x58/4]=nout; // Arm receive before starting send.
 dma[0x18/4]=send;dma[0x1c/4]=0;
 __sync_synchronize();dma[0x28/4]=nin;__sync_synchronize();return 0;
}
extern "C" int p11_v64_poll(const volatile uint32_t* dma,const volatile uint32_t* regs,
 uint32_t expected,double seconds,uint32_t* snapshot){
 if(!dma||!regs||!snapshot||seconds<=0)return -1;
 double end=now()+seconds;
 do{uint32_t tx=dma[1],rx=dma[0x34/4],fc=regs[0x34/4]&65535,st=regs[1];
  snapshot[0]=tx;snapshot[1]=rx;snapshot[2]=fc;snapshot[3]=st;
  if((tx|rx)&0x70)return -2;
  // After LENGTH, idle and frame increment, not sticky IOC, prove this ticket.
  if((tx&2)&&(rx&2)&&fc==expected&&!(st&1))return 1;
  timespec delay={0,150000};nanosleep(&delay,nullptr);
 }while(now()<end);return 0;
}


// V70: CPU geometry transaction only. Existing MMIO/owner exports above stay
// untouched. Optional OpenCV uses the same float32 points / LU method as cv2.
#include <array>
#include <cstring>
#include <new>
#ifdef P11_V70_OPENCV
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#endif

struct P70Receipt {
 bool used=false;uint64_t age=0;uint32_t packet[10]={0};int code=0,out[8]={0};
};
struct P70Plan {
 std::array<P70Receipt,128> receipts;uint64_t clock=0,hits=0,misses=0,calls=0;int entries=0;
 P70Receipt* get(const uint32_t* packet){
  for(auto& e:receipts)if(e.used&&std::memcmp(e.packet,packet,40)==0){e.age=++clock;++hits;return &e;}
  ++misses;return nullptr;
 }
 void put(const uint32_t* packet,int code,const int* out){
  if(code==-5)return; // An incomplete CPU/node prefix can never be a receipt.
  P70Receipt* slot=nullptr;
  for(auto& e:receipts){
   if(!e.used){slot=&e;break;}
   if(!slot||e.age<slot->age)slot=&e;
  }
  if(!slot)return;
  if(!slot->used)++entries;
  slot->used=true;slot->age=++clock;slot->code=code;
  std::memcpy(slot->packet,packet,40);std::memcpy(slot->out,out,8*sizeof(int));
 }
};
extern "C" int p11_v70_plan_abi(){return 7001;}
extern "C" int p11_v70_geometry_available(){
#ifdef P11_V70_OPENCV
 return 1;
#else
 return 0;
#endif
}
extern "C" void* p11_v70_plan_create(){
 try{return new P70Plan();}catch(...){return nullptr;}
}
extern "C" void p11_v70_plan_destroy(void* handle){delete static_cast<P70Plan*>(handle);}

// count<=capacity<=32; input boxes have four columns. Outputs have respectively
// 12 mapping words,10 packet words,12 proof words per box. times has16+4*capacity
// doubles. This context belongs to one sequential CPU producer, not the owner.
extern "C" int p11_v70_plan_batch(void* handle,const float* quad,int iw,int ih,int ow,int oh,
 const int32_t* boxes,int count,int capacity,double budget,double* H,int32_t* mappings,
 uint32_t* packets,int32_t* proofs,double* times){
 if(!handle||!quad||!boxes||!H||!mappings||!packets||!proofs||!times||
    iw<2||iw>1024||ih<2||ih>4095||ow<2||ow>4095||oh<2||oh>4095||
    count<1||count>capacity||capacity>32||!std::isfinite(budget)||budget<.002||budget>.03)return -1;
 for(int i=0;i<8;++i)if(!std::isfinite(quad[i]))return -2;
 for(int i=0;i<count;++i){const int32_t* b=boxes+i*4;
  if(b[0]<0||b[1]<0||b[2]>ow||b[3]>oh||b[2]-b[0]<2||b[3]-b[1]<2)return -1;
 }
#ifndef P11_V70_OPENCV
 return -90;
#else
 const double begin=guard_clock(CLOCK_MONOTONIC),cpu=guard_clock(CLOCK_THREAD_CPUTIME_ID);
 std::fill(times,times+16+4*capacity,0.);
 std::fill(proofs,proofs+12*count,0);std::fill(mappings,mappings+12*count,0);
 std::fill(packets,packets+10*count,0);
 P70Plan& ctx=*static_cast<P70Plan*>(handle);++ctx.calls;
 const uint64_t hits=ctx.hits,misses=ctx.misses;
 try{
  const cv::Point2f dst[4]={{0.f,0.f},{float(ow-1),0.f},{float(ow-1),float(oh-1)},{0.f,float(oh-1)}};
  cv::Point2f src[4];for(int i=0;i<4;++i)src[i]=cv::Point2f(quad[2*i],quad[2*i+1]);
  cv::Mat mat=cv::getPerspectiveTransform(dst,src,cv::DECOMP_LU);
  if(mat.rows!=3||mat.cols!=3||mat.type()!=CV_64F)return -2;
  double norm=mat.at<double>(2,2);
  if(!std::isfinite(norm)||std::abs(norm)<1e-12)return -2;
  for(int r=0;r<3;++r)for(int c=0;c<3;++c){
   H[r*3+c]=mat.at<double>(r,c)/norm;if(!std::isfinite(H[r*3+c]))return -2;
  }
 }catch(const cv::Exception&){return -12;}catch(...){return -13;}
 times[0]=guard_clock(CLOCK_MONOTONIC)-begin;times[1]=guard_clock(CLOCK_THREAD_CPUTIME_ID)-cpu;
 double spent=0.;
 for(int i=0;i<count;++i){
  int32_t* m=mappings+i*12;uint32_t* p=packets+i*10;int32_t* meta=proofs+i*12;
  const int32_t* box=boxes+i*4;double* t=times+16+i*4;
  double start=guard_clock(CLOCK_MONOTONIC),used=guard_clock(CLOCK_THREAD_CPUTIME_ID);
  int rc=p11_v66_mapping(H,box,iw,ih,m,p);meta[0]=rc;
  t[0]=guard_clock(CLOCK_MONOTONIC)-start;t[1]=guard_clock(CLOCK_THREAD_CPUTIME_ID)-used;
  times[2]+=t[0];times[3]+=t[1];
  if(rc){meta[1]=-100;continue;}
  int out[8]={0,0,0,0,-1,-1,0,1};bool cached=false;
  P70Receipt* receipt=ctx.get(p);
  if(receipt){rc=receipt->code;std::memcpy(out,receipt->out,sizeof(out));cached=true;}
  else if(m[3]>384&&budget-spent<.0005){rc=-5;}
  else{
   const double limit=std::max(.0005,std::min(.008,budget-spent));
   start=guard_clock(CLOCK_MONOTONIC);used=guard_clock(CLOCK_THREAD_CPUTIME_ID);
   rc=p11_v65_guard_interval(m+4,m[2],m[3],box[2]-box[0],box[3]-box[1],384,128,8192,limit,out);
   t[2]=guard_clock(CLOCK_MONOTONIC)-start;t[3]=guard_clock(CLOCK_THREAD_CPUTIME_ID)-used;
   spent+=t[3];times[4]+=t[2];times[5]+=t[3];ctx.put(p,rc,out);
  }
  meta[1]=rc;meta[2]=cached?1:0;meta[3]=out[0];
  for(int k=1;k<8;++k)meta[3+k]=out[k];
  if(cached){meta[11]=out[1];meta[4]=meta[5]=meta[6]=meta[9]=0;}
 }
 times[6]=guard_clock(CLOCK_MONOTONIC)-begin;times[7]=guard_clock(CLOCK_THREAD_CPUTIME_ID)-cpu;
 times[8]=double(ctx.hits-hits);times[9]=double(ctx.misses-misses);times[10]=ctx.entries;times[11]=count;
 times[12]=double(ctx.hits);times[13]=double(ctx.misses);times[14]=double(ctx.calls);times[15]=spent;
 return 0;
#endif
}


// V71 CPU-only display workspace. No DMA, MMIO or VideoFrame ownership here.
// Convert/clamp source samples BEFORE bilinear interpolation, as in V70.
// Pixel centers use (dst+.5)*src/dst-.5; Q11 x Q11, rounded once at Q22.
#include <vector>
#include <new>
struct V71DisplayScale {
 int sw=0,sh=0,dw=0,dh=0;
 std::vector<int> x0,x1,ax,y0,y1,ay;
 std::vector<uint32_t> horizontal0,horizontal1;
 std::vector<uint16_t> polyphase0,polyphase1;
 std::vector<uint8_t> converted;
 V71DisplayScale():x0(1920),x1(1920),ax(1920),y0(1080),y1(1080),ay(1080),
   horizontal0(1920*3),horizontal1(1920*3),polyphase0(1920*3),polyphase1(1920*3),converted(4096*3){}
};
static double v71_clock(clockid_t id){timespec t;clock_gettime(id,&t);return double(t.tv_sec)+double(t.tv_nsec)*1e-9;}
extern "C" int p11_v71_display_abi(){return 7301;}
extern "C" void* p11_v71_display_create(){try{return new V71DisplayScale();}catch(...){return nullptr;}}
extern "C" void p11_v71_display_destroy(void* p){delete static_cast<V71DisplayScale*>(p);}
static void v71_axis(int source,int target,int* low,int* high,int* weight){
 for(int d=0;d<target;++d){double f=(d+.5)*double(source)/target-.5;
  int i=int(std::floor(f));double part=f-i;
  if(i<0){i=0;part=0.;}if(i>=source-1){i=source-1;part=0.;}
  low[d]=i;high[d]=std::min(source-1,i+1);weight[d]=int(std::floor(part*2048.+.5));
 }
}
static void v71_horizontal(V71DisplayScale* c,const uint8_t* row,int kind,int mode,uint32_t* out){
 const uint8_t* s=row;int channels=4;
 if(kind==2){pack_row<3>(row,0,c->sw,mode,c->converted.data());s=c->converted.data();channels=3;}
 for(int x=0;x<c->dw;++x){int a=c->ax[x],b=2048-a;
  const uint8_t* p=s+c->x0[x]*channels;const uint8_t* q=s+c->x1[x]*channels;
  for(int k=0;k<3;++k)out[x*3+k]=uint32_t(p[k])*b+uint32_t(q[k])*a;
 }
}

// Exact specialization of the V71 Q11 bilinear rule when src/dst ==5/4.
// Center fractions repeat1/8,3/8,5/8,7/8. Cancel256 from each Q11 axis;
// keep Q3 horizontal sums in uint16 and round only after the Q6 vertical sum.
extern "C" int p11_v73_display_caps(){
#ifdef __ARM_NEON
 return 1;
#else
 return 0;
#endif
}
static void v73_horizontal_5_4(V71DisplayScale* c,const uint8_t* row,int mode,uint16_t* out){
 pack_row<3>(row,0,c->sw,mode,c->converted.data());const uint8_t* s=c->converted.data();int x=0;
#ifdef __ARM_NEON
 static const uint8_t il[8]={0,1,2,3,5,6,7,8},ir[8]={1,2,3,4,6,7,8,9};
 static const uint8_t wl[8]={7,5,3,1,7,5,3,1},wr[8]={1,3,5,7,1,3,5,7};
 const uint8x8_t left_index=vld1_u8(il),right_index=vld1_u8(ir),left_weight=vld1_u8(wl),right_weight=vld1_u8(wr);
 for(;x+8<=c->dw&&(x/4)*5+16<=c->sw;x+=8){
  const uint8x16x3_t rgb=vld3q_u8(s+(x/4)*5*3);uint16x8x3_t weighted;
  for(int k=0;k<3;++k){uint8x8x2_t table;table.val[0]=vget_low_u8(rgb.val[k]);table.val[1]=vget_high_u8(rgb.val[k]);
   const uint8x8_t p=vtbl2_u8(table,left_index),q=vtbl2_u8(table,right_index);
   weighted.val[k]=vmlal_u8(vmull_u8(p,left_weight),q,right_weight);
  }vst3q_u16(out+x*3,weighted);
 }
#endif
 // Last vector group is scalar unless all16 loaded source pixels are valid.
 for(;x<c->dw;++x){int i=(x/4)*5+(x&3),a=2*(x&3)+1,b=8-a;
  for(int k=0;k<3;++k)out[x*3+k]=uint16_t(s[i*3+k]*b+s[(i+1)*3+k]*a);
 }
}
//   ⭐ 2026-10-31：5:4 预览改「最近邻」。
//     实测（600P，800x600 -> 640x480）：
//       fused 双线性多相  input_convert 中位 77.2ms，display_thread 54ms，显示 10.0fps
//       crop  1:1 不缩放  input_convert 中位 19.0ms，display_thread 35ms，显示 15.5fps
//     ⇒ 77ms 里有 ~58ms 全是双线性多相的开销（uint16 中间缓冲 + 两次加权混合）。
//     最近邻只要「取源行 + 取源列」，没有中间缓冲、没有混合。
//     ⚠️ 本函数只服务 kind==2（YUYV 原始预览），kind==4（校正图）永远不走这里。
//     开关：P11_PREVIEW_5_4_NEAREST=0 退回原双线性（进程内只读一次）。
static int v73_preview_5_4_nearest(){
 static int on=-1;
 if(on<0){const char* e=getenv("P11_PREVIEW_5_4_NEAREST");on=(e&&e[0]=='0')?0:1;}
 return on;
}
static int v73_resize_5_4_nearest(V71DisplayScale* c,const uint8_t* src,int src_stride,int mode,uint8_t* dst,int dst_stride){
 //   ⚠️ 2026-10-31 修正：第一版每像素做了一次 `x*sw/dw`（64 位除法），
 //      307k 次除法在 Cortex-A9 上 ≈40ms，实测比双线性还慢（114.8ms vs 77.2ms）。
 //      5:4 的映射是定死的：输出 4 个像素 = 源里连续 4 个像素 = 12 字节，
 //      组间步进 5 个源像素（15 字节）。所以内层退化成 12 字节 memcpy，零除法。
 //      源行同理，直接复用 v71_axis 已经算好的 c->y0[]（与 y*sh/dh 对 5:4 完全一致）。
 for(int y=0;y<c->dh;++y){
  const int sy=c->y0[y];
  pack_row<3>(src+size_t(sy)*src_stride,0,c->sw,mode,c->converted.data());
  const uint8_t* s=c->converted.data();uint8_t* d=dst+size_t(y)*dst_stride;
  int x=0;
  for(;x+4<=c->dw;x+=4)memcpy(d+3*x,s+(size_t(x)/4)*15,12);
  for(;x<c->dw;++x){const int i=c->x0[x];d[3*x]=s[3*i];d[3*x+1]=s[3*i+1];d[3*x+2]=s[3*i+2];}
 }
 return c->dh;
}
static int v73_resize_5_4(V71DisplayScale* c,const uint8_t* src,int src_stride,int mode,uint8_t* dst,int dst_stride){
 int loaded[2]={-1,-1},rows=0;uint16_t* buffers[2]={c->polyphase0.data(),c->polyphase1.data()};
 for(int y=0;y<c->dh;++y){int low=(y/4)*5+(y&3),need[2]={low,low+1},slots[2];
  for(int j=0;j<2;++j){int slot=loaded[0]==need[j]?0:loaded[1]==need[j]?1:-1;
   if(slot<0){slot=loaded[0]!=need[1-j]?0:1;
    v73_horizontal_5_4(c,src+size_t(need[j])*src_stride,mode,buffers[slot]);loaded[slot]=need[j];++rows;
   }slots[j]=slot;
  }
  const uint16_t* p=buffers[slots[0]];const uint16_t* q=buffers[slots[1]];
  const uint16_t a=uint16_t(2*(y&3)+1),b=uint16_t(8-a);uint8_t* d=dst+size_t(y)*dst_stride;int i=0,n=c->dw*3;
#ifdef __ARM_NEON
  for(;i+8<=n;i+=8){uint16x8_t sum=vmlaq_n_u16(vmulq_n_u16(vld1q_u16(p+i),b),vld1q_u16(q+i),a);
   sum=vshrq_n_u16(vaddq_u16(sum,vdupq_n_u16(32)),6);vst1_u8(d+i,vmovn_u16(sum));
  }
#endif
  for(;i<n;++i)d[i]=uint8_t((uint32_t(p[i])*b+uint32_t(q[i])*a+32)>>6);
 }return rows;
}

extern "C" int p11_v71_display_scale(void* context,const uint8_t* src,size_t source_bytes,
 int src_stride,int sw,int sh,int kind,int mode,uint8_t* dst,int dst_stride,int dw,int dh,size_t destination_bytes,double* stats){
 if(!context||!src||!dst||!stats||sw<2||sw>4096||sh<2||sh>4096||dw<1||dw>1920||dh<1||dh>1080||
    (kind!=2&&kind!=4)||(kind==2&&(sw&1))||mode<0||mode>3||
    src_stride<sw*kind||dst_stride<dw*3||
    uint64_t(source_bytes)<uint64_t(sh-1)*src_stride+uint64_t(sw)*kind||
    uint64_t(destination_bytes)<uint64_t(dh-1)*dst_stride+uint64_t(dw)*3)return -1;
 double begin=v71_clock(CLOCK_MONOTONIC),cpu=v71_clock(CLOCK_THREAD_CPUTIME_ID);
 V71DisplayScale* c=static_cast<V71DisplayScale*>(context);int rebuilt=0,rows=0,polyphase=0;
 double map_begin=v71_clock(CLOCK_MONOTONIC);
 if(c->sw!=sw||c->sh!=sh||c->dw!=dw||c->dh!=dh){
  c->sw=sw;c->sh=sh;c->dw=dw;c->dh=dh;rebuilt=1;
  v71_axis(sw,dw,c->x0.data(),c->x1.data(),c->ax.data());
  v71_axis(sh,dh,c->y0.data(),c->y1.data(),c->ay.data());
 }
 double map_s=v71_clock(CLOCK_MONOTONIC)-map_begin;
 if(sw==dw&&sh==dh){
  for(int y=0;y<dh;++y){const uint8_t* s=src+size_t(y)*src_stride;uint8_t* d=dst+size_t(y)*dst_stride;
   if(kind==2)pack_row<3>(s,0,sw,mode,d);else bgra_row(s,d,sw);
  }rows=dh;
 }else if(kind==2&&sw*4==dw*5&&sh*4==dh*5&&(dw%4)==0&&(dh%4)==0){
  if(v73_preview_5_4_nearest()>0){rows=v73_resize_5_4_nearest(c,src,src_stride,mode,dst,dst_stride);polyphase=2;}
  else{rows=v73_resize_5_4(c,src,src_stride,mode,dst,dst_stride);polyphase=1;}
 }else{
  int loaded[2]={-1,-1};uint32_t* buffers[2]={c->horizontal0.data(),c->horizontal1.data()};
  for(int y=0;y<dh;++y){int need[2]={c->y0[y],c->y1[y]},slots[2];
   // Retain either source row already horizontally converted in this call.
   for(int j=0;j<2;++j){int slot=loaded[0]==need[j]?0:loaded[1]==need[j]?1:-1;
    if(slot<0){slot=loaded[0]!=need[1-j]?0:1;
     v71_horizontal(c,src+size_t(need[j])*src_stride,kind,mode,buffers[slot]);loaded[slot]=need[j];++rows;
    }slots[j]=slot;
   }
   const uint32_t* p=buffers[slots[0]];const uint32_t* q=buffers[slots[1]];
   uint32_t a=uint32_t(c->ay[y]),b=2048-a;uint8_t* d=dst+size_t(y)*dst_stride;int n=dw*3,i=0;
#ifdef __ARM_NEON
   for(;i+8<=n;i+=8){uint32x4_t lo=vaddq_u32(vmulq_n_u32(vld1q_u32(p+i),b),vmulq_n_u32(vld1q_u32(q+i),a));
    uint32x4_t hi=vaddq_u32(vmulq_n_u32(vld1q_u32(p+i+4),b),vmulq_n_u32(vld1q_u32(q+i+4),a));
    lo=vshrq_n_u32(vaddq_u32(lo,vdupq_n_u32(1u<<21)),22);hi=vshrq_n_u32(vaddq_u32(hi,vdupq_n_u32(1u<<21)),22);
    vst1_u8(d+i,vmovn_u16(vcombine_u16(vmovn_u32(lo),vmovn_u32(hi))));
   }
#endif
   for(;i<n;++i)d[i]=uint8_t((p[i]*b+q[i]*a+(1u<<21))>>22);
  }
 }
 stats[0]=v71_clock(CLOCK_MONOTONIC)-begin;stats[1]=v71_clock(CLOCK_THREAD_CPUTIME_ID)-cpu;
 stats[2]=map_s;stats[3]=rebuilt;stats[4]=rows;stats[5]=sw==dw&&sh==dh;stats[6]=polyphase;return 0;
}
extern "C" int p11_v71_display_copy(const uint8_t* raw,uint8_t* raw_dst,size_t raw_bytes,
 const uint8_t* out,uint8_t* out_dst,size_t out_bytes,double* stats){
 if(!stats||raw_bytes>size_t(4096)*4096*2||out_bytes>size_t(4096)*4096*4||
    (raw_bytes&&(!raw||!raw_dst))||(out_bytes&&(!out||!out_dst)))return -1;
 double t=v71_clock(CLOCK_MONOTONIC),cpu=v71_clock(CLOCK_THREAD_CPUTIME_ID);
 if(raw_bytes)memcpy(raw_dst,raw,raw_bytes);double raw_end=v71_clock(CLOCK_MONOTONIC);
 if(out_bytes)memcpy(out_dst,out,out_bytes);double end=v71_clock(CLOCK_MONOTONIC);
 stats[0]=raw_end-t;stats[1]=end-raw_end;stats[2]=end-t;stats[3]=v71_clock(CLOCK_THREAD_CPUTIME_ID)-cpu;return 0;
}
