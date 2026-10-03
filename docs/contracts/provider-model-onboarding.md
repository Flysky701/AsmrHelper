# Provider / Model 接入

新增能力应复用现有声明、验证和运行通道。TTS 的能力来源是 [Speech Provider](../guides/tts.md)，不在通用能力服务或桌面常量中复制一份模型和默认值。

| 内容 | 位置 |
| --- | --- |
| ASR / LLM 等适配与参数转换 | `src/core/engines/` 与对应领域模块 |
| TTS 声明、编译与执行 | `src/core/speech/` |
| 通用客户端能力 | `CapabilityDescriptorService` |
| 本地资源及依赖 | `config/models.yaml` |
| 就绪检查 | `ResourceService` 和对应 Provider |
| 隔离环境及 Worker | `src/core/runtime/` |

先核对项目锁定版本的真实构造和执行入口，仅公开已经接线的参数，保证“能力声明 → 运行适配 → 上游参数”一一对应。特殊的上游限制记录在相邻实现或当前指南，避免复制完整厂商文档。

已有 Provider 增加普通模型时，更新 supported_models，并为本地模型登记资源；运行模型 ID 与资源 ID 不同则使用 capability_models 显式映射。只有构造、依赖或参数语义实际不同才新建 Adapter。

完成条件：

1. Provider、Model、默认值与资源映射一致，默认模型是实际可发送的 ID。
2. 后端拒绝未知参数、错误类型和越界值；展示控件传入的参数确实由适配器消费。
3. 就绪检查能区分缺模型、依赖、工具、凭据和状态未知，只检查所选能力。
4. 使用 mock 验证映射与失败路径，保留关键兼容回归；真实样本验证另行执行并记录结果。
5. 客户端优先使用能力描述，配置检查不冒充鉴权或实际推理成功。

Faster-Whisper 的 ASMR 默认选择保留轻声，不默认启用 VAD；参数及模型集合以当前适配器和能力目录为准。新增模型不能借机改变已有任务的冻结参数。
