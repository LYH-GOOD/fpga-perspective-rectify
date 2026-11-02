"""Installation CPU smoke; no camera, HDMI, overlay, DMA or live FPS claim."""
from pathlib import Path
import json,platform
from p11_contract import RELEASE_ID
from v111_recovery import AIBudget
def run():
    from unified_cpu_check import run as previous_check
    previous=previous_check()
    budget=AIBudget()
    assert all(budget.reserve(t) for t in (100.,105.,110.))
    assert not budget.reserve(115.) and budget.due(115.)==160.
    assert budget.reserve(160.)
    result=dict(release_id=RELEASE_ID,passed=True,budget_checks=3,previous_cpu_check=previous,
        machine=platform.machine(),live_board_fps_measured=False,
        scope='CPU synthetic/policy checks and unchanged native edges; not live recovery/FPS acceptance')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':run()
