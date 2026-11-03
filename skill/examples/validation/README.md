# 验证记录

run-results.json与对应txt是本次重跑的离线结果。check-ui-layout包含正常配置和8类反例、600P与480P坐标以及预览外点击。原6个--selftest均为离线，其中check-timing的采集分支使用模拟subprocess，不启动Vivado。实际命令和退出码见结果文件。

baseline-fps33-validation.json和baseline-install-validation.json是第33版既有交付证据副本，不是本次重新上板。UI路径调整与数据库搜索为本次执行；不能据此推导板端FPS不降或第三方目录所有风格都已测试。
