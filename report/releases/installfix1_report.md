> History: previous release. Current13 behavior: overlay_release_report.md.

# 第12版安装自检修复1

旧包的v99_ai_selftest.json与v98_ai_manifest.json仍写第11版身份，而运行代码已是第12版。
前者触发Self-test version mismatch，在创建模型进程及生成结果JSON之前就退出；后者会阻止AI工作进程通过资源检查。
这属于发布元数据遗漏，目录双层嵌套不是本次报错原因。

本包仅同步两份配置的版本身份，重算发布清单及匹配安装器；新增安装前身份核对与失败输出提示。
严格身份、全部资源哈希与ARMv7/Python3.10兼容检查保留。
所有运行Python、原生源码、图片、模型、ARM运行库、bit/hwh与启动本和原第12版逐字节相同，不改变实时FPS路径，不训练。

新增8项回归通过，实际执行旧包自检入口复现原错；新自检通过版本/四图哈希前置检查，实际工作进程资源检查通过（仅主机验证时模拟板端ABI）。
四张图片在Windows原生NCNN执行，四角与配置预期偏差均为0像素。
完整安装、解压资源核对、CPU原生自检及实际首个启动单元重新验证。板端NCNN/IPC与FPS仍需实际运行验收。

电脑解压upload_all合集，将内层程序ZIP和匹配安装notebook一起上传Jupyter。不要先在Jupyter手动解压程序ZIP。
停止旧程序，运行安装本全部单元。四图与CPU自检通过后进入安装本打印的新目录，重启内核运行p11_start.ipynb。旧目录保留。
