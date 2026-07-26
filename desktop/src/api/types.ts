// ── Health ─────────────────────────────────────────────
export interface HealthResponse {
  status: string
  version: string
}

// ── Tasks ──────────────────────────────────────────────
export type TaskState =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'skipped'

export interface TaskStatusResponse {
  task_id: string
  state: TaskState
  stage: string | null
  progress: number
  message: string
  detail: string
  error: Record<string, unknown> | null
  task_type: string
  task_source: string
  input_asset_id: string
  created_at: string
  queued_at: string | null
  started_at: string | null
  updated_at: string
  finished_at: string | null
}

export interface TaskListResponse {
  tasks: TaskStatusResponse[]
}

export interface RuntimeEventResponse {
  sequence: number
  time: string
  level: string
  type: string
  task_id: string
  stage: string | null
  message: string
  detail: string | null
  data: Record<string, unknown>
}

export interface ArtifactResponse {
  artifact_id: string
  task_id: string
  type: string
  path: string
  stage: string
  label: string
  primary: boolean
  preview: boolean
  metadata: Record<string, unknown>
}

export interface TaskResultResponse {
  task_id: string
  primary_artifact_id: string | null
  artifacts: ArtifactResponse[]
  warnings: string[]
}

export type TaskArtifactsResponse = TaskResultResponse

// ── Pipeline ───────────────────────────────────────────
export interface StageProfileRequest {
  enabled: boolean
  provider: string
  model: string | null
  options: Record<string, unknown>
  provider_options: Record<string, unknown>
}

export interface PipelineExecutionProfileRequest {
  version: 1
  source_lang: string
  target_lang: string
  skip_existing: boolean
  stages: {
    separate: StageProfileRequest
    asr: StageProfileRequest
    translate: StageProfileRequest
    tts: StageProfileRequest
    mix: StageProfileRequest
    export: StageProfileRequest
  }
}

export interface PipelineRunRequest {
  input: {
    path: string
    companion_paths: string[]
  }
  output: {
    directory?: string
  }
  execution_profile: PipelineExecutionProfileRequest
}

export interface PipelineTaskCreateResponse {
  task: TaskStatusResponse
}

export interface PresetItem {
  id: string
  label: string
  description: string
  stages: string[]
}

export interface PipelinePresetsResponse {
  presets: PresetItem[]
}

export interface BatchPipelineRequest {
  input_files?: string[]
  input_dir?: string
  output_base_dir?: string
  source_lang?: string
  target_lang?: string
  use_vocal_separator?: boolean
  tts_engine?: string
  tts_voice?: string
  vocal_model?: string
  asr_model?: string
  translate_provider?: string
  tts_speed?: number
  original_volume?: number
  tts_volume_ratio?: number
  tts_delay?: number
  skip_existing?: boolean
  max_workers?: number
  use_batch_output_structure?: boolean
  voice_profile_id?: string | null
}

export interface BatchItemResultResponse {
  file: string
  status: string
  task_id: string | null
  output: string | null
  error: string | null
  duration: number
}

export interface BatchPipelineResponse {
  items: BatchItemResultResponse[]
  total_count: number
  success_count: number
  skipped_count: number
  failed_count: number
  total_duration: number
}

// ── ASR ────────────────────────────────────────────────
export interface TranscribeRequest {
  input_path: string
  output_path?: string | null
  model?: string
  language?: string
}

export interface TranscribeSegment {
  start: number
  end: number
  text: string
}

export interface TranscribeResponse {
  segments: TranscribeSegment[]
  output_path: string | null
  text: string
}

// ── Translation ────────────────────────────────────────
export interface TranslateRequest {
  input_path: string
  output_path?: string | null
  provider?: string
  source_lang?: string
  target_lang?: string
}

export interface TranslateResponse {
  items: string[]
  provider: string
  source_lang: string
  target_lang: string
}

// ── TTS ────────────────────────────────────────────────
export interface SynthesizeRequest {
  input_path: string
  output_path: string
  engine?: string
  model?: string
  voice?: string
  speed?: number
  common_options?: Record<string, unknown>
  provider_options?: Record<string, unknown>
}

export interface SynthesizeResponse {
  engine: string
  voice: string
  output_path: string
}

// ── Models ─────────────────────────────────────────────
export interface ModelSummaryResponse {
  model_id: string
  kind: string
  category: string
  backend: string
  display_name: string
  supports_install: boolean
  supports_remove: boolean
  family_id?: string | null
  variant_group?: string | null
  variant_tier?: string | null
  is_primary_variant?: boolean
  dependency_group?: string | null
  runtime_profile?: string | null
  preferred_runtime?: string | null
  install_modes?: string[]
  default_install_mode?: string | null
  required_assets?: string[]
  recommended_assets?: string[]
  required_system_tools?: string[]
  supported_os?: string[]
}

export interface ModelStatusResponse {
  model_id: string
  status: string
  detail: string
  executable: boolean
  issues: Array<{
    code: string
    requirement: string
    message: string
  }>
}

export interface ModelOperationResponse {
  action: string
  model_id: string
  success: boolean
  status: string
  detail: string
}

export interface ModelInstallRequest {
  mirror?: string
  force?: boolean
  install_mode?: string
  install_dependencies?: boolean
  install_recommended_assets?: boolean
  allow_fallback_variant?: boolean
}

export interface ModelInstallAsyncResponse {
  task_id: string
  status: string
}

export interface ModelVerificationResponse {
  model_id: string
  success: boolean
  status: string
  detail: string
}

// ── Subtitles ──────────────────────────────────────────
export interface SubtitleSegmentModel {
  start: number
  end: number
  text: string
}

export interface SubtitleDocumentModel {
  segments: SubtitleSegmentModel[]
}

export interface SubtitleLoadRequest {
  file_path: string
}

export interface SubtitleLoadResponse {
  document: SubtitleDocumentModel
  segments: SubtitleSegmentModel[]
}

export interface SubtitleExportRequest {
  document?: SubtitleDocumentModel
  segments?: SubtitleSegmentModel[]
  output_path: string
}

export interface SubtitleExportResponse {
  output_path: string
  segment_count: number
}

export interface ScriptToVttRequest {
  script_path: string
  output_path?: string
  audio_path?: string | null
  vtt_path?: string | null
  fmt?: string
  use_llm_clean?: boolean
  asr_model_size?: string
  asr_language?: string
  track_index?: number | null
  vertical_mode?: string
  debug_dir?: string | null
}

export interface ScriptToVttResponse {
  mode: string
  output_path: string | null
  text: string
  line_count: number
}

// ── Resources ──────────────────────────────────────────
export interface ResourceStatusResponse {
  name: string
  available: boolean
  detail: string
  metadata: Record<string, unknown>
}

export interface ResourceStatusListResponse {
  resources: ResourceStatusResponse[]
}

// ── Voice ──────────────────────────────────────────────
export interface VoiceProfileSummaryResponse {
  id: string
  name: string
  category: string
  engine: string
  description: string
  available: boolean
}

export interface VoiceProfileResponse {
  id: string
  name: string
  category: string
  engine: string
  description: string
  speaker: string
  instruct: string
  design_instruct: string
  ref_audio: string
  generated: boolean
  available: boolean
}

export interface VoiceDesignRequest {
  description: string
  name: string
  ref_text?: string
}

export interface VoiceDesignResponse {
  profile_id: string
  name: string
  category: string
  ref_audio_path: string
  prompt_cache_path: string
}

export interface VoiceCloneRequest {
  audio_path: string
  name: string
  ref_text?: string
}

export interface VoiceCloneResponse {
  profile_id: string
  name: string
  category: string
  ref_audio_path: string
  prompt_cache_path: string
}

export interface SegmentAnalyzeRequest {
  audio_path: string
  ref_text?: string
}

export interface SegmentInfo {
  start: number
  end: number
  text: string
  quality_score: number
}

export interface SegmentAnalyzeResponse {
  segments: SegmentInfo[]
  recommended_index: number
}

export interface VoicePreviewRequest {
  text: string
  speed?: number
}

export interface VoicePreviewResponse {
  profile_id: string
  audio_path: string
}

// ── Tool tasks ─────────────────────────────────────────
export interface ToolTaskCreateRequest {
  task_type: string
  input_path: string
  companion_paths?: string[]
  execution_profile?: Record<string, unknown>
}

export interface ToolDescriptorResponse {
  task_type: string
  name: string
  category: string
  primary_artifact: string
}

export interface ToolListResponse {
  tools: ToolDescriptorResponse[]
}

// ── Subtitle translation ───────────────────────────────
export interface SubtitleTranslationRequest {
  input_path: string
  output_path?: string
  provider?: string
  source_lang?: string
  target_lang?: string
  bilingual?: boolean
}

export interface SubtitleTranslationResponse {
  input_path: string
  output_path: string | null
  total_segments: number
  provider: string
  source_lang: string
  target_lang: string
}
