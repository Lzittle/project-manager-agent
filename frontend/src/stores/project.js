// 项目全局状态：项目列表 + 当前选中项目（仪表盘/看板/知识库共用）
import { defineStore } from 'pinia'
import { projectApi } from '../api'

export const useProjectStore = defineStore('project', {
  state: () => ({
    projects: [],
    currentId: null,
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
    // 当前项目所在层级（面包屑用）：根=1
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
        if (!this.currentId && this.projects.length) {
          this.currentId = this.projects[0].id
        }
      } finally {
        this.loading = false
      }
      return this.projects
    },
    setCurrent(id) {
      this.currentId = id
    },
    async create(name, description, parentId = null) {
      await projectApi.create({ name, description, parent_id: parentId ?? null })
      await this.load()
      return this.projects
    },
    async remove(id) {
      await projectApi.remove(id)
      if (this.currentId === id) this.currentId = null
      await this.load()
    },
  },
})
