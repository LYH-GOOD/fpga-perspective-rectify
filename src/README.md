# src —— 设计源码

本目录存放全部可读源码。**注意：这里不是可运行目录**——运行前要用 `build/assemble_runtime.py`
把分散的文件合回一个扁平目录，原因见下。

## 结构

| 路径 | 内容 | 文件数 |
|---|---|---|
| `ps/core/` | 主链路模块：取帧、检测、跟踪、规划、重映射、显示调度 | 73 |
| `ps/ui/` | 界面与交互模块：页面、触控、预览、参数面板 | 41 |
| `ps/assets/` | 界面资产：按钮图、状态条、布局 JSON | 77 |
| `ps/runtime/` | `release_manifest.json`——发布清单，含每个文件的 sha256 | 1 |
| `native/` | C++ 原生扩展：相机取流、IO 装箱、事务、边缘检测 | 6 |
| `rtl/` | PL 侧 RTL 与约束：`axis_light27.v`、`tb_light27.sv`、`hdmi_out.xdc` | 3 |
| `third_party/ai/` | ncnn 运行时与分割模型（第三方，见其 README） | 40 |

## ⚠️ 为什么不能按目录直接运行

`ps/core/p11_contract.py` 里的 `verify_package()` 是启动时的完整性闸门，它要求下面这些
**全部平铺在同一层目录**，逐个核对 sha256：

- 109 个 `.py`（74 个主链路 + 35 个界面）
- 6 个 `.cpp`
- 77 个界面资产
- `system.bit` / `system.hwh` / `system.manifest.json`
- `release_manifest.json`

少一个、改名、换个文件夹，都会直接抛 `缺少文件 X` 或 `文件版本或内容不一致`。

仓库为了符合赛规的目录要求把它们拆开了，所以运行前必须合回去：

```
python build/assemble_runtime.py
```

脚本会组装并**实际调用一次 `verify_package()`**，全部通过才打印 PASS。

## 命名约定

文件名只用小写英文字母、数字、下划线或连字符。模块名即文件名——
例如 `v87_v74_tracking.py` 导出的模块名就是 `v87_v74_tracking`，改名会让导入失败。
