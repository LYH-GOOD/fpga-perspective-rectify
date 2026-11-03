# UI设计技能目录

适用：界面结构、字体、配色、交互及可访问性评审。用法：从提交包根目录运行python3 skill/ui-ux-pro-max/scripts/search.py "touch target feedback" --domain ux；智能体入口为[SKILL.md](SKILL.md)。PYNQ必须先读[配置](references/pynq-hdmi.md)，通用概念不替代实际渲染器。

验证：本次离线运行触摸与进度两类查询，检查Python与CSV完整性；不代表所有风格均经设备测试。失效：物理触摸、像素排版和FPS必须单独实测，PYNQ没有对应--stack，网页示例不能直接上板。查询结果偏题时最多重新缩小范围一次，仍不匹配则说明降级依据。

来源：本机已安装的UI UX Pro Max目录，原版权Next Level Builder，MIT许可见[LICENSE](LICENSE)。第三方scripts/data保持原样，本地适配只修改Markdown路径、设备配置与说明。新增设备经验见[通用UI方法](../references/generic/11-embedded-touch-ui.md)。
