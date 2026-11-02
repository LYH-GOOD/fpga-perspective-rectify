// Linux V4L2 ABI is compiled on the board. Python never guesses ioctl struct sizes.
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <mutex>
#include <vector>
#include <algorithm>
#include <new>
struct Mapping{void* pointer=MAP_FAILED;size_t length=0;bool leased=false;uint64_t generation=0,returned_generation=0;};
struct Camera{int fd=-1;bool streaming=false;uint32_t width=0,height=0,stride=0;uint64_t generation_seed=0;std::vector<Mapping> buffers;std::mutex lock;};
static int xio(int fd,unsigned long req,void* arg){int rc;do{rc=ioctl(fd,req,arg);}while(rc<0&&errno==EINTR);return rc;}
static uint64_t now_ns(){timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return uint64_t(t.tv_sec)*1000000000ull+t.tv_nsec;}
static void cleanup(Camera* c){if(!c)return;if(c->streaming){v4l2_buf_type t=V4L2_BUF_TYPE_VIDEO_CAPTURE;xio(c->fd,VIDIOC_STREAMOFF,&t);}for(auto& b:c->buffers)if(b.pointer!=MAP_FAILED)munmap(b.pointer,b.length);if(c->fd>=0)close(c->fd);delete c;}
static int failure(Camera* c,char* message,int size,const char* stage,int code){if(message&&size>0)snprintf(message,size,"%s: %s (%d)",stage,strerror(code),code);cleanup(c);return -code;}
extern "C" int p11_camera_abi(){return 3102;}
static int stream_failure(char* message,int size,const char* stage,int code){
 if(message&&size>0)snprintf(message,size,"%s: %s (%d)",stage,strerror(code),code);return -code;
}
static int configure_stream(Camera* c,int w,int h,int fps,uint32_t* info,char* message,int size){
 v4l2_capability cap{};if(xio(c->fd,VIDIOC_QUERYCAP,&cap)<0)return stream_failure(message,size,"QUERYCAP",errno);
 uint32_t caps=(cap.capabilities&V4L2_CAP_DEVICE_CAPS)?cap.device_caps:cap.capabilities;
 if(!(caps&V4L2_CAP_VIDEO_CAPTURE)||!(caps&V4L2_CAP_STREAMING))return stream_failure(message,size,"single-plane capture/streaming required",ENOTSUP);
 v4l2_format fmt{};fmt.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;fmt.fmt.pix.width=w;fmt.fmt.pix.height=h;fmt.fmt.pix.pixelformat=V4L2_PIX_FMT_YUYV;fmt.fmt.pix.field=V4L2_FIELD_NONE;
 if(caps&V4L2_CAP_EXT_PIX_FORMAT)fmt.fmt.pix.priv=V4L2_PIX_FMT_PRIV_MAGIC;
 if(xio(c->fd,VIDIOC_S_FMT,&fmt)<0||xio(c->fd,VIDIOC_G_FMT,&fmt)<0)return stream_failure(message,size,"YUYV S/G_FMT",errno);
 auto& f=fmt.fmt.pix;
 if(f.pixelformat!=V4L2_PIX_FMT_YUYV||f.width!=uint32_t(w)||f.height!=uint32_t(h)||f.field!=V4L2_FIELD_NONE||f.bytesperline<uint32_t(w*2))return stream_failure(message,size,"requested progressive YUYV size was not accepted",EINVAL);
 c->width=f.width;c->height=f.height;c->stride=f.bytesperline;
 size_t needed=size_t(c->stride)*(c->height-1)+c->width*2;
 if(f.sizeimage<needed)return stream_failure(message,size,"sizeimage shorter than row-strided frame",EINVAL);
 v4l2_streamparm parm{};parm.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;parm.parm.capture.timeperframe.numerator=1;parm.parm.capture.timeperframe.denominator=fps;
 if(xio(c->fd,VIDIOC_S_PARM,&parm)<0||xio(c->fd,VIDIOC_G_PARM,&parm)<0)return stream_failure(message,size,"S/G_PARM FPS negotiation",errno);
 if(!parm.parm.capture.timeperframe.numerator||!parm.parm.capture.timeperframe.denominator)return stream_failure(message,size,"invalid negotiated frame interval",EINVAL);
 memset(info,0,16*sizeof(uint32_t));info[0]=f.width;info[1]=f.height;info[2]=f.bytesperline;info[3]=f.sizeimage;
 info[4]=parm.parm.capture.timeperframe.numerator;info[5]=parm.parm.capture.timeperframe.denominator;
 info[6]=f.colorspace;bool extended=(caps&V4L2_CAP_EXT_PIX_FORMAT)&&f.priv==V4L2_PIX_FMT_PRIV_MAGIC;
 info[7]=extended?f.ycbcr_enc:0;info[8]=extended?f.quantization:0;info[9]=extended?f.xfer_func:0;info[10]=f.pixelformat;info[11]=f.field;info[12]=extended;info[14]=caps;
 v4l2_requestbuffers req{};req.count=6;req.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;req.memory=V4L2_MEMORY_MMAP;
 if(xio(c->fd,VIDIOC_REQBUFS,&req)<0)return stream_failure(message,size,"REQBUFS",errno);
 if(req.count<4||req.count>32)return stream_failure(message,size,"at least four camera buffers required",ENOMEM);
 try{c->buffers.resize(req.count);}catch(const std::bad_alloc&){return stream_failure(message,size,"camera mapping allocation",ENOMEM);}info[13]=req.count;for(auto& m:c->buffers){m.generation=c->generation_seed;m.returned_generation=c->generation_seed;}
 for(uint32_t i=0;i<req.count;i++){v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;b.memory=V4L2_MEMORY_MMAP;b.index=i;
  if(xio(c->fd,VIDIOC_QUERYBUF,&b)<0)return stream_failure(message,size,"QUERYBUF",errno);
  if(b.length<needed)return stream_failure(message,size,"MMAP capacity",EINVAL);
  c->buffers[i].length=b.length;c->buffers[i].pointer=mmap(nullptr,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,c->fd,b.m.offset);
  if(c->buffers[i].pointer==MAP_FAILED)return stream_failure(message,size,"mmap",errno);
  if(xio(c->fd,VIDIOC_QBUF,&b)<0)return stream_failure(message,size,"initial QBUF",errno);
 }
 v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;if(xio(c->fd,VIDIOC_STREAMON,&type)<0)return stream_failure(message,size,"STREAMON",errno);
 c->streaming=true;return 0;
}
extern "C" int p11_camera_open(const char* path,int w,int h,int fps,void** result,uint32_t* info,char* message,int size){
 if(!path||!result||!info||w<2||h<2||w>1280||h>1280||(w&1)||fps<1||fps>60)return -EINVAL;
 *result=nullptr;Camera* c=new(std::nothrow) Camera;if(!c)return -ENOMEM;
 c->fd=open(path,O_RDWR|O_NONBLOCK|O_CLOEXEC);if(c->fd<0)return failure(c,message,size,"open",errno);
 int code=configure_stream(c,w,h,fps,info,message,size);
 if(code){cleanup(c);return code;}*result=c;return 0;
}
extern "C" int p11_camera_reconfigure_abi(){return 1;}
extern "C" int p11_camera_reconfigure(void* handle,int w,int h,int fps,uint32_t* info,char* message,int size){
 Camera* c=static_cast<Camera*>(handle);
 if(!c||!info||w<2||h<2||w>1280||h>1280||(w&1)||fps<1||fps>60)return -EINVAL;
 std::lock_guard<std::mutex> guard(c->lock);
 for(const auto& m:c->buffers)if(m.leased)return stream_failure(message,size,"active MMAP lease",EBUSY);
 if(c->streaming){v4l2_buf_type t=V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if(xio(c->fd,VIDIOC_STREAMOFF,&t)<0)return stream_failure(message,size,"STREAMOFF",errno);
  c->streaming=false;
 }
 for(auto& m:c->buffers)if(m.pointer!=MAP_FAILED){
  if(munmap(m.pointer,m.length)<0)return stream_failure(message,size,"munmap",errno);
  m.pointer=MAP_FAILED;
 }
 c->buffers.clear();v4l2_requestbuffers req{};req.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;req.memory=V4L2_MEMORY_MMAP;
 if(xio(c->fd,VIDIOC_REQBUFS,&req)<0)return stream_failure(message,size,"release REQBUFS",errno);
 // Epoch encoded in the existing uint64 generation receipt; no extra frame work.
 c->generation_seed+=(1ull<<32);
 return configure_stream(c,w,h,fps,info,message,size);
}
extern "C" int p11_camera_next(void* handle,int timeout_ms,void** pointer,uint64_t* meta){
 Camera* c=static_cast<Camera*>(handle);if(!c||!pointer||!meta||timeout_ms<1||timeout_ms>1000)return -EINVAL;
 pollfd fd{c->fd,POLLIN,0};int ready;do{ready=poll(&fd,1,timeout_ms);}while(ready<0&&errno==EINTR);
 if(ready<0)return -errno;if(ready==0)return 0;if(fd.revents&(POLLERR|POLLHUP|POLLNVAL))return -EIO;
 std::lock_guard<std::mutex> guard(c->lock);v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;b.memory=V4L2_MEMORY_MMAP;
 if(xio(c->fd,VIDIOC_DQBUF,&b)<0)return errno==EAGAIN?0:-errno;
 if(b.index>=c->buffers.size())return -EIO;auto& m=c->buffers[b.index];
 if(m.leased)return -EBUSY;m.leased=true;++m.generation;
 size_t need=size_t(c->stride)*(c->height-1)+c->width*2;
 memset(meta,0,12*sizeof(uint64_t));meta[0]=b.index;meta[1]=m.generation;meta[2]=b.sequence;meta[3]=b.bytesused;meta[4]=b.flags;
 meta[5]=uint64_t(b.timestamp.tv_sec)*1000000000ull+uint64_t(b.timestamp.tv_usec)*1000ull;meta[6]=now_ns();meta[7]=m.length;meta[8]=b.field;
 *pointer=m.pointer;
 if(b.bytesused<need||b.bytesused>m.length||(b.flags&V4L2_BUF_FLAG_ERROR)||b.field!=V4L2_FIELD_NONE){
  // Invalid frames are never handed to PS/DMA, and are immediately requeued.
  if(xio(c->fd,VIDIOC_QBUF,&b)<0)return -errno;m.leased=false;return 2;
 }
 return 1;
}
extern "C" int p11_camera_release(void* handle,uint32_t index,uint64_t generation){
 Camera* c=static_cast<Camera*>(handle);if(!c)return -EINVAL;std::lock_guard<std::mutex> guard(c->lock);
 if(index>=c->buffers.size()||!generation)return -EINVAL;auto& m=c->buffers[index];
 // An interrupted Python handoff may retry a completed QBUF. Its receipt must
 // never requeue the newer generation currently leased from the same buffer.
 if(generation<=m.returned_generation)return 0;
 if(!m.leased||m.generation!=generation)return -EINVAL;
 v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;b.memory=V4L2_MEMORY_MMAP;b.index=index;
 if(xio(c->fd,VIDIOC_QBUF,&b)<0)return -errno;m.leased=false;m.returned_generation=generation;return 0;
}
extern "C" int p11_camera_close(void* handle){
 Camera* c=static_cast<Camera*>(handle);if(!c)return 0;
 {std::lock_guard<std::mutex> guard(c->lock);for(const auto& m:c->buffers)if(m.leased)return -EBUSY;}
 cleanup(c);return 0;
}


// Optional controls: unsupported/read-only camera knobs never abort capture.
// Only auto-exposure priority may be disabled; exposure and AWB remain automatic.
extern "C" int p11_camera_controls(void* handle,int fixed_rate,int32_t* out){
 Camera* c=static_cast<Camera*>(handle);if(!c||!out||(fixed_rate!=0&&fixed_rate!=1))return -EINVAL;
 std::lock_guard<std::mutex> guard(c->lock);std::fill(out,out+12,0);
 const uint32_t ids[7]={V4L2_CID_EXPOSURE_AUTO,V4L2_CID_EXPOSURE_ABSOLUTE,V4L2_CID_EXPOSURE_AUTO_PRIORITY,
  V4L2_CID_GAIN,V4L2_CID_AUTOGAIN,V4L2_CID_WHITE_BALANCE_TEMPERATURE,V4L2_CID_AUTO_WHITE_BALANCE};
 for(int i=0;i<7;++i){
  v4l2_queryctrl q{};q.id=ids[i];if(xio(c->fd,VIDIOC_QUERYCTRL,&q)<0||(q.flags&V4L2_CTRL_FLAG_DISABLED))continue;
  v4l2_control v{};v.id=ids[i];if(xio(c->fd,VIDIOC_G_CTRL,&v)<0)continue;
  out[0]|=1<<i;out[2+i]=v.value;
  if(i==2&&fixed_rate&&v.value==0)out[1]|=2;
  if(i==2&&fixed_rate&&v.value!=0&&q.type==V4L2_CTRL_TYPE_BOOLEAN&&!(q.flags&V4L2_CTRL_FLAG_READ_ONLY)){
   out[1]|=1;v.value=0;
   if(xio(c->fd,VIDIOC_S_CTRL,&v)<0){out[9]=errno;out[1]|=4;continue;}
   if(xio(c->fd,VIDIOC_G_CTRL,&v)<0){out[9]=errno;out[1]|=4;continue;}
   out[2+i]=v.value;if(v.value==0)out[1]|=2;else out[1]|=4;
  }
 }
 return 0;
}
