import modelReadiness from '../../../docs/guides/model-readiness.md?raw'
import doc0 from '../../../docs/guides/workbench.md?raw'
import doc1 from '../../../docs/guides/workflow-graph-v2.md?raw'
import doc2 from '../../../docs/guides/cloud-tts-user-guide.md?raw'
import doc3 from '../../../docs/guides/voice-lab-v2.md?raw'
import doc4 from '../../../docs/guides/fish-cloning.md?raw'
import doc5 from '../../../docs/guides/reference-selection.md?raw'
import doc6 from '../../../docs/guides/tts.md?raw'
import doc7 from '../../../docs/guides/quick-start.md?raw'
import doc8 from '../../../docs/guides/installation.md?raw'
import doc9 from '../../../docs/guides/desktop-page-help.md?raw'
import extensionDoc from '../../../docs/cloud-tts-extension.md?raw'

export const HELP_DOCUMENTS: Record<string, string> = {
  'model-readiness.md': modelReadiness,
  'workbench.md': doc0,
  'workflow-graph-v2.md': doc1,
  'cloud-tts-user-guide.md': doc2,
  'voice-lab-v2.md': doc3,
  'fish-cloning.md': doc4,
  'reference-selection.md': doc5,
  'tts.md': doc6,
  'quick-start.md': doc7,
  'installation.md': doc8,
  'desktop-page-help.md': doc9,
  '../cloud-tts-extension.md': extensionDoc,
}

export function resolveHelpDocument(reference: string): { reference: string; source: string } | null {
  const [file, encodedSection] = reference.split('#', 2)
  const source = HELP_DOCUMENTS[file || ""]
  if (!source) return null
  if (!encodedSection) return { reference, source }
  let section: string
  try { section = decodeURIComponent(encodedSection) } catch { return null }
  const lines = source.split(/\r?\n/)
  const start = lines.findIndex(line => /^#{1,6} /.test(line) && line.replace(/^#{1,6} /, '') === section)
  if (start < 0) return null
  const level = lines[start]!.match(/^#+/)![0].length
  let end = start + 1
  while (end < lines.length && !(new RegExp(`^#{1,${level}} `)).test(lines[end]!)) end++
  return { reference, source: lines.slice(start, end).join('\n') }
}

export const PAGE_HELP = {
  "workbench": {"title": "工作台", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存的流水线，默认使用预设参数。"}, {"title": "导入素材并补齐输入", "detail": "导入素材，展开素材组并绑定所需输入。"}, {"title": "按需调整参数", "detail": "需要时打开调整参数，修改当前节点设置。"}, {"title": "开始处理", "detail": "勾选要处理的素材组并提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
  "workflow": { title: "流水线编辑器", document: "workflow-graph-v2.md", steps: [{"title": "打开或新建流程", "detail": "打开已保存流水线，或新建空白流程草稿。"}, {"title": "连接模块", "detail": "添加处理节点，连接端口并配置输入槽位。"}, {"title": "检查并保存", "detail": "检查节点参数与连线，填写名称后保存。"}, {"title": "在工作台运行", "detail": "返回工作台选择该流程，绑定素材后运行。"}] },
  "connections": { title: "外部服务", document: "desktop-page-help.md#外部服务", steps: [{"title": "添加服务连接", "detail": "按用途在语言模型或语音合成区域新增服务。"}, {"title": "填写连接信息", "detail": "填写名称、协议、地址和 API 密钥。"}, {"title": "保存并检查", "detail": "保存连接，按需检查配置或测试连通性。"}, {"title": "在对应模块使用", "detail": "在翻译节点或音色预设中选择已保存连接。"}] },
  "presets": { title: "音色预设", document: "desktop-page-help.md#音色预设", steps: [{"title": "制作新音色", "detail": "填写名称与合成目标语言，选择引擎和模型。"}, {"title": "准备声音来源", "detail": "按模式填写声音 ID、描述或选择参考素材。"}, {"title": "配置连接与参数", "detail": "选择外部连接或本机环境，按需调整参数。"}, {"title": "保存并复用", "detail": "保存到音色库，供试听页和工作台复用。"}] },
  "audition": { title: "试听与记录", document: "desktop-page-help.md#试听与记录", steps: [{"title": "载入已保存预设", "detail": "选择要试听的音色，核对引擎、模型和语言。"}, {"title": "输入短句试音", "detail": "输入试音台词，点击生成试音。"}, {"title": "播放并微调", "detail": "播放试听结果，按需微调参数并对比效果。"}, {"title": "保存候选设置", "detail": "将满意的候选参数另存为音色预设。"}] },
  "references": { title: "参考素材", document: "voice-lab-v2.md#声音库", steps: [{"title": "导入参考录音", "detail": "选择本机音频并添加到参考素材列表。"}, {"title": "试听并选段", "detail": "试听音频或框选片段，可加载字幕辅助定位。"}, {"title": "核对录音信息", "detail": "填写名称、语言与选段原文，确认内容一致。"}, {"title": "另存并创建音色", "detail": "保存参考片段，直接用于创建克隆音色。"}] },
  "fish-clone": { title: "Fish 远程克隆", document: "fish-cloning.md", steps: [{"title": "准备连接和素材", "detail": "选择官方 Fish 连接与已保存的 WAV 参考片段。"}, {"title": "检查上传摘要", "detail": "填写音色名称，核对上传片段与参考原文。"}, {"title": "明确提交并查状态", "detail": "提交创建并等待云端训练完成。"}, {"title": "就绪后保存音色", "detail": "状态变为 trained 后保存音色，供试听或合成使用。"}] },
  "tasks": { title: "任务记录", document: "desktop-page-help.md#任务记录", steps: [{"title": "筛选任务", "detail": "按分类、状态或名称筛选并打开任务详情。"}, {"title": "查看进度与错误", "detail": "查看执行阶段、日志与错误原因。"}, {"title": "检查运行产物", "detail": "在详情中试听音频、预览字幕或复制文件路径。"}, {"title": "按需处理记录", "detail": "按需取消、重试或清理历史任务记录。"}] },
  "batches": { title: "批次管理", document: "desktop-page-help.md#批次管理", steps: [{"title": "选择批次", "detail": "打开已提交批次，查看各素材组状态。"}, {"title": "检查冻结设置", "detail": "查看批次提交时的流程与输入配置快照。"}, {"title": "查看结果或恢复", "detail": "查看已完成产物，或对失败项执行恢复操作。"}, {"title": "核对后再重试", "detail": "确认重试范围与配置后重新提交。"}] },
  "subtitle-editor": { title: "字幕编辑", document: "desktop-page-help.md#字幕编辑", steps: [{"title": "加载字幕", "detail": "加载 SRT、VTT 或 LRC，可选配音频辅助定位。"}, {"title": "编辑字幕行", "detail": "修改起止时间与台词文本，点击行可定位试听。"}, {"title": "导出修改", "detail": "选择目标格式并导出保存。"}] },
  "subtitle-translate": { title: "字幕翻译", document: "desktop-page-help.md#字幕翻译", steps: [{"title": "准备字幕与连接", "detail": "选择字幕文件并指定翻译服务连接。"}, {"title": "设置翻译方向", "detail": "设置源语言、目标语言、双语选项与输出路径。"}, {"title": "提交并导出", "detail": "开始翻译，在任务中心查看进度与译文字幕。"}] },
  "script-text": {"title": "台本转字幕：整理台词", "document": "desktop-page-help.md#台本转字幕：整理台词", "steps": [{"title": "准备台本", "detail": "选择 PDF 或 UTF-8 TXT 台本文件。"}, {"title": "预览并确认", "detail": "预览提取的台词与排除项，修订后确认。"}, {"title": "保存台词文本", "detail": "导出整理后的纯文本台词（TXT）。"}]},
  "script-audio": {"title": "台本转字幕：录音匹配", "document": "desktop-page-help.md#台本转字幕：录音匹配", "steps": [{"title": "准备台本与录音", "detail": "选择台本、对应录音及识别语言。"}, {"title": "预览并确认", "detail": "预览并修订台词，确认与录音内容一致。"}, {"title": "匹配并核对", "detail": "查看识别匹配结果，核对未匹配或冲突片段。"}, {"title": "试听修正再导出", "detail": "在编辑器中试听微调时间轴，确认后导出字幕。"}]},
  "script-vtt": {"title": "台本转字幕：复用原文字幕", "document": "desktop-page-help.md#台本转字幕：复用原文字幕", "steps": [{"title": "准备原文字幕与录音", "detail": "选择台本、对应录音及同语言原文字幕（SRT/VTT）。"}, {"title": "预览并确认", "detail": "修订并确认台词，复用参考字幕时间锚点。"}, {"title": "核对后导出", "detail": "核对匹配结果，在编辑器中修正后导出。"}]},
  "audio-separate": { title: "人声分离", document: "desktop-page-help.md#人声分离", steps: [{"title": "选择输入音频", "detail": "选择需要分离人声与伴奏的音频文件。"}, {"title": "确认输出位置", "detail": "检查输出目录，留空则使用默认目录。"}, {"title": "运行并试听结果", "detail": "提交后在任务中心查看并试听分离结果。"}] },
  "audio-convert": { title: "格式转换", document: "desktop-page-help.md#格式转换", steps: [{"title": "选择输入音频", "detail": "选择要转换的本机音频文件。"}, {"title": "设置输出格式", "detail": "设置目标格式、采样率、声道与输出路径。"}, {"title": "提交并查看文件", "detail": "运行后在任务中心查看转换结果。"}] },
  "audio-split": { title: "按字幕切分", document: "desktop-page-help.md#按字幕切分", steps: [{"title": "准备音频与字幕", "detail": "选择音频文件及时间轴对应的字幕。"}, {"title": "设置切分参数", "detail": "设置切分前后留白与输出目录。"}, {"title": "提交并查看片段", "detail": "运行后在任务中心查看切分出的音频片段。"}] },
  "audio-translate": { title: "字幕翻译工具", document: "desktop-page-help.md#字幕翻译工具", steps: [{"title": "选择字幕文件", "detail": "选择需要翻译的时间轴字幕。"}, {"title": "设置语言方向", "detail": "选择源语言与目标语言。"}, {"title": "运行并查看译文", "detail": "提交后在任务中心查看翻译结果。"}] },
  "audio-volume": { title: "音量分析", document: "desktop-page-help.md#音量分析", steps: [{"title": "选择分析音频", "detail": "选择原音频，按需添加配音文件。"}, {"title": "核对混音比例", "detail": "设置原音频与配音轨的参考音量比例。"}, {"title": "查看分析结果", "detail": "运行后在任务详情查看响度数据与混音建议。"}] },
  "appearance": { title: "外观与语言", document: "desktop-page-help.md#外观与语言", steps: [{"title": "选择界面语言", "detail": "切换中文或英文界面显示。"}, {"title": "调整背景", "detail": "设置自定义背景图片与遮罩浓度。"}, {"title": "查看即时效果", "detail": "修改实时生效，可随时恢复默认外观。"}] },
  "preset-catalog": { title: "预设管理：当前目录", document: "desktop-page-help.md#预设管理：当前目录", steps: [{"title": "选择流水线", "detail": "搜索并查看当前目录中的流水线预设。"}, {"title": "维护流程", "detail": "打开编辑器修改结构，或另存为新预设。"}, {"title": "确认删除范围", "detail": "删除预设只移除目录项，不影响历史任务。"}] },
  "preset-templates": { title: "预设管理：内置模板", document: "desktop-page-help.md#预设管理：内置模板", steps: [{"title": "打开内置模板", "detail": "浏览系统提供的内置流水线模板。"}, {"title": "添加独立副本", "detail": "命名并添加到当前目录，生成独立预设。"}, {"title": "编辑后再运行", "detail": "按需编辑节点配置，保存后在工作台运行。"}] },
  "paths": { title: "文件与缓存", document: "desktop-page-help.md#文件与缓存", steps: [{"title": "核对工作区", "detail": "查看或切换当前工作区目录。"}, {"title": "调整存储路径", "detail": "配置默认输出、模型与临时缓存目录。"}, {"title": "保存路径设置", "detail": "保存路径修改，新任务将使用更新后的目录。"}] },
  "local-asr": { title: "ASR 识别模型", document: "desktop-page-help.md#ASR 识别模型", steps: [{"title": "查看本分类模型", "detail": "查看语音识别（ASR）模型与运行环境。"}, {"title": "查看资源状态", "detail": "检查模型权重、依赖环境与安装目录。"}, {"title": "按需验证资源", "detail": "支持一键安装、校验完整性或修复环境。"}, {"title": "回到使用页面", "detail": "就绪后在工作台或对应工具中选择该引擎。"}] },
  "local-tts": { title: "TTS 合成模型", document: "desktop-page-help.md#TTS 合成模型", steps: [{"title": "查看本分类模型", "detail": "查看本机语音合成（TTS）模型与环境。"}, {"title": "查看资源状态", "detail": "检查模型权重、依赖环境与安装目录。"}, {"title": "按需验证资源", "detail": "支持一键安装、校验完整性或修复环境。"}, {"title": "回到使用页面", "detail": "就绪后在音色库或工作台中选择该引擎。"}] },
  "local-llm": { title: "LLM 语言模型", document: "desktop-page-help.md#LLM 语言模型", steps: [{"title": "查看本分类模型", "detail": "查看本地大语言模型（LLM）与运行环境。"}, {"title": "查看资源状态", "detail": "检查模型权重、依赖环境与安装目录。"}, {"title": "按需验证资源", "detail": "支持一键安装、校验完整性或修复环境。"}, {"title": "回到使用页面", "detail": "就绪后在翻译或台本清洗中选择该引擎。"}] },
  "local-other": { title: "其他资源", document: "desktop-page-help.md#其他资源", steps: [{"title": "查看本分类模型", "detail": "查看音频分离、对齐等辅助模型与工具。"}, {"title": "查看资源状态", "detail": "检查模型权重、依赖环境与安装目录。"}, {"title": "按需验证资源", "detail": "支持一键安装、校验完整性或修复环境。"}, {"title": "回到使用页面", "detail": "就绪后在工作台或对应工具中使用。"}] },
  "workbench-common": {"title": "工作台：常用参数", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存流水线，加载预设节点配置。"}, {"title": "导入并绑定素材", "detail": "导入音频或字幕，在素材组中绑定输入槽位。"}, {"title": "工作台：常用参数", "detail": "快速调整各节点的引擎、音色、语言与连接。"}, {"title": "开始处理", "detail": "勾选要处理的素材组并提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
  "workbench-advanced": {"title": "工作台：高级参数", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存流水线，加载预设节点配置。"}, {"title": "导入并绑定素材", "detail": "导入音频或字幕，在素材组中绑定输入槽位。"}, {"title": "工作台：高级参数", "detail": "按需微调节点高级选项，或另存为新预设。"}, {"title": "开始处理", "detail": "勾选要处理的素材组并提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
} satisfies Record<string, { title: string; document: string; steps: { title: string; detail: string }[] }>
export type PageHelpTopic = keyof typeof PAGE_HELP

// Public examples only. Help never reads connections, credentials or user media.
export const SERVICE_ADDRESSES = [
  { label: 'Fish Audio', value: 'https://api.fish.audio/v1' },
  { label: 'Gemini TTS', value: 'https://generativelanguage.googleapis.com/v1beta' },
  { label: 'ElevenLabs', value: 'https://api.elevenlabs.io' },
  { label: 'MiMo TTS', value: 'https://api.xiaomimimo.com/v1' },
]
export const VOICE_STARTERS = [
  { label: 'Fish Audio', model: 's2.1-pro-free', voice: '已有 Voice ID；可查询或手填' },
  { label: 'Gemini TTS', model: 'gemini-3.8-flash-tts', voice: 'Kore' },
  { label: 'ElevenLabs', model: 'eleven_v3', voice: '自己的真实 Voice ID' },
  { label: 'MiMo TTS', model: 'mimo-v2.5-tts', voice: 'mimo_default' },
]
export const AUDITION_EXAMPLE = '欢迎使用。放松下来，听一听这段中文配音。'
