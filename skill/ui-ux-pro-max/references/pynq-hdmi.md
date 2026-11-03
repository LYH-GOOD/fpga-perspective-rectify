# PYNQ HDMI触摸界面适配

本文件是ui-ux-pro-max通用目录在PYNQ/OpenCV缓存图像渲染器上的应用配置。基线取用户确认版本；第33版案例为1280×720画布、640×480预览、480P或600P源输入。工程路径不预设，入口是v75_ui.py、v64_hdmi_display.py与v75_ui_layout.json。

先读[通用UI方法](../../references/generic/11-embedded-touch-ui.md)及[项目领域案例](../../project/references/domain/04-ai-traditional-tracking.md)。本项目不是网页、Qt或LVGL；不要因目录有React/HTML示例而迁移渲染器。

使用实际像素坐标。绘制与命中共用布局声明，触摸48×48像素只作为本项目起点。中文字形预生成并缓存，FPS字母与数字同字族、字号和基线。按真实阶段更新进度，实际有效输出提交才完成，不用静态倒计时假装成功。

图像、DMA与HDMI所有权维持现有唯一管理者。UI回调只登记状态，不增加相机读取者或显示写入线程。避免逐帧字体加载、全帧复制及装饰动画。滑条跟手反馈，增强参数最多100ms一次并在帧边界生效，松手保存。第33版输出FPS为3秒统计、100ms刷新；这些是案例参数，不是通用库默认值。

在工程包根目录运行python3 skill/ui-ux-pro-max/scripts/search.py "touch target feedback" --domain ux。PYNQ/OpenCV不属于支持的--stack，不伪装为HTML或React，不设置会引入GSAP示例的--motion。结果只作概念参考，必须映射为现有Python图集与局部更新。

验收分开：离线看图和命中检查；主机交互回归；实机触摸、吞吐与闪屏。主机检查不保证板端FPS不降。需要更改硬件时按用户配置使用Vivado MCP，先list_sessions复用会话；工具未加载则提示重启Codex，不通过shell绕过。纯文档和离线UI检查不用启动Vivado。
