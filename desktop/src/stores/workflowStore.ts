import { create } from 'zustand'
import { persist, type StateStorage } from 'zustand/middleware'
import { createJSONStorage } from 'zustand/middleware'
import { pipelineApi } from '../api/pipeline'
import type { GraphPresetDraft, GraphPresetItem, PresetItem } from '../api/types'
import type { GraphBindings, GraphDefinition, GraphMaterialBinding, GraphNode } from '../domain/workflowGraph'
import { GRAPH_NODE_KINDS, validateGraph } from '../domain/workflowGraph'
import { cloneDraft, draftFingerprint, emptyGraph, type WorkflowEditorDraft } from '../domain/workflowDraft'

type Destination = 'workbench' | 'settings'
type SaveMode = 'update' | 'copy'
type CatalogApi = Pick<typeof pipelineApi, 'graphPresets' | 'graphDraft' | 'createGraphPreset' | 'updateGraphPreset' | 'deletePreset'>
type EditorPatch = Partial<Pick<WorkflowEditorDraft, 'graph' | 'label' | 'description'>>
export interface WorkflowState {
  catalog: (PresetItem | GraphPresetItem)[]
  catalogLoading: boolean
  catalogError: string | null
  selectedPreset: GraphPresetItem | null
  runtimeGraph: GraphDefinition | null
  bindings: GraphBindings
  editor: WorkflowEditorDraft | null
  saving: boolean
  error: string | null
  /** An unrecognized saved draft is retained rather than erased during restore. */
  recoveryDraft: unknown | null
  loadCatalog: () => Promise<void>
  selectPreset: (preset: GraphPresetItem) => void
  updateRuntimeNode: (node: GraphNode) => void
  setBinding: (slotId: string, value: GraphMaterialBinding | undefined) => void
  openEditor: (preset: GraphPresetItem | null, returnTo: Destination, useRuntime?: boolean) => void
  openLegacyEditor: (preset: PresetItem, returnTo: Destination) => Promise<void>
  updateEditor: (patch: EditorPatch) => void
  closeEditor: () => void
  saveEditor: (mode: SaveMode) => Promise<GraphPresetItem | null>
  saveRuntime: (mode: SaveMode, label?: string) => Promise<GraphPresetItem | null>
  deletePreset: (id: string, revision: number) => Promise<boolean>
}

const message = (error: unknown) => error instanceof Error ? error.message : '保存失败，请重试'
const isGraph = (value: unknown): value is GraphDefinition => {
  if (!value || typeof value !== 'object') return false
  const graph = value as GraphDefinition
  return graph.version === 2 && Array.isArray(graph.nodes) && Array.isArray(graph.edges)
    && Array.isArray(graph.input_slots) && Array.isArray(graph.outputs)
    && graph.nodes.every(node => isRecord(node) && typeof node.id === 'string' && GRAPH_NODE_KINDS.includes(node.kind)
      && typeof node.provider === 'string' && (node.model === null || typeof node.model === 'string')
      && isRecord(node.options) && isRecord(node.provider_options))
    && graph.input_slots.every(slot => isRecord(slot) && typeof slot.id === 'string' && typeof slot.label === 'string' && ['audio', 'subtitle'].includes(slot.type))
    && graph.edges.every(edge => isRecord(edge) && isRecord(edge.source) && isRecord(edge.target)
      && typeof edge.target.node_id === 'string' && typeof edge.target.port === 'string'
      && (edge.source.kind === 'slot' && typeof edge.source.slot_id === 'string'
        || edge.source.kind === 'node' && typeof edge.source.node_id === 'string' && typeof edge.source.port === 'string'))
    && graph.outputs.every(output => isRecord(output) && typeof output.node_id === 'string' && typeof output.port === 'string')
}
const isPreset = (value: unknown): value is GraphPresetItem => {
  const item = value as GraphPresetItem | null
  return !!item && item.version === 2 && typeof item.id === 'string' && typeof item.label === 'string'
    && typeof item.description === 'string' && typeof item.builtin === 'boolean'
    && Number.isInteger(item.revision) && item.revision > 0 && isGraph(item.graph)
}
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
function validBindings(value: unknown): value is GraphBindings {
  return isRecord(value) && Object.values(value).every(item => isRecord(item) && typeof item.path === 'string')
}
function editorFor(preset: GraphPresetItem | null, graph: GraphDefinition, returnTo: Destination): WorkflowEditorDraft {
  const draft = { graph: cloneDraft(graph), label: preset?.label ?? '', description: preset?.description ?? '' }
  return { preset: preset ? cloneDraft(preset) : null, ...draft, returnTo, initialFingerprint: draftFingerprint(draft) }
}
function draftFor(graph: GraphDefinition, label: string, description: string): GraphPresetDraft {
  if (!label.trim() || label.trim().length > 100) throw new Error('请填写 1–100 字的流水线名称')
  if (description.length > 1000) throw new Error('流水线说明不能超过 1000 字')
  const issues = validateGraph(graph)
  if (issues.length) throw new Error(issues.map(issue => issue.message).join('；'))
  return { version: 2, label: label.trim(), description: description.trim(), graph: cloneDraft(graph) }
}

/** One draft store, one server catalog. Dependency injection is only for local mock verification. */
export function createWorkflowStore(client: CatalogApi = pipelineApi, storage?: StateStorage) {
  let selectionGeneration = 0, editorGeneration = 0, catalogGeneration = 0
  return create<WorkflowState>()(persist((set, get) => {
    const upsert = (item: GraphPresetItem) => {
      catalogGeneration++
      set(state => ({ catalog: state.catalog.some(preset => preset.id === item.id)
        ? state.catalog.map(preset => preset.id === item.id ? item : preset) : [...state.catalog, item] }))
    }
    const save = async (mode: SaveMode, preset: GraphPresetItem | null, draft: GraphPresetDraft) => {
      if (mode === 'update') {
        if (!preset || preset.builtin) throw new Error('内置流水线不可覆盖，请另存为自定义流水线')
        return client.updateGraphPreset(preset.id, { ...draft, revision: preset.revision })
      }
      return client.createGraphPreset(draft)
    }
    return {
      catalog: [], catalogLoading: false, catalogError: null, selectedPreset: null, runtimeGraph: null,
      bindings: {}, editor: null, saving: false, error: null, recoveryDraft: null,
      loadCatalog: async () => {
        if (get().catalogLoading) return
        const generation = catalogGeneration
        set({ catalogLoading: true, catalogError: null })
        try { const result = await client.graphPresets(); if (generation === catalogGeneration) set({ catalog: result.presets }) }
        catch (error) { if (generation === catalogGeneration) set({ catalogError: message(error) }) }
        finally { set({ catalogLoading: false }) }
      },
      selectPreset: preset => {
        selectionGeneration++
        set({ selectedPreset: cloneDraft(preset), runtimeGraph: cloneDraft(preset.graph), error: null })
      },
      updateRuntimeNode: node => {
        const graph = get().runtimeGraph, previous = graph?.nodes.find(item => item.id === node.id)
        if (!graph || !previous || previous.kind !== node.kind) {
          set({ error: '工作台只能调整已有模块的参数；请在流水线编辑页修改结构' }); return
        }
        selectionGeneration++
        set({ runtimeGraph: { ...graph, nodes: graph.nodes.map(item => item.id === node.id ? cloneDraft(node) : item) }, error: null })
      },
      setBinding: (slotId, value) => set(state => {
        const bindings = { ...state.bindings }
        if (value) bindings[slotId] = cloneDraft(value)
        else delete bindings[slotId]
        return { bindings }
      }),
      openEditor: (preset, returnTo, useRuntime = false) => {
        editorGeneration++
        const state = get(), graph = useRuntime && preset?.id === state.selectedPreset?.id && state.runtimeGraph
          ? state.runtimeGraph : preset?.graph ?? emptyGraph()
        const editor = editorFor(preset, graph, returnTo)
        // Runtime overrides are a draft until explicitly saved, even when opened in the editor.
        if (useRuntime && preset) editor.initialFingerprint = draftFingerprint({ graph: preset.graph, label: preset.label, description: preset.description })
        set({ editor, error: null })
      },
      openLegacyEditor: async (preset, returnTo) => {
        const generation = ++editorGeneration
        const selection = selectionGeneration
        set({ error: null })
        try {
          const result = await client.graphDraft(preset.id)
          if (generation !== editorGeneration || selection !== selectionGeneration) return
          const editor = editorFor(null, result.graph, returnTo)
          editor.label = `${preset.label}（节点版）`
          editor.description = preset.description
          editor.warnings = result.warnings
          set({ editor })
        } catch (error) { if (generation === editorGeneration) set({ error: message(error) }) }
      },
      updateEditor: patch => {
        const editor = get().editor
        if (editor) set({ editor: { ...editor, ...cloneDraft(patch) }, error: null })
      },
      closeEditor: () => { editorGeneration++; set({ editor: null, error: null }) },
      deletePreset: async (id, revision) => {
        if (get().saving) return false
        const preset = get().catalog.find(item => item.id === id)
        if (preset?.builtin) {
          set({ error: '内置预设不可删除；可以保存为自己的副本。' })
          return false
        }
        const generation = editorGeneration
        set({ saving: true, error: null })
        try {
          await client.deletePreset(id, revision)
          // Invalidate an older catalog request so it cannot restore the deleted entry.
          catalogGeneration++
          const state = get(), editor = state.editor
          if (state.selectedPreset?.id === id) selectionGeneration++
          if (editor?.preset?.id === id) editorGeneration++
          set({
            catalog: state.catalog.filter(item => item.id !== id),
            selectedPreset: state.selectedPreset?.id === id ? null : state.selectedPreset,
            // Deleting a saved template must not erase material bindings or an open draft.
            editor: editor?.preset?.id === id ? { ...editor, preset: null, initialFingerprint: '' } : editor,
          })
          return true
        } catch (error) { if (generation === editorGeneration) set({ error: message(error) }); return false }
        finally { set({ saving: false }) }
      },
      saveEditor: async mode => {
        const state = get(), editor = state.editor
        if (state.saving || !editor) return null
        const generation = editorGeneration, selection = selectionGeneration
        const fingerprint = draftFingerprint({ graph: editor.graph, label: editor.label, description: editor.description })
        set({ saving: true, error: null })
        try {
          const item = await save(mode, editor.preset, draftFor(editor.graph, editor.label, editor.description))
          upsert(item)
          const current = get().editor
          if (generation !== editorGeneration || !current || selection !== selectionGeneration) return null
          const currentFingerprint = draftFingerprint({ graph: current.graph, label: current.label, description: current.description })
          if (currentFingerprint !== fingerprint) {
            set({ editor: { ...current, preset: cloneDraft(item), initialFingerprint: draftFingerprint({ graph: item.graph, label: item.label, description: item.description }) }, error: '已保存提交时的版本；之后的编辑仍在草稿中，请再次保存' })
            return null
          }
          selectionGeneration++
          set({ selectedPreset: cloneDraft(item), runtimeGraph: cloneDraft(item.graph), editor: editorFor(item, item.graph, editor.returnTo) })
          return item
        } catch (error) { if (generation === editorGeneration) set({ error: message(error) }); return null }
        finally { set({ saving: false }) }
      },
      saveRuntime: async (mode, label) => {
        const state = get()
        if (state.saving || !state.runtimeGraph) return null
        const generation = selectionGeneration, preset = state.selectedPreset
        set({ saving: true, error: null })
        try {
          const item = await save(mode, preset, draftFor(state.runtimeGraph, label ?? preset?.label ?? '', preset?.description ?? ''))
          upsert(item)
          if (generation !== selectionGeneration) return null
          selectionGeneration++
          set({ selectedPreset: cloneDraft(item), runtimeGraph: cloneDraft(item.graph) })
          return item
        } catch (error) { if (generation === selectionGeneration) set({ error: message(error) }); return null }
        finally { set({ saving: false }) }
      },
    }
  }, {
    name: 'asmr-workflow-v2-draft', version: 1,
    ...(storage ? { storage: createJSONStorage(() => storage) } : {}),
    partialize: state => ({ selectedPreset: state.selectedPreset, runtimeGraph: state.runtimeGraph,
      bindings: state.bindings, editor: state.editor, recoveryDraft: state.recoveryDraft }),
    migrate: value => ({ recoveryDraft: value, selectedPreset: null, runtimeGraph: null, bindings: {}, editor: null }),
    merge: (saved, current) => {
      if (!isRecord(saved)) return { ...current, recoveryDraft: saved ?? null }
      const editor = saved.editor as WorkflowEditorDraft | null
      const editorValid = editor === null || isRecord(editor) && isGraph(editor.graph)
        && (editor.preset === null || isPreset(editor.preset)) && typeof editor.label === 'string'
        && typeof editor.description === 'string' && typeof editor.initialFingerprint === 'string'
        && ['settings', 'workbench'].includes(editor.returnTo)
      if (!(saved.selectedPreset === null || isPreset(saved.selectedPreset))
        || !(saved.runtimeGraph === null || isGraph(saved.runtimeGraph)) || !validBindings(saved.bindings) || !editorValid) {
        return { ...current, recoveryDraft: saved }
      }
      return { ...current, selectedPreset: saved.selectedPreset as GraphPresetItem | null,
        runtimeGraph: saved.runtimeGraph as GraphDefinition | null, bindings: saved.bindings,
        editor, recoveryDraft: saved.recoveryDraft ?? null }
    },
  }))
}

export const useWorkflowStore = createWorkflowStore()
