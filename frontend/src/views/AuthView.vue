<template>
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-brand">
        <svg viewBox="0 0 32 32" class="auth-mark" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#0f766e" />
          <circle cx="12" cy="13" r="4" fill="#fff" />
          <circle cx="21" cy="13" r="4" fill="#7dd8cf" />
          <path d="M8 24c1-4 2.5-6 4-6s3 2 4 6" fill="#fff" />
          <path d="M17 24c1-4 2.5-6 4-6s3 2 4 6" fill="#7dd8cf" />
        </svg>
        <div class="auth-brandtext">
          <b>Squad</b><i>小队智脑</i>
        </div>
      </div>

      <!-- 已登录：直接给身份现状 + 认领 / 退出 -->
      <template v-if="auth.isLoggedIn">
        <div class="auth-me">
          <span class="auth-ava">{{ auth.displayName.slice(0, 1).toUpperCase() }}</span>
          <div class="auth-metext">
            <b>{{ auth.displayName }}</b>
            <span>{{ auth.username }} · {{ statusText }}</span>
          </div>
        </div>

        <div v-if="auth.memberId" class="auth-note ok">
          名册成员 #{{ auth.memberId }} —— 「我」的范围、指派给你的任务都按这个身份算。
        </div>
        <div v-else class="auth-note wait">
          你还没有名册身份。输入队长给你的邀请码认领，占位成员上原先派的活会自动归位。
        </div>

        <div class="auth-field">
          <label class="auth-label">邀请码</label>
          <div class="auth-row">
            <el-input
              v-model="inviteCode"
              placeholder="如 PWMDGA"
              maxlength="20"
              class="auth-code"
              @keyup.enter="doClaim"
            />
            <el-button type="primary" :loading="auth.busy" @click="doClaim">认领</el-button>
          </div>
        </div>

        <div class="auth-foot">
          <button class="auth-link" type="button" @click="goWorkspace">回到工作台</button>
          <button class="auth-link danger" type="button" @click="doLogout">退出登录</button>
        </div>
      </template>

      <!-- 未登录：登录 / 注册两个分段 -->
      <template v-else>
        <div class="auth-tabs" role="tablist" :class="{ reg: mode === 'register' }">
          <button
            class="auth-tab"
            :class="{ on: mode === 'login' }"
            role="tab"
            type="button"
            @click="switchMode('login')"
          >登录</button>
          <button
            class="auth-tab"
            :class="{ on: mode === 'register' }"
            role="tab"
            type="button"
            @click="switchMode('register')"
          >注册 · 加入小队</button>
        </div>

        <div class="auth-field">
          <label class="auth-label">用户名</label>
          <el-input v-model="form.username" placeholder="你的名字" maxlength="50" @keyup.enter="submit" />
        </div>

        <div v-if="mode === 'register'" class="auth-field">
          <label class="auth-label">邮箱</label>
          <el-input v-model="form.email" placeholder="you@example.com" maxlength="120" @keyup.enter="submit" />
        </div>

        <div class="auth-field">
          <label class="auth-label">密码</label>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="mode === 'register' ? '至少 6 位' : '请输入密码'"
            maxlength="128"
            @keyup.enter="submit"
          />
        </div>

        <el-button
          type="primary"
          class="auth-submit"
          :loading="auth.busy"
          @click="submit"
        >{{ mode === 'login' ? '登录' : '注册并加入小队' }}</el-button>

        <p class="auth-hint">
          {{ mode === 'login'
            ? '注册即入队：新账号马上能被指派，也能在「我」里看到自己的任务。'
            : '注册后会立刻登记成小队的 active 成员，队长就能把任务派给你。' }}
        </p>

        <div class="auth-foot">
          <button class="auth-link" type="button" @click="goWorkspace">先随便看看（演示身份）</button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const mode = ref('login')                 // login | register
const form = reactive({ username: '', email: '', password: '' })
const inviteCode = ref('')

const statusText = computed(() =>
  auth.user?.member_status === 'placeholder' ? '待认领' : (auth.memberId ? '已入队' : '未认领'))

function switchMode(next) {
  mode.value = next
  if (next === 'login') form.email = ''
}

function goWorkspace() {
  router.push('/')
}

async function submit() {
  const username = form.username.trim()
  const email = form.email.trim()
  if (!username) return ElMessage.warning('请填用户名')
  if (mode.value === 'register' && !email) return ElMessage.warning('请填邮箱')
  if (!form.password) return ElMessage.warning('请填密码')
  if (mode.value === 'register' && form.password.length < 6) return ElMessage.warning('密码至少 6 位')

  try {
    if (mode.value === 'login') {
      await auth.login({ username, password: form.password })
      ElMessage.success(`欢迎回来，${auth.displayName}`)
    } else {
      await auth.register({ username, email, password: form.password })
      ElMessage.success(`注册成功，${auth.displayName} 已加入名册`)
    }
    goWorkspace()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function doClaim() {
  const code = inviteCode.value.trim()
  if (!code) return ElMessage.warning('请输入邀请码')
  try {
    await auth.claim(code)
    inviteCode.value = ''
    ElMessage.success(`已认领名册身份：${auth.displayName}`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function doLogout() {
  auth.logout()
  ElMessage.success('已退出，切回演示身份')
  goWorkspace()
}
</script>

<style scoped>
/* v5 令牌（D-013）：卡片 = surface 底 + line 边 + 16 圆角；分段切换走 999 胶囊；
   状态提示用四色软块（mint / sand）而不是 Element 的 success/warning 浅色变量 */
.auth-wrap {
  min-height: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: clamp(1.5rem, 6vh, 4rem) 1rem 4rem;
}
.auth-card {
  width: min(100%, 26rem);
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-radius: var(--p-r-lg);
  box-shadow: 0 2px 10px -2px rgba(55, 53, 47, 0.06), 0 1px 2px rgba(55, 53, 47, 0.04);
  padding: 1.75rem 1.6rem 1.5rem;
}
.auth-brand { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 1.25rem; }
.auth-mark { width: 34px; height: 34px; border-radius: var(--p-r-sm); }
.auth-brandtext { line-height: 1.1; }
.auth-brandtext b { font-size: 1.1rem; display: block; color: var(--p-ink); }
.auth-brandtext i { font-style: normal; font-size: var(--p-fs-eyebrow); letter-spacing: 2px; color: var(--p-idle); }

/* 分段切换：白滑块用 ::before 平移做出「滑过去」的效果（不再靠底色突然切换） */
.auth-tabs {
  position: relative;
  display: flex;
  padding: 4px;
  background: var(--p-line-soft);
  border-radius: var(--p-r-pill);
  margin-bottom: 1.15rem;
}
.auth-tabs::before {
  content: '';
  position: absolute;
  inset: 4px 50% 4px 4px;          /* 右边界压到 50% → 宽度恰等于单个 tab（无 gap） */
  border-radius: var(--p-r-pill);
  background: var(--p-surface);
  box-shadow: 0 1px 2px rgba(55, 53, 47, 0.08);
  transition: transform 0.22s var(--squad-ease);
}
.auth-tabs.reg::before { transform: translateX(100%); }
.auth-tab {
  position: relative;
  z-index: 1;
  flex: 1;
  border: 0;
  background: transparent;
  padding: 0.42rem 0.5rem;
  border-radius: var(--p-r-pill);
  font-size: var(--p-fs-ui);
  font-weight: 600;
  color: var(--p-ink-2);
  cursor: pointer;
  transition: color var(--p-dur) var(--squad-ease);
}
.auth-tab:hover { color: var(--p-ink); }
.auth-tab.on { color: var(--p-brand-strong); }

.auth-field { margin-bottom: 0.9rem; }
.auth-label { display: block; font-size: var(--p-fs-meta); color: var(--p-ink-2); margin-bottom: 0.35rem; }
.auth-row { display: flex; gap: 0.5rem; }
.auth-code { flex: 1; }

.auth-submit { width: 100%; margin-top: 0.35rem; }
.auth-hint { font-size: var(--p-fs-meta); color: var(--p-idle); line-height: var(--p-lh-ui); margin: 0.8rem 0 0; }

.auth-me {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.8rem;
  background: var(--p-brand-wash);
  border-radius: var(--p-r-sm);
  margin-bottom: 0.9rem;
}
.auth-ava {
  width: 40px; height: 40px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--p-brand); color: #fff; font-weight: 700; font-size: var(--p-fs-title);
}
.auth-metext { line-height: var(--p-lh-tight); }
.auth-metext b { display: block; font-size: var(--p-fs-body); color: var(--p-ink); }
.auth-metext span { font-size: var(--p-fs-meta); color: var(--p-ink-2); }

.auth-note { font-size: var(--p-fs-meta); line-height: var(--p-lh-ui); padding: 0.6rem 0.75rem; border-radius: var(--p-r-sm); margin-bottom: 1rem; }
.auth-note.ok { background: var(--p-block-mint); color: var(--p-on-mint); }
.auth-note.wait { background: var(--p-block-sand); color: var(--p-on-sand); }

.auth-foot { display: flex; justify-content: space-between; gap: 0.75rem; margin-top: 1.1rem; }
.auth-link {
  border: 0; background: transparent; padding: 0;
  font-size: var(--p-fs-meta); color: var(--p-brand); cursor: pointer;
}
.auth-link:hover { text-decoration: underline; }
.auth-link.danger { color: var(--p-danger); }
</style>
