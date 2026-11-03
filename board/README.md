# board —— 上板运行

| 文件 | 说明 |
|---|---|
| `system.bit` | PL 比特流，sha256 `aaa9f632d3f8a7a1…`（硬件版本 `p11_pwl_light_20261030_27`，Vivado 2025.2 建出） |
| `system.hwh` | 同名硬件描述，必须是 XML，sha256 `459a4c51f7290d12…` |
| `system.manifest.json` | 硬件配对清单（含 `bit_sha256` / `hwh_sha256` / 时钟与 remap 参数） |
| `p11_start.ipynb` | 板上启动 Notebook（默认 480P；两种发布布局都认） |
| `install_ai_fps_full_20261101_33.ipynb` | **33 版 zip 安装**的 Notebook（老路径，需同目录放 zip） |
| `fps33_upload_checksums.json` | 33 版上板时留下的校验快照，与 `build/delivery_manifest.json` **逐字节相同**。⚠️ 它**不进运行包**（`build_merged_release.py` 的 `RELEASE_EXCLUDE` 里有它），全包 0 处引用；留着只是因为它也是位流登记点之一 |
| `ai_selftest.ipynb` | AI 模块自检（只用包内图片，不开相机/FPGA） |

### 位流与板上日志是同一对文件

`logs/` 里两份日志（22.73 fps 的出处）就是用 `system.bit` + `system.hwh` 这一对跑出来的：
日志中的 `P1_PAIR_ADMITTED` 与这两个文件的 sha256 逐位相同。

## 实测输出（`logs/`）

⚠️ **`logs/` 是证据，不进运行包** —— `build/build_merged_release.py` 与 `assemble_runtime.py`
都排掉了它（否则包要多 2 个文件 / +14 MB，且会被写进 `release_manifest.json`）。

`build/light27_hardware.json` 的 `board_evidence` 引用的就是这两份，原样保存、未删行未截断：

| 文件 | 大小 | 对应的量 |
|---|---|---|
| `run-result-2026-10-30T232851.860.log` | 4.4 MB | 480P 静止场景首测 |
| `run-result-2026-10-30T233907.730.log` | 10.0 MB | 同配置续跑，22.73 fps 的出处 |

**怎么读**（⚠️ 别按字面找"fps"字段）：

- **真实帧率只有一个口径**：`HDMI_PROGRESS` 里的 `frames` 累计值**斜率**，且要在 `frames`
  回退处切段。`V64_FRAME`、`current_fps`、`hdmi_submit_fps` 这些都不能当帧率用。
- **日志内部时间戳不可信**：板上没有 RTC（fake-hwclock），文件里写的是 `2025-05-13`。
  **真实时间看文件名**。
- **判据是板端路径**：出现 `/home/xilinx/...armv7l.so` 才是板上跑出来的；主机日志是
  `C:\...\AMD64.dll`（那份在 `sim/results/run-result.log`）。
- 日志里 `system.bit` 的路径含 `p11_rgb_v9_ai_light_20261030_27/`，与包内
  `release_manifest.json` 的 `hardware_release_id` 对得上（`system.manifest.json` 里叫 `build_id`，同值）。

## 环境

| 项 | 版本 |
|---|---|
| 开发板 | PYNQ-Z2（`xc7z020clg400-1`） |
| 板上镜像 | PYNQ v3.1（pynq 3.1.1 / Python 3.10.4） |

## 上板步骤

1. **构建**：`python build/build_merged_release.py` —— 产出 layers-6 合并包（114 文件 / 25.0 MB），
   `p11_start.ipynb` / `system.bit` / `system.hwh` 都已从本目录拷进去
2. **上传**：`python build/upload_merged.py <本地运行目录> <板上目标目录>`
   （Git Bash 里要加 `MSYS_NO_PATHCONV=1`，否则路径被改写，见 [`build/README.md`](../build/README.md)）
   —— SFTP 先传 `/tmp/<目录>.new`，
   板上逐文件核 sha256，一致才 `sudo cp -a` 就地覆盖，覆盖后再核一遍；
   不一致就中止、老目录原样保留
3. **板端**：在目标目录打开 `p11_start.ipynb`，**先重启内核**，再运行第 1 单元

> ⚠️ **本目录是打包源，不是上传目录本身。** 构建脚本把这里的 `system.bit`、`system.hwh`、
> `*.ipynb`、`system.manifest.json` 拷进运行目录，运行目录才是要传上板的那一坨。
>
> `install_ai_fps_full_20261101_33.ipynb` 是 **33 版 zip 安装**的老路径（要同目录放
> `p11_rgb_v9_ai_fps_20261101_33.zip`）；现在主路径是第 2 步的 SFTP 直传，两者不叠加使用。

## 约定

- `.hwh` 必须与 `.bit` **同名、同目录**，否则 `Overlay()` 找不到硬件信息。
- `system.bit` 的 sha256 与 `p11_contract.EXACT_PAIR_SHA256` 不一致时，
  `verify_package()` 会拒绝启动——这是设计如此，不是 bug。
- 板上实测数据必须注明采集条件（分辨率、相机、光照），不得与其他配置的数据混算。

## 清单里哪些字段是"出位流那一刻"的旧话，别看错

交付包里有**四处**字面值仍停在出位流那一刻，与后来掌握的证据不符 —— 都不是 bug，是没跟着改：

| 位置 | 现在写的 | 实际 |
|---|---|---|
| `system.manifest.json` 的 `notes` | `boardFPS pending.` | 2026-10-30 出位流时写的；板上帧率证据在 `logs/` 与 [`build/light27_hardware.json`](../build/light27_hardware.json) |
| 两份清单的 `board_hardware_tested` | `false` | 同一对 bit/hwh 的板上日志就在 `logs/`（`P1_PAIR_ADMITTED` 与 sha256 吻合） |
| `release_manifest.json` 的 `ready_scope` | `... 2h board soak pending` | 2026-11-01 打 33 版时的状态 |
| 两份清单的 `software_adapter_board_tested` | `false` | 该字段**没有任何代码读取**，是纯人工记录 |

`board_hardware_tested` 确实会被代码读：`v64_p1_backend.py:353` 把它写进 checkpoint。

⚠️ 上面这几个字面值**都被 release 清单的 sha256 锁着** —— 改一个字节，`verify_package()`
就会拒绝启动。要改就得整包重打、重算清单、重新上板；上面几处没改就是这个原因。
