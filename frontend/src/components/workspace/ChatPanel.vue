<!-- 对话列：消息时间线 + 输入框。滚动只在 thread 内部（D-014 的不变式）。 -->
<template>
  <section class="ws-chat">
    <div class="ws-thin">
      <div ref="threadEl" class="ws-thread">
        <div v-if="!messages.length" class="ws-hello">
          <p class="ws-hello-title">我是 Squad。说一句你想推进的事，我会拆成任务放到右边的现场里。</p>
          <div class="ws-suggest">
            <button class="ws-act" type="button" @click="$emit('send', '帮我规划几项任务')">帮我规划几项任务</button>
            <button class="ws-act" type="button" @click="$emit('send', '现在有哪些任务？')">现在有哪些任务？</button>
          </div>
        </div>
        <ChatMessage
          v-for="(m, i) in messages"
          :key="i"
          :role="m.role"
          :content="m.content"
          :trace="m.trace"
          @goto="$emit('goto', $event)"
        />
        <div v-if="sending" class="ws-typing">正在思考并调用工具…</div>
      </div>

      <div class="ws-composer">
        <textarea
          class="ws-input"
          rows="1"
          :value="draft"
          placeholder="说一句要干什么…（Enter 发送，Shift+Enter 换行）"
          @input="$emit('update:draft', $event.target.value)"
          @keydown.enter.exact.prevent="$emit('send')"
        />
        <div class="ws-sendrow">
          <span class="ws-note">对话产出的任务会直接落到右边的现场</span>
          <button class="ws-send" type="button" :disabled="sending || !draft.trim()" @click="$emit('send')">发送</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import ChatMessage from '../ChatMessage.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sending: Boolean,
  draft: { type: String, default: '' },   // v-model:draft
})
defineEmits(['update:draft', 'send', 'goto'])

const threadEl = ref(null)
function scrollToBottom() {
  nextTick(() => {
    if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
  })
}
// 新消息进来就滚到底——父组件不用再操心"发完要滚"
watch(() => props.messages.length, scrollToBottom)
defineExpose({ scrollToBottom })
</script>
