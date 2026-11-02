# board —— 上板运行

| 文件 | 说明 |
|---|---|
| `system.bit` | PL 比特流（锐化核，硬件版本 `p11_pwl_light_20261030_27`） |
| `system.hwh` | 同名硬件描述，必须是 XML |
| `system.manifest.json` | 硬件配对清单 |
| `p11_start.ipynb` | 板上启动 Notebook |
| `install_ai_fps_full_20261101_33.ipynb` | 安装 Notebook：把程序装进板端目录 |
| `fps33_upload_checksums.json` | 上传校验和 |
| `ai_selftest.ipynb` | AI 模块自检 |

## 环境

| 项 | 版本 |
|---|---|
| 开发板 | PYNQ-Z2（`xc7z020clg400-1`） |
| 板上镜像 | PYNQ v3.1（pynq 3.1.1 / Python 3.10.4） |

## 上板步骤

1. 本机执行 `python build/assemble_runtime.py`，生成扁平运行目录
2. 把该目录整体上传到板端
3. 在板端 Jupyter 打开 `p11_start.ipynb` 运行

## 约定

- `.hwh` 必须与 `.bit` **同名、同目录**，否则 `Overlay()` 找不到硬件信息。
- `system.bit` 的 sha256 与 `p11_contract.EXACT_PAIR_SHA256` 不一致时，
  `verify_package()` 会拒绝启动——这是设计如此，不是 bug。
- 板上实测数据必须注明采集条件（分辨率、相机、光照），不得与其他配置的数据混算。
