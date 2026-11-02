# 第24版：交接bit的remap1.5兼容修复

## 原因与证据

第23版使用交接包experiment_bypass硬件对，却沿用了生产1.7的版本契约（0x00010007）。板端在加载后读到0x00010005，因此在进入相机跟踪前被VERSION检查拒绝。交接文档声称实验对与生产对版本相同，实际RTL和板端读数不支持这条说明；此前软件自检没有打开硬件，未能发现这个错误。

用户提供只读实测：REMAP_VERSION=0x10005，REMAP_CTRL=0，BYPASS_VERSION=0x53420001。交接RTL axi_lite_regs声明VERSION_MINOR=5，CTRL只接受start/reset且回读0；axis_remap_top未覆盖该版本、没有YUYV前端。故这不是目录重名或触摸/AI问题，也不能用删除版本检查解决。

## 修复范围

按用户选择继续使用原始交接bit/HWH，不重建、不换回生产硬件。完整硬件契约、规划器ABI、软件清单及安装身份统一为remap1.5；仍严查配对SHA/CRC/HWH连接及板端VERSION，错误版本和0值仍拒绝。错误信息打印实际/期望十六进制值，日志P1_HARDWARE_IDENTITY提供可核查读数。

输入固定为该核支持的BGRX32，每像素4字节。通过现有native C++转色内核及多块打包工作区处理；ARM环境沿用原有NEON编译配置。关闭原本不适用的PL YUYV能力探测，不写CTRL格式位，即使P11_YUYV_INPUT=1也不能强迫不支持的格式。原DMA长度选择随input_yuyv=False走4字节分支，避免颜色错位、长度不一致和超时。未新增Python逐像素处理，也未增加CPU锐化。

锐化驱动、滑条/预设、Apply帧边界、提交确认及保存与23版字节相同。自动/AI、手动跟踪、相机复用、480P/600P进度和每次2秒恢复冷却保留。仅单块、输出宽≤512时启用锐化；其他明确旁路。

## 性能口径

用户已明确选择原交接bit加现有CPU转色路线。相比原生产1.7在PL转色的路径，这会增加PS转色工作和输入DMA字节量（2→4字节/像素），不能承诺原帧率不降。UI、跟踪和模型不变不代表端到端帧率必然相同。主机CPU测试不等于ARM NEON性能或板端CORR/HDMI帧率。

本次不沿用23版主机UI开销对照作为24版FPS结论，也不做冻结/限帧来掩盖变化。若实机下降不可接受，需要后续在1.7快速路径基础上重新集成硬件锐化，届时要重新产生bit/HWH并验证。

## 验证

517项主机检查通过，其中11项新增：真实validate_overlay接受实测1.5、拒绝1.7与0并报告实际/期望值；manifest能力一致性；禁止格式位探测；现有打包分支选择；源范围；实际生产C++转色函数数值测试。宿主编译只提取未改动pack函数及其依赖前缀，分别检查四种颜色模式、偶/奇crop、带padding行步长、饱和及目的缓冲边界；ARM NEON本次未执行。

其余506项为本包重新执行的既有自动/AI、手动、显示连续性、切档、相机复用、锐化协议/触摸测试。既有硬件scope只放行本次授权的_input_format方法，并新增独立检查。八图Windows NCNN通过；9张实际合成器截图检查（设备替身）。CPU检查额外核对1.5契约与BGRX分支，不打开FPGA。

Vivado MCP本次已复用可用会话并确认2025.2，无需重新综合以修复软件适配。本包bit/HWH与23版及交接对逐字节相同，没有宣称重新仿真或上板验证。用户读数只证明硬件身份，不能证明24版相机/DMA/锐化/FPS已经通过。

## 安装与上板

使用新的完整ZIP和安装Notebook，停止旧程序后上传到同一目录，执行全部安装、自检；进入打印TARGET目录，重启内核运行p11_start.ipynb。保留22、23版，不零散覆盖。

启动日志应见P1_HARDWARE_IDENTITY actual_hex=expected_hex=0x00010005；P1_INPUT_FORMAT yuyv=false / input_format=BGRX32 / bytes_per_pixel=4。先关闭锐化确认相机和矫正连续，再以单块输出测试1.0/1.5/2.0，观察PL已启用或分块旁路。在相同档位、目标和光照下对照原22版CORR/HDMI帧率、input_copy_s和dma_wait_s，并保留run-result.log。

可选sharp23_board_check.py --board继续可用：先停止UI再运行，会下载当前同一硬件对并测试小图DMA/锐化数值。不要与UI同时运行；完成后重启内核。该脚本本次未在板上执行，不验收边缘像素或FPS。

当前说明见sharp24_release_report.md；验证sharp24_validation.json。所有23及更早报告仅为历史资料。
