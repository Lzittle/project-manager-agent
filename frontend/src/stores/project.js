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
    async create(name, description) {
      await projectApi.create({ name, description })
      await this.load()
    },
    async remove(id) {
      await projectApi.remove(id)
      if (this.currentId === id) this.currentId = null
      await this.load()
    },
  },
})
