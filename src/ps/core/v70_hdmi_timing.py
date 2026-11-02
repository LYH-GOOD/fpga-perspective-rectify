"""P1 software-only 1024x600 CVT frontend; existing bit/hwh stay immutable.

Register conventions: Xilinx XVtc_ConvTiming2Signal/SetGenerator (origin=1,
progressive, vertical sync -1), Digilent/PYNQ DisplayClkFindReg. No private
CPython object memory or global PYNQ mode-table patch is used.
"""
from pathlib import Path
import hashlib,threading,time,xml.etree.ElementTree as ET
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# Manual page6: hdmi_cvt1024 600 60 6 0 0 0. CVT request expanded to
# 15:9, progressive, no margins/reduced blanking; nominal60Hz (59.8503Hz).
# These derived register parameters are not a verbatim vendor porch table.
TIMING=dict(width=1024,height=600,pixel_clock_hz=49000000,
    h_front=40,h_sync=104,h_back=144,v_front=3,v_sync=7,v_back=14,
    h_positive=True,v_positive=True,h_total=1312,v_total=624,
    source='manual_page6_CVT_1024_600_60_aspect6_no_margins_progressive_no_RB')
# REF_CLK_I=FCLK2=100MHz. VCO=100*49/5=980MHz; 5x=980/4=245MHz;
# existing BUFR /5 yields49MHz. clk0L,clkFBL,clkFBH_clk0H,divclk,lockL,filter.
# The two lookup words use fbmult49 in upstream PYNQ video_display.h.
CLOCK_WORDS=(0x00000082,0x00800619,0x00000000,0x00002083,0xCFAFA401,0x00A300FF)
SOURCE_SELECT=0x03F7EF00
_BASE='video/hdmi_out/frontend/'


class Cvt1024Frontend:
    """Only the existing HDMI owner may configure this output frontend."""
    def __init__(self,vout,overlay,timeout_s=3.):
        from pynq import MMIO,Clocks
        self.owner=threading.get_ident();self.timeout=float(timeout_s)
        self.original=vout._hdmi;self._mode=None;self.running=False
        if not hasattr(self.original,'_display'):raise RuntimeError('1024x600 requires PYNQ-Z2 DVI frontend')
        if int(self.original._display.state())!=0:raise RuntimeError('HDMI frontend already running before custom timing')
        modules=ET.parse(Path(overlay.bitfile_name).with_suffix('.hwh')).findall('.//MODULE')
        dyn=next((m for m in modules if m.get('FULLNAME')=='/'+_BASE+'axi_dynclk'),None)
        vtc=next((m for m in modules if m.get('FULLNAME')=='/'+_BASE+'vtc_out'),None)
        if dyn is None or vtc is None:raise RuntimeError('Specified P1 timing metadata missing')
        ref=dyn.find("./PORTS/PORT[@NAME='REF_CLK_I']")
        if ref is None or ref.get('SIGNAME')!='ps7_FCLK_CLK2' or int(ref.get('CLKFREQUENCY','0'))!=100000000:
            raise RuntimeError('1024x600 fixed clock receipt requires specified100MHz FCLK2 reference')
        if abs(float(Clocks.fclk2_mhz)-100.)>.01:raise RuntimeError('Actual FCLK2 differs from100MHz HDMI clock reference')
        pars={p.get('NAME'):p.get('VALUE') for p in vtc.findall('./PARAMETERS/PARAMETER')}
        if pars.get('C_HAS_AXI4_LITE')!='1' or pars.get('C_GENERATE_EN')!='1' or pars.get('C_INTERLACE_EN')!='0':
            raise RuntimeError('Specified P1 progressive programmable VTC contract differs')
        self.clock=MMIO(int(overlay.ip_dict[_BASE+'axi_dynclk']['phys_addr']),0x20)
        self.vtc=MMIO(int(overlay.ip_dict[_BASE+'vtc_out']['phys_addr']),0x100)
        self.original.stop()
        self.vtc.write(0,int(self.vtc.read(0))&~4)
        if self.vtc.read(0)&4:raise RuntimeError('VTC generator could not stop before custom timing')
        self.detail=dict(TIMING,refresh_hz=49000000./(1312*624),reference_clock_hz=100000000,
            serial_clock_hz=245000000,clock_words=list(CLOCK_WORDS),clock_source='FCLK2',
            hardware_modified=False,vtc_version=int(self.vtc.read(0x10)),physical_display_validated=False)
    def _owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('HDMI timing access must stay on HDMI owner')
    def _wait_clock(self,running):
        deadline=time.perf_counter()+self.timeout
        while bool(self.clock.read(4)&1)!=bool(running):
            if time.perf_counter()>=deadline:raise TimeoutError('HDMI dynamic clock did not '+('lock' if running else 'stop'))
            time.sleep(.001)
    @property
    def mode(self):return self._mode
    @mode.setter
    def mode(self,value):
        self._owner()
        if (int(value.width),int(value.height),int(value.bits_per_pixel))!=(1024,600,24):
            raise ValueError('Custom frontend requires1024x600 BGR24')
        if abs(float(value.fps)-60.)>.01:raise ValueError('Custom CVT frontend uses nominal60Hz')
        if self.running:self.stop()
        self._mode=value
    def start(self):
        self._owner()
        if self.running:return
        if self._mode is None:raise RuntimeError('Set HDMI mode before start')
        # Reprogram only with the generator disabled and before VDMA starts.
        if self.vtc.read(0)&4:raise RuntimeError('VTC enabled during timing reconfiguration')
        self.clock.write(0,0);self._wait_clock(False)
        for offset,value in zip(range(8,32,4),CLOCK_WORDS):self.clock.write(offset,value)
        clock_read=tuple(int(self.clock.read(offset)) for offset in range(8,32,4))
        if clock_read!=CLOCK_WORDS:raise RuntimeError('HDMI clock parameter readback mismatch')
        self.clock.write(0,1);self._wait_clock(True)
        p=TIMING;w,h=p['width'],p['height'];hs=w+p['h_front'];he=hs+p['h_sync']
        vs=h+p['v_front']-1;ve=vs+p['v_sync'];ht=p['h_total'];vt=p['v_total']
        # XVtc origin=1: full totals, vertical sync start/end minus one;
        # VBlank horizontal offset=HActive, VSync horizontal offset=HSyncStart.
        registers={0x60:(h<<16)|w,0x6C:0x7F,0x70:ht,0x74:(vt<<16)|vt,
            0x78:(he<<16)|hs,0x7C:(w<<16)|w,0x80:(ve<<16)|vs,
            0x84:(hs<<16)|hs,0x88:(w<<16)|w,0x8C:(ve<<16)|vs,0x90:(hs<<16)|hs}
        self.vtc.write(0,SOURCE_SELECT|2)
        self.vtc.write(0x68,int(self.vtc.read(0x68))&~0x140) # progressive, chroma parity0; preserve RGB format
        for offset,value in registers.items():self.vtc.write(offset,value)
        readback={offset:int(self.vtc.read(offset)) for offset in registers}
        # Field1/chroma/field-ID hardware is optional in this progressive P1
        # core. Write the official mirror registers but prove active fields;
        # do not require unused/omitted field1 registers to echo their value.
        masks={0x60:0x3FFF3FFF,0x6C:0x1F,0x70:0x3FFF,0x74:0x3FFF,
            0x78:0x3FFF3FFF,0x7C:0x3FFF3FFF,0x80:0x3FFF3FFF,0x84:0x3FFF3FFF}
        if any((readback[k]&mask)!=(registers[k]&mask) for k,mask in masks.items()):
            raise RuntimeError('1024x600 active VTC timing readback mismatch')
        if self.vtc.read(0x68)&0x40:raise RuntimeError('VTC progressive encoding readback failed')
        self.vtc.write(0,SOURCE_SELECT|7)
        if not self.vtc.read(0)&4:raise RuntimeError('VTC generator enable readback failed')
        self.running=True
        checkpoint('HDMI_CUSTOM_TIMING_READY',durable=True,**self.detail,
            vtc_control=int(self.vtc.read(0)),vtc_registers={hex(k):v for k,v in readback.items()},
            vtc_active_readback_masks={hex(k):v for k,v in masks.items()},
            clock_locked=bool(self.clock.read(4)&1),timing_source='vendor CVT request expanded in PS; board confirmation pending')
    def stop(self):
        self._owner()
        self.vtc.write(0,int(self.vtc.read(0))&~4)
        if self.vtc.read(0)&4:raise RuntimeError('HDMI VTC generator disable not proved')
        self.running=False


def install_1024_frontend(vout,overlay,timeout_s):
    """Replace only this VideoOut instance's mode frontend, keeping official VDMA."""
    if not hasattr(vout,'_hdmi'):raise RuntimeError('Installed PYNQ VideoOut frontend interface differs')
    frontend=Cvt1024Frontend(vout,overlay,timeout_s)
    vout._hdmi=frontend
    return frontend
