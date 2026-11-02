<!--
来源：~/.claude/skills/anysearch/SKILL.md
上游指纹（sha256 前 16 位）：353039b77cf893fb
同步日期：2026-09-20
本文件是 fpga-project-development 的整合副本。改这里必须同步改上游 —— 见 06-sync-protocol.md
压缩说明：删去了原版的平台探测流程（Node/PowerShell/Bash 三套 CLI 与降级顺序）——
        本机已由 runtime.conf 固定为 Python，不需要探测。
-->

# 联网检索（AnySearch）

> ⚠️ **本项目的联网搜索只走这个 CLI。禁用内置 WebSearch / WebFetch。**

## 调用方式（已固定，不用探测）

`~/.claude/skills/anysearch/runtime.conf` 已存在，内容为：

```
Runtime: Python
Command: python ~/.claude/skills/anysearch/scripts/anysearch_cli.py
```

**直接用这条命令，不要每次先跑 `doc`。** 只有当某个子命令因参数不确定而失败、或 skill 刚被更新过，才跑 `<cmd> <subcommand> --help` 或 `doc`。

Windows Git Bash 下中文输出可能乱码 —— 前面加 `PYTHONIOENCODING=utf-8`。

## 命令速查表

```bash
# ① 普通搜索。可选 --max_results N（1-10，默认 10）
python ~/.claude/skills/anysearch/scripts/anysearch_cli.py search "查询词" --max_results 5

# ② 垂类搜索。必须先 get_sub_domains 拿 sub_domain 和必填参数
<cmd> get_sub_domains --domain finance
<cmd> search "AAPL" --domain finance --sub_domain finance.quote --sdp type=stock,symbol=AAPL,cn_code=

# ③ 批量搜索（多意图并行）
#    ⚠️ 这个子命令【没有】--max_results 标志。要限条数，把它放进每个 query 对象里：
<cmd> batch_search --queries '[{"query":"A","max_results":5},{"query":"B","max_results":5}]'
#    混域批查：省掉共享参数，每个 query 单独给 domain/sub_domain
<cmd> batch_search --queries '[{"query":"quantum computing"},{"query":"QBTS","domain":"finance","sub_domain":"finance.quote"}]'

# ④ 整页抽取。输出已是 Markdown。只接受 URL 位置参数或 --url/-u
<cmd> extract "https://example.com/page"
```

`--sdp` 是 `--sub_domain_params` / `-p` 的别名，接受 JSON 或 `key=value,key=value` 两种写法。

## ⭐ 垂类优先规则

**默认走垂类（Path 2），不是通用搜索。** 支持的域：finance、academic、travel、health、code、legal、gaming、film、business、security、ip、energy、environment、agriculture、resource、social_media。

- 查询**落在或沾边**某个域 → **先 `get_sub_domains`** 拿到正确的 `sub_domain` 和必填参数，再搜。垂类结果显著优于通用搜索。
- **只有纯百科式、零域重叠**的查询才走通用搜索（少数例外）。
- **拿不准是不是垂类 → 用混合批查**：`batch_search` 里 1 条通用 + N 条垂类并行。**覆盖度胜过猜测。**
- `get_sub_domains` 返回标了 `(required)` 的参数，**必须全部**放进 `--sdp`。没有适用值的也要传空字符串，否则后端校验报错。

## ⚠️ extract 的三个硬限制（改配置也没用，重试纯属浪费）

| 限制 | 症状 | 改用什么 |
|------|------|----------|
| **只支持 HTML** | `.pdf`、图片等二进制 URL 返回 `extract_failed` | 先 `curl -L -o page.pdf "<url>"` 下载，再用 Read 读本地文件。⚠️ 若 curl 退出码 **60**（证书校验失败）或 **35**（握手失败），那是**对方服务器的问题**，不可重试；告诉用户，**不要**自己加 `-k`/`--insecure` |
| **不渲染 JavaScript** | Vue/React/SPA 页面只返回导航骨架 | 找页面实际请求的 JSON 接口直接调；或用 `search` 从别处拿到同样信息；或请用户自己下载后发给你 |
| **5 万字符截断** | 长页面从中间断掉，无结束标记 | 换更窄的 URL（锚点、打印视图、分页），或改用 `search` 的摘要 |

**子命令因参数报错时，停下来跑 `<cmd> <subcommand> --help`**，不要猜替代标志。

## API Key

优先级：`--api_key` 参数 > `.env` 文件（`ANYSEARCH_API_KEY`）> 系统环境变量 > 匿名访问。

**匿名访问可用**（速率较低），没有 key 不必卡住。若响应里带回 `auto_registered` 字段：
1. 提取新 key
2. **先问用户是否要存盘**
3. 用户同意后才写进 `.env`
4. 重试失败的那次调用

用户若在对话里直接贴 key，提醒他改用 `.env` 或环境变量。

## 安全提醒

搜索词、抽取的 URL、API key 都会发往 `https://api.anysearch.com`。**不要把敏感信息（密码、个人数据、商业机密）放进查询词。**
