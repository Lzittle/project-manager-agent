// 身份状态（轮 3，D-030）：账号（users）管登录，成员（members）管指派，两层在「我」这里汇合。
//
// 约定：
//   - 未登录 = 演示身份（DEMO_USER_ID=1 / alice）—— 演示脚本、评测、只读探针不因此失效；
//   - 登录后 userId 换成账号 id，所有请求的 `user_id` 参数随之切换（见 api/index.js）；
//   - token + 身份落 localStorage，刷新即恢复；启动时用 /auth/me 复核一次，令牌失效就静默登出。
import { defineStore } from 'pinia'
import { authApi, memberApi, DEMO_USER_ID, TOKEN_KEY, USER_KEY } from '../api'

function persist(token, user) {
  try {
    if (token && user) {
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } else {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    }
  } catch { /* 隐私模式下忽略：本次会话内仍然可用 */ }
}

function loadCached() {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    const raw = localStorage.getItem(USER_KEY)
    return { token: token || '', user: raw ? JSON.parse(raw) : null }
  } catch {
    return { token: '', user: null }
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => {
    const cached = loadCached()
    return {
      token: cached.token,
      user: cached.user, // MeOut：{ id, username, email, member_id, member_name, member_status }
      ready: false,      // 是否已完成启动时的身份复核
      busy: false,
    }
  },
  getters: {
    isLoggedIn: (s) => !!s.token && !!s.user,
    // 请求里传的 user_id：登录用账号 id，未登录回退演示用户
    userId: (s) => s.user?.id ?? DEMO_USER_ID,
    username: (s) => s.user?.username || 'alice',
    // 名册上的身份（认领后才有）—— 指派/「我」的范围按它算
    memberId: (s) => s.user?.member_id ?? null,
    memberName: (s) => s.user?.member_name ?? null,
    // 展示名：优先名册名字，其次账号名
    displayName: (s) => s.user?.member_name || s.user?.username || 'alice',
    // 还没认领名册（注册即入队的人不会是这种；受邀账号才会有）
    needsClaim: (s) => (s.user ? !s.user.member_id : false),
  },
  actions: {
    _accept({ token, user }) {
      this.token = token
      this.user = user
      persist(token, user)
    },
    _forget() {
      this.token = ''
      this.user = null
      persist('', null)
    },

    /** 启动时复核令牌：成功刷新身份，失败（过期/被改）静默登出。 */
    async restore() {
      if (!this.token) { this.ready = true; return }
      try {
        this.user = await authApi.me()
        persist(this.token, this.user)
      } catch {
        this._forget()
      } finally {
        this.ready = true
      }
    },

    async register({ username, email, password }) {
      this.busy = true
      try {
        const res = await authApi.register({ username, email, password })
        this._accept(res)
        return res.user
      } finally {
        this.busy = false
      }
    },

    async login({ username, password }) {
      this.busy = true
      try {
        const res = await authApi.login({ username, password })
        this._accept(res)
        return res.user
      } finally {
        this.busy = false
      }
    },

    /** 用邀请码认领占位成员；成功后刷新身份（member_id 变了，界面跟着切到本人）。 */
    async claim(inviteCode) {
      this.busy = true
      try {
        await memberApi.claim(inviteCode)
        this.user = await authApi.me()
        persist(this.token, this.user)
        return this.user
      } finally {
        this.busy = false
      }
    },

    logout() {
      this._forget()
    },
  },
})
