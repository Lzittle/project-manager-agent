// 项目全局状态：项目列表 + 当前选中项目（工作台对话/看板/记忆/总览共用）
// 约定：NO_PROJECT(0) 表示「全局 · 不绑定项目」——对话可建任意项目、看板/记忆给出先选项目引导。
import { defineStore } from 'pinia'
import { projectApi } from '../api'

export const NO_PROJECT = 0

export const useProjectStore = defineStore('project', {
  state: () => ({
    projects: [],
    currentId: NO_PROJECT,
    loading: false,
  }),
  getters: {
    current: (s) => s.projects.find((p) => p.id === s.currentId) || null,
    // 树形展开后的项目行（根在前，子项目紧随其后带 depth），供下拉/面包屑/仪表盘复用
    treeRows: (s) => {
      const byId = new Map(s.projects.map((p) => [p.id, p]))
      const childrenOf = new Map()
      for (const p of s.projects) {
        if (p.parent_id && byId.has(p.parent_id)) {
          if (!childrenOf.has(p.parent_id)) childrenOf.set(p.parent_id, [])
          childrenOf.get(p.parent_id).push(p)
        }
      }
      const rows = []
      const walk = (p, depth) => {
        rows.push({ ...p, depth })
        const kids = (childrenOf.get(p.id) || []).sort((a, b) => b.id - a.id)
        for (const c of kids) walk(c, depth + 1)
      }
      // 视为根：parent_id 为空，或父项目已不存在（孤儿容错）
      const roots = s.projects
        .filter((p) => !p.parent_id || !byId.has(p.parent_id))
        .sort((a, b) => b.id - a.id)
      roots.forEach((r) => walk(r, 1))
      return rows
    },
    // 当前项目所在层级（面包屑用）：根=1；全局时 =1
    currentDepth: (s) => {
      const node = s.treeRows.find((r) => r.id === s.currentId)
      return node ? node.depth : 1
    },
  },
  actions: {
    async load() {
      this.loading = true
      try {
        this.projects = await projectApi.list()
        // 默认停在「全局」；仅当当前选中的项目已被删除时才退回全局，绝不悄悄替你绑定某个项目
        const stillValid =
          this.currentId !== null &&
          this.currentId !== undefined &&
          this.currentId !== NO_PROJECT &&
          this.projects.some((p) => p.id === this.currentId)
        if (!stillValid) this.currentId = NO_PROJECT
      } finally {
        this.loading = false
      }
      return this.projects
    },
    setCurrent(id) {
      this.currentId = id ?? NO_PROJECT
    },
    async create(name, description, parentId = null) {
      await projectApi.create({ name, description, parent_id: parentId ?? null })
      await this.load()
      return this.projects
    },
    async remove(id) {
      await projectApi.remove(id)
      if (this.currentId === id) this.currentId = NO_PROJECT
      await this.load()
    },
  },
})
