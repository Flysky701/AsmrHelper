// ── Health ─────────────────────────────────────────────
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
  session_id: string
  input_asset_id: string
  created_at: string
  queued_at: string | null
  started_at: string | null
  updated_at: string
  finished_at: string | null
  artifact_set_id: string | null
  retry_of_task_id: string | null
  review_state: '' | 'accepted' | 'needs_review' | 'needs_rework'
  review_note: string
}

export interface TaskListResponse {
  tasks: TaskStatusResponse[]
}

export interface TaskSpecResponse {
  task_id: string
  task_type: string
  task_source: string
  session_id: string
  input_asset_id: string
  companion_asset_ids: string[]
  execution_profile: Record<string, unknown>
  priority: number
  dedupe_key: string
  retry_of_task_id: string | null
  created_at: string
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

export type WorkflowStageId = 'separate' | 'asr' | 'align' | 'translate' | 'tts' | 'mix' | 'export'
export type WorkflowReference =
  | { kind: 'asset'; path: string; language?: string; language_confirmed?: boolean; audio_path?: string; pair_confirmed?: boolean }
  | { kind: 'stage'; stage: WorkflowStageId }
export interface PipelineWorkflowRequest {
  version: 1
  bindings: Partial<Record<WorkflowStageId, Record<string, WorkflowReference>>>
  outputs: WorkflowStageId[]
}

export interface PipelineExecutionProfileRequest {
  version: 1
  workflow?: PipelineWorkflowRequest
  source_lang: string
  target_lang: string
  skip_existing: boolean
  stages: {
    separate: StageProfileRequest
    asr: StageProfileRequest
    align?: StageProfileRequest
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
  outputs: string[]
  revision: number
  builtin: boolean
}

export interface GraphPipelineRunRequest extends Omit<PipelineRunRequest, 'execution_profile'> {
  execution_profile: import('../domain/workflowGraph').GraphExecutionProfile
}

export interface GraphPresetDraft {
  version: 2
  label: string
  description: string
  graph: import('../domain/workflowGraph').GraphDefinition
}

export interface GraphPresetItem extends GraphPresetDraft {
  id: string
  revision: number
  builtin: boolean
}

export type FlowPresetDraft = Pick<PresetItem, 'label' | 'description' | 'stages' | 'outputs'>

export interface PipelinePresetsResponse {
  presets: PresetItem[]
}

// ── Batch runs ─────────────────────────────────────────
export type BatchRunState =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'completed_with_errors'
  | 'cancelled'
  | 'interrupted'
  | 'history_deleted'

export interface BatchDiscoveredFileResponse {
  path: string
  name: string
  size_bytes: number
  kind?: 'audio' | 'subtitle'
  companion_paths: string[]
  companion_subtitles?: import('@/domain/workbenchInput').CompanionSubtitle[]
}

export interface BatchDiscoverResponse {
  directory: string
  files: BatchDiscoveredFileResponse[]
}

export interface BatchRunCreateRequest {
  name: string
  inputs: Array<{
    path: string
    companion_paths: string[]
  }>
  output: {
    directory?: string
  }
  execution_profile: PipelineExecutionProfileRequest
  max_parallel: number
}

export interface GraphBatchRunCreateRequest {
  name: string
  client_request_id: string
  groups: Array<{ group_id: string; label?: string; bindings: import('@/domain/workflowGraph').GraphBindings }>
  output: { directory?: string }
  execution_profile: { version: 2; graph: import('@/domain/workflowGraph').GraphDefinition }
  max_parallel: number
}

export interface BatchRunItemResponse {
  item_id: string
  input_path: string
  companion_paths: string[]
  task_ids: string[]
  current_task_id: string | null
  state: TaskState | 'history_deleted'
  progress: number
  message: string
  output_path: string
  error: Record<string, unknown> | null
  group_id?: string | null
  label?: string
  bindings?: import('@/domain/workflowGraph').GraphBindings
  retry_available?: boolean
  retry_blocked_reason?: string | null
}

export interface BatchRunResponse {
  batch_id: string
  name: string
  state: BatchRunState
  progress: number
  created_at: string
  updated_at: string
  finished_at: string | null
  output_dir: string
  max_parallel: number
  total_count: number
  pending_count: number
  running_count: number
  completed_count: number
  failed_count: number
  cancelled_count: number
  skipped_count: number
  history_deleted_count?: number
  items: BatchRunItemResponse[]
  client_request_id?: string | null
  retry_available?: boolean
  retry_blocked_reason?: string | null
}

export interface BatchRunListResponse {
  batches: BatchRunResponse[]
}

// ── Models ─────────────────────────────────────────────
export interface ModelSummaryResponse {
  capability_models?: string[]
  model_id: string
  kind: string
  category: string
  backend: string
  display_name: string
  description?: string
  estimated_size_mb?: number | null
  inference_vram_gb?: number | null
  install_strategy: string
  supports_install: boolean
  supports_remove: boolean
  family_id?: string | null
  variant_group?: string | null
  variant_tier?: string | null
  is_primary_variant?: boolean
  is_auxiliary?: boolean
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

export type ModelRuntimeStatus =
  | 'missing'
  | 'not_installed'
  | 'invalid'
  | 'installed'
  | 'ready'
  | 'loaded'
  | 'configured'
  | 'unconfigured'
  | 'installing'
  | 'unknown'

export interface ModelStatusResponse {
  model_id: string
  status: ModelRuntimeStatus
  detail: string
  executable: boolean
  path?: string | null
  weights_ready?: boolean
  runtime_ready?: boolean
  shared_readonly?: boolean
  issues: Array<{
    code: string
    requirement: string
    message: string
  }>
}

export interface ModelInstallRequest {
  mirror?: string
  force?: boolean
  install_mode?: string
  install_dependencies?: boolean
  install_recommended_assets?: boolean
  allow_fallback_variant?: boolean
}

export interface ModelVerificationResponse {
  model_id: string
  success: boolean
  status: string
  detail: string
  issues: ModelStatusResponse['issues']
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

export interface ScriptToSubtitleRequest {
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
  confirmed_text?: string | null
  fingerprint?: string | null
  use_llm_match?: boolean
  reference_confirmed?: boolean
}

export interface ScriptPreview {
  raw_text: string
  clean_text: string
  actions: string[]
  sections: { index: number; title: string }[]
  fingerprint: string
}

export interface ScriptReview {
  complete: boolean
  script_lines: string[]
  entries: (SubtitleSegmentModel & { script_idx: number })[]
  asr_segments: SubtitleSegmentModel[]
  draft_entries?: SubtitleSegmentModel[]
  unmatched: { script_idx: number; text: string }[]
  extra_asr: (SubtitleSegmentModel & { asr_idx: number })[]
  conflicts: string[]
  audio_path?: string | null
  output_path: string
  duration?: number | null
  timestamp_source: string
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

// ── Tool tasks ─────────────────────────────────────────
export interface ToolTaskCreateRequest {
  task_type: string
  input_path: string
  companion_paths?: string[]
  execution_profile?: Record<string, unknown>
}

export interface CapabilityOptionResponse {
  name: string
  type: string
  required: boolean
  default: unknown
  description: string
  enum: unknown[]
  min: number | null
  max: number | null
  advanced: boolean
  secret: boolean
}

export interface CapabilityDescriptorResponse {
  category: 'asr' | 'tts' | 'llm' | 'separator' | string
  provider: string
  display_name: string
  kind: 'local' | 'cloud' | string
  supported_models: string[]
  default_model: string | null
  common_option_schema: CapabilityOptionResponse[]
  provider_option_schema: CapabilityOptionResponse[]
  supports: Record<string, unknown>
  runtime_requirements: {
    python_modules: string[]
    system_tools: string[]
  }
}

export interface TaskReadinessIssueResponse {
  stage: string
  category: string
  provider: string
  model: string | null
  code: string
  requirement: string
  message: string
  action: 'engines' | 'settings' | string
}

export interface TaskReadinessResponse {
  task_type: string
  ready: boolean
  missing_requirements: string[]
  issues: TaskReadinessIssueResponse[]
  execution_profile: Record<string, unknown>
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
export type TaskDeletionMode = 'history_only' | 'history_and_files'

export interface TaskDeletionPreviewResponse {
  preview_id: string
  mode: TaskDeletionMode
  expires_at: string
  can_execute: boolean
  tasks: Array<{
    task_id: string
    state: string | null
    eligible: boolean
    reason: string | null
    batch_ids: string[]
    files: Array<{ path: string; action: 'delete' | 'retain'; reason: string | null; size_bytes: number | null }>
  }>
  summary: {
    selected_count: number
    eligible_count: number
    blocked_count: number
    delete_file_count: number
    retain_file_count: number
    delete_bytes: number
  }
}

export interface TaskDeletionExecuteResponse {
  preview_id: string
  mode: TaskDeletionMode
  results: Array<{
    task_id: string
    history_deleted: boolean
    status: 'deleted' | 'blocked' | 'failed' | 'partial'
    reason: string | null
    files: Array<{ path: string; status: 'deleted' | 'retained' | 'failed'; reason: string | null }>
  }>
  summary: {
    deleted_count: number
    blocked_count: number
    failed_count: number
    partial_count: number
    deleted_file_count: number
    retained_file_count: number
    failed_file_count: number
  }
}

// ── Two-Phase Draft Sessions (`/api/v1/drafts`) ────────
export type DraftState =
  | 'preparing'
  | 'awaiting_review'
  | 'committing'
  | 'completed'
  | 'failed'

export interface DraftTrackItem {
  track_id: string
  stem: string
  path: string
  duration?: number
  sample_rate?: number
  channels?: number
  format?: string
  paired_stems?: {
    vocals?: string | null
    no_se?: string | null
    se_only?: string | null
    alternates?: string[]
  }
  paired_subtitles?: Array<Record<string, unknown>>
  paired_scripts?: string[]
}

export interface DraftSegment {
  index: number
  cue_id: string
  start: number
  end: number
  source_text: string
  translation: string
  speaker?: string | null
  delivery?: string
  emotion?: string
}

export interface OverSpeedCueItem {
  index: number
  cue_id: string
  start: number
  end: number
  cue_duration: number
  available_slack: number
  effective_slot: number
  char_count: number
  estimated_duration: number
  predicted_atempo: number
  max_recommended_chars: number
  source_text: string
  translation: string
}

export interface DraftReferenceCandidate {
  path: string
  source_audio_path?: string
  start?: number
  end?: number
  duration?: number
  sample_rate?: number
  snr_db?: number
  rms?: number
  transcript?: string
}

export interface DraftSampleTake {
  index: number
  cue_id: string
  text: string
  audio_path: string
  duration: number
  take_id?: string
}

export interface QualityAuditReport {
  script_alignment?: {
    unmatched: Array<{ line: number; text: string }>
    low_confidence: Array<{ line: number; cue_id: string; confidence: number }>
    extra_cue_ids: string[]
    conflicts: string[]
  } | null
  draft_id?: string | null
  state?: DraftState | string | null
  revision?: number | null
  untranslated_indices: number[]
  japanese_residue_indices: number[]
  empty_or_symbol_indices: number[]
  over_speed_cues: OverSpeedCueItem[]
  summary_counts: Record<string, number>
  gate_passed: boolean
  chars_per_second: number
  max_atempo: number
  reference_quality?: DraftReferenceCandidate | null
  warnings: string[]
}

export interface DraftDubbingArtifact {
  tts_track_path?: string
  mixed_audio_path?: string
  background_audio_path?: string
  binaural_source_path?: string | null
  borrow_silence_slack?: boolean
  channels?: number
  processing?: Record<string, unknown>
  assembly_id?: string
  reused_take_count?: number
  synthesized_take_count?: number
  total_spoken_cues?: number
}

export interface DraftArtifacts {
  primary_track_path?: string | null
  subtitle_source_mode?: string
  source_subtitles?: string[]
  reference_candidate?: DraftReferenceCandidate | null
  sample_takes?: DraftSampleTake[]
  take_cache?: Record<string, unknown>
  output_dir?: string
  subtitles?: Record<string, string>
  tts_track_path?: string
  mixed_audio_path?: string
  dubbing?: DraftDubbingArtifact | null
  last_error?: string
  [key: string]: unknown
}

export interface DraftSummary {
  draft_id: string
  state: DraftState
  work_dir: string
  title: string
  tracks: DraftTrackItem[]
  segments: DraftSegment[]
  voice_plan?: Record<string, unknown>
  audit_report?: Partial<QualityAuditReport>
  artifacts?: DraftArtifacts
  revision: number
  created_at: string
  updated_at: string
}

export interface DraftDetail extends DraftSummary {
  voice_plan: Record<string, unknown>
  audit_report: Partial<QualityAuditReport>
  artifacts: DraftArtifacts
}

export interface DraftListResponse {
  drafts: DraftDetail[]
}

export interface DraftSegmentEdit {
  index?: number
  cue_id?: string
  source_text?: string
  translation?: string
  start?: number
  end?: number
  speaker?: string | null
  delivery?: string
  emotion?: string
}

export interface DraftPatchRequest {
  edits: DraftSegmentEdit[]
  voice_plan_patch?: Record<string, unknown> | null
  title?: string | null
  expected_revision?: number | null
}

export interface DraftCommitRequest {
  regenerate_cue_ids?: string[]
  output_dir: string
  export_formats?: string[]
  enable_dubbing?: boolean
  bilingual?: boolean
  mix_options?: Record<string, unknown> | null
  expected_revision?: number | null
}

export interface DraftCommitResponse extends DraftDetail {}

export interface DraftInspectResponse {
  work_dir: string
  title: string
  tracks: DraftTrackItem[]
  audio_files: Array<{ path: string }>
  subtitles: Array<{ path: string; valid?: boolean }>
  scripts: Array<{ path: string }>
  stem_pairs: Array<Record<string, unknown>>
  readiness: Record<string, unknown>
}

export interface DraftPrepareRequest {
  path_or_dir: string
  track_path?: string | null
  subtitle_path?: string | null
  script_path?: string | null
  title?: string | null
  source_lang?: string
  target_lang?: string
  enable_translation?: boolean
  duration_aware?: boolean
  auto_detect_delivery?: boolean
  force_asr?: boolean
  asr_provider?: string | null
  asr_model?: string | null
  asr_options?: Record<string, unknown> | null
  llm_provider?: string | null
  llm_model?: string | null
  llm_options?: Record<string, unknown> | null
  voice_plan?: Record<string, unknown> | null
  prepare_stems?: boolean
  separation_model?: string | null
  extract_voice_reference?: boolean
  synthesize_samples?: boolean
  sample_cue_count?: number
  chars_per_second?: number
  max_atempo?: number
}


