import { api } from './client'
import type { GraphExecutionProfile } from '@/domain/workflowGraph'
import type {
  PipelineExecutionProfileRequest,
  ResourceStatusListResponse,
  TaskReadinessResponse,
} from './types'

export const resourcesApi = {
  getStatus: () => api.get<ResourceStatusListResponse>('/resources/status'),
  checkTaskReadiness: (
    taskType: string,
    executionProfile: PipelineExecutionProfileRequest | GraphExecutionProfile,
    inputPath?: string,
  ) =>
    api.post<TaskReadinessResponse>('/runtime/check-task-readiness', {
      task_type: taskType,
      execution_profile: executionProfile,
      input_path: inputPath,
    }),
}
