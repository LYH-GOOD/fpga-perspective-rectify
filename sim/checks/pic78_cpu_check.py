from ui28_cpu_check import run
if __name__=="__main__":
 import json
 from pathlib import Path
 result=run();Path(__file__).with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2))
