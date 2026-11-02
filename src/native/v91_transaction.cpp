// CPU-only V91 orchestration. Calls original verified V74/IO kernels by address.
// No device registers, DMA submission, camera ownership or acceptance waivers.
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <cmath>
#include <algorithm>
#include <vector>
#include <time.h>

using EdgeKernel=int(*)(const uint8_t*,int,int,int,const double*,double,double*,double*);
using SourceKernel=int(*)(const uint8_t*,int,int,int,int,const double*,double,double*,double*);
using PackKernel=int(*)(const uint8_t*,int,int,int,int,int,int,int,int,uint8_t*,size_t);
static double wall(){timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static double cpu(){timespec t;clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec+t.tv_nsec*1e-9;}
extern "C" int p11_v91_abi(){return 9101;}

// CURRENT24 fit .055..945 and independent source64 fit .06..94 retain their
// original kernels and float32 intermediate corners. Python applies every
// original search/polarity/source/independence gate before using these outputs.
extern "C" int p11_v91_postlk(void* edge_function,void* source_function,
 const uint8_t* gray,int gw,int gh,int gs,const uint8_t* raw,int sw,int sh,int rs,int mode,
 const double* proposed,double radius,const double* scale,const int32_t* previous_polarity,double* current,double* edge_stats,
 double* source,double* source_stats,double* meta){
 if(!edge_function||!source_function||!gray||!raw||!proposed||!scale||!previous_polarity||!current||!edge_stats||
    !source||!source_stats||!meta||gw<2||gh<2||gw>4096||gh>4096||gs<gw||
    sw<2||sh<2||sw>4096||sh>4096||(sw&1)||rs<sw*2||mode<0||mode>3||
    !std::isfinite(scale[0])||!std::isfinite(scale[1])||scale[0]<=0||scale[1]<=0)return -1;
 std::fill(meta,meta+8,0.);std::fill(source_stats,source_stats+27,0.);
 double began=wall();
 int code=reinterpret_cast<EdgeKernel>(edge_function)(gray,gw,gh,gs,proposed,radius,current,edge_stats);
 if(code)return code;
 meta[5]=wall()-began;
 // Only a strong complete Y fit can use the fused source-Y route. Other cases
 // return the same first measurement and use the original colour/fallback path.
 bool eligible=radius>3.&&edge_stats[20]!=0.&&edge_stats[16]==4.&&edge_stats[17]==4.;
 double rms=0.;bool bounded_rms=true;
 for(int i=0;i<4;i++){
  eligible=eligible&&edge_stats[i]>=.60&&edge_stats[12+i]<=1.&&edge_stats[4+i]*previous_polarity[i]>=0.;
  bounded_rms=bounded_rms&&std::isfinite(edge_stats[12+i])&&edge_stats[12+i]>=0.&&edge_stats[12+i]<=2.;
  rms=std::max(rms,edge_stats[12+i]);
 }
 if(!eligible)return 0;
 const double lo=std::min(scale[0],scale[1]),hi=std::max(scale[0],scale[1]);
 const double noise=bounded_rms?rms*lo:0.;
 const double half=std::min(6.,std::max(3.,std::max(3.,1.5*lo)+1.25*noise));
 const double narrow=half/hi,actual_half=std::min(24.,std::max(3.,narrow*hi));
 double local[8];
 for(int i=0;i<8;i++){
  // NumPy q is float32: (q + .5) rounds before multiplying float64 scale.
  float shifted=float(current[i])+.5f;
  local[i]=double(shifted)*scale[i&1]-.5;
  if(!std::isfinite(local[i])||local[i]<2.||local[i]>((i&1)?sh-3:sw-3))return 0;
 }
 meta[0]=actual_half;meta[1]=narrow;meta[2]=wall();meta[3]=cpu();
 code=reinterpret_cast<SourceKernel>(source_function)(raw,sw,sh,rs,mode,local,actual_half,source,source_stats);
 meta[6]=wall()-meta[2];meta[7]=cpu()-meta[3];
 if(code==-9)return 0; // Original optional source kernel unavailable.
 if(code)return code;
 meta[4]=1.;return 0;
}

struct PackWorkspace {
 PackKernel kernel;
 std::vector<uint8_t> rows;
 explicit PackWorkspace(PackKernel fn):kernel(fn){}
};
extern "C" void* p11_v91_pack_create(void* function){
 if(!function)return nullptr;
 try{return new PackWorkspace(reinterpret_cast<PackKernel>(function));}catch(...){return nullptr;}
}
extern "C" void p11_v91_pack_destroy(void* handle){delete static_cast<PackWorkspace*>(handle);}

// Each descriptor is x,y,w,h,destination_byte_offset. Destination spans are
// disjoint and the owner has reserved this idle input CMA for the entire call.
extern "C" int p11_v91_pack_batch(void* handle,const uint8_t* raw,int stride,int sw,int sh,int mode,
 const int32_t* descriptors,int count,uint8_t* destination,size_t capacity,double* stats){
 if(!handle||!raw||!descriptors||!destination||!stats||sw<2||sh<2||sw>4096||sh>4096||
    (sw&1)||stride<sw*2||mode<0||mode>3||count<1||count>32)return -1;
 auto* ws=static_cast<PackWorkspace*>(handle);std::fill(stats,stats+10,0.);
 int first=sh,last=0;size_t requested=0;uint64_t overlap_area=0;
 for(int i=0;i<count;i++){
  const int32_t* d=descriptors+5*i;int x=d[0],y=d[1],w=d[2],h=d[3],offset=d[4];
  if(x<0||y<0||w<2||h<2||w>sw||h>sh||x>sw-w||y>sh-h||offset<0||(offset&3))return -2;
  size_t bytes=size_t(w)*size_t(h)*4;
  if(size_t(offset)>capacity||bytes>capacity-size_t(offset))return -3;
  for(int j=0;j<i;j++){
   const int32_t* p=descriptors+5*j;size_t end=size_t(p[4])+size_t(p[2])*p[3]*4;
   if(size_t(offset)<end&&size_t(p[4])<size_t(offset)+bytes)return -4;
   int ow=std::max(0,std::min(x+w,int(p[0]+p[2]))-std::max(x,int(p[0])));
   int oh=std::max(0,std::min(y+h,int(p[1]+p[3]))-std::max(y,int(p[1])));
   overlap_area+=uint64_t(ow)*oh;
  }
  first=std::min(first,y);last=std::max(last,y+h);requested+=size_t(w)*h;
 }
 const uintptr_t src=reinterpret_cast<uintptr_t>(raw),dst=reinterpret_cast<uintptr_t>(destination);
 const size_t source_bytes=size_t(sh-1)*stride+size_t(sw)*2;
 if(src>UINTPTR_MAX-source_bytes||dst>UINTPTR_MAX-capacity||
    (src<dst+capacity&&dst<src+source_bytes))return -5;
 const double began=wall(),started_cpu=cpu();
 try{
  if(overlap_area*10<uint64_t(requested)){
   // Little overlap: original full-crop kernels write directly into each CMA
   // span. Keep one Python/native transaction without extra row copies.
   for(int i=0;i<count;i++){
    const int32_t* d=descriptors+5*i;
    int code=ws->kernel(raw,stride,sw,sh,d[0],d[1],d[2],d[3],mode,
        destination+size_t(d[4]),capacity-size_t(d[4]));
    if(code)return code;
   }
   stats[0]=count;stats[1]=double(requested);stats[2]=double(requested);stats[3]=double(requested)*4;
   stats[4]=wall()-began;stats[5]=cpu()-started_cpu;stats[6]=double(ws->rows.capacity());
   stats[7]=count;stats[8]=0.;stats[9]=double(overlap_area);return 0;
  }
  ws->rows.resize(size_t(sw)*8); // Two reusable BGRX rows, not a full frame.
  for(int y=first;y<last;y+=2){
   int left=sw,right=0,active[32],n=0;size_t row_width_sum=0;
   const int until=std::min(y+2,last);
   for(int i=0;i<count;i++){
    const int32_t* d=descriptors+5*i;
    if(d[1]<until&&d[1]+d[3]>y){active[n++]=i;left=std::min(left,int(d[0]));
     right=std::max(right,int(d[0]+d[2]));row_width_sum+=size_t(d[2]);}
   }
   if(!n)continue;
   if(size_t(right-left)>row_width_sum){
    // Sparse disjoint crops: avoid converting large unused horizontal gaps.
    // One native batch still invokes the original kernel per requested band.
    for(int a=0;a<n;a++){
     const int32_t* d=descriptors+5*active[a];const int cy=std::max(y,int(d[1])),end=std::min(until,int(d[1]+d[3]));
     int sy=std::min(cy,sh-2);int code=ws->kernel(raw,stride,sw,sh,d[0],sy,d[2],2,mode,ws->rows.data(),ws->rows.size());
     if(code)return code;
     for(int row=cy;row<end;row++)memcpy(destination+size_t(d[4])+size_t(row-d[1])*d[2]*4,
         ws->rows.data()+size_t(row-sy)*d[2]*4,size_t(d[2])*4);
     stats[0]+=1;stats[1]+=double(d[2])*2;
    }
   }else{
    const int width=right-left,sy=std::min(y,sh-2);
    int code=ws->kernel(raw,stride,sw,sh,left,sy,width,2,mode,ws->rows.data(),ws->rows.size());
    if(code)return code;
    for(int a=0;a<n;a++){
     const int32_t* d=descriptors+5*active[a];const int cy=std::max(y,int(d[1])),end=std::min(until,int(d[1]+d[3]));
     for(int row=cy;row<end;row++)memcpy(destination+size_t(d[4])+size_t(row-d[1])*d[2]*4,
         ws->rows.data()+(size_t(row-sy)*width+size_t(d[0]-left))*4,size_t(d[2])*4);
    }
    stats[0]+=1;stats[1]+=double(width)*2;
   }
  }
 }catch(...){return -9;}
 stats[2]=double(requested);stats[3]=double(requested)*4;stats[4]=wall()-began;stats[5]=cpu()-started_cpu;
 stats[6]=double(ws->rows.capacity());stats[7]=count;stats[8]=1.;stats[9]=double(overlap_area);return 0;
}
