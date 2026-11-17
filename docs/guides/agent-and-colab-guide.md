# AI Agent 协作与 Colab 云端算力指南

本指南说明如何通过 **MCP Server** 让外部 AI Agent（Antigravity、Claude Code、Cursor 等）调用 ASMR Helper 完成两阶段半自动精制，以及如何在无独立显卡（或显存受限）的机器上使用 **Google Colab GPU Worker** 与**国内高速镜像源**。

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

### MCP JSON 配置示例

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

## 4. 启动 Colab 云端 GPU Worker 远程卸载推理

当本机没有 NVIDIA 显卡或显存不足以同时运行 Demucs、Whisper、强制对齐与本地大模型 TTS（`qwen3` / `voxcpm2`）时，可将重算力无状态卸载至免费/Pro 版 Google Colab（T4 16GB / L4 24GB）：

### 步骤 1：在 Colab 运行 Worker Notebook

1. 在 Google Colab 打开仓库中的 [notebooks/colab_gpu_worker.ipynb](../../notebooks/colab_gpu_worker.ipynb)，将运行时类型切换为 **T4 GPU** 或 **L4 GPU**。
2. **单元格 1（可选持久化缓存）**：保持 `MOUNT_GOOGLE_DRIVE = True`，模型权重将缓存在 `/content/drive/MyDrive/AsmrHelperModels`（自动绑定 `ASMR_HELPER_MODEL_ROOT`、`HF_HOME` 与 `MODELSCOPE_CACHE`），下次重启会话免重复下载。
3. **单元格 2（环境准备）**：复用 Colab 预装 PyTorch 快速安装推理组件。若需在云端运行 `qwen3` 或 `voxcpm2` 本地 TTS，可在该单元格补充安装对应包（如 `pip install qwen-tts` 或 `pip install voxcpm`）。
4. **单元格 3（启动服务与加密隧道）**：后台启动 `python -m packages.gpu_worker.cli --serve`（内置 `ModelLeaseManager` 在 16GB 显存上跨阶段自动卸载旧模型防 OOM），并通过免注册的 `cloudflared` 打印临时公网地址与随机令牌：

   ```text
   ASMR_HELPER_REMOTE_WORKER_URL=https://xxxx-xxxx.trycloudflare.com
   ASMR_HELPER_REMOTE_WORKER_TOKEN=<随机生成的安全令牌>
   ```

### 步骤 2：在本机或 MCP 环境接入远程 Worker

将 Colab 输出的两行环境变量配置到本机终端、桌面端启动环境或 MCP Server 的 `env` 字段中：

```powershell
$env:ASMR_HELPER_REMOTE_WORKER_URL = "https://xxxx-xxxx.trycloudflare.com"
$env:ASMR_HELPER_REMOTE_WORKER_TOKEN = "粘贴输出的随机令牌"
```

（也可直接把上述两行发送给 Agent，让其在调用 `asmr_prepare_draft` 时传入 `remote_worker_url` 与 `remote_worker_token`，或在声音库为 `qwen3` / `voxcpm2` 连接填入该 `base_url` 与 `api_key`。）

配置生效后，本机将自动完成透明卸载，无需在本地安装庞大的 `.runtimes` 模型权重：

- **Demucs 人声分离**（`SeparatorEngineRuntime`）、**ASR 识别**与**强制时间轴对齐**自动通过无损 `.flac` 压缩上传音频（节省约 60% 隧道上传带宽），并在本机还原目标 `.wav` 分轨与时间轴；
- **Qwen3-TTS 与 VoxCPM2**：就绪探测（`probe`）直接校验远端 `/v1/capabilities`；批量配音（`SpeechService.run_requests`）在本地先行校验参考音频 SHA256 摘要后，将克隆参考音频无损转码为 `.flac` 单次上传至 `/v1/tts/batch`，并将返回的无损音频解码写入本地 float32 WAV，工作区数据库、草稿状态与最终双声道混音全程安全保留在本机。
