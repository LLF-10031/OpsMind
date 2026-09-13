<template>
  <div class="assistant-wrap">
    <div class="assistant-side">
      <el-tabs v-model="sideTab" stretch class="side-tabs">
        <el-tab-pane label="会话" name="sessions">
          <div class="side-head">
            <span>会话</span>
            <el-button size="small" type="primary" plain @click="newSession">新建</el-button>
          </div>
          <div class="side-list">
            <div
              v-for="s in sessions"
              :key="s.id"
              class="side-item"
              :class="{ active: s.id === currentId }"
              @click="switchSession(s.id)"
            >
              <span class="side-name">{{ s.title || '未命名会话' }}</span>
              <span class="side-ops">
                <el-button size="small" link type="primary" @click.stop="openRename(s)">重命名</el-button>
                <el-button size="small" link type="danger" @click.stop="removeSession(s)">删除</el-button>
              </span>
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="知识库" name="kb">
          <div class="side-head">
            <span>知识库文档</span>
            <el-button size="small" @click="loadDocs">刷新</el-button>
          </div>
          <div class="side-list">
            <div v-for="d in docOptions" :key="d.id" class="side-item" @click="openDocText(d.id)">
              <span class="side-name">{{ d.name }}</span>
              <span class="side-ops"><el-button size="small" link type="primary">读全文</el-button></span>
            </div>
            <div v-if="!docOptions.length" class="side-empty">暂无文档</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div class="assistant-main">
      <div class="chat-list">
        <div v-if="currentId && hasMore" class="load-more">
          <el-button size="small" link type="primary" :loading="loadingMore" @click="loadMore">加载更早消息</el-button>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="chat-item" :class="m.role">
          <div class="chat-role">{{ m.role === 'user' ? '我' : '助手' }}</div>
          <div class="chat-content">
            <div v-if="m.role === 'bot'" class="chat-kb" v-show="m.kb_used">
              参考知识库：{{ m.kb_used }}
            </div>
            <div class="chat-text mono">{{ m.content }}</div>
          </div>
        </div>
        <div v-if="streaming" class="chat-item bot">
          <div class="chat-role">助手</div>
          <div class="chat-content"><span class="stream-cursor">▍</span></div>
        </div>
      </div>

      <div class="chat-input">
        <div class="chat-docs">
          <span class="chat-docs-label">知识库文档</span>
          <el-select
            v-model="selectedDocIds"
            multiple
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="勾选才检索（未勾选本次不查库）"
            style="flex: 1"
          >
            <el-option
              v-for="d in docOptions"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </div>
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          placeholder="询问主机/脚本/报告等，Ctrl+Enter 发送"
          @keydown.ctrl.enter.prevent="send"
        />
        <div class="chat-actions">
          <el-button :disabled="!currentId" @click="openSaveMemory">保存为记忆</el-button>
          <span v-if="streaming" class="chat-tip">助手回复中…</span>
          <el-button type="primary" :disabled="!input.trim() || streaming" :loading="streaming" @click="send">发送</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="memoryVisible" title="保存为记忆" width="520px">
      <el-form label-width="80px">
        <el-form-item label="主题">
          <el-input v-model="memoryForm.topic" placeholder="留空则用摘要作为主题" />
        </el-form-item>
        <el-form-item label="摘要" required>
          <el-input v-model="memoryForm.summary" type="textarea" :rows="6" placeholder="将这段内容存为 Episodic 记忆" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="memoryVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingMemory" @click="handleSaveMemory">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="docTextVisible" :title="`知识库全文 · ${docText.name || ''}`" width="820" top="6vh">
      <el-tabs v-model="docTextTab">
        <el-tab-pane label="规范化内容" name="normalized">
          <pre class="doc-preview">{{ docText.normalized_md || '（无内容）' }}</pre>
        </el-tab-pane>
        <el-tab-pane label="原始原文" name="raw">
          <pre class="doc-preview">{{ docText.raw_content || '（无原文）' }}</pre>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="docTextVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listSessions, createSession, updateSession, deleteSession, listMessages,
  saveMemory
} from '../api/chatSessions'
import { chatStreamUrl } from '../api/chat'
import { postEventStream } from '../utils/sse'
import { listDocuments, getDocumentContent } from '../api/documents'

const sessions = ref([])
const currentId = ref(null)
const messages = ref([])
const input = ref('')
const streaming = ref(false)
const docOptions = ref([])
const selectedDocIds = ref([])
const hasMore = ref(false)
const loadingMore = ref(false)
let controller = null

const sideTab = ref('sessions')
const docTextVisible = ref(false)
const docTextTab = ref('normalized')
const docText = ref({})

const memoryVisible = ref(false)
const savingMemory = ref(false)
const memoryForm = reactive({ topic: '', summary: '' })

async function loadSessions() {
  sessions.value = await listSessions()
}

async function newSession() {
  currentId.value = null
  messages.value = []
  input.value = ''
  hasMore.value = false
}

async function switchSession(id) {
  if (streaming.value) return
  currentId.value = id
  const res = await listMessages(id)
  messages.value = res.items
  hasMore.value = res.items.length >= 50
}

async function loadMore() {
  if (!currentId.value || loadingMore.value) return
  const oldest = messages.value.find((m) => m.id)
  if (!oldest) return
  loadingMore.value = true
  try {
    const res = await listMessages(currentId.value, { before_id: oldest.id, limit: 50 })
    messages.value = [...res.items, ...messages.value]
    hasMore.value = res.items.length >= 50
  } catch {
    // 拦截器已提示
  } finally {
    loadingMore.value = false
  }
}

async function removeSession(s) {
  await ElMessageBox.confirm(`删除会话「${s.title || '未命名'}」？`, '确认', { type: 'warning' })
  await deleteSession(s.id)
  if (s.id === currentId.value) newSession()
  loadSessions()
}

async function openRename(s) {
  try {
    const { value } = await ElMessageBox.prompt('会话标题', '重命名', {
      inputValue: s.title || '', inputPattern: /.+/, inputErrorMessage: '标题不能为空'
    })
    await updateSession(s.id, { title: value })
    s.title = value
    ElMessage.success('已重命名')
  } catch {
    // 取消
  }
}

function openSaveMemory() {
  const session = sessions.value.find((s) => s.id === currentId.value)
  const lastBot = [...messages.value].reverse().find((m) => m.role === 'bot' && m.content && m.content.trim())
  memoryForm.topic = session?.title || ''
  memoryForm.summary = lastBot ? lastBot.content.slice(0, 800) : ''
  memoryVisible.value = true
}

async function handleSaveMemory() {
  const summary = memoryForm.summary.trim()
  if (!summary) {
    ElMessage.warning('摘要必填')
    return
  }
  savingMemory.value = true
  try {
    const res = await saveMemory(currentId.value, {
      topic: memoryForm.topic.trim() || summary,
      summary
    })
    ElMessage.success(`已保存为记忆 #${res.id}`)
    memoryVisible.value = false
  } catch {
    // BAD_REQUEST/FILTERED 已由拦截器提示
  } finally {
    savingMemory.value = false
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  let sessionId = currentId.value
  if (!sessionId) {
    const created = await createSession({ title: text.slice(0, 20) })
    sessionId = created.session_id
    currentId.value = sessionId
    loadSessions()
  }
  messages.value.push({ role: 'user', content: text, kb_used: null })
  messages.value.push({ role: 'bot', content: '', kb_used: null })
  streaming.value = true
  controller = new AbortController()
  let done = false
  try {
    const onEvent = (type, data) => {
      if (type === 'token') {
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'bot') last.content += data?.text ?? ''
      } else if (type === 'kb_ready') {
        const last = messages.value[messages.value.length - 1]
        if (last) {
          last.kb_used = !selectedDocIds.value.length
            ? '未勾选文档，本次未检索'
            : data && data.found
              ? '已检索知识库'
              : '未检索到知识库'
        }
      } else if (type === 'done') {
        done = true
      } else if (type === 'error') {
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'bot') last.content = (last.content || '') + (data?.message || '')
      }
    }
    await postEventStream(
      chatStreamUrl(),
      { message: text, session_id: sessionId, document_ids: selectedDocIds.value },
      { onEvent, signal: controller.signal }
    )
  } catch (e) {
    if (e.name !== 'AbortError' && !done) {
      ElMessage.error(e.message || '对话失败，请重试')
      messages.value[messages.value.length - 1].content = (messages.value[messages.value.length - 1].content || '') || e.message
    }
  } finally {
    streaming.value = false
    controller = null
  }
}

async function loadDocs() {
  try {
    docOptions.value = await listDocuments()
  } catch {
    docOptions.value = []
  }
}

async function openDocText(id) {
  docTextVisible.value = true
  docTextTab.value = 'normalized'
  docText.value = {}
  try {
    docText.value = await getDocumentContent(id)
  } catch (e) {
    ElMessage.error(e.message || '加载全文失败')
  }
}

onMounted(() => {
  loadSessions()
  loadDocs()
})
onBeforeUnmount(() => controller && controller.abort())
</script>

<style scoped>
.assistant-wrap {
  display: flex;
  gap: 14px;
  height: calc(100vh - 60px);
}
.assistant-side {
  width: 220px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
}
.side-tabs {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.side-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
}
.side-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.side-empty {
  padding: 12px;
  font-size: 12px;
  color: #c0c4cc;
  text-align: center;
}
.doc-preview {
  max-height: 62vh;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}
.side-head {
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #ebeef5;
  font-weight: 600;
  font-size: 13px;
}
.side-list {
  flex: 1;
  overflow: auto;
}
.side-item {
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid #f2f3f5;
}
.side-item:hover {
  background: #f5f7fa;
}
.side-item.active {
  background: #ecf5ff;
  color: #409eff;
}
.side-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.side-ops {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.assistant-main {
  flex: 1;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
}
.chat-list {
  flex: 1;
  overflow: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.load-more {
  text-align: center;
}
.chat-item {
  max-width: 78%;
}
.chat-item.user {
  align-self: flex-end;
}
.chat-item.bot {
  align-self: flex-start;
}
.chat-role {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.chat-content {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.7;
}
.chat-item.user .chat-content {
  background: #ecf5ff;
}
.chat-kb {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 4px;
}
.mono {
  white-space: pre-wrap;
}
.stream-cursor {
  color: #409eff;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.chat-input {
  border-top: 1px solid #ebeef5;
  padding: 12px;
}
.chat-docs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.chat-docs-label {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
.chat-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.chat-tip {
  font-size: 12px;
  color: #e6a23c;
}
</style>
