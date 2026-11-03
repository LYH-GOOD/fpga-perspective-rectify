// CPU-only boundary fitting. No OpenCV dependency, hardware or frame ownership.
#include <math.h>
#include <stdint.h>

#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif
API int p11_edges_abi() { return 10501; }
static float sample(const uint8_t* g,int w,int h,int stride,float x,float y) {
    if(x<0 || y<0 || x>=w-1 || y>=h-1) return NAN;
    int a=(int)x,b=(int)y;float u=x-a,v=y-b;
    return (1-v)*((1-u)*g[b*stride+a]+u*g[b*stride+a+1])+
           v*((1-u)*g[(b+1)*stride+a]+u*g[(b+1)*stride+a+1]);
}
API int p11_edges(const uint8_t* g,int w,int h,int stride,const float* q,float radius,
                  const float* reference,float* body,float* out,float* stats) {
    if(!g||!q||!body||!out||!stats||w<8||h<8||stride<w||radius<1||radius>48) return -1;
    double line[4][3];
    for(int side=0;side<4;++side) {
        int next=(side+1)%4;float x=q[2*side],y=q[2*side+1];
        float dx=q[2*next]-x,dy=q[2*next+1]-y,len=hypot(dx,dy);
        if(!isfinite(len)||len<24) return -2;
        float nx=dy/len,ny=-dx/len;
        float shifts[24],tt[24],brightness[24];bool good[24];
        for(int j=0;j<24;++j) {
            float along=.10f+.80f*j/23,px=x+along*dx,py=y+along*dy;
            tt[j]=2*along-1;float best=-1e9f,bestoff=0,bestbody=0,bestmag=0;
            float mags[193],bodies[193],cap=16;int steps=int(4*radius)+1;
            for(int k=0;k<steps;++k) {
                float offset=-radius+.5f*k,cx=px+offset*nx,cy=py+offset*ny;
                float a=sample(g,w,h,stride,cx+nx,cy+ny);
                float b=sample(g,w,h,stride,cx-nx,cy-ny);
                float inside=sample(g,w,h,stride,cx-2*nx,cy-2*ny);
                mags[k]=isfinite(a+b+inside)?fabs(a-b):-1000;
                bodies[k]=inside;
                if(fabs(offset)<=2)cap=fmax(cap,fmin(80,1.05f*mags[k]));
            }
            for(int k=1;k<steps-1;++k) {
                float offset=-radius+.5f*k,mag=mags[k],inside=bodies[k];
                if(mag<8||mag<mags[k-1]||mag<mags[k+1])continue;
                float error=reference ? fabs(inside-reference[side*24+j]) : 0;
                if(error>40) continue;
                float score=fmin(mag,cap)-.8f*fabs(offset)-.65f*error;
                if(score>best){
                    float den=mags[k-1]-2*mag+mags[k+1];
                    float refine=fabs(den)>.01f?.25f*(mags[k-1]-mags[k+1])/den:0;
                    best=score;bestoff=offset+fmax(-.4f,fmin(.4f,refine));bestbody=inside;bestmag=mag;
                }
            }
            shifts[j]=bestoff;brightness[j]=bestbody;
            good[j]=bestmag>=8 && fabs(bestoff)<radius-.1f;
        }
        double intercept=0,tilt=0;
        for(int pass=0;pass<3;++pass) {
            double n=0,s=0,ss=0,v=0,sv=0;
            for(int j=0;j<24;++j)if(good[j]){
                n++;s+=tt[j];ss+=tt[j]*tt[j];v+=shifts[j];sv+=tt[j]*shifts[j];
            }
            double den=n*ss-s*s;if(den<1) return -3;
            tilt=(n*sv-s*v)/den;intercept=(v-tilt*s)/n;
            if(pass<2)for(int j=0;j<24;++j)
                good[j]=good[j] && fabs(shifts[j]-intercept-tilt*tt[j])<=1.;
        }
        int count=0;double error=0,lo=2,hi=-2;
        for(int j=0;j<24;++j) {
            if(good[j]){count++;double e=shifts[j]-intercept-tilt*tt[j];error+=e*e;
                lo=fmin(lo,(double)tt[j]);hi=fmax(hi,(double)tt[j]);}
            // Reference is sampled on the fitted physical boundary, never on video features.
            float off=intercept+tilt*tt[j],along=.10f+.80f*j/23;
            body[side*24+j]=sample(g,w,h,stride,x+along*dx+(off-2)*nx,y+along*dy+(off-2)*ny);
            if(!isfinite(body[side*24+j]))return -3;
        }
        double rms=sqrt(error/fmax(count,1));
        if(count<15||hi-lo<1.1||rms>.7)return -4;
        stats[side]=count/24.f;stats[side+4]=rms;stats[side+8]=intercept;
        double ax=x+nx*(intercept-tilt),ay=y+ny*(intercept-tilt);
        double bx=x+dx+nx*(intercept+tilt),by=y+dy+ny*(intercept+tilt);
        line[side][0]=by-ay;line[side][1]=ax-bx;
        line[side][2]=-(line[side][0]*ax+line[side][1]*ay);
    }
    for(int i=0;i<4;++i){int p=(i+3)%4;
        double* a=line[p];double* b=line[i];double det=a[0]*b[1]-a[1]*b[0];
        if(fabs(det)<.1*hypot(a[0],a[1])*hypot(b[0],b[1]))return -5;
        out[2*i]=(a[1]*b[2]-a[2]*b[1])/det;out[2*i+1]=(a[2]*b[0]-a[0]*b[2])/det;
    }
    return 0;
}
