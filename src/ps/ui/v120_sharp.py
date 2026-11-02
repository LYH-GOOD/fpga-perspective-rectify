"""PL stream sharpening. UI publishes a request; the existing P1 owner applies it.

No CPU pixel filter, camera/overlay restart, new frame buffer or polling thread.
The supplied kernel is packet-local; multi-tile frames use explicit bypass.
"""
from pathlib import Path
import hashlib,json,math,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_WIDTH=512
BYPASS_VERSION=0x53420001

def quantize(level):
    if isinstance(level,bool):raise ValueError('Invalid sharpness')
    value=float(level)
    if not math.isfinite(value) or not 0.<=value<=4.:raise ValueError('Sharpness must be 0..4')
    return int(math.floor(value*10.+.5))

class SharpControl:
    """Atomic immutable requests; completed-output acknowledgement is separate."""
    def __init__(self,folder=None):
        self.path=None if folder is None else Path(folder)/'p11_sharp_settings.json'
        level=0
        if self.path is not None and self.path.is_file():
            try:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('format')!='p11-sharp-settings-v1':raise ValueError('Unknown settings format')
                level=quantize(value['level'])
            except (ValueError,KeyError,TypeError,OSError) as exc:
                checkpoint('SHARP_SETTINGS_LOAD_FAILED',error=str(exc)[:200],default_level=0.)
        self.requested=(0,level);self.lock=threading.Lock();self.last_submitted=None
        self.frame_request=self.requested;self.frame_request_at=-float('inf')
        self.save_lock=threading.Lock();self.saved_serial=-1;self.save_request=None;self.writers=[]
    def request(self,tenths):
        if isinstance(tenths,bool) or int(tenths)!=tenths or not 0<=tenths<=40:raise ValueError('Invalid sharpness tenths')
        with self.lock:
            if self.requested[1]==int(tenths):return self.requested
            self.requested=(self.requested[0]+1,int(tenths));request=self.requested
        return request
    def for_frame(self):
        # The existing P1 owner calls once before the frame's first packet.
        # Healthy frames avoid clocks/locks. A drag only replaces one tuple;
        # no intermediate values queue up and no timer/worker touches MMIO.
        if self.requested is self.frame_request:return self.frame_request
        now=time.perf_counter()
        changed=False
        # Only this existing frame owner writes frame_request/frame_request_at.
        # Read the immutable UI tuple atomically; never wait for a save lock.
        if now-self.frame_request_at>=.1:
            self.frame_request=self.requested;self.frame_request_at=now;changed=True
        request=self.frame_request
        if changed:
            checkpoint('SHARP_SETTING_REQUESTED',serial=request[0],level=request[1]/10.,pixel_processing='PL_only',
                camera_restarted=False,applied_on='frame_boundary',latest_only=True,min_interval_s=.1)
        return request
    def finish(self):
        """Gesture finished: persist the final setting, even without a target."""
        with self.lock:
            serial,tenths=self.requested
            if self.path is None or serial<=0 or serial<=self.saved_serial:return
            self.saved_serial=serial;self.save_request=(serial,tenths)
        worker=threading.Thread(target=self._save,args=(serial,tenths),name='p11-sharp-save',daemon=True)
        self.writers=[w for w in self.writers if w.is_alive()];self.writers.append(worker);worker.start()
    def submitted(self,receipt):
        """Called only AFTER this actual rectified frame was submitted to HDMI."""
        if receipt is None or receipt is self.last_submitted:return False
        # An older, genuinely displayed frame remains the actual value while
        # the newest request waits for the next allowed frame boundary.
        if self.last_submitted is not None and receipt['serial']<self.last_submitted['serial']:return False
        if receipt['serial']>self.requested[0]:return False
        self.last_submitted=receipt
        checkpoint('SHARP_FRAME_SUBMITTED',**receipt,physical_scan_time_measured=False)
        return True
    def _save(self,serial,tenths):
        try:
            with self.save_lock:
                if (serial,tenths)!=self.save_request:return
                tmp=self.path.with_suffix('.tmp')
                tmp.write_text(json.dumps(dict(format='p11-sharp-settings-v1',level=tenths/10.),ensure_ascii=False)+'\n',encoding='utf-8')
                with self.lock:
                    if (serial,tenths)!=self.save_request:return
                    tmp.replace(self.path)
        except OSError as exc:checkpoint('SHARP_SETTINGS_SAVE_FAILED',serial=serial,error=str(exc)[:200])
    def close(self):
        for w in self.writers:w.join(1.)

def inspect_sharp_metadata(modules):
    """Use paired XML metadata, never source-comment absolute addresses."""
    expected={'/axis_sharp_0':('xilinx.com:hls:axis_sharp:1.0','C_S_AXI_CONTROL_BASEADDR',0x40030000),
              '/axis_bypass_0':('xilinx.com:module_ref:axis_bypass_bd:1.0','C_BASEADDR',0x40001000)}
    for path,(vlnv,param,address) in expected.items():
        node=modules.get(path)
        if node is None or node.get('VLNV')!=vlnv:raise ValueError('Missing or incorrect sharp IP '+path)
        params={x.get('NAME'):x.get('VALUE') for x in node.findall('./PARAMETERS/PARAMETER')}
        if int(params.get(param,'-1'),0)!=address:raise ValueError('Sharp IP address mismatch '+path)
    def bus(path,name):
        if path not in modules:return None
        node=modules[path].find('./BUSINTERFACES/BUSINTERFACE[@NAME="'+name+'"]')
        return None if node is None else node.get('BUSNAME')
    links=[('/axis_light_0','M_AXIS','/axis_data_fifo_0','S_AXIS'),
           ('/axis_data_fifo_0','M_AXIS','/axis_bypass_0','S_AXIS'),
           ('/axis_bypass_0','SH_AXIS','/axis_sharp_0','s_axis'),
           ('/axis_sharp_0','m_axis','/axis_bypass_0','FS_AXIS'),
           ('/axis_bypass_0','M_AXIS','/axi_dma_0','S_AXIS_S2MM')]
    if '/axis_data_fifo_0' not in modules:raise ValueError('Missing sharp stream FIFO')
    for a,ap,b,bp in links:
        if bus(a,ap) is None or bus(a,ap)!=bus(b,bp):raise ValueError('Sharp stream topology mismatch '+a+'/'+ap)

class SharpDriver:
    def __init__(self,overlay,mmio_factory,control):
        self.control=control;self.frame_receipt=None;self.receipt_key=None
        self.shape=None;self.amount=None;self.route=None;self.in_flight=False;self.check_route=False
        ips=overlay.ip_dict
        def mm(name):
            spec=ips[name];return mmio_factory(int(spec['phys_addr']),int(spec['addr_range']))
        self.core=mm('axis_sharp_0');self.gate=mm('axis_bypass_0')
        if int(self.gate.read(0x04))!=BYPASS_VERSION:raise RuntimeError('Incorrect PL sharp bypass version')
        self.gate.write(0x00,0);self.route=0
        checkpoint('SHARP_BACKEND_READY',kernel='axis_sharp_0',bypass='axis_bypass_0',max_output_width=MAX_WIDTH,
            default_level=control.requested[1]/10.,multi_tile='explicit_hardware_bypass',CPU_fallback=False)
    def begin_frame(self,tiles):
        if self.in_flight:raise RuntimeError('Previous sharp packet has not completed')
        serial,tenths=self.control.for_frame()
        reason='disabled' if tenths==0 else 'multi_tile_bypass' if len(tiles)!=1 else 'PL'
        if reason=='PL':
            x0,y0,x1,y1=tiles[0].box
            if not 0<x1-x0<=MAX_WIDTH or not 0<y1-y0<=65535:reason='output_shape_bypass'
        enabled=reason=='PL';key=(serial,tenths,enabled,reason)
        if key!=self.receipt_key:
            self.receipt_key=key
            self.frame_receipt=dict(serial=serial,tenths=tenths,requested_level=tenths/10.,
                effective_level=tenths/10. if enabled else 0.,enabled=enabled,reason=reason)
            checkpoint('SHARP_ROUTE_SELECTED',**self.frame_receipt)
        return self.frame_receipt
    def prepare_tile(self,tile):
        if self.in_flight:raise RuntimeError('Cannot change an active sharp packet')
        receipt=self.frame_receipt
        if receipt is None:raise RuntimeError('Sharp frame configuration missing')
        route=int(receipt['enabled'])
        if route:
            x0,y0,x1,y1=tile.box;shape=(x1-x0,y1-y0)
            if shape!=self.shape:
                self.core.write(0x10,shape[0]);self.core.write(0x18,shape[1]);self.shape=shape
            a8=(receipt['tenths']*256+5)//10
            if a8!=self.amount:self.core.write(0x20,a8);self.amount=a8
            self.core.write(0x28,1);self.core.write(0x00,1)
            self.in_flight=True
        if route!=self.route:
            self.gate.write(0x00,route);self.route=route;self.check_route=True
    def completed_tile(self):
        # The existing DMA owner calls this only after S2MM completion. Do not
        # sleep or poll: the packet and its output bytes have already drained.
        if self.in_flight:
            status=int(self.core.read(0x00))
            if not(status&6):raise RuntimeError('PL sharp did not finish after DMA completion')
            self.in_flight=False
        if self.check_route:
            if int(self.gate.read(0x14))!=self.route:raise RuntimeError('PL sharp route acknowledgement mismatch')
            self.check_route=False
    def close(self):
        if self.in_flight:raise RuntimeError('Cannot close an active PL sharp packet')
        self.gate.write(0x00,0);self.route=0;self.control.close()
