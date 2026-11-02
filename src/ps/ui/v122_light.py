"""Zero-image-buffer PL PWL light controls; MMIO belongs to the P1 owner."""
from pathlib import Path
import hashlib,json,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v120_sharp import SharpControl
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
VERSION=0x4c540001

class LightControl(SharpControl):
    def __init__(self,folder=None):
        super().__init__(None)
        self.path=None if folder is None else Path(folder)/'p11_light_settings.json'
        value=0
        if self.path is not None and self.path.is_file():
            try:
                saved=json.loads(self.path.read_text(encoding='utf-8'))
                value=saved['percent']
                if saved.get('format')!='p11-light-settings-v1' or isinstance(value,bool) or int(value)!=value or not 0<=value<=100:
                    raise ValueError('Incorrect light settings')
            except (ValueError,KeyError,TypeError,OSError) as exc:
                value=0;checkpoint('LIGHT_SETTINGS_LOAD_FAILED',error=str(exc)[:200])
        self.requested=(0,int(value));self.frame_request=self.requested
    def request(self,percent):
        if isinstance(percent,bool) or int(percent)!=percent or not 0<=percent<=100:raise ValueError('Light percent must be0..100')
        with self.lock:
            if self.requested[1]!=int(percent):self.requested=(self.requested[0]+1,int(percent))
            return self.requested
    def for_frame(self):
        if self.requested is self.frame_request:return self.frame_request
        now=time.perf_counter()
        if now-self.frame_request_at>=.1:
            self.frame_request=self.requested;self.frame_request_at=now
            checkpoint('LIGHT_SETTING_REQUESTED',serial=self.frame_request[0],percent=self.frame_request[1],
                applied_on='frame_boundary',latest_only=True,min_interval_s=.1)
        return self.frame_request
    def submitted(self,receipt):
        if receipt is None or receipt is self.last_submitted:return False
        if self.last_submitted is not None and receipt['serial']<self.last_submitted['serial']:return False
        if receipt['serial']>self.requested[0]:return False
        self.last_submitted=receipt;checkpoint('LIGHT_FRAME_SUBMITTED',**receipt,physical_scan_time_measured=False);return True
    def _save(self,serial,percent):
        try:
            with self.save_lock:
                if (serial,percent)!=self.save_request:return
                tmp=self.path.with_suffix('.tmp')
                tmp.write_text(json.dumps(dict(format='p11-light-settings-v1',percent=percent))+'\n',encoding='utf-8')
                with self.lock:
                    if (serial,percent)==self.save_request:tmp.replace(self.path)
        except OSError as exc:checkpoint('LIGHT_SETTINGS_SAVE_FAILED',error=str(exc)[:200])

class LightDriver:
    def __init__(self,overlay,mmio_factory,control):
        self.control=control
        ip=overlay.ip_dict['axis_light_0']
        if int(ip['phys_addr'])!=0x40002000 or int(ip['addr_range'])<64:raise RuntimeError('PL light address mismatch')
        self.mmio=mmio_factory(int(ip['phys_addr']),int(ip['addr_range']))
        if int(self.mmio.read(4))!=VERSION:raise RuntimeError('PL light version mismatch')
        self.mmio.write(0,0);self.q8=0;self.key=None;self.receipt=None;self.changed=False
        checkpoint('LIGHT_BACKEND_READY',version=VERSION,pixel_processing='PL_PWL',image_buffer=False,
            requested_percent=control.requested[1],CPU_pixel_fallback=False)
    def begin_frame(self,tiles):
        request=self.control.for_frame()
        if self.key is None and self.control.frame_request_at==-float('inf'):
            self.control.frame_request_at=time.perf_counter()
        if request is not self.key:
            self.key=request;serial,percent=request;q8=(percent*256+50)//100
            if q8!=self.q8:
                self.mmio.write(0,q8)
                if int(self.mmio.read(0))!=q8:raise RuntimeError('PL light setting readback mismatch')
                self.q8=q8;self.changed=True
            self.receipt=dict(serial=serial,percent=percent,q8=q8,enabled=percent>0)
        return self.receipt
    def completed_frame(self):
        if self.changed:
            if int(self.mmio.read(8))!=self.q8:raise RuntimeError('PL light active parameter mismatch')
            self.changed=False
    def close(self):
        self.control.close();self.mmio.write(0,0)

def inspect_light_metadata(modules):
    node=modules.get('/axis_light_0')
    if node is None or node.get('VLNV')!='xilinx.com:module_ref:axis_light27:1.0':raise ValueError('Missing PL light IP')
    params={p.get('NAME'):p.get('VALUE') for p in node.findall('./PARAMETERS/PARAMETER')}
    if int(params.get('C_BASEADDR','-1'),0)!=0x40002000:raise ValueError('PL light address mismatch')
    for name in ('aclk','aresetn'):
        a=node.find('./PORTS/PORT[@NAME="'+name+'"]');b=modules['/remap'].find('./PORTS/PORT[@NAME="'+name+'"]')
        if a is None or b is None or a.get('SIGNAME')!=b.get('SIGNAME'):raise ValueError('PL light clock/reset mismatch')
    def bus(path,name):
        n=modules[path].find('./BUSINTERFACES/BUSINTERFACE[@NAME="'+name+'"]')
        return None if n is None else n.get('BUSNAME')
    for a,ap,b,bp in [('/remap','m_axis','/axis_light_0','S_AXIS'),('/axis_light_0','M_AXIS','/axis_data_fifo_0','S_AXIS')]:
        if bus(a,ap) is None or bus(a,ap)!=bus(b,bp):raise ValueError('PL light stream topology mismatch')
