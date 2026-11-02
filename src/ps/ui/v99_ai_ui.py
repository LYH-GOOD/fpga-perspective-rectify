"""Event-only home status and application-owned service attachment."""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def attach(state,native_setup):
    import cv2,numpy as np
    from v99_ai_service import Service
    assets=state.assets;root=Path(__file__).resolve().parent
    image=cv2.imdecode(np.frombuffer((root/'v99_ai_home_status.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    names=('waiting_native','loading','ready','on_demand','error','off')
    if image is None or image.shape!=(288,340,3):raise ValueError('Invalid resident AI home status asset')
    base=assets.home
    def changed(status):
        with state.condition:
            state.ai_status=status
            if state.page!='home' or state.stopping:return
            index=names.index(status) if status in names else names.index('loading')
            home=base.copy();home[20:68,900:1240]=image[index*48:(index+1)*48]
            home.setflags(write=False);assets.home=home
            assets.return_home=None;assets.error_home=None;assets.home_pressed_cache=None;assets.home_pressed_key=None
            display=state.display
            if display is not None:
                with display.condition:
                    display.ui_dirty=True;display.condition.notify_all()
    state.ai_status_changed=changed
    canvas_kib=((int(assets.mode[0])*int(assets.mode[1])*3+4095)//4096)*4
    service=Service(native_gate=native_setup.done,status_callback=changed,cma_reserve_kib=canvas_kib+4)
    state.ai_service=service
    if state.display is not None:state.display.ai_service=service
    changed('waiting_native');service.enter_home()
    return service


def entered_home(state):
    service=getattr(state,'ai_service',None)
    if service is None:return
    state.ai_status_changed(service.state);service.enter_home()
