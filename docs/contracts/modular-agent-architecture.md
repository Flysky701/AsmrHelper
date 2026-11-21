# 模块化分层与 Agent 驱动架构契约（V2 演进蓝图）

本文档定义 ASMR Helper 面向“Agent 自动编排 + 双轨 GPU 算力（本机 / Colab）+ 桌面精修接力”的长期模块边界、职责负面清单与分阶段演进路线。任何新增能力必须先归属到明确分层，严禁跨层耦合或向核心引擎塞入个人化策略。

---

## 1. 五层模块边界与职责负面清单

仓库采用 **Monorepo 单向依赖分层**（上层仅可依赖下层契约，禁止反向引用）：

```text
[外部独立层]  个人 Agent Plugin / Skills（媒体库寻址、个人偏好映射、审稿改词策略）
                    │                              │
             (MCP 标准工具)                 (共享 DraftSession)
                    ▼                              ▼
[4. 接入与表现层]  packages/mcp-server    packages/cli    desktop/ (Tauri 试听与精修端)
                    └──────────────┬───────────────┘
                                   ▼
[3. 领域编排层]    packages/core（DraftSession 两段式门禁、ASMR 双耳 DSP、台本对齐、极速源管理）
                                   │
                        (统一 Compute RPC 契约)
                         ┌─────────┴─────────┐
                         ▼                   ▼
[2. 算力执行层]    本机 .runtimes 子进程    Colab / 远端 GPU HTTP 服务
                         └─────────┬─────────┘
                                   ▼
                         packages/gpu-worker（无状态模型推理：Demucs / ASR / 对齐 / 本地 TTS）
                                   │
[1. 基础契约层]           packages/protocol（纯 Pydantic 数据契约与错误码，零重型运行依赖）
```

### 各层准入与禁入红线

| 层级 | 允许承载的核心职责 | 严禁塞入的内容（防膨胀红线） |
| --- | --- | --- |
| `packages/protocol` | Compute 任务请求/响应、能力探测、错误码、`DraftSession` 与 `QualityAuditReport` 数据结构 | 严禁依赖 PyTorch、FastAPI、SQLite、FFmpeg 或任何业务状态 |
| `packages/gpu-worker` | 无状态重算力执行（分离、VAD+ASR、强制对齐、本地 TTS 批量合成）、显存按需装卸与并发互斥 | 严禁感知任务数据库、台本业务逻辑、双耳混音规则或用户账户配置 |
| `packages/core` | 字幕/台本解析对齐、ASMR 音频 DSP（差分、双耳声像跟随、门限响度、句间借时、多轨混音）、`DraftSession` 两段式状态机、节点断点恢复、国内镜像源下载 | 严禁硬编码个人磁盘目录规则、DLsite 爬虫、主观偏好猜测、LLM 循环改写逻辑或内网穿透工具 |
| `packages/mcp-server` / `cli` / `http` | 协议转换、参数校验、将 `core` 服务映射为 MCP Tools / REST / CLI 命令 | 严禁复制编排逻辑或绕过 `core` 直接拼装底层文件 |
| 外部 `Agent Skill` / `Desktop` | `Skill` 负责搜寻本地音声目录、映射用户口头偏好、解读质检摘要；`Desktop` 负责波形可视化、耳机 A/B 试听与手工微调 | 前端不在浏览器私有缓存中独占业务真相，草稿一律以 `core` 的 `DraftSession` 为唯一真相 |

---

## 2. 双轨算力协议与国内极速分发策略

### 2.1 一套 `gpu-worker`，两种挂载传输
本地 `.runtimes` 与远端 Colab / 云 GPU 运行**同一套 `packages/gpu-worker` 代码**，仅传输适配器不同：

1. **Local Subprocess 模式（本机有显卡）**：主项目在隔离环境启动 `gpu-worker`，直接传递本地文件路径，零网络传输开销。
2. **Remote HTTP 模式（Colab / AutoDL / 局域网台式机）**：
   - 提供单文件 `notebooks/colab_gpu_worker.ipynb`，一键拉起 `gpu-worker` HTTP 服务与免注册 `Cloudflare Quick Tunnel`（输出临时 HTTPS 地址与随机 Bearer Token），并支持挂载 Google Drive 持久化缓存模型权重以实现秒级冷启动。
   - 本机客户端自动将待处理音频转为无损 `.flac`（缩减约 60% 传输体积）上传推理，结果拉回本机落盘并记入本地 SQLite 检查点；远端断连重开后可从已完成轨/句无缝续跑。
   - Worker 内部按阶段实行显存租约自动驱逐（如整批分离完成后释放 Demucs 显存，再加载 ASR 或本地 TTS），保障 16GB 级显卡（如 Colab T4）稳定运行。

### 2.2 本机“零 GitHub 依赖”下载链路
- **子模块源码**：随 Monorepo 内置，本机无需联网拉取子仓库；Colab 位于海外机房，拉取代码与依赖无国内限速瓶颈。
- **工具链与运行环境**：`setup` 与环境准备支持纯国内链路（阿里/清华 PyPI 镜像获取 `uv` 与基础包、国内镜像拉取托管 Python 与 PyTorch CUDA Wheel）。
- **模型权重三级源**：资源目录统一支持 **`ModelScope（魔搭社区，国内默认主源）→ HF-Mirror（备选）→ HuggingFace 官方（海外/兜底）`** 按序回退。

---

## 3. 两段式门禁状态机（`DraftSession`）

为兼顾“Agent 全托管省心执行”与“关键节点可控、可接力精修”，长流程拆分为带显式门禁的两阶段：

### 第一段：`PREPARE` → `AWAITING_REVIEW`（客观提取与预审门禁）
1. 完成音轨探测、人声分离/差分提取、前置 VAD + ASR 识别（或 PDF/TXT 台本锚点对齐）、初版译文生成。
2. 若启用原声克隆，自动从分离人声中筛选高信噪比、无触发音重叠的干净片段作为候选参考干声，并可选试合成 **1–2 句代表性样音**供听感确认。
3. 生成结构化 **`QualityAuditReport`（客观质检报告）**：
   - 未翻译/日文假名残留行号；
   - 台本未匹配或低置信度时间锚点；
   - **语速超限预警**：扣除句后可借用静音间隙后，预计仍需 `atempo > 1.35x` 压缩的台词列表；
   - 参考干声信噪比与时长评估。
4. 状态机停驻在 `AWAITING_REVIEW`，不消耗全量 TTS 时间与计费额度。

### 第二段：`COMMIT` → `COMPLETED`（补丁修订与成品交付）
1. 接收来自 **MCP（Agent 自动精简超长译文/切换音色）** 或 **Desktop UI（人工试听微调）** 的 `DraftPatch`。
2. 执行全量/增量 TTS 合成（未改动台词自动复用已有候选音频）。
3. 执行 ASMR 专属拼轨与混音算子：
   - **双耳声像自动跟随（Binaural Panning）**：测量原分离人声每句区间的左右耳能量比（ILD），将单声道 TTS 动态映射回对应声像位置；
   - **句间静音借时与受控变速**：优先向句后停顿借时，软上限保护防电音失真；
   - **门限响度匹配与可选侧链闪避**：保护掏耳/环境触发音底轨动态，导出双语 `.srt` / `.vtt` / `.lrc` 与无损混音成品。

---

## 4. 渐进式实施里程碑（禁止停摆式推倒重写）

所有演进均在 `dev` 基线上按垂直切片推进，每完成一个里程碑必须保持现有回归测试与桌面端可用：

- **Milestone 1：契约抽离、双轨 `gpu-worker` 与国内极速源**
  - 建立 `packages/protocol` 与 `packages/gpu-worker`；
  - 落地 `notebooks/colab_gpu_worker.ipynb`（Cloudflare Tunnel + Google Drive 权重缓存）与本机 Remote Compute 连接支持；
  - 接入 ModelScope 权重下载主源与国内 PyPI/Wheel 镜像配置。
- **Milestone 2：`DraftSession` 两段式门禁与 ASMR 核心音频算子**
  - 在 `core` 实现持久化 `DraftSession`、`QualityAuditReport` 与门禁样音试合成；
  - 落地 Anime Whisper 前置 VAD 切片、句间静音借时及双耳左右耳声像自动跟随（Binaural Panning）。
- **Milestone 3：`packages/mcp-server` 与个人 Agent Skill 闭环**
  - 封装高层正交 MCP 工具集（素材探测、阶段一预审、草稿修订、阶段二合成、坏句局部重抽）；
  - 建立外部个人工作流 `SKILL.md`（媒体库模糊寻址、偏好映射、质检自动改词策略），打通零 UI 对话式生产。
- **Milestone 4：Desktop 门禁接力视图与历史包袱清理**
  - Desktop 对接后端 `DraftSession`（支持一键打开 Agent 挂起的草稿试听样音并确认合成）；
  - 退役旧版 V1 隐式流水线兼容分支，归档清理 `.tmp/full-stack-v2`。
