# build —— 可复现构建

## 组装运行目录（最常用）

```
python build/assemble_runtime.py
```

把 `src/` 与 `board/` 下分散的 245 个文件合回一个扁平目录，并调用
`p11_contract.verify_package()` 逐文件核对 sha256——通过才打印 PASS。

输出默认到 `../_runtime_build/p11_fps33_20261101/`，同目录下另有
`assemble_runtime_report.txt` 记录完整过程。

## 其他文件

| 路径 | 内容 |
|---|---|
| `reports/` | Vivado 综合与实现报告：时序、资源、DRC、IO、时钟 |
| `delivery_manifest.json` | 交付包清单：版本号、产物 sha256、测试状态 |
| `light27_hardware.json` | PL 硬件参数记录 |
| `upload_inventory.json` | 上板文件清单 |

## 环境

| 项 | 版本 |
|---|---|
| EDA 工具 | Vivado / Vitis **2026.1** |
| 目标器件 | `xc7z020clg400-1` |

## 约定

- 构建脚本必须能从零跑通，不依赖任何手工点击。
- 报告保留原始输出，不截断、不做摘要。
- ⛔ 不提交 Vivado 构建产物（`.runs/` `.cache/` `.hw/` 等），已在 `.gitignore` 中排除。
