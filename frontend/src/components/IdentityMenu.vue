<template>
  <div class="idm" ref="rootEl">
    <!-- 触发按钮由调用方给（顶栏是头像块、工作台是 ws-avatar），保证各处观感一致 -->
    <span class="idm-trigger" role="button" tabindex="0" :aria-expanded="open"
          @click="toggle" @keydown.enter.prevent="toggle" @keydown.space.prevent="toggle">
      <slot name="trigger">
        <span class="idm-ava">{{ auth.displayName.slice(0, 1).toUpperCase() }}</span>
        <span class="idm-name">{{ auth.displayName }}</span>
      </slot>
    </span>

    <div v-if="open" class="idm-pop" role="dialog" aria-label="身份">
      <div class="idm-head">
        <span class="idm-ava big">{{ auth.displayName.slice(0, 1).toUpperCase() }}</span>
        <div class="idm-headtext">
          <b>{{ auth.displayName }}</b>
          <span v-if="auth.isLoggedIn">{{ auth.username }} · {{ statusText }}</span>
          <span v-else>当前是演示身份（未登录）</span>
        </div>
      </div>

      <!-- 已登录且已认领 / 未认领 -->
      <template v-if="auth.isLoggedIn">
        <p v-if="auth.memberId" class="idm-note ok">
          名册成员 #{{ auth.memberId }}：指派给你的活、「我」的范围都按这个身份算。
        </p>
        <template v-else>
          <p class="idm-note wait">还没有名册身份 —— 填队长给的邀请码认领，指派到占位成员的活会自动归位。</p>
          <div class="idm-claim">
            <input
              v-model="code"
              class="idm-input"
              type="text"
              placeholder="邀请码，如 PWMDGA"
              maxlength="20"
              aria-label="邀请码"
              @keydown.enter="claim"
            />
            <button class="idm-btn solid" type="button" :disabled="auth.busy" @click="claim">认领</button>
          </div>
        </template>
        <button class="idm-item danger" type="button" @click="logout">退出登录</button>
      </template>

      <!-- 未登录 -->
      <template v-else>
        <p class="idm-note">
          未登录也能用（就是队长视角的演示身份 alice）。登录后「我」按你本人算。
        </p>
        <button class="idm-item primary" type="button" @click="goAuth">登录 / 注册 · 加入小队</button>
        <button class="idm-item" type="button" @click="goAuth">我用邀请码认领身份</button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const open = ref(false)
const code = ref('')
const rootEl = ref(null)

const statusText = computed(() => (auth.memberId ? '已入队' : '未认领'))

function toggle() { open.value = !open.value }
function close() { open.value = false }

function goAuth() {
  close()
  router.push('/auth')
}

async function claim() {
  const v = code.value.trim()
  if (!v) return ElMessage.warning('请输入邀请码')
  try {
    await auth.claim(v)
    code.value = ''
    close()
    ElMessage.success(`已认领名册身份：${auth.displayName}`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function logout() {
  auth.logout()
  close()
  ElMessage.success('已退出，切回演示身份')
}

// 点空白处收起（浮层是叠加式，不遮罩 —— 与项目里「就地浮层」的习惯一致）
function onDocClick(e) {
  if (open.value && rootEl.value && !rootEl.value.contains(e.target)) close()
}
onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<style scoped>
/* v5 令牌（D-013）：浮层 = surface 底 + line 边 + 16 圆角；状态色走 --p-ok / --p-on-sand；危险走 --p-danger */
.idm { position: relative; }
.idm-trigger { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; border-radius: var(--p-r-pill); }
.idm-ava {
  width: 28px; height: 28px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--p-brand); color: #fff;
  font-size: var(--p-fs-ui); font-weight: 700; text-transform: uppercase;
}
.idm-ava.big { width: 36px; height: 36px; font-size: var(--p-fs-title); }
.idm-name { font-size: var(--p-fs-ui); color: var(--p-ink-2); margin-left: 0.5rem; }

.idm-pop {
  position: absolute; right: 0; top: calc(100% + 8px); z-index: 40;
  width: 17rem; padding: 0.75rem;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-radius: var(--p-r-lg);
  box-shadow: 0 16px 40px -12px rgba(55, 53, 47, 0.18), 0 2px 8px rgba(55, 53, 47, 0.06);
  text-align: left;
}
.idm-head { display: flex; align-items: center; gap: 0.6rem; padding-bottom: 0.65rem; border-bottom: 1px solid var(--p-line); margin-bottom: 0.65rem; }
.idm-headtext { line-height: var(--p-lh-tight); min-width: 0; }
.idm-headtext b { display: block; font-size: var(--p-fs-body); color: var(--p-ink); }
.idm-headtext span { font-size: var(--p-fs-tag); color: var(--p-ink-2); }

.idm-note { font-size: var(--p-fs-meta); line-height: var(--p-lh-ui); color: var(--p-ink-2); margin: 0 0 0.6rem; }
.idm-note.ok { color: var(--p-ok); }
.idm-note.wait { color: var(--p-on-sand); }

.idm-claim { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; }
.idm-input {
  flex: 1; min-width: 0; height: 30px; padding: 0 0.55rem;
  border: 1px solid var(--p-line); border-radius: var(--p-r-sm);
  font-size: var(--p-fs-meta); color: var(--p-ink); background: var(--p-surface);
  outline: none; font-family: inherit;
}
.idm-input:focus { border-color: var(--p-brand); }
.idm-btn {
  height: 30px; padding: 0 0.7rem; border-radius: var(--p-r-sm); border: 1px solid var(--p-line);
  background: var(--p-line-soft); font-size: var(--p-fs-meta); cursor: pointer; font-family: inherit;
  color: var(--p-ink-2);
}
.idm-btn.solid { background: var(--p-brand); border-color: var(--p-brand); color: #fff; }
.idm-btn:disabled { opacity: 0.6; cursor: default; }

.idm-item {
  display: block; width: 100%; text-align: left;
  padding: 0.45rem 0.55rem; border: 0; border-radius: var(--p-r-sm);
  background: transparent; font-size: var(--p-fs-ui); cursor: pointer;
  color: var(--p-ink-2); font-family: inherit;
}
.idm-item:hover { background: var(--p-line-soft); }
.idm-item.primary { color: var(--p-brand-strong); font-weight: 600; }
.idm-item.danger { color: var(--p-danger); }
</style>
