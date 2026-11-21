# AI Agent 协作与 Colab 云端算力指南

本指南说明如何通过 **MCP Server** 让外部 AI Agent（Antigravity、Claude Code、Cursor 等）调用 ASMR Helper 完成两阶段半自动精制，以及如何在无独立显卡（或显存受限）的机器上使用 **Google Colab GPU 识别音频** 与**国内高速镜像源**。

---

## 1. 国内高速镜像安装与 ModelScope 优先下载

在国内网络环境下初始化项目依赖或下载本地模型时，使用 `-DomesticMirror`（或 `-Mirror`）开关即可自动启用国内加速链路：

```powershell
# 仅安装/修复前后端基础运行环境（使用阿里云 PyPI + npmmirror）
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -DomesticMirror

# 同时按需下载推荐模型权重（优先走 ModelScope 源）
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -DomesticMirror

# 指定引擎定向下载（如 Qwen3-TTS 与 VoxCPM2）
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -Engines qwen3,voxcpm2 -DomesticMirror
```

启用国内镜像后，模型与依赖遵循三级自动回退策略：

1. **ModelScope 优先**：Faster-Whisper、Fun-ASR、Qwen3-ASR / ForcedAligner、Qwen3-TTS、VoxCPM2 等已收录模型优先通过纯 HTTP 接口从 `https://www.modelscope.cn` 拉取并进行 SHA256 完整性校验（无需额外安装 `modelscope` SDK）。
2. **HF-Mirror 回退**：未收录于 ModelScope 的社区权重（如 `litagin/anime-whisper`）或临时限流时自动切换至 `https://hf-mirror.com`。
3. **HuggingFace 兜底**：最终回退至官方 `https://huggingface.co`。

也可在终端或系统环境变量中持久设置 `ASMR_HELPER_DOWNLOAD_REGION=cn`，使桌面端“引擎与资源”页同样默认采用 ModelScope 优先策略。

---

## 2. 配置 MCP Server（Antigravity / Claude Code / Cursor）

ASMR Helper 内置零额外依赖的 JSON-RPC 2.0 标准输入输出服务 `packages.mcp_server.server`，暴露 6 个正交工具：

- `asmr_inspect_work`：扫描作品目录，自动配对无损主轨、伴随分轨（`no_se` / `se_only` / `vocals`）与同名字幕/台本。
- `asmr_prepare_draft`：执行第一阶段（ASR 识别 / 字幕对齐 / 翻译 / 样音与克隆参考提取），生成持久化 `DraftSession` 并停在 `awaiting_review` 门禁。
- `asmr_get_draft_audit`：读取 `QualityAuditReport`（漏译、日文假名残留、超速挤压预警 `over_speed_cues`）。
- `asmr_patch_draft`：按乐观并发版本号（`expected_revision`）批量修订台词译文、精简改词或调整音色方案。
- `asmr_commit_draft`：通过门禁后合成全曲双声道声像跟随配音、借用句间静音缓冲并导出 `.srt` / `.lrc` 与混音成品。
- `asmr_list_voices_and_presets`：枚举真实可用的声音库配方、连接与引擎列表。

### Codex 接入 Windows 安装版

首次打开安装版并完成工作区选择后，使用安装版自带的 Python 和后端启动 MCP。工作区取桌面端保存的路径，因此两端会读取同一份草稿、音色和配置。安装位置不同的话，修改 `$App`。

```powershell
$App = 'D:\Apps\ASMRHelper'
$Locator = Join-Path $env:LOCALAPPDATA 'ASMRHelperTest\workspace.json'
$Data = (Get-Content -Raw -LiteralPath $Locator | ConvertFrom-Json).workspace
codex mcp add asmr-helper -- "$App\backend\python\python.exe" -I -B "$App\backend\app\desktop_backend.py" --mcp --data-dir "$Data"
```

重新打开 Codex 后即可调用 `asmr-helper`。如果日后在桌面端切换工作区，用新路径更新 MCP 配置。

### 开发目录的 MCP JSON 配置示例

在 **Antigravity**（`mcp_config.json`）、**Cursor**（`.cursor/mcp.json`）或 **Claude Code**（`.mcp.json` / `claude mcp add`）中添加 `asmr-helper` 服务（请将路径替换为你的项目实际目录）：

```json
{
  "mcpServers": {
    "asmr-helper": {
      "command": "D:/WorkSpace/AsmrHelper/.venv/Scripts/python.exe",
      "args": ["-m", "packages.mcp_server.server"],
      "cwd": "D:/WorkSpace/AsmrHelper",
      "env": {
        "PYTHONPATH": "D:/WorkSpace/AsmrHelper",
        "ASMR_HELPER_DOWNLOAD_REGION": "cn"
      }
    }
  }
}
```

若使用 Claude Code 命令行注册：

```powershell
claude mcp add asmr-helper -- D:\WorkSpace\AsmrHelper\.venv\Scripts\python.exe -m packages.mcp_server.server
```

---

## 3. 配置偏好模板与 `asmr-producer` 两阶段制作流

为了让 Agent 记住你的作品库路径、口语化耳语译风、默认音色与输出目录规则，而无需污染核心代码：

1. **复制偏好配置模板**：

   ```powershell
   Copy-Item config\agent_preferences.example.yaml config\agent_preferences.yaml
   ```

   按需编辑 [agent_preferences.yaml](../../config/agent_preferences.example.yaml) 中的：
   - `library_roots`：本地作品存放目录（支持直接对 Agent 说作品名或 RJ 号自动检索）；
   - `translation_style`：译文语气、`chars_per_second`（默认 `4.2`）与最大允许倍速 `max_atempo`（默认 `1.35`）；
   - `voice_preferences`：默认 `preset`（指定 `recipe_id` 或内置音色）或 `clone`（自动截取 6–10 秒高信噪比干声克隆）；
   - `output_policy` 与 `mix_defaults`：默认导出 `["srt", "lrc"]`、双语开关及背景音/人声混音比例。

2. **启用 `asmr-producer` Skill**：
   将仓库内的 [skills/asmr-producer/SKILL.md](../../skills/asmr-producer/SKILL.md) 加入 Agent 的技能目录（或在对话中引用该技能）。

3. **两阶段门禁工作流（`prepare` → 门禁确认 → `commit`）**：
   - **第一阶段（Prepare）**：告诉 Agent *“帮我处理 RJxxxxxx”*。Agent 调用 `asmr_inspect_work` 与 `asmr_prepare_draft`，**绝不会盲目一次性跑完全曲 TTS**，而是在 `awaiting_review` 状态停下。
   - **门禁审查（Review Gate）**：Agent 输出不超过 10 行的紧凑体检摘要，并对所有预计倍速 `> 1.35x` 的 `over_speed_cues` 自动给出符合耳语语气的精简改词建议（你也可随时打开桌面端“任务中心 → 待审草稿”试听样音并微调）。
   - **第二阶段（Commit）**：确认无误后回复 **`跑`** 或 **`OK`**，Agent 自动调用 `asmr_patch_draft` 写入精简译文并通过 `asmr_commit_draft` 渲染双声道成品与 `.srt` / `.lrc` 字幕。后续若微调个别台词再次提交，未改动句会自动复用已有合成音频。

---

## 4. 在 Colab 用 Faster-Whisper 生成字幕

[Colab 笔记本](../../notebooks/colab_gpu_worker.ipynb) 在单次任务内加载模型、识别音频并导出 SRT。模型默认缓存到当前会话。开启 `PERSIST_MODEL_ON_DRIVE` 可复用「我的云端硬盘」下 `AsmrHelper_Models/models` 的权重。CLI 会话如果已挂载这个目录，也会复用其中的权重。Demucs、RoFormer、Seed-VC、CosyVoice 2 和 GPT-SoVITS 也从此目录读取预装权重。对应模型的 Python 环境在工作节点准备。

### 网页笔记本

在 Colab 上传 `.ipynb` 文件，选择 T4 等 GPU 运行时。按顺序运行单元格，在第 3 格上传音频，第 4 格下载 `result.srt`。默认使用 `small` 识别日语，可在第 1 格修改模型与语言。字幕保留原文和时间轴，可同原音频一起导入桌面端，或通过 MCP 的 `subtitle_path` 交给 `asmr_prepare_draft`。

### Colab CLI

在已登录的 CLI 中查看 `colab usage`，然后按账户可用额度选择是否创建 GPU 会话。下列脚本要求提供一个现有会话，不会申请额外 GPU，也不会覆盖已有字幕。

```powershell
$ColabExe = 'C:\path\to\colab.exe'
& $ColabExe usage
# 确认允许使用该会话后，创建或选用一个 T4 会话
& $ColabExe new -s asmr --gpu T4
.\.venv\Scripts\python.exe scripts/run_colab_asr.py 'D:\audio\track.wav' --colab $ColabExe --session asmr --language ja --output 'D:\audio\track.colab.srt'
& $ColabExe stop -s asmr
```

Windows 原生 CLI 的完整平台支持仍以 [Google 官方说明](https://github.com/googlecolab/google-colab-cli) 为准。`--colab` 接受 CLI 可执行文件的完整路径，方便同机保留多个版本。也可以直接走网页笔记本流程。

## 5. 在桌面流水线使用 Colab GPU Worker

在创作台选择本地音频即可。分离、识别、对齐和配音参考会按节点需要以压缩音频传给 Worker，结果回到本机。Google Drive 只在你选择用它跨会话保存权重时需要。下面的方式使用会话磁盘保存缓存。

| 流水线节点 | Colab 环境 | 默认准备的模型 |
| --- | --- | --- |
| 人声分离、语音识别、时间轴对齐 | `pipeline`，端口 `8765` | Demucs `htdemucs`、Faster-Whisper Base、Qwen3 ForcedAligner 0.6B |
| 配音 | `qwen3`，端口 `8766` | Qwen3-TTS CustomVoice。克隆选择 `--model qwen3-base`，设计音色选择 `--model qwen3-voice-design` |
| 配音 | `voxcpm2`，端口 `8767` | VoxCPM2 |
| 高级分离和后置变声 | 所选 Worker | 准备 `pipeline` 时加 `--roformer` 安装 RoFormer。加 `--seed-vc` 安装 Seed-VC 的独立环境 |

同一个 Colab 会话可以运行基础 Worker 和所选配音 Worker。Qwen3 ASR/对齐和 Qwen3-TTS 使用独立的 Python 环境。配置 CosyVoice 2 或 GPT-SoVITS 时，按对应上游文档安装模型与独立 Python 环境，启动 Worker 前设置 `ASMR_COSYVOICE2_ROOT` / `ASMR_COSYVOICE2_PYTHON` 或 `ASMR_GPT_SOVITS_ROOT` / `ASMR_GPT_SOVITS_PYTHON`。Qwen3-TTS 和 VoxCPM2 的准备步骤会一并下载用于验卡的 Faster-Whisper Small。启用 Seed-VC 时，须让执行配音的 Worker 同时读到 Seed-VC 环境。使用 Edge TTS 或其他云端配音服务时，把 Seed-VC 配在基础 Worker。

在项目目录打包当前源码。归档仅包含运行源码和模型目录清单。

```powershell
.\.venv\Scripts\python.exe scripts/colab_worker.py bundle .tmp/asmr-colab-worker.zip
colab status -s asmr
colab upload -s asmr .tmp/asmr-colab-worker.zip /content/asmr-colab-worker.zip
```

以上传输使用已创建的 `asmr` 会话。进入既有会话的 Colab 终端，解包到新目录并安装所选模型。

```bash
cd /content
python -m zipfile -e asmr-colab-worker.zip asmr-worker
cd asmr-worker
python -m pip install uv
python scripts/colab_worker.py prepare
python scripts/colab_worker.py prepare --profile qwen3 --model qwen3-custom-voice
read -rs -p 'Worker Token: ' ASMR_WORKER_TOKEN
export ASMR_WORKER_TOKEN
python scripts/colab_worker.py serve &
python scripts/colab_worker.py serve --profile qwen3
```

只需要分离、识别和对齐时，省略 `qwen3` 的准备步骤，让 `pipeline` Worker 在前台运行。模型可以通过 `ASMR_HELPER_MODEL_ROOT` 指定单独的缓存目录。只在需要的会话中启用 GPU，并在使用完毕时关闭会话以释放算力。

在安装 Colab CLI 的 WSL/Linux 终端，通过既有会话转发端口。将 `colab` 改成该终端中 CLI 的绝对路径，帐号需有 SSH 权限和有效的本地 SSH 密钥。执行前用 `colab status -s asmr` 确认会话已存在。关闭会话前先断开 SSH 转发。[Colab SSH 官方说明](https://github.com/googlecolab/google-colab-cli/blob/main/docs/06_ssh_access.md)

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -o 'ProxyCommand=/opt/colab-cli/bin/colab ssh --proxy-mode -s asmr' \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -L 127.0.0.1:8765:127.0.0.1:8765 -L 127.0.0.1:8766:127.0.0.1:8766 root@asmr
```

关闭原有桌面窗口后，在项目目录通过 PowerShell 使用同一个 Token 启动 UI V2。在「算力与模型 → 远端算力」检查连接，然后运行流水线。使用远端 Qwen3-TTS 或 VoxCPM2 的配方时，在声音库把引擎连接指向对应的转发端口，并填入同一 Token。翻译沿用流水线选中的翻译连接，混音与导出在本机完成。仅试跑分离、识别和对齐时，可把这三个节点与字幕导出组成一条流水线。

```powershell
$env:ASMR_HELPER_REMOTE_WORKER_URL = 'http://127.0.0.1:8765'
$env:ASMR_HELPER_REMOTE_WORKER_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Worker Token' -AsSecureString)).Password
.\RUNGUI.bat
```

## 台本预审、桌面接力与单句重抽

在 `asmr_prepare_draft` 中传入 `script_path` 可将 TXT 或 PDF 台词对到已有原文字幕或 ASR 时间点。设置 `prepare_stems: true` 会优先使用已有分轨，通过差分补齐缺轨，缺少参考轨时调用 Demucs。审稿报告的 `script_alignment` 列出匹配行、未匹配行、录音多出的片段、低置信度锚点和时间冲突。

桌面端和 MCP 使用同一工作区与声音库。自定义数据目录时，两个进程的 `ASMR_HELPER_STATE_DB` 应指向同一个 SQLite 文件，`ASMR_HELPER_VOICE_LAB_DIR` 应指向同一个声音库目录。Agent 交出 `draft_id` 后，可在桌面草稿列表打开对应草稿，试听样音、改词并确认合成。

对已配音的草稿，使用 `asmr_get_draft_audit` 并设置 `include_segments: true` 取得当前修订号与台词 ID。在 `asmr_commit_draft` 中传入该修订号、输出目录和 `regenerate_cue_ids: ["cue-0002"]` 即可只重抽指定句，并重新混音。普通提交会复用内容和声音设置相同的已完成录音；合成中断后，可以按最新修订继续提交。需要逐句恢复的草稿会分句请求远端 GPU，每句返回后即保存。设置 `mix_options.sidechain_ducking: true` 可在配音发声时自动压低背景。

## 双耳重制与 Colab 模型

- **桌面工作流**可在模块库添加「配音混音」，将分离节点的「背景与触发音」连入其中。将同一时间轴的原声或人声干轨连到配音节点的「原声参考」，即可在「声学与重制」中开启动态双耳、响度或频响匹配等选项。混音侧链可用于保留原声的双语混音。使用纯替换背景时可开启底噪填补，同时连接原始完整音轨作为混音参考。
- **草稿**可在 `asmr_prepare_draft` 传入 `auto_detect_delivery: true`、`duration_aware: true`，分别建议发声方式和约束译文字数。审稿时可覆盖建议。需要重建分轨时，可同时指定 `prepare_stems: true` 和 `separation_model: "mel_band_roformer"`。渲染选项放在 `voice_plan.acoustic_options`，例如 `{"binaural_mode":"dynamic_hrtf","loudness_match":"per_cue","eq_matching":true,"time_stretch_engine":"pytsmod_wsola","reverb_match":true}`。底噪填补使用 `mix_options.room_tone_inpaint`。
- **可选 Colab Worker**可按本页第 5 节启动。参考克隆配方可配置 `reference_mode: "per_style"` 或 `"per_cue"`，用时间轴匹配的原文和音频替换配方的单段参考。桌面工作流可由翻译节点提供原文，草稿可使用原文字幕或 ASR 转录。
- **合成验卡和变声**可在 `voice_plan` 设置 `verify_with_asr: true`、`max_retries: 2`、`min_similarity: 0.75`，并用 `vc_refinement: {"enabled":true,"provider":"seed_vc","diffusion_steps":25}` 开启后置变声。CosyVoice 2 与 GPT-SoVITS 分别通过 `cosyvoice2`、`gpt_sovits` Worker 语音连接使用。WSOLA 需要项目现有的可选 `audio` 依赖。
- **离线 A/B**使用同一批干声试听本地处理差异。传入原音、字幕以及按句排序的干声文件，脚本会导出对比 WAV 和 JSON 指标。

```powershell
python scripts/benchmark_asmr_remake.py original.wav timing.srt --takes cue1.wav cue2.wav --background no_vocals.wav --reference vocals.wav
```
