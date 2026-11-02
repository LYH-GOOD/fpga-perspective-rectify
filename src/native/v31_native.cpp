#include <time.h>
#include <cstring>
#if defined(__linux__)
#include <sys/resource.h>
#endif
struct P11Metric {double wall=0,cpu=0,count=0;double os[4]={0,0,0,0};};
static thread_local P11Metric p11_metrics[30];
static thread_local int p11_depth=0;
static double p11_cpu(){timespec t;clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return double(t.tv_sec)+double(t.tv_nsec)*1e-9;}
static double p11_wall(){timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return double(t.tv_sec)+double(t.tv_nsec)*1e-9;}
static void p11_usage(double* out){
 for(int i=0;i<4;i++)out[i]=0.;
#if defined(__linux__) && defined(RUSAGE_THREAD)
 rusage u;if(getrusage(RUSAGE_THREAD,&u)==0){out[0]=double(u.ru_nvcsw);out[1]=double(u.ru_nivcsw);out[2]=double(u.ru_minflt);out[3]=double(u.ru_majflt);}
#endif
}
struct P11Scope {int id;double wall,cpu;bool outer,os;double usage[4];
 P11Scope(int n):id(n),wall(p11_wall()),cpu(p11_cpu()),outer(p11_depth++==0),os(n==1||n==7||n==17||n==18||n==25||n==26||n==27||n==28||n==29){if(os)p11_usage(usage);}
 ~P11Scope(){double w=p11_wall()-wall,c=p11_cpu()-cpu;--p11_depth;
  p11_metrics[id].wall+=w;p11_metrics[id].cpu+=c;p11_metrics[id].count+=1;
  if(outer){p11_metrics[24].wall+=w;p11_metrics[24].cpu+=c;p11_metrics[24].count+=1;}
  if(os){double current[4];p11_usage(current);for(int i=0;i<4;i++){double d=current[i]-usage[i];p11_metrics[id].os[i]+=d;if(outer)p11_metrics[24].os[i]+=d;}}
 }
};
extern "C" int p11_profile_os_snapshot(double* out,int count){
 if(!out||count!=120)return -1;
 for(int i=0;i<30;i++)for(int j=0;j<4;j++)out[i*4+j]=p11_metrics[i].os[j];
 return 0;
}
// Dependency-free C ABI: bounded edge profiles and fixed-point geometry guard.
// Base helpers need no OpenCV development package; LK/RANSAC are optional.
// MMIO completion polling is owner-only, read-only and bounded; no fast-math.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>
#include <atomic>
#include <chrono>
#include <thread>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif
#ifdef P11_OPENCV_LK
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/video/tracking.hpp>
#include <opencv2/calib3d.hpp>
struct LKCache {
    std::vector<cv::Mat> anchor, current;
    cv::Mat anchor_image;
    int anchor_levels=0,current_levels=0,w=0,h=0;
    bool current_ready=false,allow_retry_cache=false;uint32_t current_generation=0xffffffffu;
    std::vector<cv::Point2f> p,f,b;
    std::vector<uchar> s,sb;
    std::vector<float> e,eb;
    float flow_f[200],flow_b[200],flow_error[100];
    uint8_t flow_s[100],flow_sb[100];
    LKCache(){p.reserve(100);f.reserve(100);b.reserve(100);s.reserve(100);sb.reserve(100);e.reserve(100);eb.reserve(100);}
};
extern "C" void* p11_lk_create(){try{return new LKCache();}catch(...){return nullptr;}}
extern "C" void p11_lk_destroy(void* p){delete static_cast<LKCache*>(p);}
extern "C" int p11_lk_anchor(void* pointer,const uint8_t* gray,int w,int h) { P11Scope profile(0);
    if(!pointer||!gray||w<2||h<2||w>640||h>640)return -1;
    try {
        auto& c=*static_cast<LKCache*>(pointer);
        cv::Mat image(h,w,CV_8UC1,const_cast<uint8_t*>(gray));
        image.copyTo(c.anchor_image);
        c.anchor_levels=-1;c.current_generation=0xffffffffu;
        c.w=w;c.h=h;c.current_ready=false;return 0;
    }catch(...){return -2;}
}
extern "C" int p11_lk_track(void* pointer,const uint8_t* gray,int w,int h,
                            const float* points,int n,float* forward,float* backward,
                            uint8_t* status,uint8_t* reverse_status,float* error,
                            const float* initial,int requested_levels,int iterations) { P11Scope profile(1);
    if(!pointer||!gray||!points||!forward||!backward||!status||!reverse_status||!error||n<4||n>100)return -1;
    try {
        auto& c=*static_cast<LKCache*>(pointer);
        if(w!=c.w||h!=c.h||c.anchor_image.empty()||requested_levels<1||requested_levels>3||iterations<8||iterations>30)return -2;
        if(c.anchor_levels<requested_levels) {
            // Own a snapshot because anchor_image may refer to anchor[0]
            // after promotion and buildOpticalFlowPyramid can replace its output.
            cv::Mat anchor_image=c.anchor_image.clone();
            c.anchor_levels=cv::buildOpticalFlowPyramid(anchor_image,c.anchor,cv::Size(21,21),requested_levels,
                true,cv::BORDER_REFLECT_101,cv::BORDER_CONSTANT,false);
        }
        cv::Mat image(h,w,CV_8UC1,const_cast<uint8_t*>(gray));
        if(!c.allow_retry_cache||!c.current_ready||c.current_levels<requested_levels) {
            c.current_levels=cv::buildOpticalFlowPyramid(image,c.current,cv::Size(21,21),requested_levels,
                true,cv::BORDER_REFLECT_101,cv::BORDER_CONSTANT,false);
        }
        auto& p=c.p;auto& f=c.f;auto& b=c.b;p.resize(n);f.clear();b.clear();
        for(int i=0;i<n;i++)p[i]=cv::Point2f(points[i*2],points[i*2+1]);
        auto& s=c.s;auto& sb=c.sb;auto& e=c.e;auto& eb=c.eb;s.clear();sb.clear();e.clear();eb.clear();
        auto criteria=cv::TermCriteria(cv::TermCriteria::COUNT|cv::TermCriteria::EPS,iterations,.02);
        int flags=0;
        if(initial) {
            f.resize(n);
            for(int i=0;i<n;i++) {
                if(!std::isfinite(initial[2*i])||!std::isfinite(initial[2*i+1]))return -5;
                f[i]=cv::Point2f(initial[2*i],initial[2*i+1]);
            }
            flags=cv::OPTFLOW_USE_INITIAL_FLOW;
        }
        int levels=std::min(requested_levels,std::min(c.anchor_levels,c.current_levels));
        cv::calcOpticalFlowPyrLK(c.anchor,c.current,p,f,s,e,cv::Size(21,21),levels,criteria,flags);
        b=p;
        cv::calcOpticalFlowPyrLK(c.current,c.anchor,f,b,sb,eb,cv::Size(21,21),levels,criteria,cv::OPTFLOW_USE_INITIAL_FLOW);
        if(int(f.size())!=n||int(b.size())!=n)return -3;
        for(int i=0;i<n;i++){
            forward[i*2]=f[i].x;forward[i*2+1]=f[i].y;
            backward[i*2]=b[i].x;backward[i*2+1]=b[i].y;
            status[i]=s[i];reverse_status[i]=sb[i];error[i]=e[i];
        }
        c.current_ready=true;return 0;
    }catch(...){return -4;}
}
extern "C" int p11_lk_promote(void* pointer) { P11Scope profile(2);
    if(!pointer)return -1;
    auto& c=*static_cast<LKCache*>(pointer);
    if(!c.current_ready)return -2;
    c.anchor.swap(c.current);c.anchor_levels=c.current_levels;c.anchor_image=c.anchor[0];c.current_ready=false;
    return 0;
}
extern "C" int p11_lk_available(){return 1;}
#else
extern "C" int p11_lk_available(){return 0;}
#endif
struct Point { double x,y; };
static double med(double* a,int n) {
    double b[25]; std::copy(a,a+n,b); std::sort(b,b+n);
    return n%2?b[n/2]:(b[n/2-1]+b[n/2])*.5;
}
static double sample(const uint8_t* g,int w,int h,int stride,double x,double y) {
    // OpenCV INTER_LINEAR's 1/32 lookup and BORDER_REPLICATE, 8-bit destination.
    int sx=int(std::nearbyint(float(x)*32.f)),sy=int(std::nearbyint(float(y)*32.f));
    int ix=int(std::floor(sx/32.)),iy=int(std::floor(sy/32.));
    int fx=sx-ix*32,fy=sy-iy*32;
    int x0=std::max(0,std::min(w-1,ix)), x1=std::max(0,std::min(w-1,ix+1));
    int y0=std::max(0,std::min(h-1,iy)), y1=std::max(0,std::min(h-1,iy+1));
    int sum=(g[y0*stride+x0]*(32-fx)+g[y0*stride+x1]*fx)*(32-fy)
           +(g[y1*stride+x0]*(32-fx)+g[y1*stride+x1]*fx)*fy;
    return (sum+512)>>10;
}
static bool tls(const std::vector<Point>& p,double* line,double& rms) {
    if(p.size()<2)return false;
    double mx=0,my=0,xx=0,xy=0,yy=0;
    for(auto a:p){mx+=a.x;my+=a.y;}mx/=p.size();my/=p.size();
    for(auto a:p){double x=a.x-mx,y=a.y-my;xx+=x*x;xy+=x*y;yy+=y*y;}
    double gap=std::hypot(xx-yy,2*xy);
    if(!std::isfinite(gap)||gap<=1e-10*(xx+yy+1))return false;
    double theta=.5*std::atan2(2*xy,xx-yy),nx=-std::sin(theta),ny=std::cos(theta);
    line[0]=nx;line[1]=ny;line[2]=-nx*mx-ny*my;
    double sum=0;for(auto a:p){double d=nx*a.x+ny*a.y+line[2];sum+=d*d;}
    rms=std::sqrt(sum/p.size());return std::isfinite(rms);
}
extern "C" int p11_v31_abi(){return 3107;}
extern "C" int p11_gray_backend(){
#ifdef __ARM_NEON
    return 2;
#else
    return 1;
#endif
}
// The common 544x960 -> 272x480 observation uses every source pixel.
// Average EACH BGR channel with AREA-2x rounding, then BT.601 gray.
// This keeps the original resize-before-gray order and pixel-centre geometry.
extern "C" int p11_gray2(const uint8_t* bgr,int w,int h,int stride,uint8_t* gray) { P11Scope profile(3);
    if(!bgr||!gray||w<4||h<4||w>8192||h>8192||(w&1)||(h&1)||stride<w*3)return -1;
    const int ow=w/2;
    for(int y=0;y<h/2;y++) {
        const uint8_t* a=bgr+(2*y)*stride;
        const uint8_t* b=a+stride;
        uint8_t* dst=gray+y*ow;
        int x=0;
#ifdef __ARM_NEON
        for(;x+8<=ow;x+=8) {
            uint8x16x3_t ra=vld3q_u8(a+x*6),rb=vld3q_u8(b+x*6);
            uint16x8_t avg[3];
            for(int c=0;c<3;c++) {
                uint16x8_t sum=vaddq_u16(vpaddlq_u8(ra.val[c]),vpaddlq_u8(rb.val[c]));
                avg[c]=vshrq_n_u16(vaddq_u16(sum,vdupq_n_u16(2)),2);
            }
            uint32x4_t lo=vmull_n_u16(vget_low_u16(avg[0]),3735);
            uint32x4_t hi=vmull_n_u16(vget_high_u16(avg[0]),3735);
            lo=vmlal_n_u16(lo,vget_low_u16(avg[1]),19235);
            hi=vmlal_n_u16(hi,vget_high_u16(avg[1]),19235);
            lo=vmlal_n_u16(lo,vget_low_u16(avg[2]),9798);
            hi=vmlal_n_u16(hi,vget_high_u16(avg[2]),9798);
            lo=vshrq_n_u32(vaddq_u32(lo,vdupq_n_u32(16384)),15);
            hi=vshrq_n_u32(vaddq_u32(hi,vdupq_n_u32(16384)),15);
            vst1_u8(dst+x,vmovn_u16(vcombine_u16(vmovn_u32(lo),vmovn_u32(hi))));
        }
#endif
        for(;x<ow;x++) {
            int i=x*6;
            int blue=(a[i]+a[i+3]+b[i]+b[i+3]+2)>>2;
            int green=(a[i+1]+a[i+4]+b[i+1]+b[i+4]+2)>>2;
            int red=(a[i+2]+a[i+5]+b[i+2]+b[i+5]+2)>>2;
            dst[x]=uint8_t((blue*3735+green*19235+red*9798+16384)>>15);
        }
    }
    return 0;
}

static void horizontal3(const uint8_t* src,int w,uint16_t* dst) {
    dst[0]=uint16_t(86*src[1]+170*src[0]);int x=1;
#ifdef __ARM_NEON
    for(;x+8<w;x+=8) {
        uint16x8_t a=vmovl_u8(vld1_u8(src+x-1)),b=vmovl_u8(vld1_u8(src+x)),c=vmovl_u8(vld1_u8(src+x+1));
        uint16x8_t sum=vaddq_u16(vmulq_n_u16(vaddq_u16(a,c),43),vmulq_n_u16(b,170));
        vst1q_u16(dst+x,sum);
    }
#endif
    for(;x<w-1;x++)dst[x]=uint16_t(43*(src[x-1]+src[x+1])+170*src[x]);
    dst[w-1]=uint16_t(86*src[w-2]+170*src[w-1]);
}
// OpenCV 4.5.4 8-bit fixed Gaussian for size3/sigma0.6:
// [43,170,43]/256 in each axis, REFLECT_101, ONE rounding after both axes.
// Caller owns 3*w uint16 scratch. Output is separate, never aliases LK anchor.
extern "C" int p11_gaussian3(const uint8_t* src,int w,int h,int stride,uint16_t* rows,uint8_t* dst) { P11Scope profile(4);
    if(!src||!rows||!dst||w<2||h<2||w>640||h>640||stride<w)return -1;
    horizontal3(src,w,rows);horizontal3(src+stride,w,rows+w);
    for(int y=0;y<h;y++) {
        if(y+1<h&&y>=1)horizontal3(src+(y+1)*stride,w,rows+((y+1)%3)*w);
        const uint16_t* a=rows+((y==0?1:y-1)%3)*w;
        const uint16_t* b=rows+(y%3)*w;
        const uint16_t* c=rows+((y==h-1?h-2:y+1)%3)*w;
        uint8_t* out=dst+y*w;int x=0;
#ifdef __ARM_NEON
        for(;x+8<=w;x+=8) {
            uint16x8_t aa=vld1q_u16(a+x),bb=vld1q_u16(b+x),cc=vld1q_u16(c+x);
            uint32x4_t lo=vmull_n_u16(vget_low_u16(aa),43),hi=vmull_n_u16(vget_high_u16(aa),43);
            lo=vmlal_n_u16(lo,vget_low_u16(bb),170);hi=vmlal_n_u16(hi,vget_high_u16(bb),170);
            lo=vmlal_n_u16(lo,vget_low_u16(cc),43);hi=vmlal_n_u16(hi,vget_high_u16(cc),43);
            lo=vshrq_n_u32(vaddq_u32(lo,vdupq_n_u32(32768)),16);
            hi=vshrq_n_u32(vaddq_u32(hi,vdupq_n_u32(32768)),16);
            vst1_u8(out+x,vmovn_u16(vcombine_u16(vmovn_u32(lo),vmovn_u32(hi))));
        }
#endif
        for(;x<w;x++)out[x]=uint8_t((uint32_t(a[x])*43+uint32_t(b[x])*170+uint32_t(c[x])*43+32768)>>16);
    }
    return 0;
}

static double quad_area(const double* q) {
    double a=0.;for(int i=0;i<4;i++){int j=(i+1)%4;a+=q[i*2]*q[j*2+1]-q[i*2+1]*q[j*2];}return std::abs(a)*.5;
}
extern "C" int p11_quad_valid(const double* q,int w,int h,const double* previous) { P11Scope profile(5);
    if(!q||w<2||h<2)return -1;
    for(int i=0;i<4;i++) {
        if(!std::isfinite(q[2*i])||!std::isfinite(q[2*i+1])||q[2*i]<0||q[2*i+1]<0||q[2*i]>w-1||q[2*i+1]>h-1)return 0;
        int j=(i+1)%4,k=(i+2)%4;
        double cross=(q[j*2]-q[i*2])*(q[k*2+1]-q[j*2+1])-(q[j*2+1]-q[i*2+1])*(q[k*2]-q[j*2]);
        if(!(cross>0))return 0;
    }
    double area=quad_area(q);if(area<.035*w*h)return 0;
    if(previous) {
        for(int i=0;i<8;i++)if(!std::isfinite(previous[i]))return 0;
        double ratio=area/std::max(quad_area(previous),1.);
        if(!(ratio>.55&&ratio<1.8))return 0;
    }
    return 1;
}
static bool spatial(const float* points,int n,const double* q) {
    if(n<4||n>100)return false;
    std::vector<Point> p(n),hull(2*n);
    for(int i=0;i<n;i++) {
        if(!std::isfinite(points[2*i])||!std::isfinite(points[2*i+1]))return false;
        p[i]={points[2*i],points[2*i+1]};
    }
    std::sort(p.begin(),p.end(),[](const Point& a,const Point& b){return a.x<b.x||(a.x==b.x&&a.y<b.y);});
    auto cross=[](Point a,Point b,Point c){return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);};
    int k=0;
    for(int i=0;i<n;i++){while(k>=2&&cross(hull[k-2],hull[k-1],p[i])<=0)k--;hull[k++]=p[i];}
    for(int i=n-2,t=k+1;i>=0;i--){while(k>=t&&cross(hull[k-2],hull[k-1],p[i])<=0)k--;hull[k++]=p[i];}
    if(k<4)return false;k--;
    double area=0.;for(int i=0;i<k;i++){Point a=hull[i],b=hull[(i+1)%k];area+=a.x*b.y-a.y*b.x;}
    if(std::abs(area)*.5<.25*std::max(quad_area(q),1.))return false;
    bool seen[4]={false,false,false,false};
    for(int i=0;i<n;i++) {
        double best=1e300;int nearest=0;
        for(int j=0;j<4;j++) {
            int z=(j+1)%4;double dx=q[2*z]-q[2*j],dy=q[2*z+1]-q[2*j+1];
            double px=points[2*i]-q[2*j],py=points[2*i+1]-q[2*j+1];
            double t=std::max(0.,std::min(1.,(px*dx+py*dy)/std::max(dx*dx+dy*dy,1e-6)));
            double dist=(px-t*dx)*(px-t*dx)+(py-t*dy)*(py-t*dy);
            if(dist<best){best=dist;nearest=j;}
        }
        seen[nearest]=true;
    }
    int count=0;for(bool b:seen)count+=b;
    return count>=3||n==4;
}
extern "C" int p11_spatial(const float* points,int n,const double* q) { P11Scope profile(6);
    if(!points||!q||n<0||n>100)return -1;
    for(int i=0;i<8;i++)if(!std::isfinite(q[i]))return 0;
    try{return spatial(points,n,q)?1:0;}catch(...){return -2;}
}

#ifdef P11_OPENCV_LK
static thread_local double p11_lk_motion_info[4]={0,0,0,0};
extern "C" int p11_filter_available(){return 1;}
extern "C" int p11_lk_filter(const float* p,const float* f,const float* b,
        const uint8_t* status,const uint8_t* reverse,const float* error,int n,
        const double* anchor_q,const double* previous,int w,int h,
        float* result,float* retained,double* stats) { P11Scope profile(7);
    if(!p||!f||!b||!status||!reverse||!error||!anchor_q||!previous||!result||!retained||!stats||n<4||n>100)return -1;
    try {
        static thread_local std::vector<cv::Point2f> a,z;
        static thread_local std::vector<double> fb;
        a.clear();z.clear();fb.clear();a.reserve(100);z.reserve(100);fb.reserve(100);
        for(int i=0;i<n;i++) {
            double d=std::hypot(double(b[2*i])-p[2*i],double(b[2*i+1])-p[2*i+1]);
            if(status[i]&&reverse[i]&&std::isfinite(d)&&d<1.4&&std::isfinite(error[i])&&error[i]<30&&
               std::isfinite(f[2*i])&&std::isfinite(f[2*i+1])) {
                a.emplace_back(p[2*i],p[2*i+1]);z.emplace_back(f[2*i],f[2*i+1]);fb.push_back(d);
            }
        }
        std::fill(p11_lk_motion_info,p11_lk_motion_info+4,0.);
        p11_lk_motion_info[1]=a.size();
        if(a.size()<4)return -2;
        static thread_local cv::Mat mask;
        cv::Mat H;
        bool low_points=a.size()<8;
        if(!low_points) {
            H=cv::findHomography(a,z,cv::RANSAC,1.6,mask,1000,.99);
            if(!H.empty()&&!mask.empty()&&cv::countNonZero(mask)<8)low_points=true;
        }
        if(low_points) {
            // Proposal only: CURRENT exterior gates remain mandatory.
            cv::Mat affine=cv::estimateAffinePartial2D(a,z,mask,cv::RANSAC,1.6,1000,.99,10);
            if(affine.empty())return -3;
            H=cv::Mat::eye(3,3,CV_64F);
            affine.copyTo(H(cv::Rect(0,0,3,2)));
            p11_lk_motion_info[0]=1.;
        }else p11_lk_motion_info[0]=2.;
        if(H.empty()||mask.empty()||!cv::checkRange(H))return -3;
        static thread_local std::vector<float> original;original.clear();original.reserve(200);int kept=0;
        for(unsigned i=0;i<a.size();i++)if(mask.ptr<uint8_t>()[i]) {
            original.push_back(a[i].x);original.push_back(a[i].y);
            retained[2*kept]=z[i].x;retained[2*kept+1]=z[i].y;kept++;
        }
        double fraction=double(kept)/a.size();
        p11_lk_motion_info[2]=kept;
        if(kept<4||fraction<.65||!spatial(original.data(),kept,anchor_q))return -4;
        double residual2=0.;const double* hm=H.ptr<double>();
        for(unsigned i=0;i<a.size();i++)if(mask.ptr<uint8_t>()[i]) {
            double den=hm[6]*a[i].x+hm[7]*a[i].y+hm[8];
            if(!std::isfinite(den)||std::abs(den)<1e-9)return -5;
            double dx=(hm[0]*a[i].x+hm[1]*a[i].y+hm[2])/den-z[i].x;
            double dy=(hm[3]*a[i].x+hm[4]*a[i].y+hm[5])/den-z[i].y;
            residual2+=dx*dx+dy*dy;
        }
        p11_lk_motion_info[3]=std::sqrt(residual2/kept);
        if(!std::isfinite(p11_lk_motion_info[3])||p11_lk_motion_info[3]>1.6)return -4;
        double q[8];const double* mat=H.ptr<double>();
        for(int i=0;i<4;i++) {
            double den=mat[6]*anchor_q[2*i]+mat[7]*anchor_q[2*i+1]+mat[8];
            if(!std::isfinite(den)||std::abs(den)<1e-9)return -5;
            // Same float destination as cv::perspectiveTransform on Point2f.
            result[2*i]=float((mat[0]*anchor_q[2*i]+mat[1]*anchor_q[2*i+1]+mat[2])/den);
            result[2*i+1]=float((mat[3]*anchor_q[2*i]+mat[4]*anchor_q[2*i+1]+mat[5])/den);
            q[2*i]=result[2*i];q[2*i+1]=result[2*i+1];
        }
        if(p11_quad_valid(q,w,h,previous)!=1)return -6;
        std::sort(fb.begin(),fb.end());int k=fb.size();
        stats[0]=n;stats[1]=a.size();stats[2]=fraction;
        stats[3]=k%2?fb[k/2]:(fb[k/2-1]+fb[k/2])*.5;stats[4]=kept;return 0;
    }catch(...){return -7;}
}
#else
extern "C" int p11_filter_available(){return 0;}
#endif
extern "C" int p11_edges(const uint8_t* gray,int w,int h,int stride,const double* q,
                          double radius,double* result,double* stats) { P11Scope profile(8);
    if(!gray||!q||!result||!stats||w<2||h<2||w>4096||h>4096||stride<w||
       !std::isfinite(radius)||radius<1||radius>12)return -1;
    for(int i=0;i<8;i++)if(!std::isfinite(q[i])||std::abs(q[i])>8192)return -2;
    std::copy(q,q+8,result);std::fill(stats,stats+20,0.);
    double cx=0,cy=0;for(int i=0;i<4;i++){cx+=q[i*2];cy+=q[i*2+1];}cx/=4;cy/=4;
    double lines[4][3];bool supported[4]={false,false,false,false};
    for(int i=0;i<4;i++) {
        int j=(i+1)%4;double ax=q[i*2],ay=q[i*2+1],ex=q[j*2]-ax,ey=q[j*2+1]-ay;
        double len=std::hypot(ex,ey);if(len<1e-6)continue;
        double nx=-ey/len,ny=ex/len;
        if((cx-ax-ex*.5)*nx+(cy-ay-ey*.5)*ny<0){nx=-nx;ny=-ny;}
        static thread_local std::vector<Point> point_pool[4],keep_pool[4];
        auto& points=point_pool[i];auto& keep=keep_pool[i];points.clear();keep.clear();points.reserve(24);keep.reserve(24);
        double shifts[24],contrasts[24];int count=0,first=-1,last=-1;
        for(int k=0;k<24;k++) {
            double t=.055+.89*k/23.,bx=ax+t*ex,by=ay+t*ey,profile[25];
            for(int z=0;z<25;z++){double d=-radius+2*radius*z/24.;profile[z]=sample(gray,w,h,stride,bx+d*nx,by+d*ny);}
            double outer=med(profile,4),inner=med(profile+21,4),contrast=inner-outer;
            contrasts[k]=contrast;double level=(inner+outer)*.5,sign=contrast>=0?1.:-1.;
            double best=1e30,shift=0;bool crossing=false;
            for(int z=0;z<24;z++){
                double a=(profile[z]-level)*sign,b=(profile[z+1]-level)*sign;
                double mid=-radius+2*radius*(z+.5)/24.;
                if(a<=0&&b>0&&std::abs(mid)<best){best=std::abs(mid);crossing=true;
                    double alpha=std::max(0.,std::min(1.,-a/std::max(b-a,1e-6)));
                    shift=-radius+2*radius*(z+alpha)/24.;}
            }
            if(crossing&&std::abs(contrast)>=8&&std::abs(shift)<radius*.85){
                points.push_back({bx+shift*nx,by+shift*ny});shifts[count++]=std::abs(shift);
                if(first<0)first=k;last=k;
            }
        }
        double c=med(contrasts,24);stats[4+i]=std::abs(c)>=8?(c>0?1:-1):0;
        stats[8+i]=count?med(shifts,count):radius;
        double rms=1e30;
        if(count>=10&&(last-first)*.89/23.>=.55){
            for(int iteration=0;iteration<2;iteration++){
                if(!tls(points,lines[i],rms))break;
                double residual[24];for(unsigned k=0;k<points.size();k++)residual[k]=std::abs(lines[i][0]*points[k].x+lines[i][1]*points[k].y+lines[i][2]);
                double threshold=std::max(.6,2.5*med(residual,points.size()));
                keep.clear();for(unsigned k=0;k<points.size();k++)if(residual[k]<=threshold)keep.push_back(points[k]);
                if(keep.size()==points.size()||keep.size()<8)break;points.swap(keep);
            }
            if(tls(points,lines[i],rms)&&rms<=1.25){supported[i]=true;stats[i]=count/24.;}
        }
        stats[12+i]=rms;
    }
    int refined=0,edges=0;
    for(int i=0;i<4;i++){
        if(stats[i]>=.42)edges++;
        int j=(i+3)%4;if(!supported[j]||!supported[i])continue;
        double a=lines[j][0],b=lines[j][1],c=lines[j][2],d=lines[i][0],e=lines[i][1],f=lines[i][2];
        double det=a*e-b*d;if(std::abs(det)<=.06)continue;
        double x=(b*f-c*e)/det,y=(c*d-a*f)/det;
        if(std::hypot(x-q[i*2],y-q[i*2+1])<radius*2.8){result[i*2]=x;result[i*2+1]=y;refined++;}
    }
    stats[16]=refined;stats[17]=edges;return 0;
}
extern "C" int p11_guard(const int32_t* regs,const int32_t* field,const int32_t* uv,
                         int count,double* xy) { P11Scope profile(9);
    if(!regs||!field||!uv||!xy||count<1||count>20000)return -1;
    const int64_t a=regs[0],b=regs[1],c=regs[2],d=regs[3],e=regs[4],f=regs[5],g=regs[6],h=regs[7];
    for(int k=0;k<count;k++){
        int u=uv[k*2],v=uv[k*2+1];if(u<0||v<0||u>=1280||v>=1280)return -2;
        int64_t den=(g*u*32+h*v*32+(int64_t(1)<<32))>>16;
        int64_t xn=(a*u*32+b*v*32+c*65536)>>16,yn=(d*u*32+e*v*32+f*65536)>>16;
        if(den<16384||den>=(int64_t(1)<<31)||xn<INT32_MIN||xn>INT32_MAX||yn<INT32_MIN||yn>INT32_MAX)return -3;
        int cell=(v/64*21+u/64)*4,fx=u%64,fy=v%64;
        for(int axis=0;axis<2;axis++){
            int64_t tl=field[cell+axis],tr=field[cell+4+axis],bl=field[cell+84+axis],br=field[cell+88+axis];
            int64_t local=(((tl*(64-fx)+tr*fx)*(64-fy)+(bl*(64-fx)+br*fx)*fy)>>12);
            int64_t q=(axis==0?xn:yn)*65536/den+local*256;
            if(q<INT32_MIN||q>INT32_MAX)return -4;
            xy[k*2+axis]=q/65536.;
        }
    }
    return 0;
}

static bool project_checked(const double* H,double u,double v,double& x,double& y) {
    double den=H[6]*u+H[7]*v+H[8];
    if(!std::isfinite(den)||den<=1e-7)return false;
    x=(H[0]*u+H[1]*v+H[2])/den;y=(H[3]*u+H[4]*v+H[5])/den;
    return std::isfinite(x)&&std::isfinite(y);
}
// Paper-coordinate spline samples are immutable between surface refreshes.
// H is applied AGAIN for every frame, including every quality guard sample.
// Same signed32/range checks, Q8 rounding and 16px sample error as V17.
static int p11_plan_geometry_core(const double* H,const int32_t* regs,
        const double* paper_nodes,int nx,int ny,const int32_t* uv,
        const double* paper_samples,int count,int32_t* field,double* residual,
        std::vector<double>& actual) { P11Scope profile(10);
    if(!H||!regs||!paper_nodes||!uv||!paper_samples||!field||!residual||
       nx<2||nx>21||ny<2||ny>21||count<1||count>20000)return -10;
    try {
    for(int i=0;i<9;i++)if(!std::isfinite(H[i]))return -11;
    for(int j=0;j<ny;j++)for(int i=0;i<nx;i++) {
        int k=(j*nx+i)*2;double tx,ty,bx,by;
        if(!project_checked(H,paper_nodes[k],paper_nodes[k+1],tx,ty)||
           !project_checked(H,i*64.,j*64.,bx,by))return -12;
        double dx=std::nearbyint((tx-bx)*256.),dy=std::nearbyint((ty-by)*256.);
        if(std::abs(dx)>32768||std::abs(dy)>32768)return -13;
        int cell=(j*21+i)*4;
        field[cell]=int32_t(dx);field[cell+1]=int32_t(dy);
        field[cell+2]=256;field[cell+3]=0;
    }
    for(int j=0;j<21;j++)for(int i=0;i<21;i++) {
        if(i<nx&&j<ny)continue;
        int cell=(j*21+i)*4,from=(std::min(j,ny-1)*21+std::min(i,nx-1))*4;
        std::copy(field+from,field+from+4,field+cell);
    }
    // The chronological fused producer retains this capacity across frames.
    // Contents are overwritten by the exact fixed arithmetic guard every time.
    actual.resize(count*2);
    int code=p11_guard(regs,field,uv,count,actual.data());
    if(code)return code;
    double maximum=0.;
    for(int k=0;k<count;k++) {
        double tx,ty;
        if(!project_checked(H,paper_samples[k*2],paper_samples[k*2+1],tx,ty))return -14;
        double d=std::hypot(actual[k*2]-tx,actual[k*2+1]-ty);
        if(!std::isfinite(d))return -15;
        maximum=std::max(maximum,d);
    }
    *residual=maximum;return 0;
    }catch(...){return -16;}
}
extern "C" int p11_plan_geometry(const double* H,const int32_t* regs,
        const double* paper_nodes,int nx,int ny,const int32_t* uv,
        const double* paper_samples,int count,int32_t* field,double* residual) {
    std::vector<double> actual;
    return p11_plan_geometry_core(H,regs,paper_nodes,nx,ny,uv,paper_samples,
                                 count,field,residual,actual);
}

// Encode exactly the existing normalized inverse H, then check its four
// extrema with the same fixed arithmetic before adding nonlinear nodes.
extern "C" int p11_prepare(const double* H,int w,int h,int32_t* regs) { P11Scope profile(11);
    if(!H||!regs||w<2||h<2||w>1280||h>1280)return -1;
    const int indexes[8]={0,1,2,3,4,5,6,7};
    for(int j=0;j<8;j++) {
        double value=H[indexes[j]]*65536.;
        if(j!=2&&j!=5)value*=2048.;
        value=std::nearbyint(value);
        if(!std::isfinite(value)||value<INT32_MIN||value>INT32_MAX)return -2;
        regs[j]=int32_t(value);
    }
    int32_t field[21*21*4]={0};
    for(int j=0;j<441;j++)field[j*4+2]=256;
    int32_t uv[8]={0,0,w-1,0,w-1,h-1,0,h-1};double xy[8];
    return p11_guard(regs,field,uv,4,xy);
}
extern "C" int p11_packet(const int32_t* field,const int32_t* regs,
        int wi,int hi,int wo,int ho,int flags,uint32_t* packet) { P11Scope profile(12);
    if(!field||!regs||!packet||std::min(std::min(wi,hi),std::min(wo,ho))<2||
       std::max(std::max(wi,hi),std::max(wo,ho))>1280||flags<0||flags>15)return -1;
    for(int j=0;j<441;j++) {
        const int32_t* f=field+j*4;
        if(int64_t(f[0])<-32768||int64_t(f[0])>32768||
           int64_t(f[1])<-32768||int64_t(f[1])>32768||f[2]<128||f[2]>768||
           int64_t(f[3])<-49152||int64_t(f[3])>49152)return -2;
    }
    packet[0]=0x50394c44;packet[1]=(uint32_t(wi)<<16)|hi;
    packet[2]=(uint32_t(wo)<<16)|ho;
    std::memcpy(packet+3,regs,8*4);packet[11]=flags;
    std::memcpy(packet+12,field,441*4*4);return 0;
}
static int reflect101(int x,int n) {
    while(x<0||x>=n){if(x<0)x=-x;else x=2*n-2-x;}
    return x;
}
extern "C" int p11_signature(const uint8_t* gray,int w,int h,int stride,
        const double* H,const float* kernel,float* structure,float* background,double* stats) { P11Scope profile(13);
    if(!gray||!H||!kernel||!structure||!background||!stats||
       w<2||h<2||w>640||h>640||stride<w)return -1;
    for(int i=0;i<9;i++)if(!std::isfinite(H[i])||!std::isfinite(kernel[i]))return -2;
    try {
        const int W=96,V=128,N=W*V;
        std::vector<float> pixels(N),temp(N),blur(N);
        double sum=0,squares=0;
        for(int y=0;y<V;y++)for(int x=0;x<W;x++) {
            double sx,sy;if(!project_checked(H,x,y,sx,sy))return -3;
            sx=std::max(-1.,std::min(double(w),sx));sy=std::max(-1.,std::min(double(h),sy));
            float value=float(sample(gray,w,h,stride,sx,sy));
            pixels[y*W+x]=value;sum+=value;squares+=value*value;
        }
        double mean=sum/N,sd=std::sqrt(std::max(0.,squares/N-mean*mean));
        stats[0]=mean;stats[1]=sd;
        for(int j=0;j<N;j++)structure[j]=float((pixels[j]-mean)/std::max(12.,sd));
        for(int y=0;y<V;y++) {
            int x=0;
            for(;x<4;x++){float s=0;for(int k=0;k<9;k++)s+=kernel[k]*pixels[y*W+reflect101(x+k-4,W)];temp[y*W+x]=s;}
#ifdef __ARM_NEON
            for(;x+4<=W-4;x+=4) {
                float32x4_t s=vdupq_n_f32(0);
                for(int k=0;k<9;k++)s=vmlaq_n_f32(s,vld1q_f32(pixels.data()+y*W+x+k-4),kernel[k]);
                vst1q_f32(temp.data()+y*W+x,s);
            }
#endif
            for(;x<W;x++){float s=0;for(int k=0;k<9;k++)s+=kernel[k]*pixels[y*W+reflect101(x+k-4,W)];temp[y*W+x]=s;}
        }
        for(int y=0;y<V;y++) {
            int x=0;
#ifdef __ARM_NEON
            for(;x+4<=W;x+=4) {
                float32x4_t s=vdupq_n_f32(0);
                for(int k=0;k<9;k++)s=vmlaq_n_f32(s,vld1q_f32(temp.data()+reflect101(y+k-4,V)*W+x),kernel[k]);
                vst1q_f32(blur.data()+y*W+x,s);
            }
#endif
            for(;x<W;x++){float s=0;for(int k=0;k<9;k++)s+=kernel[k]*temp[reflect101(y+k-4,V)*W+x];blur[y*W+x]=s;}
        }
        for(int y=0;y<8;y++)for(int x=0;x<8;x++) {
            double s=0;for(int j=0;j<16;j++)for(int i=0;i<12;i++)s+=blur[(y*16+j)*W+x*12+i];
            background[y*8+x]=float(s/192.);
        }
        return 0;
    }catch(...){return -4;}
}

// V23: one CPU-only transaction, no MMIO, and no change in rounding/guards.
static int p11_prepare_control_core(const double* H,const double* nodes,int nx,int ny,
    const int32_t* uv,const double* samples,int count,const int32_t* gain,
    const int32_t* offset,int wi,int hi,int wo,int ho,int flags,
    uint32_t* packet,double* residual,std::vector<double>* scratch=nullptr) {
    if(!H||!nodes||!uv||!samples||!gain||!offset||!packet||!residual)return -100;
    int32_t regs[8],field[21*21*4];
    int code=p11_prepare(H,wo,ho,regs);
    if(code)return -200+code;
    if(scratch)code=p11_plan_geometry_core(H,regs,nodes,nx,ny,uv,samples,count,field,residual,*scratch);
    else code=p11_plan_geometry(H,regs,nodes,nx,ny,uv,samples,count,field,residual);
    if(code)return -300+code;
    if(!std::isfinite(*residual)||*residual>.65)return -400;
    for(int i=0;i<21*21;i++){field[i*4+2]=gain[i];field[i*4+3]=offset[i];}
    code=p11_packet(field,regs,wi,hi,wo,ho,flags,packet);
    return code ? -500+code : 0;
}


// Tiny aligned observation. No full-size warp, Gaussian or pixel output.
extern "C" int p11_probe(const uint8_t* gray,int w,int h,int stride,const double* H,
                         float* structure,float* background,double* stats) { P11Scope profile(15);
    if(!gray||!H||!structure||!background||!stats||w<2||h<2||stride<w)return -1;
    for(int i=0;i<9;i++)if(!std::isfinite(H[i]))return -2;
    double sum=0.,sum2=0.;std::fill(background,background+64,0.f);
    for(int y=0;y<32;y++)for(int x=0;x<32;x++) {
        double sx,sy;if(!project_checked(H,x,y,sx,sy))return -3;
        float value=float(sample(gray,w,h,stride,sx,sy));
        structure[y*32+x]=value;sum+=value;sum2+=double(value)*value;
        background[(y/4)*8+x/4]+=value/16.f;
    }
    double mean=sum/1024.,sd=std::sqrt(std::max(0.,sum2/1024.-mean*mean));
    for(int i=0;i<1024;i++)structure[i]=float((structure[i]-mean)/std::max(sd,12.));
    stats[0]=mean;stats[1]=sd;return 0;
}

// Only the hardware owner calls this through ctypes.CDLL (GIL released).
// Existing PYNQ MMIO mappings stay alive for the entire call. No DMA programming,
// cache operation or ownership transition happens in this helper.
extern "C" int p11_wait_io(volatile uint32_t* pl,volatile uint32_t* dma,
                          uint32_t before,int kind,double timeout,uint32_t* result) { P11Scope profile(16);
    if(!pl||!dma||!result||!std::isfinite(timeout)||timeout<=0.||timeout>3600.||kind<0||kind>1)return -1;
    const auto began=std::chrono::steady_clock::now();
    for(;;) {
        std::atomic_thread_fence(std::memory_order_seq_cst);
        uint32_t ps=pl[1],error=pl[0x38/4],tx=0,rx=0;
        if(kind==1){tx=dma[0x04/4];rx=dma[0x34/4];}
        std::atomic_thread_fence(std::memory_order_seq_cst);
        result[0]=ps;result[1]=error;result[2]=tx;result[3]=rx;
        if(kind==1&&(((tx|rx)&0x71)||error))return 2;
        if(kind==0&&error&&!(ps&1))return 3;
        bool complete=!(ps&1)&&(ps&2);
        if(kind==1)complete=complete&&((tx&0x1002)==0x1002)&&((rx&0x1002)==0x1002);
        if(complete&&uint32_t(pl[0x34/4]-before)==1)return 0;
        if(std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count()>=timeout)return 1;
        std::this_thread::sleep_for(std::chrono::microseconds(kind==0?200:100));
    }
}


// Identical AREA2 -> BT.601 -> fixed Gaussian arithmetic in one GIL-free call.
extern "C" int p11_observe2(const uint8_t* bgr,int w,int h,int stride,uint8_t* scratch,
                            uint16_t* rows,uint8_t* observation,double* timings) { P11Scope profile(17);
    if(!timings||!scratch||!rows||!observation||w>1280||h>1280)return -1;
    auto began=std::chrono::steady_clock::now();
    int code=p11_gray2(bgr,w,h,stride,scratch);if(code)return code;
    auto middle=std::chrono::steady_clock::now();
    code=p11_gaussian3(scratch,w/2,h/2,w/2,rows,observation);if(code)return code;
    auto end=std::chrono::steady_clock::now();
    timings[0]=std::chrono::duration<double>(middle-began).count();
    timings[1]=std::chrono::duration<double>(end-middle).count();return 0;
}

extern "C" int p11_profile_snapshot(double* out,int n){if(!out||n!=90)return -1;for(int i=0;i<30;i++){out[i*3]=p11_metrics[i].wall;out[i*3+1]=p11_metrics[i].cpu;out[i*3+2]=p11_metrics[i].count;}return 0;}


// Exact byte copies; row crops remain row-strided. No color conversion.
extern "C" int p11_copy_bgr(const uint8_t* src,uint8_t* dst,int w,int h,
                            int ss,int ds) { P11Scope profile(19);
    if(!src||!dst||w<1||h<1||w>16384||h>16384||ss<w*3||ds<w*3)return -1;
    const size_t bytes=size_t(w)*3;
    if(ss==int(bytes)&&ds==int(bytes))std::memcpy(dst,src,bytes*size_t(h));
    else for(int y=0;y<h;y++)std::memcpy(dst+size_t(y)*ds,src+size_t(y)*ss,bytes);
    return 0;
}

// Same RX-before-TX-before-PL ordering as the Python owner. Cached arrays stay
// alive, all physical-address/cache/state checks precede this call in Python.
extern "C" int p11_arm_io(volatile uint32_t* pl,volatile uint32_t* dma,
    uint32_t src,uint32_t dst,uint32_t send,uint32_t receive,uint32_t sequence,int kind) { P11Scope profile(20);
    if(!pl||!dma||kind<0||kind>1||!send||!receive||send>=(1u<<23)||receive>=(1u<<23)
       ||(src&7)||(dst&7)||uint64_t(src)+send>0x20000000ull||uint64_t(dst)+receive>0x20000000ull
       ||(kind==1&&(!sequence||send!=7104||receive!=4)))return -1;
    if(kind==1)pl[8/4]=sequence;
    dma[0x34/4]=0x1000;dma[0x04/4]=0x1000;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    dma[0x48/4]=dst;dma[0x58/4]=receive;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    dma[0x18/4]=src;dma[0x28/4]=send;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    pl[0]=1;std::atomic_thread_fence(std::memory_order_seq_cst);return 0;
}

extern "C" int p11_frame_state(volatile uint32_t* pl,volatile uint32_t* dma,
                               uint32_t* out) { P11Scope profile(22);
    if(!pl||!dma||!out)return -1;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    out[0]=pl[4/4];out[1]=pl[0x38/4];out[2]=dma[4/4];out[3]=dma[0x34/4];
    out[4]=pl[0x34/4];out[5]=pl[0x48/4];out[6]=pl[0x4c/4];out[7]=pl[0x50/4];
    out[8]=pl[0xa4/4];out[9]=pl[0x54/4];out[10]=pl[0xc8/4];out[11]=dma[0x58/4];
    std::atomic_thread_fence(std::memory_order_seq_cst);return 0;
}

// Read-only owner wait for independent scan or counted receiver ACK. No
// accepted command/state is changed here. Every timeout reaches Python _fatal.
extern "C" int p11_plan_wait(volatile uint32_t* planner,volatile uint32_t* pixel,
    volatile uint32_t* dma,uint32_t sequence,int kind,double timeout,uint32_t* out) { P11Scope profile(21);
    if(!planner||!pixel||!dma||!out||!sequence||kind<0||kind>1||!std::isfinite(timeout)
       ||timeout<=0.||timeout>3600.)return -1;
    auto begin=std::chrono::steady_clock::now();
    for(;;) {
        std::atomic_thread_fence(std::memory_order_seq_cst);
        if(kind==0) {
            uint32_t tx=dma[4/4],rx=dma[0x34/4],status=planner[4/4],error=planner[0x38/4];
            out[0]=tx;out[1]=rx;out[2]=status;out[3]=error;
            if((tx|rx)&0x71)return 2;
            bool ack=(tx&0x1002)==0x1002&&(rx&0x1002)==0x1002;
            if(ack&&!(status&1)&&(error||((status&2)&&planner[0x10/4]==sequence)))return 0;
        } else {
            uint32_t pe=planner[0x70/4],xe=pixel[0xdc/4];out[0]=pe;out[1]=xe;
            out[2]=planner[0x14/4];out[3]=pixel[0xc4/4];
            if(pe||xe)return 2;
            if(out[2]==sequence&&out[3]==sequence&&pixel[0xa4/4]==1)return 0;
        }
        if(std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count()>=timeout)return 1;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
}


// Same measured edge solver and same area/convexity/reference guards, with
// the float32 returned-corner rounding performed before validation.
extern "C" int p11_edges_checked(const uint8_t* gray,int w,int h,int stride,
    const double* q,double radius,double* result,double* stats) {
    if(!stats)return -1;
    int code=p11_edges(gray,w,h,stride,q,radius,result,stats);if(code)return code;
    double rounded[8];for(int i=0;i<8;i++)rounded[i]=double(float(result[i]));
    int valid=p11_quad_valid(rounded,w,h,q);if(valid<0)return valid;
    stats[20]=(stats[17]>=3&&stats[16]>=2&&valid)?1.:0.;return 0;
}

// Four float32 points only. Fuse repeated tiny NumPy norm reductions and the
// drift accumulator without changing geometric/LK/edge acceptance thresholds.
extern "C" int p11_motion_values(const float* candidate,const float* prediction,
    const float* previous,const float* anchor,float* drift,double* out) { P11Scope profile(23);
    if(!candidate||!prediction||!previous||!anchor||!drift||!out)return -1;
    for(int i=0;i<8;i++)if(!std::isfinite(candidate[i])||!std::isfinite(prediction[i])
        ||!std::isfinite(previous[i])||!std::isfinite(anchor[i])||!std::isfinite(drift[i]))return -2;
    float motion=0.,correction=0.,accumulated=0.,travel=0.;
    for(int i=0;i<4;i++) {
        int x=i*2,y=x+1;
        float dx=candidate[x]-prediction[x],dy=candidate[y]-prediction[y];
        drift[x]+=dx;drift[y]+=dy;
        correction=std::max(correction,std::sqrt(dx*dx+dy*dy));
        dx=candidate[x]-previous[x];dy=candidate[y]-previous[y];
        motion=std::max(motion,std::sqrt(dx*dx+dy*dy));
        dx=candidate[x]-anchor[x];dy=candidate[y]-anchor[y];
        travel=std::max(travel,std::sqrt(dx*dx+dy*dy));
        accumulated=std::max(accumulated,std::sqrt(drift[x]*drift[x]+drift[y]*drift[y]));
    }
    float dx=previous[4]-previous[0],dy=previous[5]-previous[1];
    out[0]=motion;out[1]=correction;out[2]=accumulated;out[3]=std::sqrt(dx*dx+dy*dy);out[4]=travel;
    return 0;
}

// V31 persistent observation: measured edges + unchanged confidence gate and
// motion reductions in one GIL-free call. This never reads PL registers.
extern "C" int p11_edges_motion(const uint8_t* gray,int w,int h,int stride,
    const double* predicted,const float* previous,const float* anchor,float* drift,
    const int32_t* polarity,double radius,double* result,double* stats,
    double* motion,double* gate) { P11Scope profile(18);
    if(!previous||!anchor||!drift||!polarity||!motion||!gate)return -1;
    int code=p11_edges_checked(gray,w,h,stride,predicted,radius,result,stats);
    if(code)return code;
    float candidate[8],prediction[8];float correction=0.f;
    double support=1.,rms=0.;int flips=0;
    for(int i=0;i<4;i++) {
        candidate[2*i]=float(result[2*i]);candidate[2*i+1]=float(result[2*i+1]);
        prediction[2*i]=float(predicted[2*i]);prediction[2*i+1]=float(predicted[2*i+1]);
        result[2*i]=double(candidate[2*i]);result[2*i+1]=double(candidate[2*i+1]);
        float dx=candidate[2*i]-prediction[2*i],dy=candidate[2*i+1]-prediction[2*i+1];
        correction=std::max(correction,std::sqrt(dx*dx+dy*dy));
        support=std::min(support,stats[i]);rms=std::max(rms,stats[12+i]);
        flips+=int(polarity[i])*int(stats[4+i])<0;
    }
    bool reliable=stats[20]!=0.&&stats[17]==4.&&stats[16]==4.&&support>=.60
        &&rms<=1.&&correction<=radius*.65&&flips==0;
    gate[0]=reliable?1.:0.;gate[1]=support;gate[2]=rms;gate[3]=correction;
    gate[4]=flips;gate[5]=radius;
    for(int i=0;i<5;i++)motion[i]=0.;
    if(reliable)return p11_motion_values(candidate,prediction,previous,anchor,drift,motion);
    return 0;
}

// V31 CPU-only fused current-quad H, aligned probe and checked control packet.
// It neither reads MMIO nor updates a caller's surface/light references.
static bool p11_quad_h(const double* q,int w,int h,double* H) {
 if(!q||!H||w<2||h<2)return false;
 for(int i=0;i<8;i++)if(!std::isfinite(q[i]))return false;
#ifdef P11_OPENCV_LK
 cv::Point2f src[4]={{0,0},{float(w-1),0},{float(w-1),float(h-1)},{0,float(h-1)}};
 cv::Point2f dst[4];for(int k=0;k<4;k++)dst[k]=cv::Point2f(float(q[k*2]),float(q[k*2+1]));
 cv::Mat mat=cv::getPerspectiveTransform(src,dst);
 double norm=mat.at<double>(2,2);if(!std::isfinite(norm)||std::abs(norm)<1e-12)return false;
 for(int i=0;i<9;i++)H[i]=mat.at<double>(i/3,i%3)/norm;
#else
 // Same four point equations, double precision and partial pivoting.
 double a[8][9]={0};const double u[4]={0,double(w-1),double(w-1),0};
 const double v[4]={0,0,double(h-1),double(h-1)};
 for(int k=0;k<4;k++){
  double x=double(float(q[k*2])),y=double(float(q[k*2+1]));
  double* r=a[k*2];r[0]=u[k];r[1]=v[k];r[2]=1;r[6]=-x*u[k];r[7]=-x*v[k];r[8]=x;
  r=a[k*2+1];r[3]=u[k];r[4]=v[k];r[5]=1;r[6]=-y*u[k];r[7]=-y*v[k];r[8]=y;
 }
 for(int i=0;i<8;i++){
  int p=i;for(int j=i+1;j<8;j++)if(std::abs(a[j][i])>std::abs(a[p][i]))p=j;
  if(std::abs(a[p][i])<1e-12)return false;
  if(p!=i)for(int k=i;k<9;k++)std::swap(a[p][k],a[i][k]);
  double z=a[i][i];for(int k=i;k<9;k++)a[i][k]/=z;
  for(int j=0;j<8;j++)if(j!=i){z=a[j][i];for(int k=i;k<9;k++)a[j][k]-=z*a[i][k];}
 }
 for(int i=0;i<8;i++)H[i]=a[i][8];H[8]=1.;
#endif
 const double u2[4]={0,double(w-1),double(w-1),0},v2[4]={0,0,double(h-1),double(h-1)};
 for(int k=0;k<4;k++){
  double x,y;if(!project_checked(H,u2[k],v2[k],x,y))return false;
  if(std::hypot(x-double(float(q[k*2])),y-double(float(q[k*2+1])))>1e-3)return false;
 }
 return true;
}
struct FramePrepareCache {
 std::vector<double> guard_xy;
 std::thread::id owner;
 bool owner_set=false;
};
extern "C" void* p11_frame_create(){try{return new FramePrepareCache();}catch(...){return nullptr;}}
extern "C" void p11_frame_destroy(void* pointer){delete static_cast<FramePrepareCache*>(pointer);}
extern "C" int p11_frame_prepare(void* workspace,const double* q,const uint8_t* gray,int gw,int gh,int stride,
 double sx,double sy,int wo,int ho,const float* ref_structure,const float* ref_background,
 const double* ref_shape,const double* nodes,int nx,int ny,const int32_t* uv,
 const double* samples,int count,const int32_t* gain,const int32_t* offset,
 int wi,int hi,int flags,int control,double* H,double* shape,float* structure,
 float* background,double* info,uint32_t* packet) { P11Scope profile(14);
 if(!workspace||!q||!gray||!H||!shape||!structure||!background||!info||!ref_structure||
    !ref_background||!ref_shape||!std::isfinite(sx)||!std::isfinite(sy)||sx<=0.||sy<=0.||
    gw<2||gh<2||stride<gw||wo<2||ho<2||wo>1280||ho>1280)return -1;
 auto& cache=*static_cast<FramePrepareCache*>(workspace);
 if(cache.owner_set&&cache.owner!=std::this_thread::get_id())return -7;
 cache.owner=std::this_thread::get_id();cache.owner_set=true;
 try {
 double started=p11_wall();if(!p11_quad_h(q,wo,ho,H))return -2;
 info[7]=p11_wall()-started;
 double probe_q[8],probe_H[9];
 // Tracking stores sx=source_width/gray_width, sy=source_height/gray_height.
 // Keep NumPy float32 (q + .5) followed by float64 per-axis division and
 // subtraction. p11_quad_h then uses the same Point2f rounding as OpenCV.
 for(int i=0;i<8;i++)probe_q[i]=double(float(q[i])+.5f)/(i%2?sy:sx)-.5;
 double t=p11_wall();if(!p11_quad_h(probe_q,32,32,probe_H))return -3;
 if(p11_probe(gray,gw,gh,stride,probe_H,structure,background,info))return -4;
 double structure_change=0.,light_change=0.;
 for(int i=0;i<1024;i++){if(!std::isfinite(ref_structure[i]))return -5;structure_change+=std::abs(double(structure[i])-ref_structure[i]);}
 for(int i=0;i<64;i++){if(!std::isfinite(ref_background[i]))return -5;light_change+=std::abs(double(background[i])-ref_background[i]);}
 float lengths[4],mean=0.;for(int i=0;i<4;i++){
  int j=(i+1)%4;float x=float(q[j*2])-float(q[i*2]),y=float(q[j*2+1])-float(q[i*2+1]);
  lengths[i]=std::sqrt(x*x+y*y);mean+=lengths[i]/4.f;
 }
 info[2]=structure_change/1024.;info[3]=light_change/64.;info[4]=0.;
 for(int i=0;i<4;i++){if(!std::isfinite(ref_shape[i]))return -5;shape[i]=double(lengths[i]/std::max(mean,1.f));info[4]=std::max(info[4],std::abs(shape[i]-ref_shape[i]));}
 info[8]=p11_wall()-t;info[5]=0.;info[6]=0.;info[9]=0.;
 if(control){
  t=p11_wall();info[6]=p11_prepare_control_core(H,nodes,nx,ny,uv,samples,count,gain,offset,wi,hi,wo,ho,flags,packet,info+5,&cache.guard_xy);
  info[9]=p11_wall()-t;
 }
 info[10]=p11_wall()-started;return 0;
 }catch(...){return -6;}
}

extern "C" int p11_prepare_control(const double* H,const double* nodes,int nx,int ny,
 const int32_t* uv,const double* samples,int count,const int32_t* gain,
 const int32_t* offset,int wi,int hi,int wo,int ho,int flags,uint32_t* packet,double* residual) {
 P11Scope profile(14);return p11_prepare_control_core(H,nodes,nx,ny,uv,samples,count,gain,offset,wi,hi,wo,ho,flags,packet,residual);
}


// Common exact-half observation, current outer edges, gate and drift reduction.
// All output pointers belong to one chronological producer; no device access.
extern "C" int p11_observe_edges(const uint8_t* bgr,int w,int h,int stride,
 uint8_t* scratch,uint16_t* rows,uint8_t* observation,const double* prediction,
 const float* previous,const float* anchor,float* drift,const int32_t* polarity,
 double radius,double* result,double* stats,double* motion,double* gate,double* times) { P11Scope profile(25);
 if(!bgr||!scratch||!rows||!observation||!prediction||!previous||!anchor||!drift||
    !polarity||!result||!stats||!motion||!gate||!times||w<4||h<4||w>1280||h>1280||(w&1)||(h&1)||stride<w*3)return -1;
 double begin=p11_wall();int code=p11_observe2(bgr,w,h,stride,scratch,rows,observation,times);
 if(code)return code;double edge_begin=p11_wall();
 code=p11_edges_motion(observation,w/2,h/2,w/2,prediction,previous,anchor,drift,polarity,radius,result,stats,motion,gate);
 times[2]=p11_wall()-edge_begin;times[3]=p11_wall()-begin;return code?-200+code:0;
}

#ifdef P11_OPENCV_LK
// Keep bidirectional LK, error/FB threshold, RANSAC and spatial checks intact.
extern "C" int p11_lk_checked(void* context,const uint8_t* gray,int w,int h,
 const float* points,int n,const float* initial,int levels,int iterations,uint32_t generation,
 const double* anchor,const double* previous,float* quad,float* retained,double* stats,double* times) { P11Scope profile(26);
 if(!context||!times||!anchor||!previous||!quad||!retained||!stats)return -101;
 auto& c=*static_cast<LKCache*>(context);double began=p11_wall();
 if(c.current_generation!=generation){c.current_ready=false;c.current_generation=generation;}
 c.allow_retry_cache=true;
 int code=p11_lk_track(context,gray,w,h,points,n,c.flow_f,c.flow_b,c.flow_s,c.flow_sb,c.flow_error,initial,levels,iterations);
 c.allow_retry_cache=false;times[0]=p11_wall()-began;if(code)return -100+code;
 began=p11_wall();code=p11_lk_filter(points,c.flow_f,c.flow_b,c.flow_s,c.flow_sb,c.flow_error,n,anchor,previous,w,h,quad,retained,stats);
 times[1]=p11_wall()-began;return code;
}

extern "C" int p11_lk_checked_motion(void* context,const uint8_t* gray,int w,int h,
 const float* points,int n,const float* initial,int levels,int iterations,uint32_t generation,
 const double* anchor,const double* previous,float* quad,float* retained,double* stats,double* times,double* motion) {
 if(!motion)return -101;
 std::fill(p11_lk_motion_info,p11_lk_motion_info+4,0.);
 int code=p11_lk_checked(context,gray,w,h,points,n,initial,levels,iterations,generation,
     anchor,previous,quad,retained,stats,times);
 std::copy(p11_lk_motion_info,p11_lk_motion_info+4,motion);return code;
}

// Bounded corner ROIs only. Retained inliers are never replaced by fake corners.
extern "C" int p11_roi_features(const uint8_t* gray,int w,int h,const float* q,
 const float* retained,int count,float* out,int32_t* stats) { P11Scope profile(27);
 if(!gray||!q||!out||!stats||w<2||h<2||w>640||h>640||count<0||count>100||(count&&!retained))return -1;
 try {
  static thread_local cv::Mat mask,inside;
  static thread_local std::vector<cv::Point2f> found;
  static thread_local std::vector<cv::Point> polygon(4);
  int n=count,regions=0;for(int i=0;i<count*2;i++)out[i]=retained[i];
  for(int k=0;k<4;k++) {
   float x=q[2*k],y=q[2*k+1];if(!std::isfinite(x)||!std::isfinite(y))return -1;
   int near=0;for(int i=0;i<n;i++)near+=std::hypot(out[2*i]-x,out[2*i+1]-y)<18.f;
   if(near>=2||n>=100)continue;
   int x0=std::max(0,int(x)-20),y0=std::max(0,int(y)-20);
   int x1=std::min(w,int(x)+21),y1=std::min(h,int(y)+21);
   if(std::min(x1-x0,y1-y0)<7)continue;
   for(int i=0;i<4;i++)polygon[i]=cv::Point(int(std::nearbyint(q[2*i]-x0)),int(std::nearbyint(q[2*i+1]-y0)));
   mask.create(y1-y0,x1-x0,CV_8UC1);inside.create(y1-y0,x1-x0,CV_8UC1);mask.setTo(0);inside.setTo(0);
   const cv::Point* ptr=polygon.data();int four=4;
   cv::polylines(mask,&ptr,&four,1,true,cv::Scalar(255),4);
   cv::fillConvexPoly(inside,polygon,cv::Scalar(255));cv::bitwise_and(mask,inside,mask);
   cv::Mat image(h,w,CV_8UC1,const_cast<uint8_t*>(gray));found.clear();found.reserve(6);
   cv::goodFeaturesToTrack(image(cv::Rect(x0,y0,x1-x0,y1-y0)),found,6,.012,5.,mask,5);
   regions++;for(size_t j=0;j<std::min(size_t(4),found.size())&&n<100;j++) {
    float px=found[j].x+x0,py=found[j].y+y0;bool distinct=true;
    for(int i=0;i<n;i++)if(std::hypot(out[2*i]-px,out[2*i+1]-py)<=4.f){distinct=false;break;}
    if(distinct){out[2*n]=px;out[2*n+1]=py;n++;}
   }
  }
  stats[0]=n;stats[1]=regions;stats[2]=n-count;return 0;
 }catch(...){return -2;}
}
#endif

#ifdef P11_OPENCV_LK
// V79 optional CPU-only entry points. Existing IO/geometry/LK ABIs are unchanged.
extern "C" int p11_lk_track_generation(void* pointer,const uint8_t* gray,int w,int h,
 const float* points,int n,float* forward,float* backward,uint8_t* status,
 uint8_t* reverse_status,float* error,const float* initial,int levels,int iterations,uint32_t generation) {
 if(!pointer||generation==0xffffffffu)return -1;
 auto& c=*static_cast<LKCache*>(pointer);
 if(c.current_generation!=generation){c.current_ready=false;c.current_generation=generation;}
 c.allow_retry_cache=true;
 int code=p11_lk_track(pointer,gray,w,h,points,n,forward,backward,status,reverse_status,error,initial,levels,iterations);
 c.allow_retry_cache=false;return code;
}

extern "C" int p11_cover_features(const uint8_t* gray,int w,int h,const float* q,
 const float* rim,int count,float* out,int32_t* stats,double cpu_budget) { P11Scope profile(27);
 if(!gray||!q||!rim||!out||!stats||w<7||h<7||w>640||h>640||count<3||count>100||
    !std::isfinite(cpu_budget)||cpu_budget<=0.||cpu_budget>.02)return -1;
 std::fill(stats,stats+8,0);double began=p11_cpu();
 try {
  cv::Point2f quad[4],unit[4]={{0,0},{1,0},{1,1},{0,1}};
  for(int k=0;k<4;k++){
   if(!std::isfinite(q[2*k])||!std::isfinite(q[2*k+1]))return -1;
   quad[k]=cv::Point2f(q[2*k],q[2*k+1]);
  }
  // Real exterior points only, <=4 nearest each corner, no synthetic corners.
  int n=0;
  for(int k=0;k<4;k++)for(int quota=0;quota<4;quota++){
   int best=-1;float distance=1e30f;
   for(int i=0;i<count;i++){
    cv::Point2f p(rim[2*i],rim[2*i+1]);if(!std::isfinite(p.x)||!std::isfinite(p.y))continue;
    bool distinct=true;for(int j=0;j<n;j++)if(std::hypot(p.x-out[2*j],p.y-out[2*j+1])<=3.f){distinct=false;break;}
    if(!distinct)continue;
    float edge_distance=1e30f;
    for(int e=0;e<4;e++){
     cv::Point2f d=quad[(e+1)%4]-quad[e],a=p-quad[e];float den=d.dot(d);
     if(den<16.f)return -1;
     float t=std::max(0.f,std::min(1.f,a.dot(d)/den));cv::Point2f r=a-d*t;
     edge_distance=std::min(edge_distance,std::sqrt(r.dot(r)));
    }
    if(edge_distance>2.5f)continue;
    cv::Point2f d=p-quad[k];float score=d.dot(d);
    if(score<distance){distance=score;best=i;}
   }
   if(best>=0&&n<16){out[2*n]=rim[2*best];out[2*n+1]=rim[2*best+1];n++;}
  }
  stats[1]=n;if(n<3){stats[0]=n;return 0;}
  cv::Mat H=cv::getPerspectiveTransform(unit,quad);
  auto map=[&](double u,double v){double z=H.at<double>(2,0)*u+H.at<double>(2,1)*v+H.at<double>(2,2);
   return cv::Point2f(float((H.at<double>(0,0)*u+H.at<double>(0,1)*v+H.at<double>(0,2))/z),
                      float((H.at<double>(1,0)*u+H.at<double>(1,1)*v+H.at<double>(1,2))/z));};
  float descriptors[16][49];int cover=0,regions=0;
  for(int region=0;region<4&&cover<16;region++){
   double u=(region==1||region==2)?.68:.06,v=region>=2?.68:.06;
   cv::Point2f p[4]={map(u,v),map(u+.26,v),map(u+.26,v+.26),map(u,v+.26)};
   float lx=w,ly=h,hx=0,hy=0;
   for(int j=0;j<4;j++){if(!std::isfinite(p[j].x)||!std::isfinite(p[j].y))return -1;
    lx=std::min(lx,p[j].x);ly=std::min(ly,p[j].y);hx=std::max(hx,p[j].x);hy=std::max(hy,p[j].y);}
   int x0=std::max(3,int(std::floor(lx))),y0=std::max(3,int(std::floor(ly)));
   int x1=std::min(w-4,int(std::ceil(hx))),y1=std::min(h-4,int(std::ceil(hy)));
   struct Candidate {float score;int x,y;};Candidate best[16];int used=0;
   for(int y=y0;y<=y1;y+=2){
    if(p11_cpu()-began>=cpu_budget){stats[6]=1;break;}
    for(int x=x0;x<=x1;x+=2){
     bool positive=false,negative=false;
     for(int e=0;e<4;e++){cv::Point2f d=p[(e+1)%4]-p[e];float cross=d.x*(y-p[e].y)-d.y*(x-p[e].x);
      positive|=cross>0;negative|=cross<0;}
     if(positive&&negative)continue;
     float a=0,b=0,c=0;
     for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){
      int offset=(y+dy)*w+x+dx;float gx=int(gray[offset+1])-int(gray[offset-1]);
      float gy=int(gray[offset+w])-int(gray[offset-w]);a+=gx*gx;b+=gx*gy;c+=gy*gy;
     }
     float score=.5f*(a+c-std::sqrt((a-c)*(a-c)+4*b*b));if(score<800.f)continue;
     stats[7]++;
     // Suppress neighboring tensor peaks before the bounded ranking list;
     // otherwise a textured letter can occupy all sixteen candidate slots.
     bool near=false;
     for(int i=0;i<used;i++)if(std::hypot(float(x-best[i].x),float(y-best[i].y))<5.f){
      if(score<=best[i].score){near=true;break;}
      for(int j=i+1;j<used;j++)best[j-1]=best[j];used--;i--;
     }
     if(near)continue;
     int position=used;
     for(int i=0;i<used;i++)if(score>best[i].score){position=i;break;}
     if(position>=16)continue;
     for(int i=std::min(used,15);i>position;i--)best[i]=best[i-1];
     best[position]={score,x,y};used=std::min(16,used+1);
    }
   }
   int added=0;
   for(int j=0;j<used&&added<4&&cover<16;j++){
    float x=best[j].x,y=best[j].y;bool distinct=true;
    for(int i=0;i<n;i++)if(std::hypot(x-out[2*i],y-out[2*i+1])<5.f){distinct=false;break;}
    if(!distinct)continue;
    float patch[49],mean=0,norm=0;int t=0;
    for(int dy=-3;dy<=3;dy++)for(int dx=-3;dx<=3;dx++){float value=gray[(best[j].y+dy)*w+best[j].x+dx];patch[t++]=value;mean+=value;}
    mean/=49.f;for(int i=0;i<49;i++){patch[i]-=mean;norm+=patch[i]*patch[i];}
    if(mean<=8||mean>=242||norm<56.f*56.f){stats[5]++;continue;}
    norm=1.f/std::sqrt(norm);for(int i=0;i<49;i++)patch[i]*=norm;
    bool duplicate=false;for(int d=0;d<cover;d++){float dot=0;for(int i=0;i<49;i++)dot+=patch[i]*descriptors[d][i];
     if(std::abs(dot)>.94f){duplicate=true;break;}}
    if(duplicate){stats[4]++;continue;}
    std::copy(patch,patch+49,descriptors[cover]);out[2*n]=x;out[2*n+1]=y;n++;cover++;added++;
   }
   regions+=added>0;if(stats[6])break;
   // Enough distributed evidence; do not scan the fourth region needlessly.
   if(cover>=10&&regions>=3)break;
  }
  stats[0]=n;stats[2]=cover;stats[3]=regions;return 0;
 }catch(...){return -2;}
}
#endif

// Nonblocking completion probe: return1 means pending, never a deadline error.
extern "C" int p11_io_probe(volatile uint32_t* pl,volatile uint32_t* dma,uint32_t before,int kind,uint32_t* out) { P11Scope profile(28);
 if(!pl||!dma||!out||kind<0||kind>1)return -1;
 std::atomic_thread_fence(std::memory_order_seq_cst);
 uint32_t ps=pl[1],error=pl[0x38/4],tx=kind?dma[4/4]:0,rx=kind?dma[0x34/4]:0;
 out[0]=ps;out[1]=error;out[2]=tx;out[3]=rx;
 if(kind&&(((tx|rx)&0x71)||error))return 2;
 if(!kind&&error&&!(ps&1))return 3;
 bool done=!(ps&1)&&(ps&2);if(kind)done=done&&(tx&0x1002)==0x1002&&(rx&0x1002)==0x1002;
 return done&&uint32_t(pl[0x34/4]-before)==1?0:1;
}

// Single owner only. Batch upload validation/arm, receiver commit/wait and snapshot.
extern "C" int p11_owner_batch(volatile uint32_t* planner,volatile uint32_t* pixel,
 volatile uint32_t* dma,uint32_t src,uint32_t dst,uint32_t sequence,double timeout,int operation,uint32_t* out) { P11Scope profile(28);
 if(!planner||!pixel||!dma||!out||operation<0||operation>3)return -1;
 if(operation&&(!sequence||!std::isfinite(timeout)||timeout<=0.||timeout>(operation==3?30.:1.)))return -1;
 int code=0;
 if(operation==1) {
  if(planner[1]&1)return 4;if((dma[4/4]|dma[0x34/4])&0x71)return 2;
  code=p11_arm_io(planner,dma,src,dst,7104,4,sequence,1);
 }else if(operation==3) {
  // Read-only exact scan/DMA completion plus one reusable full snapshot.
  // CPU invalidates and verifies the ACK buffer after this call returns.
  code=p11_plan_wait(planner,pixel,dma,sequence,0,timeout,out);if(code)return code;
 }else if(operation==2) {
  if(pixel[1]&1)return 4;
  // Reconfirm the exact certificate before publishing the import command.
  if(planner[0x38/4]||planner[0x10/4]!=sequence||planner[0x0c/4]!=sequence)return 2;
  planner[0]=3;std::atomic_thread_fence(std::memory_order_seq_cst);
  code=p11_plan_wait(planner,pixel,dma,sequence,1,timeout,out);if(code)return code;
 }
 if(code)return code;std::atomic_thread_fence(std::memory_order_seq_cst);
 const int po[]={4,0x38,0x0c,0x10,0xa0,0xa8,0x40,0x44,0x48,0x4c};
 for(int i=0;i<10;i++)out[i]=planner[po[i]/4];out[10]=dma[0x58/4];out[11]=planner[0x14/4];
 out[12]=pixel[0xc4/4];out[13]=pixel[0xa4/4];out[14]=pixel[0xd8/4];out[15]=pixel[0xd0/4];
 out[16]=planner[0x5c/4];out[17]=pixel[1];out[18]=dma[4/4];out[19]=dma[0x34/4];return 0;
}


// Success returns a complete state snapshot, eliminating a second host read.
// A zero timeout is a probe; positive timeout is a bounded owner wait.
extern "C" int p11_owner_complete(volatile uint32_t* pl,volatile uint32_t* dma,
 uint32_t before,int kind,double timeout,uint32_t* out) { P11Scope profile(29);
 if(!pl||!dma||!out||kind<0||kind>1||!std::isfinite(timeout)||timeout<0.||timeout>3600.)return -1;
 const double began=p11_wall();
 for(;;) {
  std::atomic_thread_fence(std::memory_order_seq_cst);
  uint32_t ps=pl[1],error=pl[0x38/4],tx=kind?dma[4/4]:0,rx=kind?dma[0x34/4]:0;
  out[0]=ps;out[1]=error;out[2]=tx;out[3]=rx;
  if(kind&&(((tx|rx)&0x71)||error))return 2;
  if(!kind&&error&&!(ps&1))return 3;
  bool done=!(ps&1)&&(ps&2);
  if(kind)done=done&&(tx&0x1002)==0x1002&&(rx&0x1002)==0x1002;
  if(done&&uint32_t(pl[0x34/4]-before)==1) {
   int code=p11_frame_state(pl,dma,out);if(code)return code;
   // The hardware owner cannot arm/import another frame inside this call.
   if(uint32_t(out[4]-before)!=1)return 2;
   return 0;
  }
  if(timeout==0.||p11_wall()-began>=timeout)return 1;
  std::this_thread::sleep_for(std::chrono::microseconds(kind?100:200));
 }
}

// V31 raw YUYV observers. Normalize limited-range Y with one 256-entry LUT.
static uint8_t y31(uint8_t y,int mode){return (mode&1)?y:uint8_t((std::min(219,std::max(0,int(y)-16))*255+109)/219);}
extern "C" int p11_yuyv_gray2(const uint8_t* src,int w,int h,int stride,int mode,uint8_t* dst){P11Scope scope(3);
 if(!src||!dst||w<4||h<4||w>1280||h>1280||(w&1)||(h&1)||stride<w*2||mode<0||mode>3)return -1;
 uint8_t lut[256];for(int i=0;i<256;i++)lut[i]=y31(uint8_t(i),mode);
 for(int y=0;y<h/2;y++){const uint8_t* a=src+size_t(2*y)*stride;const uint8_t* b=a+stride;int x=0;
#ifdef __ARM_NEON
  for(;x+8<=w/2;x+=8){
   uint8x16_t ya=vld2q_u8(a+4*x).val[0],yb=vld2q_u8(b+4*x).val[0];
   uint16x8_t sum=vaddq_u16(vpaddlq_u8(ya),vpaddlq_u8(yb));
   uint8_t tmp[8];vst1_u8(tmp,vmovn_u16(vshrq_n_u16(vaddq_u16(sum,vdupq_n_u16(2)),2)));
   for(int k=0;k<8;k++)dst[y*(w/2)+x+k]=lut[tmp[k]];
  }
#endif
  for(;x<w/2;x++)dst[y*(w/2)+x]=lut[(int(a[4*x])+a[4*x+2]+b[4*x]+b[4*x+2]+2)>>2];
 }return 0;
}
extern "C" int p11_yuyv_observe2(const uint8_t* src,int w,int h,int stride,int mode,
 uint8_t* scratch,uint16_t* rows,uint8_t* observation,double* times){P11Scope scope(17);
 if(!times||!rows||!observation)return -1;double begin=p11_wall();
 int code=p11_yuyv_gray2(src,w,h,stride,mode,scratch);if(code)return code;double mid=p11_wall();
 code=p11_gaussian3(scratch,w/2,h/2,w/2,rows,observation);if(code)return code;
 times[0]=mid-begin;times[1]=p11_wall()-mid;return 0;
}
extern "C" int p11_yuyv_observe_edges(const uint8_t* src,int w,int h,int stride,int mode,
 uint8_t* scratch,uint16_t* rows,uint8_t* observation,const double* prediction,
 const float* previous,const float* anchor,float* drift,const int32_t* polarity,
 double radius,double* result,double* stats,double* motion,double* gate,double* times){P11Scope scope(25);
 if(!times||!prediction||!previous||!anchor||!drift||!polarity||!result||!stats||!motion||!gate)return -1;
 double begin=p11_wall();int code=p11_yuyv_observe2(src,w,h,stride,mode,scratch,rows,observation,times);
 if(code)return code;double mid=p11_wall();
 code=p11_edges_motion(observation,w/2,h/2,w/2,prediction,previous,anchor,drift,polarity,radius,result,stats,motion,gate);
 times[2]=p11_wall()-mid;times[3]=p11_wall()-begin;return code?-200+code:0;
}
extern "C" int p11_copy_yuyv(const uint8_t* src,uint8_t* dst,int w,int h,int ss,int ds){P11Scope scope(19);
 if(!src||!dst||w<2||h<1||w>1280||h>1280||(w&1)||ss<w*2||ds<w*2)return -1;
 size_t row=size_t(w)*2;if(ss==int(row)&&ds==int(row))std::memcpy(dst,src,row*size_t(h));
 else for(int y=0;y<h;y++)std::memcpy(dst+size_t(y)*ds,src+size_t(y)*ss,row);return 0;
}
static uint8_t c31(int sum){int v=(sum+128)>>8;return uint8_t(std::min(255,std::max(0,v)));}
extern "C" int p11_yuyv_bgr(const uint8_t* src,int w,int h,int stride,int mode,uint8_t* dst){
 if(!src||!dst||w<2||h<2||w>1280||h>1280||(w&1)||stride<w*2||mode<0||mode>3)return -1;
 static const int k[4][5]={{298,409,100,208,516},{256,359,88,183,454},{298,459,55,136,541},{256,403,48,120,475}};
 for(int y=0;y<h;y++)for(int x=0;x<w;x+=2){const uint8_t* a=src+size_t(y)*stride+2*x;int u=int(a[1])-128,v=int(a[3])-128;
  for(int j=0;j<2;j++){int yy=k[mode][0]*((mode&1)?int(a[2*j]):std::max(0,int(a[2*j])-16));
   uint8_t* b=dst+3*(size_t(y)*w+x+j);b[0]=c31(yy+k[mode][4]*u);b[1]=c31(yy-k[mode][2]*u-k[mode][3]*v);b[2]=c31(yy+k[mode][1]*v);
  }
 }return 0;
}


// Host preview only: resize the leased YUYV directly into a small owned BGR
// packet. Same four CSC modes as PL/model CSC. No device/CMA access or retention.
// Interpolation occurs before CSC; display pixels are not the exact PL reference.
struct P34Axis {int lo[640],hi[640],fraction[640];};
struct P34Preview {int wi=0,hi=0,wo=0,ho=0;P34Axis x,chroma,y;};
static thread_local P34Preview p34_preview;
static void p34_axis(P34Axis& a,int source,int target){
 for(int i=0;i<target;i++){
  double p=std::max(0.,std::min(double(source-1),(i+.5)*source/target-.5));
  a.lo[i]=int(std::floor(p));a.hi[i]=std::min(source-1,a.lo[i]+1);
  a.fraction[i]=int(std::floor((p-a.lo[i])*256.+.5));
 }
}
static int p34_sample(const uint8_t* src,int stride,const P34Axis& x,const P34Axis& y,
 int xx,int yy,int step,int channel){
 int fx=x.fraction[xx],fy=y.fraction[yy];
 const uint8_t* a=src+size_t(y.lo[yy])*stride;
 const uint8_t* b=src+size_t(y.hi[yy])*stride;
 int top=(256-fx)*a[step*x.lo[xx]+channel]+fx*a[step*x.hi[xx]+channel];
 int bottom=(256-fx)*b[step*x.lo[xx]+channel]+fx*b[step*x.hi[xx]+channel];
 return ((256-fy)*top+fy*bottom+32768)>>16;
}
extern "C" int p11_yuyv_preview(const uint8_t* src,int wi,int hi,int stride,int mode,
 uint8_t* dst,int wo,int ho){
 if(!src||!dst||wi<2||hi<2||wi>1280||hi>1280||(wi&1)||stride<wi*2
    ||mode<0||mode>3||wo<1||ho<1||wo>640||ho>640)return -1;
 P34Preview& c=p34_preview;
 if(c.wi!=wi||c.hi!=hi||c.wo!=wo||c.ho!=ho){
  p34_axis(c.x,wi,wo);p34_axis(c.chroma,wi/2,wo);p34_axis(c.y,hi,ho);
  c.wi=wi;c.hi=hi;c.wo=wo;c.ho=ho;
 }
 static const int k[4][5]={{298,409,100,208,516},{256,359,88,183,454},
                          {298,459,55,136,541},{256,403,48,120,475}};
 for(int y=0;y<ho;y++)for(int x=0;x<wo;x++){
  int yy=p34_sample(src,stride,c.x,c.y,x,y,2,0);
  int u=p34_sample(src,stride,c.chroma,c.y,x,y,4,1)-128;
  int v=p34_sample(src,stride,c.chroma,c.y,x,y,4,3)-128;
  int l=k[mode][0]*((mode&1)?yy:std::max(0,yy-16));
  uint8_t* b=dst+3*(size_t(y)*wo+x);
  b[0]=c31(l+k[mode][4]*u);b[1]=c31(l-k[mode][2]*u-k[mode][3]*v);b[2]=c31(l+k[mode][1]*v);
 }
 return 0;
}

// V35 display-only nearest sampling. Half-size YUYV reads complete Y0/U/Y1/V
// pairs with vld4; correction/model pixels and all PL arithmetic stay unchanged.
#ifdef __ARM_NEON
static uint8x8_t p35_channel(int16x8_t y,int16x8_t u,int16x8_t v,const int* k,int channel){
 int32x4_t lo=vmull_n_s16(vget_low_s16(y),int16_t(k[0]));
 int32x4_t hi=vmull_n_s16(vget_high_s16(y),int16_t(k[0]));
 if(channel==0){lo=vmlal_n_s16(lo,vget_low_s16(u),int16_t(k[4]));hi=vmlal_n_s16(hi,vget_high_s16(u),int16_t(k[4]));}
 else if(channel==2){lo=vmlal_n_s16(lo,vget_low_s16(v),int16_t(k[1]));hi=vmlal_n_s16(hi,vget_high_s16(v),int16_t(k[1]));}
 else{
  lo=vmlsl_n_s16(lo,vget_low_s16(u),int16_t(k[2]));hi=vmlsl_n_s16(hi,vget_high_s16(u),int16_t(k[2]));
  lo=vmlsl_n_s16(lo,vget_low_s16(v),int16_t(k[3]));hi=vmlsl_n_s16(hi,vget_high_s16(v),int16_t(k[3]));
 }
 lo=vshrq_n_s32(vaddq_s32(lo,vdupq_n_s32(128)),8);
 hi=vshrq_n_s32(vaddq_s32(hi,vdupq_n_s32(128)),8);
 return vqmovn_u16(vcombine_u16(vqmovun_s32(lo),vqmovun_s32(hi)));
}
#endif
extern "C" int p11_yuyv_preview_nearest(const uint8_t* src,int wi,int hi,int stride,int mode,
 uint8_t* dst,int wo,int ho){
 if(!src||!dst||wi<2||hi<2||wi>1280||hi>1280||(wi&1)||stride<wi*2
    ||mode<0||mode>3||wo<1||ho<1||wo>640||ho>640)return -1;
 static const int k[4][5]={{298,409,100,208,516},{256,359,88,183,454},
                         {298,459,55,136,541},{256,403,48,120,475}};
 const int* coefficients=k[mode];bool half=(wi==2*wo&&hi==2*ho);
 for(int y=0;y<ho;y++){
  const uint8_t* row=src+size_t((y*hi)/ho)*stride;uint8_t* out=dst+size_t(y)*wo*3;int x=0;
#ifdef __ARM_NEON
  if(half)for(;x+8<=wo;x+=8){
   uint8x8x4_t a=vld4_u8(row+4*x);
   int16x8_t yy=vreinterpretq_s16_u16(vmovl_u8(a.val[0]));
   if(!(mode&1))yy=vmaxq_s16(vsubq_s16(yy,vdupq_n_s16(16)),vdupq_n_s16(0));
   int16x8_t u=vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(a.val[1])),vdupq_n_s16(128));
   int16x8_t v=vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(a.val[3])),vdupq_n_s16(128));
   uint8x8x3_t b;
   for(int channel=0;channel<3;channel++)b.val[channel]=p35_channel(yy,u,v,coefficients,channel);
   vst3_u8(out+3*x,b);
  }
#endif
  for(;x<wo;x++){
   int sx=(x*wi)/wo;const uint8_t* pair=row+4*(sx/2);
   int yy=coefficients[0]*((mode&1)?int(pair[2*(sx&1)]):std::max(0,int(pair[2*(sx&1)])-16));
   int u=int(pair[1])-128,v=int(pair[3])-128;
   out[3*x]=c31(yy+coefficients[4]*u);
   out[3*x+1]=c31(yy-coefficients[2]*u-coefficients[3]*v);
   out[3*x+2]=c31(yy+coefficients[1]*v);
  }
 }return 0;
}

// Preview only: immutable coordinate maps live in the UI workspace. Neither
// input nor destination is a device lease; the owner made paired RAM copies.
extern "C" int p11_bgr_preview_nearest(const uint8_t* src,int wi,int hi,int stride,
 uint8_t* dst,int wo,int ho,const int32_t* xs,const int32_t* ys){
 if(!src||!dst||!xs||!ys||wi<2||hi<2||wi>1280||hi>1280||stride<wi*3
    ||wo<1||ho<1||wo>640||ho>640||wo>wi||ho>hi)return -1;
 for(int x=0;x<wo;x++)if(xs[x]<0||xs[x]>=wi)return -2;
 for(int y=0;y<ho;y++)if(ys[y]<0||ys[y]>=hi)return -3;
 for(int y=0;y<ho;y++){
  uint8_t* out=dst+size_t(y)*wo*3;
  if(y&&ys[y]==ys[y-1]){std::memcpy(out,out-size_t(wo)*3,size_t(wo)*3);continue;}
  const uint8_t* in=src+size_t(ys[y])*stride;
  for(int x=0;x<wo;x++){
   const uint8_t* px=in+size_t(xs[x])*3;
   out[3*x]=px[0];out[3*x+1]=px[1];out[3*x+2]=px[2];
  }
 }return 0;
}


// V38 ordinary-RAM preview transaction. No camera/CMA leases or MMIO here.
// The producer validated/owns both packets until the UI consumer releases them.
extern "C" int p11_preview_pair_copy(const uint8_t* raw,uint8_t* raw_out,
 int rw,int rh,int rs,int rds,const uint8_t* bgr,uint8_t* bgr_out,
 int bw,int bh,int bs,int bds,double* times){
 if(!raw||!raw_out||!bgr||!bgr_out||!times||rw<2||rh<2||rw>1280||rh>1280
    ||(rw&1)||rs<rw*2||rds<rw*2||bw<2||bh<2||bw>1280||bh>1280||bs<bw*3||bds<bw*3)return -1;
 double begin=p11_wall();int code=p11_copy_yuyv(raw,raw_out,rw,rh,rs,rds);
 double middle=p11_wall();if(code)return code;
 code=p11_copy_bgr(bgr,bgr_out,bw,bh,bs,bds);
 times[0]=middle-begin;times[1]=p11_wall()-middle;return code;
}

extern "C" int p11_compact_preview(const uint8_t* raw,int wi,int hi,int stride,int mode,
 const uint8_t* bgr,int bw,int bh,int bstride,uint8_t* left,int lw,
 uint8_t* right,int rw,int height,const int32_t* xs,const int32_t* ys,
 uint8_t* canvas,double* times){
 if(!raw||!bgr||!left||!canvas||!times||wi<2||hi<2||wi>1280||hi>1280
    ||(wi&1)||stride<wi*2||bw<2||bh<2||bw>1280||bh>1280||bstride<bw*3
    ||mode<0||mode>3||lw<1||lw>640||rw<1||rw>640||height<1||height>640)return -1;
 bool resize=right!=nullptr;
 if(resize){
  if(!xs||!ys||rw>bw||height>bh)return -2;
  for(int x=0;x<rw;x++)if(xs[x]<0||xs[x]>=bw)return -2;
  for(int y=0;y<height;y++)if(ys[y]<0||ys[y]>=bh)return -2;
 }else if(rw!=bw||height!=bh)return -2;
 double begin=p11_wall();int code=p11_yuyv_preview_nearest(raw,wi,hi,stride,mode,left,lw,height);
 double after_convert=p11_wall();if(code)return code;
 if(resize){code=p11_bgr_preview_nearest(bgr,bw,bh,bstride,right,rw,height,xs,ys);if(code)return code;}
 double after_resize=p11_wall();
 const uint8_t* right_pixels=resize?right:bgr;size_t right_stride=resize?size_t(rw)*3:size_t(bstride);
 size_t out_stride=size_t(lw+rw)*3;
 for(int y=0;y<height;y++){
  std::memcpy(canvas+size_t(y)*out_stride,left+size_t(y)*lw*3,size_t(lw)*3);
  std::memcpy(canvas+size_t(y)*out_stride+size_t(lw)*3,right_pixels+size_t(y)*right_stride,size_t(rw)*3);
 }
 times[0]=after_convert-begin;times[1]=after_resize-after_convert;
 times[2]=p11_wall()-after_resize;return 0;
}


#ifdef P11_OPENCV_LK
struct P11Refine64Workspace {
 cv::Mat mx,my,profiles;
 double points[128],retained[128],lines[12];
 P11Refine64Workspace():mx(64,65,CV_32F),my(64,65,CV_32F),profiles(64,65,CV_8U){}
};
static double p11_refine64_median(const double* x,int n) {
 double tmp[64];std::copy(x,x+n,tmp);std::sort(tmp,tmp+n);
 return n%2?tmp[n/2]:(tmp[n/2-1]+tmp[n/2])*.5;
}
static bool p11_refine64_tls(double* points,int n,double* line,double& rms) {
 if(n<20)return false;
 double cx=0,cy=0,xx=0,xy=0,yy=0;
 for(int i=0;i<n;i++){cx+=points[2*i];cy+=points[2*i+1];}cx/=n;cy/=n;
 for(int i=0;i<n;i++){double x=points[2*i]-cx,y=points[2*i+1]-cy;xx+=x*x;xy+=x*y;yy+=y*y;}
 if(!std::isfinite(xx+yy)||xx+yy<1e-9)return false;
 // Principal eigenvector of 2x2 covariance == right singular vector of Nx2.
 double angle=.5*std::atan2(2*xy,xx-yy),nx=-std::sin(angle),ny=std::cos(angle);
 line[0]=nx;line[1]=ny;line[2]=-nx*cx-ny*cy;
 double squared=0.;
 for(int i=0;i<n;i++){double r=nx*(points[2*i]-cx)+ny*(points[2*i+1]-cy);squared+=r*r;}
 rms=std::sqrt(squared/n);return std::isfinite(rms);
}
#endif
// Normalize only the four neighbors of requested packed-Y samples.
// Q5 coordinate quantization / Q10 bilinear weights, replicate border, uint8
// rounding; matches the existing normalize-then-linear profile definition.
static uint8_t p46_y_sample(const uint8_t* raw,int w,int h,int stride,int mode,float x,float y){
 int ix=int(std::lrint(double(x)*32.)),iy=int(std::lrint(double(y)*32.));
 int x0=int(std::floor(double(ix)/32.)),y0=int(std::floor(double(iy)/32.));
 int fx=ix-x0*32,fy=iy-y0*32;
 int xa=std::max(0,std::min(w-1,x0)),xb=std::max(0,std::min(w-1,x0+1));
 int ya=std::max(0,std::min(h-1,y0)),yb=std::max(0,std::min(h-1,y0+1));
 auto load=[&](int px,int py){int value=raw[size_t(py)*stride+2*px];
  return (mode&1)?value:(std::min(219,std::max(0,value-16))*255+109)/219;};
 int a=load(xa,ya),b=load(xb,ya),c=load(xa,yb),d=load(xb,yb);
 return uint8_t((a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy+512)>>10);
}
static int p46_refine64(const uint8_t* gray,int w,int h,int stride,const double* q,
 double half,double* result,double* stats,int packed_mode=-1) { P11Scope profile(8);
 if(!gray||!q||!result||!stats||w<2||h<2||w>4096||h>4096||stride<w||
    !std::isfinite(half)||half<3||half>48||packed_mode>3||packed_mode<-1||
    (packed_mode>=0&&((w&1)||stride<w*2)))return -1;
 for(int i=0;i<8;i++)if(!std::isfinite(q[i])||std::abs(q[i])>8192)return -2;
#ifdef P11_OPENCV_LK
 double began=p11_wall(),cpu=p11_cpu();
 try {
  static thread_local P11Refine64Workspace ws;
  std::copy(q,q+8,result);std::fill(stats,stats+27,0.);
  double cx=0,cy=0;for(int i=0;i<4;i++){cx+=q[2*i];cy+=q[2*i+1];}cx/=4;cy/=4;
  bool accepted[4]={false,false,false,false};
  cv::Mat source(h,w,CV_8U,const_cast<uint8_t*>(gray),size_t(stride));
  for(int e=0;e<4;e++){
   int next=(e+1)%4;double ax=q[2*e],ay=q[2*e+1],ex=q[2*next]-ax,ey=q[2*next+1]-ay;
   double len=std::hypot(ex,ey);if(len<1e-9)continue;
   double nx=-ey/len,ny=ex/len;
   if((cx-ax-ex*.5)*nx+(cy-ay-ey*.5)*ny<0){nx=-nx;ny=-ny;}
   for(int k=0;k<64;k++){
    double t=.06+.88*k/63.,bx=ax+t*ex,by=ay+t*ey;
    float* mx=ws.mx.ptr<float>(k);float* my=ws.my.ptr<float>(k);
    for(int j=0;j<65;j++){double d=-half+2*half*j/64.;mx[j]=float(bx+d*nx);my[j]=float(by+d*ny);}
   }
   // Same OpenCV uint8 interpolation table and BORDER_REPLICATE as Python P1.
   if(packed_mode<0)cv::remap(source,ws.profiles,ws.mx,ws.my,cv::INTER_LINEAR,cv::BORDER_REPLICATE);
   else for(int k=0;k<64;k++)for(int j=0;j<65;j++)
    ws.profiles.ptr<uint8_t>(k)[j]=p46_y_sample(gray,w,h,stride,packed_mode,ws.mx.ptr<float>(k)[j],ws.my.ptr<float>(k)[j]);
   double contrasts[64];int n=0,first=-1,last=-1;
   for(int k=0;k<64;k++){
    const uint8_t* row=ws.profiles.ptr<uint8_t>(k);double a[8],b[8];
    for(int j=0;j<8;j++){a[j]=row[j];b[j]=row[j+57];}
    double outer=p11_refine64_median(a,8),inner=p11_refine64_median(b,8);
    double contrast=inner-outer,level=(outer+inner)*.5,sign=contrast>=0?1.:-1.;contrasts[k]=contrast;
    if(std::abs(contrast)<12)continue;
    double best=1e30,shift=0;bool found=false;
    for(int j=0;j<64;j++){
     double before=(row[j]-level)*sign,after=(row[j+1]-level)*sign;
     double distance=std::abs(-half+2*half*(j+.5)/64.);
     if(before<=0&&after>0&&distance<best){
      best=distance;found=true;
      double alpha=std::max(0.,std::min(1.,-before/std::max(after-before,1e-9)));
      shift=-half+2*half*(j+alpha)/64.;
     }
    }
    double t=.06+.88*k/63.,px=ax+t*ex+shift*nx,py=ay+t*ey+shift*ny;
    if(!found||px<1||px>=w-1||py<1||py>=h-1)continue;
    ws.points[2*n]=px;ws.points[2*n+1]=py;n++;if(first<0)first=k;last=k;
   }
   stats[6*e]=n;stats[6*e+5]=p11_refine64_median(contrasts,64);if(n<20)continue;
   double rms=0.;int retained=n;double* line=ws.lines+3*e;bool valid=true;
   for(int iteration=0;iteration<3;iteration++){
    if(!p11_refine64_tls(ws.points,retained,line,rms)){valid=false;break;}
    double residual[64];
    for(int k=0;k<retained;k++)residual[k]=std::abs(line[0]*ws.points[2*k]+line[1]*ws.points[2*k+1]+line[2]);
    double threshold=std::max(1.,3*p11_refine64_median(residual,retained));int kept=0;
    for(int k=0;k<retained;k++)if(residual[k]<=threshold){ws.retained[2*kept]=ws.points[2*k];ws.retained[2*kept+1]=ws.points[2*k+1];kept++;}
    if(kept==retained||kept<20)break;
    std::copy(ws.retained,ws.retained+2*kept,ws.points);retained=kept;
   }
   valid=valid&&p11_refine64_tls(ws.points,retained,line,rms);
   double coverage=.88*(last-first)/63.;
   stats[6*e+1]=valid?rms:1e30;stats[6*e+2]=retained;stats[6*e+3]=coverage;
   accepted[e]=valid&&rms<=std::max(1.5,.06*half)&&coverage>=.60;
   stats[6*e+4]=accepted[e]?1.:0.;
  }
  int refined=0;
  for(int e=0;e<4;e++)if(accepted[(e+3)%4]&&accepted[e]){
   const double* a=ws.lines+3*((e+3)%4);const double* b=ws.lines+3*e;
   double den=a[0]*b[1]-a[1]*b[0];if(std::abs(den)<.08)continue;
   double x=(a[1]*b[2]-a[2]*b[1])/den,y=(a[2]*b[0]-a[0]*b[2])/den;
   if(std::hypot(x-q[2*e],y-q[2*e+1])<=3*half&&x>=0&&x<=w-1&&y>=0&&y<=h-1){
    result[2*e]=x;result[2*e+1]=y;refined++;
   }
  }
  stats[24]=refined;stats[25]=p11_wall()-began;stats[26]=p11_cpu()-cpu;return 0;
 }catch(...){return -3;}
#else
 return -9; // Explicit optional-backend absence; original Python64 fallback.
#endif
}

extern "C" int p11_refine64(const uint8_t* gray,int w,int h,int stride,const double* q,
 double half,double* result,double* stats){return p46_refine64(gray,w,h,stride,q,half,result,stats);}
extern "C" int p11_yuyv_refine64(const uint8_t* raw,int w,int h,int stride,int mode,const double* q,
 double half,double* result,double* stats){
 if(mode<0||mode>3)return -1;
 return p46_refine64(raw,w,h,stride,q,half,result,stats,mode);
}

struct P11CoherentWorkspace {
 float smooth[64*65*3],gradient[64*65],work[64*65];
 double positions[64*3],strengths[64*3],t[64],noise[64];
 bool eligible[64*3];int best_peak[64];bool best_keep[64];double affinity[64*3];
 double model_slope[1024],model_intercept[1024];bool model_used[1024];
};
static int p51_coherent_core(const float* bands,int n,int channels,
 double half,double first,double last,double minimum,float* out,double* times,double deadline,const double* prior=nullptr,double lock_radius=0.,const double* local_prior=nullptr) { P11Scope scope(8);
 if(!bands||!out||!times||(n!=24&&n!=64)||(channels!=1&&channels!=3)||
    !std::isfinite(half)||half<2.5||half>24||!std::isfinite(minimum)||minimum<0||
    !std::isfinite(first)||!std::isfinite(last)||first<0||last>1||first>=last)return -1;
 if(!std::isfinite(lock_radius)||lock_radius<0||lock_radius>half)return -1;
 const double began=p11_wall(),cpu=p11_cpu();
 static thread_local P11CoherentWorkspace ws;
 for(int edge=0;edge<4;edge++){
   if(deadline>0&&p11_wall()>=deadline){times[0]=p11_wall()-began;times[1]=p11_cpu()-cpu;return 1;}
  const float* data=bands+edge*n*65*channels;
  for(int k=0;k<n;k++){
   ws.t[k]=first+(last-first)*k/(n-1.);double differences[64];
   for(int j=0;j<65;j++)for(int c=0;c<channels;c++){
    const int pos=(k*65+j)*channels+c;const float value=data[pos];
    if(!std::isfinite(value))return -2;
    ws.smooth[pos]=(j==0||j==64)?value:(data[pos-channels]+2.f*value+data[pos+channels])*.25f;
   }
   for(int j=0;j<64;j++){
    double d=0;for(int c=0;c<channels;c++)d=std::max(d,double(std::abs(data[(k*65+j+1)*channels+c]-data[(k*65+j)*channels+c])));
    differences[j]=d;
   }
   std::sort(differences,differences+64);ws.noise[k]=(differences[31]+differences[32])*.5;
   for(int j=0;j<65;j++){
    float g=0;if(j>=4&&j<61)for(int c=0;c<channels;c++)
     g=std::max(g,std::abs(ws.smooth[(k*65+j+4)*channels+c]-ws.smooth[(k*65+j-4)*channels+c]));
    ws.gradient[k*65+j]=g;
    const double offset=-half+2*half*j/64.;
    ws.work[k*65+j]=(lock_radius>0&&std::abs(offset)>lock_radius)?0.f:
        float(g/(1.+.35*std::abs(offset)/std::max(1.,half)));
   }
  }
  for(int peak=0;peak<3;peak++)for(int k=0;k<n;k++){
   int col=0;for(int j=1;j<65;j++)if(ws.work[k*65+j]>ws.work[k*65+col])col=j;
   const double left=ws.gradient[k*65+std::max(col-1,0)],mid=ws.gradient[k*65+col],right=ws.gradient[k*65+std::min(col+1,64)];
   const double den=left-2*mid+right;
   const double alpha=std::abs(den)>1e-5?std::max(-.5,std::min(.5,.5*(left-right)/den)):0.;
       const int pos=k*3+peak;ws.affinity[pos]=0.;
    const double* signed_prior=local_prior?local_prior+(edge*n+k)*3:(prior?prior+edge*3:nullptr);
    if(signed_prior&&channels==3&&col>=4&&col<61){
     double pn=0,gn=0,dot=0;
     for(int c=0;c<3;c++){double a=signed_prior[c];double g=ws.smooth[(k*65+col+4)*3+c]-ws.smooth[(k*65+col-4)*3+c];pn+=a*a;gn+=g*g;dot+=a*g;}
     // Only choose among real supported peaks. A signed side prior breaks
     // parallel-border ties; it cannot create contrast or waive support/TLS.
     if(pn>=256.&&gn>1.)ws.affinity[pos]=std::max(-1.,std::min(1.,dot/std::sqrt(pn*gn)));
    }
    ws.positions[pos]=-half+2*half*(col+alpha)/64.;ws.strengths[pos]=mid;
   ws.eligible[pos]=mid>=std::max(minimum,4*ws.noise[k])&&std::abs(ws.positions[pos])<half*.9;
   if(lock_radius>0){
    ws.eligible[pos]=ws.eligible[pos]&&std::abs(ws.positions[pos])<=lock_radius;
    if(signed_prior&&channels==3){
     double pn=0;for(int c=0;c<3;c++)pn+=signed_prior[c]*signed_prior[c];
     // Locked verification cannot change to the opposite side of a bezel.
     // A weak prior does not manufacture a sign; real support/TLS is mandatory.
     if(pn>=256.)ws.eligible[pos]=ws.eligible[pos]&&ws.affinity[pos]>=.25;
    }
   }
   for(int j=-4;j<=4;j++)ws.work[k*65+std::max(0,std::min(64,col+j))]=0;
  }
  double best=-1e30;bool found=false;std::fill(ws.model_used,ws.model_used+1024,false);
   for(int ai=0;ai<8;ai++){
    if(deadline>0&&p11_wall()>=deadline){times[0]=p11_wall()-began;times[1]=p11_cpu()-cpu;return 1;}
    for(int bi=0;bi<8;bi++)for(int ka=0;ka<3;ka++)for(int kb=0;kb<3;kb++){
   const int a=ai*(n-1)/7,b=bi*(n-1)/7;const double dt=ws.t[b]-ws.t[a];
   if(dt<.4||!ws.eligible[a*3+ka]||!ws.eligible[b*3+kb])continue;
   const double slope=(ws.positions[b*3+kb]-ws.positions[a*3+ka])/dt;
   const double intercept=ws.positions[a*3+ka]-slope*ws.t[a];
   const double model_limit=lock_radius>0?lock_radius:half;
   if(std::max(std::abs(intercept+slope*ws.t[0]),std::abs(intercept+slope*ws.t[n-1]))>model_limit)continue;
   // Score each EXACT line model once. No quantization/tolerance or changed
   // winner ordering: a later identical model has identical profile residuals.
   double si=slope==0.?0.:slope,ic=intercept==0.?0.:intercept;
   uint64_t sbits=0,ibits=0;std::memcpy(&sbits,&si,8);std::memcpy(&ibits,&ic,8);
   unsigned bucket=unsigned((sbits^(sbits>>29)^ibits^(ibits>>31))*0x9e3779b97f4a7c15ULL)&1023u;
   while(ws.model_used[bucket]&&(ws.model_slope[bucket]!=si||ws.model_intercept[bucket]!=ic))bucket=(bucket+1)&1023u;
   if(ws.model_used[bucket])continue;
   ws.model_used[bucket]=true;ws.model_slope[bucket]=si;ws.model_intercept[bucket]=ic;
   int selected[64];bool keep[64];double count=0,strong=0,affinity=0;
   for(int k=0;k<n;k++){
    const double predicted=intercept+slope*ws.t[k];double distance=1e30;int chosen=0;
    for(int peak=0;peak<3;peak++)if(ws.eligible[k*3+peak]){
     const double d=std::abs(ws.positions[k*3+peak]-predicted);if(d<distance){distance=d;chosen=peak;}
    }
    selected[k]=chosen;keep[k]=distance<=.85;
    if(keep[k]){count++;strong+=std::min(ws.strengths[k*3+chosen],64.);affinity+=ws.affinity[k*3+chosen];}
   }
   const double score=count+.08*strong/64.-.08*std::abs(intercept+slope*.5)+.20*affinity;
   if(!found||score>best){found=true;best=score;std::copy(selected,selected+n,ws.best_peak);std::copy(keep,keep+n,ws.best_keep);}
  }
   }
  for(int k=0;k<n;k++){
   const int chosen=found?ws.best_peak[k]:0;const int pos=(edge*n+k)*3;
   out[pos]=float(ws.positions[k*3+chosen]);out[pos+1]=float(ws.strengths[k*3+chosen]);out[pos+2]=(found&&ws.best_keep[k])?1.f:0.f;
  }
 }
 times[0]=p11_wall()-began;times[1]=p11_cpu()-cpu;return 0;
}

extern "C" int p11_coherent_profiles(const float* bands,int n,int channels,
 double half,double first,double last,double minimum,float* out,double* times){
 return p51_coherent_core(bands,n,channels,half,first,last,minimum,out,times,0.);
}

// V62 spatially locked independent grid; same real peaks and consensus fit.
extern "C" int p11_locked_coherent_profiles(const float* bands,int n,int channels,
 double half,double first,double last,double minimum,double lock_radius,const double* prior,
 float* out,double* times){
 if(prior)for(int i=0;i<12;i++)if(!std::isfinite(prior[i])||std::abs(prior[i])>1024.)return -2;
 return p51_coherent_core(bands,n,channels,half,first,last,minimum,out,times,0.,prior,lock_radius);
}

// V46 preview: cached source coordinates, write directly into owned small canvas.
// No source pointer survives return; owner pins both leases for this call.
extern "C" int p11_preview_canvas_maps(const uint8_t* raw,int wi,int hi,int stride,int mode,
 const uint8_t* bgr,int bw,int bh,int bstride,uint8_t* canvas,int lw,int rw,int height,
 const int32_t* lx,const int32_t* ly,const int32_t* rx,const int32_t* ry,double* times){
 if(!raw||!bgr||!canvas||!lx||!ly||!rx||!ry||!times||wi<2||hi<2||wi>1280||hi>1280
  ||(wi&1)||stride<2*wi||bw<2||bh<2||bw>1280||bh>1280||bstride<3*bw||mode<0||mode>3
  ||lw<1||rw<1||height<1||lw>640||rw>640||height>640||lw>wi||rw>bw||height>hi||height>bh)return -1;
 for(int x=0;x<lw;x++)if(lx[x]<0||lx[x]>=wi)return -2;
 for(int x=0;x<rw;x++)if(rx[x]<0||rx[x]>=bw)return -2;
 for(int y=0;y<height;y++)if(ly[y]<0||ly[y]>=hi||ry[y]<0||ry[y]>=bh)return -2;
 const int k[4][5]={{298,409,100,208,516},{256,359,88,183,454},{298,459,55,136,541},{256,403,48,120,475}};
 const int* coeff=k[mode];double begin=p11_wall();size_t out_stride=size_t(lw+rw)*3;
 for(int y=0;y<height;y++){
  const uint8_t* row=raw+size_t(ly[y])*stride;uint8_t* dst=canvas+size_t(y)*out_stride;
  for(int x=0;x<lw;x++){
   int sx=lx[x];const uint8_t* pair=row+4*(sx/2);
   int yy=coeff[0]*((mode&1)?int(pair[2*(sx&1)]):std::max(0,int(pair[2*(sx&1)])-16));
   int u=int(pair[1])-128,v=int(pair[3])-128;
   dst[3*x]=c31(yy+coeff[4]*u);dst[3*x+1]=c31(yy-coeff[2]*u-coeff[3]*v);dst[3*x+2]=c31(yy+coeff[1]*v);
  }
 }
 double middle=p11_wall();
 for(int y=0;y<height;y++){
  const uint8_t* row=bgr+size_t(ry[y])*bstride;uint8_t* dst=canvas+size_t(y)*out_stride+3*lw;
  for(int x=0;x<rw;x++)std::memcpy(dst+3*x,row+3*rx[x],3);
 }
 times[0]=middle-begin;times[1]=p11_wall()-middle;times[2]=0.;return 0;
}


// V47 display-only Q8 bilinear sampling. Five immutable Nx3 axis tables
// [low, high, fraction/256] belong to the ordinary-RAM preview workspace.
// Chroma uses half-width pair-centre geometry, matching p11_yuyv_preview.
// The owner holds both source leases until return; no pointer is retained.
static bool p47_axis_valid(const int32_t* axis,int count,int limit){
 if(!axis||count<1||limit<1)return false;
 for(int i=0;i<count;i++){
  const int32_t* a=axis+3*i;
  if(a[0]<0||a[0]>=limit||a[1]<a[0]||a[1]>=limit||a[1]>a[0]+1||a[2]<0||a[2]>256)return false;
 }return true;
}
static inline int p47_sample(const uint8_t* top,const uint8_t* bottom,
 const int32_t* x,int fy,int step,int channel){
 const int fx=x[2];
 int a=(256-fx)*top[step*x[0]+channel]+fx*top[step*x[1]+channel];
 int b=(256-fx)*bottom[step*x[0]+channel]+fx*bottom[step*x[1]+channel];
 return ((256-fy)*a+fy*b+32768)>>16;
}
extern "C" int p11_preview_canvas_linear(const uint8_t* raw,int wi,int hi,int stride,int mode,
 const uint8_t* bgr,int bw,int bh,int bstride,uint8_t* canvas,int lw,int rw,int height,
 const int32_t* lx,const int32_t* ly,const int32_t* lc,
 const int32_t* rx,const int32_t* ry,double* times){
 if(!raw||!bgr||!canvas||!times||wi<2||hi<2||wi>1280||hi>1280||(wi&1)||stride<2*wi
  ||bw<2||bh<2||bw>1280||bh>1280||bstride<3*bw||mode<0||mode>3
  ||lw<1||rw<1||height<1||lw>640||rw>640||height>640||lw>wi||rw>bw||height>hi||height>bh)return -1;
 if(!p47_axis_valid(lx,lw,wi)||!p47_axis_valid(lc,lw,wi/2)
  ||!p47_axis_valid(ly,height,hi)||!p47_axis_valid(rx,rw,bw)||!p47_axis_valid(ry,height,bh))return -2;
 static const int k[4][5]={{298,409,100,208,516},{256,359,88,183,454},
                         {298,459,55,136,541},{256,403,48,120,475}};
 const int* coeff=k[mode];const size_t out_stride=size_t(lw+rw)*3;
 double begin=p11_wall();
 for(int y=0;y<height;y++){
  const int32_t* ay=ly+3*y;
  const uint8_t* top=raw+size_t(ay[0])*stride;
  const uint8_t* bottom=raw+size_t(ay[1])*stride;
  uint8_t* dst=canvas+size_t(y)*out_stride;
  for(int x=0;x<lw;x++){
   int value=p47_sample(top,bottom,lx+3*x,ay[2],2,0);
   int u=p47_sample(top,bottom,lc+3*x,ay[2],4,1)-128;
   int v=p47_sample(top,bottom,lc+3*x,ay[2],4,3)-128;
   int l=coeff[0]*((mode&1)?value:std::max(0,value-16));
   dst[3*x]=c31(l+coeff[4]*u);
   dst[3*x+1]=c31(l-coeff[2]*u-coeff[3]*v);
   dst[3*x+2]=c31(l+coeff[1]*v);
  }
 }
 double middle=p11_wall();
 for(int y=0;y<height;y++){
  const int32_t* ay=ry+3*y;
  const uint8_t* top=bgr+size_t(ay[0])*bstride;
  const uint8_t* bottom=bgr+size_t(ay[1])*bstride;
  uint8_t* dst=canvas+size_t(y)*out_stride+3*lw;
  for(int x=0;x<rw;x++)for(int c=0;c<3;c++)
   dst[3*x+c]=uint8_t(p47_sample(top,bottom,rx+3*x,ay[2],3,c));
 }
 times[0]=middle-begin;times[1]=p11_wall()-middle;times[2]=0.;return 0;
}

// V48 CPU-only packed exterior sampling; no device access or retained pointers.
static float p48_plane(const uint8_t* raw,int stride,int width,int height,
 int step,int channel,float x,float y){
 x=std::max(0.f,std::min(float(width-1),x));y=std::max(0.f,std::min(float(height-1),y));
 int ix=int(std::floor(x)),iy=int(std::floor(y));
 int jx=std::min(ix+1,width-1),jy=std::min(iy+1,height-1);
 // OpenCV INTER_LINEAR remap uses 1/32 phases, replicate border and rounded bytes.
 int fx=int(std::nearbyint((x-ix)*32.f)),fy=int(std::nearbyint((y-iy)*32.f));
 const uint8_t* a=raw+size_t(iy)*stride;const uint8_t* b=raw+size_t(jy)*stride;
 int top=(32-fx)*a[step*ix+channel]+fx*a[step*jx+channel];
 int bottom=(32-fx)*b[step*ix+channel]+fx*b[step*jx+channel];
 return float(((32-fy)*top+fy*bottom+512)>>10);
}
extern "C" int p11_yuyv_profiles(const uint8_t* raw,int width,int height,int stride,
 const float* x,const float* y,int count,float* output){
 if(!raw||!x||!y||!output||width<2||height<2||width>1280||height>1280
    ||(width&1)||stride<2*width||count<1||count>4*64*65)return -1;
 for(int i=0;i<count;i++)if(!std::isfinite(x[i])||!std::isfinite(y[i])
    ||std::abs(x[i])>1000000.f||std::abs(y[i])>1000000.f)return -2;
 for(int i=0;i<count;i++){
  float ux=(x[i]-.5f)*.5f;
  output[3*i]=p48_plane(raw,stride,width,height,2,0,x[i],y[i]);
  output[3*i+1]=1.75f*(p48_plane(raw,stride,width/2,height,4,1,ux,y[i])-128.f);
  output[3*i+2]=1.75f*(p48_plane(raw,stride,width/2,height,4,3,ux,y[i])-128.f);
 }
 return 0;
}

// V51 CPU-only current exterior transaction. Source lease is borrowed only until
// return. TLS workspaces are thread-local; no camera/CMA/MMIO pointer is stored.
struct P51ExteriorWorkspace {
 float bands[4*64*65*3],selection[4*64*3];
 double points[128],trimmed[128],residual[64],lines[12],normal[8],local_prior[4*64*3];
};
static double p51_median(const double* values,int count){
 double tmp[64];std::copy(values,values+count,tmp);std::sort(tmp,tmp+count);
 return count%2?tmp[count/2]:(tmp[count/2-1]+tmp[count/2])*.5;
}
static bool p51_tls(const double* points,int count,double* line,double& rms){
 if(count<12)return false;
 double cx=0,cy=0,xx=0,xy=0,yy=0;
 for(int i=0;i<count;i++){cx+=points[2*i];cy+=points[2*i+1];}cx/=count;cy/=count;
 for(int i=0;i<count;i++){double x=points[2*i]-cx,y=points[2*i+1]-cy;xx+=x*x;xy+=x*y;yy+=y*y;}
 if(!std::isfinite(xx+yy)||std::hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1))return false;
 double angle=.5*std::atan2(2*xy,xx-yy),nx=-std::sin(angle),ny=std::cos(angle);
 line[0]=nx;line[1]=ny;line[2]=-nx*cx-ny*cy;
 double sum=0;for(int i=0;i<count;i++){double d=nx*(points[2*i]-cx)+ny*(points[2*i+1]-cy);sum+=d*d;}
 rms=std::sqrt(sum/count);return std::isfinite(rms);
}
static double p51_area(const double* q){
 double area=0;for(int i=0;i<4;i++){int j=(i+1)%4;area+=q[2*i]*q[2*j+1]-q[2*j]*q[2*i+1];}return area*.5;
}
static bool p51_convex(const double* q){
 double sign=0;
 for(int i=0;i<4;i++){
  int j=(i+1)%4,k=(i+2)%4;
  double cross=(q[2*j]-q[2*i])*(q[2*k+1]-q[2*j+1])-(q[2*j+1]-q[2*i+1])*(q[2*k]-q[2*j]);
  if(std::abs(cross)<1e-6||(sign!=0&&cross*sign<=0))return false;sign=cross;
 }return true;
}
static int p62_yuyv_exterior_core(const uint8_t* raw,int w,int h,int stride,const double* q,
 double half,int n,double first,double last,double minimum,double support,double max_rms,
 double deadline,const double* prior,double* out,double* stats,double lock_radius,bool point_local_sign=false){ P11Scope scope(8);
 if(!raw||!q||!out||!stats||w<2||h<2||w>1280||h>1280||(w&1)||stride<2*w
    ||(n!=24&&n!=64)||!std::isfinite(half)||half<2.5||half>24
    ||!std::isfinite(first)||!std::isfinite(last)||first<0||last>1||first>=last
    ||!std::isfinite(minimum)||minimum<0||!std::isfinite(support)||support<.60||support>1
    ||!std::isfinite(max_rms)||max_rms<=0||!std::isfinite(deadline)||deadline<0)return -1;
 for(int i=0;i<4;i++)if(!std::isfinite(q[2*i])||!std::isfinite(q[2*i+1])
    ||q[2*i]<1||q[2*i]>=w-1||q[2*i+1]<1||q[2*i+1]>=h-1)return -2;
   if(!std::isfinite(lock_radius)||lock_radius<0||lock_radius>half)return -1;
   if(!p51_convex(q)||std::abs(p51_area(q))<16)return -2;
  if(prior)for(int i=0;i<12;i++)if(!std::isfinite(prior[i])||std::abs(prior[i])>1024.)return -2;
 const double began=p11_wall(),cpu=p11_cpu();std::copy(q,q+8,out);std::fill(stats,stats+80,0.);
 for(int e=0;e<4;e++)stats[e*13+3]=1e30;
 auto finish=[&](int code){stats[54]=p11_wall()-began;stats[55]=p11_cpu()-cpu;
  if(code==1){stats[52]=stats[53]=0;stats[62]=1;std::copy(q,q+8,out);}return code;};
 auto expired=[&](){return deadline>0&&p11_wall()>=deadline;};
 if(expired())return finish(1);
 try {
  static thread_local P51ExteriorWorkspace ws;
  double cx=0,cy=0;for(int e=0;e<4;e++){cx+=q[2*e];cy+=q[2*e+1];}cx/=4;cy/=4;
  double stage=p11_wall(),stage_cpu=p11_cpu();
  for(int e=0;e<4;e++){
   int next=(e+1)%4;double ax=q[2*e],ay=q[2*e+1],ex=q[2*next]-ax,ey=q[2*next+1]-ay;
   double len=std::hypot(ex,ey);if(len<4)return finish(-2);
   double nx=-ey/len,ny=ex/len;if((cx-ax-ex*.5)*nx+(cy-ay-ey*.5)*ny<0){nx=-nx;ny=-ny;}
   ws.normal[2*e]=nx;ws.normal[2*e+1]=ny;
   for(int k=0;k<n;k++){
    if((k&7)==0&&expired()){stats[56]=p11_wall()-stage;stats[57]=p11_cpu()-stage_cpu;return finish(1);}
    double t=first+(last-first)*k/(n-1.),bx=ax+t*ex,by=ay+t*ey;
    if(point_local_sign){
     // Independent verification follows the selected CURRENT physical line.
     // A multicolour cover does not have one signed vector for the entire side.
     double* sign=ws.local_prior+(e*n+k)*3;
     float ox=float(bx-3.*nx),oy=float(by-3.*ny),ix=float(bx+3.*nx),iy=float(by+3.*ny);
     sign[0]=p48_plane(raw,stride,w,h,2,0,ix,iy)-p48_plane(raw,stride,w,h,2,0,ox,oy);
     sign[1]=1.75*(p48_plane(raw,stride,w/2,h,4,1,(ix-.5f)*.5f,iy)-p48_plane(raw,stride,w/2,h,4,1,(ox-.5f)*.5f,oy));
     sign[2]=1.75*(p48_plane(raw,stride,w/2,h,4,3,(ix-.5f)*.5f,iy)-p48_plane(raw,stride,w/2,h,4,3,(ox-.5f)*.5f,oy));
    }
    for(int j=0;j<65;j++){
     double d=-half+2*half*j/64.;float x=float(bx+d*nx),y=float(by+d*ny),ux=(x-.5f)*.5f;
     float* dst=ws.bands+((e*n+k)*65+j)*3;
     dst[0]=p48_plane(raw,stride,w,h,2,0,x,y);
     dst[1]=1.75f*(p48_plane(raw,stride,w/2,h,4,1,ux,y)-128.f);
     dst[2]=1.75f*(p48_plane(raw,stride,w/2,h,4,3,ux,y)-128.f);
    }
    const float near_inside=ws.bands[((e*n+k)*65+48)*3];
    if(near_inside>=250.f)stats[65+e]+=1./n;
    if(near_inside<=4.f)stats[69+e]+=1./n;
   }
  }
  stats[56]=p11_wall()-stage;stats[57]=p11_cpu()-stage_cpu;
  double times[2]={0,0};int code=p51_coherent_core(ws.bands,n,3,half,first,last,minimum,ws.selection,times,deadline,prior,lock_radius,point_local_sign?ws.local_prior:nullptr);
  stats[58]=times[0];stats[59]=times[1];if(code)return finish(code);
  stage=p11_wall();stage_cpu=p11_cpu();bool accepted[4]={false,false,false,false};
  const int needed=int(std::ceil(n*support));
  for(int e=0;e<4;e++){
   if(expired()){stats[60]=p11_wall()-stage;stats[61]=p11_cpu()-stage_cpu;return finish(1);}
   int next=(e+1)%4,count=0;double ax=q[2*e],ay=q[2*e+1],ex=q[2*next]-ax,ey=q[2*next+1]-ay;
   double nx=ws.normal[2*e],ny=ws.normal[2*e+1],outer[3][64],inner[3][64],contrasts[64];
   for(int k=0;k<n;k++){
    const float* band=ws.bands+(e*n+k)*65*3;
    for(int c=0;c<3;c++){
     double a[8],b[8];for(int j=0;j<8;j++){a[j]=band[j*3+c];b[j]=band[(57+j)*3+c];}
     outer[c][k]=p51_median(a,8);inner[c][k]=p51_median(b,8);
    }
    contrasts[k]=inner[0][k]-outer[0][k];
    const float* selected=ws.selection+(e*n+k)*3;if(selected[2]<=.5f)continue;
    double t=first+(last-first)*k/(n-1.),px=ax+t*ex+selected[0]*nx,py=ay+t*ey+selected[0]*ny;
    if(px<1||px>=w-1||py<1||py>=h-1)continue;
    ws.points[2*count]=px;ws.points[2*count+1]=py;count++;
   }
   double* s=stats+13*e;s[0]=count;s[5]=p51_median(contrasts,n);s[12]=std::abs(s[5])>=8?(s[5]>0?1.:-1.):0.;
   for(int c=0;c<3;c++){s[6+c]=p51_median(outer[c],n);s[9+c]=p51_median(inner[c],n);}
   if(count<needed)continue;
   int retained=count;double rms=1e30;double* line=ws.lines+3*e;bool fitted=true;
   for(int iteration=0;iteration<3;iteration++){
    if(!p51_tls(ws.points,retained,line,rms)){fitted=false;break;}
    for(int k=0;k<retained;k++)ws.residual[k]=std::abs(line[0]*ws.points[2*k]+line[1]*ws.points[2*k+1]+line[2]);
    double threshold=std::min(1.25,std::max(.55,2.5*p51_median(ws.residual,retained)));int keep=0;
    for(int k=0;k<retained;k++)if(ws.residual[k]<=threshold){ws.trimmed[2*keep]=ws.points[2*k];ws.trimmed[2*keep+1]=ws.points[2*k+1];keep++;}
    if(keep==retained||keep<12)break;std::copy(ws.trimmed,ws.trimmed+2*keep,ws.points);retained=keep;
   }
   fitted=fitted&&p51_tls(ws.points,retained,line,rms);double lo=1e30,hi=-1e30;
   for(int k=0;k<retained;k++){double t=((ws.points[2*k]-ax)*ex+(ws.points[2*k+1]-ay)*ey)/(ex*ex+ey*ey);lo=std::min(lo,t);hi=std::max(hi,t);}
       s[1]=retained;s[2]=hi-lo;s[3]=rms;
    // Side signature is always sampled at +/-3 source pixels of the fitted
    // physical line. Changing search radius no longer changes its meaning.
    if(fitted){
     double oa[3][64],ia[3][64];double inward=(line[0]*nx+line[1]*ny)>=0?1.:-1.;
     for(int k=0;k<n;k++){
      double t=first+(last-first)*k/(n-1.),x=ax+t*ex,y=ay+t*ey,d=line[0]*x+line[1]*y+line[2];
      x-=d*line[0];y-=d*line[1];
      for(int side=0;side<2;side++){
       float px=float(x+(side?3.:-3.)*inward*line[0]),py=float(y+(side?3.:-3.)*inward*line[1]);
       double* v=side?ia[0]:oa[0];v[k]=p48_plane(raw,stride,w,h,2,0,px,py);
       (side?ia[1]:oa[1])[k]=1.75*(p48_plane(raw,stride,w/2,h,4,1,(px-.5f)*.5f,py)-128.);
       (side?ia[2]:oa[2])[k]=1.75*(p48_plane(raw,stride,w/2,h,4,3,(px-.5f)*.5f,py)-128.);
      }
     }
     for(int c=0;c<3;c++){s[6+c]=p51_median(oa[c],n);s[9+c]=p51_median(ia[c],n);}
    }
    accepted[e]=fitted&&retained>=needed&&s[2]>=.60&&rms<=max_rms;s[4]=accepted[e]?1.:0.;
  }
  int refined=0;
  for(int e=0;e<4;e++)if(accepted[(e+3)%4]&&accepted[e]){
   const double* a=ws.lines+3*((e+3)%4);const double* b=ws.lines+3*e;
   double den=a[0]*b[1]-a[1]*b[0];if(std::abs(den)<.08)continue;
   double x=(a[1]*b[2]-a[2]*b[1])/den,y=(a[2]*b[0]-a[0]*b[2])/den;
   if(std::isfinite(x)&&std::isfinite(y)&&std::hypot(x-q[2*e],y-q[2*e+1])<=3*half&&x>=1&&x<w-1&&y>=1&&y<h-1){out[2*e]=x;out[2*e+1]=y;refined++;}
  }
  stats[63]=std::abs(p51_area(out))/std::abs(p51_area(q));
  bool valid=refined==4&&p51_convex(out)&&stats[63]>=.85&&stats[63]<=1.15;
  stats[52]=valid?4.:0.;stats[53]=valid?1.:0.;if(!valid)std::copy(q,q+8,out);
  stats[60]=p11_wall()-stage;stats[61]=p11_cpu()-stage_cpu;
  if(expired())return finish(1);return finish(0);
 }catch(...){return finish(-3);}
}

extern "C" int p11_yuyv_exterior(const uint8_t* raw,int w,int h,int stride,const double* q,
 double half,int n,double first,double last,double minimum,double support,double max_rms,
 double deadline,const double* prior,double* out,double* stats){
 return p62_yuyv_exterior_core(raw,w,h,stride,q,half,n,first,last,minimum,support,max_rms,deadline,prior,out,stats,0.);
}
extern "C" int p11_locked_yuyv_exterior(const uint8_t* raw,int w,int h,int stride,const double* q,
 double half,int n,double first,double last,double minimum,double support,double max_rms,
 double deadline,const double* prior,double* out,double* stats,double lock_radius){
 if(!std::isfinite(lock_radius)||lock_radius<=0)return -1;
 return p62_yuyv_exterior_core(raw,w,h,stride,q,half,n,first,last,minimum,support,max_rms,deadline,prior,out,stats,lock_radius);
}

// V83 independent grid: keep all peak/contrast/support/TLS gates, use current
// point-local signed side evidence. No source pointer survives this call.
extern "C" int p11_v83_locked_yuyv_exterior(const uint8_t* raw,int w,int h,int stride,const double* q,
 double half,int n,double first,double last,double minimum,double support,double max_rms,
 double deadline,const double* prior,double* out,double* stats,double lock_radius){
 if(!std::isfinite(lock_radius)||lock_radius<=0)return -1;
 return p62_yuyv_exterior_core(raw,w,h,stride,q,half,n,first,last,minimum,support,max_rms,deadline,prior,out,stats,lock_radius,true);
}

// V52 CPU native owner transaction AFTER CPU cache invalidate + packet ACK.
// OwnerBatch pins the mappings. No worker can invoke this or share device IO.
extern "C" int p11_owner_admit(volatile uint32_t* planner,volatile uint32_t* pixel,
 volatile uint32_t* dma,uint32_t sequence,uint32_t input_size,uint32_t output_size,
 uint32_t capacity,double timeout,uint32_t* out,double* times){ P11Scope profile(28);
 if(!planner||!pixel||!dma||!out||!times||!sequence||capacity<1||capacity>512
    ||!std::isfinite(timeout)||timeout<=0||timeout>1.)return -1;
 const double begin=p11_wall(),cpu=p11_cpu();
 std::atomic_thread_fence(std::memory_order_seq_cst);
 if(pixel[1]&1)return 4;
 if(planner[0x38/4]||planner[0x0c/4]!=sequence||planner[0x10/4]!=sequence
    ||(planner[1]&3)!=2||planner[0xa0/4]>capacity
    ||planner[0x40/4]!=input_size||planner[0x44/4]!=output_size)return 2;
 int code=p11_owner_batch(planner,pixel,dma,0,0,sequence,timeout,2,out);
 times[0]=p11_wall()-begin;times[1]=p11_cpu()-cpu;
 if(code)return code;
 if(out[11]!=sequence||out[12]!=sequence||out[13]!=1
    ||out[14]!=((output_size&0xffff)<<16|441u)||(out[15]&15)!=2)return 2;
 return 0;
}

// V52 paired ordinary-RAM snapshot; 2x area averages preserve YUYV pairing.
// Destination dimensions must be either exact or floor-halved; no leases escape.
extern "C" int p11_preview_snapshot(const uint8_t* raw,int w,int h,int stride,uint8_t* dst,int dw,int dh,
 const uint8_t* bgr,int bw,int bh,int bs,uint8_t* out,int ow,int oh,double* times){
 if(!raw||!dst||!bgr||!out||!times||w<4||h<2||(w&1)||dw<2||(dw&1)||stride<2*w||bs<3*bw)return -1;
 int rf=(dw==w&&dh==h)?1:(dw==w/2&&dh==h/2&&w%4==0)?2:0;
 int bf=(ow==bw&&oh==bh)?1:(ow==bw/2&&oh==bh/2)?2:0;
 if(!rf||!bf||bw<2||bh<2)return -1;
 double begin=p11_wall();
 if(rf==1){for(int y=0;y<h;y++)std::memcpy(dst+size_t(y)*2*w,raw+size_t(y)*stride,2*w);}
 else for(int y=0;y<dh;y++){
  const uint8_t* a=raw+size_t(2*y)*stride;const uint8_t* b=a+stride;uint8_t* z=dst+size_t(y)*2*dw;
  for(int x=0;x<dw/2;x++){
   int k=8*x;z[4*x]=uint8_t((a[k]+a[k+2]+b[k]+b[k+2]+2)>>2);
   z[4*x+2]=uint8_t((a[k+4]+a[k+6]+b[k+4]+b[k+6]+2)>>2);
   z[4*x+1]=uint8_t((a[k+1]+a[k+5]+b[k+1]+b[k+5]+2)>>2);
   z[4*x+3]=uint8_t((a[k+3]+a[k+7]+b[k+3]+b[k+7]+2)>>2);
  }
 }
 double middle=p11_wall();
 if(bf==1){for(int y=0;y<bh;y++)std::memcpy(out+size_t(y)*3*bw,bgr+size_t(y)*bs,3*bw);}
 else for(int y=0;y<oh;y++){
  const uint8_t* a=bgr+size_t(2*y)*bs;const uint8_t* b=a+bs;uint8_t* z=out+size_t(y)*3*ow;
  for(int x=0;x<ow;x++)for(int c=0;c<3;c++)z[3*x+c]=uint8_t((a[6*x+c]+a[6*x+3+c]+b[6*x+c]+b[6*x+3+c]+2)>>2);
 }
 times[0]=middle-begin;times[1]=p11_wall()-middle;return 0;
}


// V67 same-frame locked64 + independently spaced locked24 in one CPU call.
// Reuses the unchanged exterior core; no quad is accepted by this function.
extern "C" int p11_v67_locked_pair(const uint8_t* raw,int w,int h,int stride,const double* q,
 double half,double minimum,double support,double max_rms,double deadline,const double* prior,
 double primary_lock,double scale_min,double cpu_budget,double* q64,double* s64,double* q24,double* s24,double* times){
 if(!raw||!q||!q64||!s64||!q24||!s24||!times||!std::isfinite(scale_min)||scale_min<=0
    ||!std::isfinite(cpu_budget)||cpu_budget<=0)return -1;
 const double began=p11_wall(),cpu=p11_cpu();std::copy(q,q+8,q24);std::fill(s24,s24+80,0.);
 for(int e=0;e<4;++e)s24[e*13+3]=1e30;
 auto finish=[&](int code){times[0]=p11_wall()-began;times[1]=p11_cpu()-cpu;times[2]=code;times[3]=code==0?1.:0.;return code;};
 int code=p11_v83_locked_yuyv_exterior(raw,w,h,stride,q,half,64,.10,.90,minimum,support,max_rms,deadline,prior,q64,s64,primary_lock);
 if(code!=0){s24[62]=1.;return finish(code);}
 if(s64[53]==0)return finish(2);
 if(p11_cpu()-cpu>=cpu_budget){s24[62]=1.;return finish(3);}
 double next_prior[12];double noise=0.;bool valid_noise=true;
 for(int e=0;e<4;++e){
  double rms=s64[e*13+3];if(!std::isfinite(rms)||rms<0||rms/scale_min>2.)valid_noise=false;
  noise=std::max(noise,rms);
  for(int c=0;c<3;++c){
   float outer=float(s64[e*13+6+c]),inner=float(s64[e*13+9+c]),weight=c==0?255.f:224.f;
   float delta=inner-outer;float normalized=std::max(-1.5f,std::min(1.5f,delta/weight));
   next_prior[e*3+c]=double(normalized)*weight;
  }
 }
 if(!valid_noise)noise=0.;
 double secondary_lock=std::min(.70*half,std::max(1.25,std::min(2.,1.25+.75*noise)));
 // Both independent grids sample the same CURRENT locked line, not a wide
 // motion-search corridor. Python retains continuity/line/agreement gates.
 code=p11_v83_locked_yuyv_exterior(raw,w,h,stride,q64,half,24,.12,.88,minimum,support,max_rms,deadline,next_prior,q24,s24,secondary_lock);
 return finish(code);
}

// V68 CPU-only small-quad workspace. The old edge/LK kernels stay unchanged.
// Similarity residual is a jitter diagnostic, never a projective acceptance test.
static double p68_line_error(const double* a,const double* b){
 double maximum=0.;
 for(int pass=0;pass<2;++pass){const double* p=pass?b:a;const double* q=pass?a:b;
  for(int e=0;e<4;++e){int n=(e+1)%4;double dx=p[2*n]-p[2*e],dy=p[2*n+1]-p[2*e+1];
   double len=std::hypot(dx,dy);if(len<4.)return 1e30;
   const double fractions[3]={.15,.5,.85};
   for(int i=0;i<3;++i){double f=fractions[i];double x=q[2*e]+f*(q[2*n]-q[2*e]);double y=q[2*e+1]+f*(q[2*n+1]-q[2*e+1]);
    maximum=std::max(maximum,std::abs((x-p[2*e])*(-dy)+(y-p[2*e+1])*dx)/len);}
  }
 }return maximum;
}
extern "C" int p11_v68_stabilize(const uint8_t* gray,int w,int h,int stride,
 const double* previous,const double* prediction,const double* current,const double* support,
 const double* rms,const int32_t* polarity,int allow_filter,double* out,double* checked,double* edges,double* stats){
 if(!gray||!previous||!prediction||!current||!support||!rms||!polarity||!out||!checked||!edges||!stats
    ||w<4||h<4||w>1280||h>1280||stride<w||(allow_filter!=0&&allow_filter!=1))return -1;
 for(int i=0;i<8;++i)if(!std::isfinite(previous[i])||!std::isfinite(prediction[i])||!std::isfinite(current[i]))return -2;
 for(int e=0;e<4;++e)if(!std::isfinite(support[e])||!std::isfinite(rms[e])||support[e]<0.||support[e]>1.||rms[e]<0.)return -3;
 const double begin=p11_wall(),cpu=p11_cpu();std::fill(stats,stats+26,0.);std::fill(edges,edges+21,0.);
 std::copy(current,current+8,out);std::copy(current,current+8,checked);
 auto finish=[&](){stats[12]=p11_wall()-begin;stats[13]=p11_cpu()-cpu;return 0;};
 double pc[2]={0.,0.},cc[2]={0.,0.},motion=0.,correction=0.,noise=.06,min_support=1.;
 for(int e=0;e<4;++e){
  pc[0]+=prediction[2*e]/4.;pc[1]+=prediction[2*e+1]/4.;cc[0]+=current[2*e]/4.;cc[1]+=current[2*e+1]/4.;
  motion=std::max(motion,std::hypot(current[2*e]-previous[2*e],current[2*e+1]-previous[2*e+1]));
  correction=std::max(correction,std::hypot(current[2*e]-prediction[2*e],current[2*e+1]-prediction[2*e+1]));
  noise=std::max(noise,rms[e]);min_support=std::min(min_support,support[e]);
 }
 double den=0.,dot=0.,cross=0.;
 for(int e=0;e<4;++e){double x=prediction[2*e]-pc[0],y=prediction[2*e+1]-pc[1];
  double a=current[2*e]-cc[0],b=current[2*e+1]-cc[1];den+=x*x+y*y;dot+=x*a+y*b;cross+=x*b-y*a;}
 if(den<64.)return finish();
 double sx=dot/den,sy=cross/den,residual=0.,offsets[4];
 for(int e=0;e<4;++e){int n=(e+1)%4;double x=prediction[2*e]-pc[0],y=prediction[2*e+1]-pc[1];
  residual=std::max(residual,std::hypot(cc[0]+sx*x-sy*y-current[2*e],cc[1]+sy*x+sx*y-current[2*e+1]));
  double dx=prediction[2*n]-prediction[2*e],dy=prediction[2*n+1]-prediction[2*e+1],len=std::hypot(dx,dy);
  if(len<4.)return finish();
  double mx=(current[2*e]+current[2*n]-prediction[2*e]-prediction[2*n])*.5;
  double my=(current[2*e+1]+current[2*n+1]-prediction[2*e+1]-prediction[2*n+1])*.5;
  stats[16+e]=(-dy*mx+dx*my)/len;offsets[e]=std::abs(stats[16+e]);
 }
 std::sort(offsets,offsets+4);
 bool suspect=motion<=3.&&min_support>=.65&&noise<=1.
  &&offsets[3]>std::max(.85,2.8*noise)&&offsets[2]<=std::max(.35,1.4*noise)
  &&residual>std::max(.20,.8*noise);
 stats[0]=suspect?1.:0.;stats[2]=motion;stats[3]=correction;stats[4]=residual;
 stats[5]=offsets[3];stats[6]=offsets[2];stats[7]=noise;stats[8]=1.;stats[20]=motion>.8?1.:0.;
 int valid=p11_quad_valid(current,w,h,previous);if(valid!=1)return finish();stats[21]=1.;
 bool strong=min_support>=.80&&noise<=.50;stats[15]=strong?1.:0.;
 if(!allow_filter||suspect||!strong||motion>.8||correction>1.||residual>std::max(.35,1.5*noise))return finish();
 double alpha=std::max(.55,std::min(1.,motion/std::max(.35,2.5*noise)));
 double shift=motion*(1.-alpha);if(shift<.06||shift>.25)return finish();
 double proposed[8];for(int i=0;i<8;++i)proposed[i]=double(float(previous[i]+alpha*(current[i]-previous[i])));
 stats[8]=alpha;stats[9]=shift;stats[10]=p68_line_error(proposed,current);stats[22]=1.;
 if(stats[10]>.25||p11_quad_valid(proposed,w,h,previous)!=1)return finish();stats[25]=1.;
 // Actual CURRENT gray profiles are remeasured around the filtered quad.
 int code=p11_edges_checked(gray,w,h,stride,proposed,1.75,checked,edges);if(code)return code;
 stats[14]=1.;stats[11]=p68_line_error(proposed,checked);double ms=1.,mr=0.,corner=0.;int flips=0;
 for(int e=0;e<4;++e){ms=std::min(ms,edges[e]);mr=std::max(mr,edges[12+e]);
  flips+=polarity[e]*int(edges[4+e])<0;corner=std::max(corner,std::hypot(checked[2*e]-proposed[2*e],checked[2*e+1]-proposed[2*e+1]));}
 stats[23]=ms;stats[24]=mr;
 if(edges[20]!=0.&&edges[16]==4.&&edges[17]==4.&&ms>=.80&&mr<=.50&&flips==0
    &&stats[11]<=.35&&corner<=.50&&p68_line_error(current,checked)<=.50){
  std::copy(proposed,proposed+8,out);stats[1]=1.;
 }return finish();
}
