# third_party —— 第三方组件

本目录内容**不是本项目原创**，按各自的原许可条款使用与分发。

## ai/

| 路径 | 说明 |
|---|---|
| `plane.ncnn.param` / `plane.ncnn.bin` | 本项目的分割模型（PIC7 / PIC8 训练），ncnn 格式 |
| `runtime/ncnn/` | ncnn 的 Python 绑定，版本 `1.0.20261020`，面向 ARMv7 / Python 3.10 |
| `runtime/ncnn.libs/` | OpenMP 运行时 `libgomp` |
| `conversion_report.json` | 模型转换记录 |

ncnn 遵循其自带许可，全文见
`runtime/ncnn-1.0.20261020.dist-info/licenses/LICENSE.txt`。

## ⚠️ 为什么 `ai/` 这个目录名不能改

`v98_ai_worker.py` 和 `v99_ai_worker.py` 里写死了这两个路径：

```
ROOT/'ai'/'runtime'          # sys.path 追加
ROOT/'ai'/'plane.ncnn.param' # 模型参数
ROOT/'ai'/'plane.ncnn.bin'   # 模型权重
```

改名或把这层拍平，AI 模式会直接起不来。
