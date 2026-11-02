"""Installed CPU admission/protocol/UI check; never opens board hardware."""
from pathlib import Path
import hashlib,json,types
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def run():
    from profile22_cpu_check import run as previous_run
    previous=previous_run()
    from v64_p1_backend import inspect_pair
    root=Path(__file__).resolve().parent;path,manifest,hz=inspect_pair(root/'system.bit')
    from v120_sharp import SharpControl,SharpDriver,quantize
    from v120_image_settings import ImageSettingsUI
    assert [quantize(x/10.) for x in range(41)]==list(range(41))
    control=SharpControl();display=types.SimpleNamespace(timeout=3.,sharp_control=control)
    state=types.SimpleNamespace(page='compare',generation=1,stopping=False,camera_profile='480P')
    ui=ImageSettingsUI(state,display);ui.show();ui.tab='sharp';ui.sharp_candidate=15
    control.request(ui.sharp_candidate)
    assert not ui.apply() and control.requested==(1,15)
    tile=types.SimpleNamespace(box=(0,0,362,512));mms={}
    class MM:
        def __init__(self,address,length):self.address=address;self.writes=[];self.reg={4:0x53420001,0:6,0x14:0}
        def read(self,offset):return self.reg.get(offset,0)
        def write(self,offset,value):
            self.writes.append((offset,value))
            if self.address==0x40001000 and offset==0:self.reg[0x14]=value
    def make(addr,length):mms[addr]=MM(addr,length);return mms[addr]
    overlay=types.SimpleNamespace(ip_dict={'axis_sharp_0':dict(phys_addr=0x40030000,addr_range=65536),'axis_bypass_0':dict(phys_addr=0x40001000,addr_range=4096)})
    driver=SharpDriver(overlay,make,control);receipt=driver.begin_frame([tile]);driver.prepare_tile(tile);driver.completed_tile()
    assert (0x20,384) in driver.core.writes and control.last_submitted is None
    ui.sharp_submitted(dict(sharp_receipt=receipt));assert ui.view()['sharp_status']=='PL'
    assert not driver.begin_frame([tile,tile])['enabled']
    driver.close();ui.cancel('cpu_smoke')
    return dict(passed=bool(previous['passed']),release_id=RELEASE_ID,previous_cpu_check=previous,
        sharp_pair_SHA_CRC_graph_checked=True,sharp_request_and_mock_MMIO_checked=True,sharp_UI_metadata_checked=True,
        hardware_opened=False,RTL_simulation_run=False,board_FPS_tested=False)

if __name__=='__main__':
    result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
