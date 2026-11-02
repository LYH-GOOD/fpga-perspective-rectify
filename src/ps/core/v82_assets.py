"""Decode V82 interaction labels once; no runtime fonts, web, or UI renderer."""
from pathlib import Path
import hashlib
import cv2
from p11_contract import RELEASE_ID
from v82_interaction import MANUAL_RECT,REFIND_RECT,ZOOM_RECT
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_interaction_assets(assets,root):
    def read(name,shape):
        image=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
        if image is None or image.shape!=shape:raise ValueError('Invalid V82 UI asset '+name)
        image.setflags(write=False);return image
    assets.manual=MANUAL_RECT;assets.zoom=ZOOM_RECT;assets.refind=REFIND_RECT
    for view in ('compare','rectified','snapshot'):
        assets.headers[view]=read('v82_header_'+view+'.png',(72,1280,3))
    assets.header=assets.headers['compare']
    assets.snapshot_busy=read('v82_header_busy.png',(72,1280,3))
    refind=read('v82_refind.png',(144,200,3));assets.refind_controls={'ready':refind[:72],'preparing':refind[72:]}
    assets.inspect_header=read('v82_header_inspect.png',(72,1280,3))
    assets.calibration_help=read('v82_calibration_help.png',(232,544,3))
    assets.reading_help=read('v82_reading_help.png',(48,512,3))
    assets.inspection_buttons={}
    for name,h in (('undo',64),('refresh',64),('confirm',72),('auto',72),('zoom_scale',64),('zoom_close',64)):
        assets.inspection_buttons[name]=read('v82_button_'+name+'.png',(h,244,3))
    for name in ('left','up','down','right'):
        assets.inspection_buttons[name]=read('v97_1_button_'+name+'.png',(56,112,3))
    notices=read('v82_calibration_notices.png',(256,512,3))
    assets.calibration_notices={name:notices[i*64:(i+1)*64] for i,name in enumerate(('select','ready','invalid','busy'))}
    manual=read('v82_manual_badges.png',(84,320,3))
    assets.status_badges.update({name:manual[i*28:(i+1)*28] for i,name in enumerate(('MANUAL','MANUAL_HELD','MANUAL_FIXED'))})
