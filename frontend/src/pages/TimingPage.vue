<template>
  <q-page class="page-pad timing-page">
    <div class="row items-center q-mb-md">
      <div class="text-h5">耗时台 · 超时门禁</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="loadAll" :loading="loading" />
    </div>

    <q-banner dense rounded class="bg-blue-1 text-blue-9 q-mb-md">
      所有阶段耗时（毫秒）、平均耗时与超时判定均由<strong class="q-mx-xs">服务端</strong>计算返回，
      前端仅做展示；超时上限落库，作业运行时按当时配置快照判定。
    </q-banner>

    <!-- 1. 超时门禁配置 -->
    <div class="text-subtitle1 q-mb-sm">
      ① 各 Actor 超时上限（毫秒）
      <span class="text-caption text-grey-7 q-ml-sm">
        {{ auth.role === 'bioops' ? '可编辑，保存后对后续作业生效' : '审计员只读，不可修改' }}
      </span>
    </div>
    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left" style="width: 60px">顺序</th>
              <th class="text-left">Actor</th>
              <th class="text-left" style="width: 220px">超时上限 (ms)</th>
              <th class="text-left">最近更新人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in configs" :key="c.actor_name">
              <td>{{ actorOrder(c.actor_name) }}</td>
              <td class="text-weight-medium">{{ c.actor_name }}</td>
              <td>
                <q-input
                  v-model.number="draft[c.actor_name]"
                  type="number"
                  dense
                  outlined
                  :readonly="auth.role !== 'bioops'"
                  :disable="auth.role !== 'bioops'"
                  input-class="text-weight-bold"
                  :rules="[(v) => Number(v) >= 1 || '需为正整数毫秒']"
                />
              </td>
              <td class="text-grey-8">{{ c.updated_by }}<span class="q-ml-sm text-grey-6">{{ fmt(c.updated_at) }}</span></td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
      <q-card-actions v-if="auth.role === 'bioops'" align="right">
        <q-btn
          color="primary"
          label="保存超时配置"
          :loading="saving"
          :disable="!configDirty"
          @click="saveConfig"
        />
      </q-card-actions>
    </q-card>

    <!-- 2. 最近成功作业平均耗时 -->
    <div class="row items-center q-mb-sm">
      <div class="text-subtitle1">② 最近成功作业各阶段平均耗时</div>
      <q-space />
      <span class="text-caption text-grey-7 q-mr-sm">取最近</span>
      <q-btn-toggle
        v-model="windowSize"
        dense
        toggle-color="primary"
        :options="[5, 10, 20, 50].map((n) => ({ label: `${n}`, value: n }))"
        @update:model-value="loadOverview"
      />
    </div>
    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <div class="text-caption text-grey-7 q-mb-sm">
          实际纳入 {{ overview.job_count }} 个成功作业
          （#{{ overview.recent_success_job_ids.slice().reverse().join(', #') || '—' }}）
        </div>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left" style="width: 60px">顺序</th>
              <th class="text-left">Actor</th>
              <th class="text-right">平均 (ms)</th>
              <th class="text-right">最小 (ms)</th>
              <th class="text-right">最大 (ms)</th>
              <th class="text-right">样本数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in overview.averages" :key="a.actor_name">
              <td>{{ a.stage_order }}</td>
              <td class="text-weight-medium">{{ a.actor_name }}</td>
              <td class="text-right text-weight-bold">{{ a.avg_duration_ms }}</td>
              <td class="text-right">{{ a.min_duration_ms ?? '—' }}</td>
              <td class="text-right">{{ a.max_duration_ms ?? '—' }}</td>
              <td class="text-right">{{ a.sample_count }}</td>
            </tr>
            <tr v-if="!overview.job_count">
              <td colspan="6" class="text-grey-6 text-center q-pa-md">暂无成功作业</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
    </q-card>

    <!-- 3. 单作业四阶段耗时 -->
    <div class="row items-center q-mb-sm">
      <div class="text-subtitle1">③ 单作业四阶段毫秒耗时</div>
      <q-space />
      <q-input
        v-model.number="queryJobId"
        type="number"
        dense
        outlined
        label="作业 ID"
        style="width: 140px"
        @keyup.enter="loadJobTiming"
      >
        <template #append>
          <q-btn dense flat icon="search" @click="loadJobTiming" :loading="timingLoading" />
        </template>
      </q-input>
    </div>
    <q-card flat bordered class="q-mb-lg">
      <q-card-section v-if="jobTiming">
        <div class="row items-center q-mb-sm">
          <q-badge :color="statusColor(jobTiming.status)" class="text-caption">
            {{ statusLabel(jobTiming.status) }}
          </q-badge>
          <q-badge v-if="jobTiming.timed_out" color="negative" class="q-ml-sm">
            作业超时
          </q-badge>
          <span class="q-ml-sm text-grey-8">{{ jobTiming.sample_name }}</span>
          <q-space />
          <span class="text-caption text-grey-7">
            四阶段合计 {{ jobTiming.total_duration_ms ?? '—' }} ms
          </span>
          <q-btn dense flat color="primary" label="进详情" :to="`/jobs/${jobTiming.job_id}`" />
        </div>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left" style="width: 60px">顺序</th>
              <th class="text-left">Actor</th>
              <th class="text-left">状态</th>
              <th class="text-right">耗时 (ms)</th>
              <th class="text-right">上限 (ms)</th>
              <th class="text-left">门禁</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in jobTiming.stages" :key="s.actor_name" :class="{ 'row-timeout': s.timed_out }">
              <td>{{ s.stage_order }}</td>
              <td class="text-weight-medium">{{ s.actor_name }}</td>
              <td>
                <q-badge :color="stageColor(s.status)">{{ statusLabel(s.status) }}</q-badge>
              </td>
              <td class="text-right text-weight-bold">{{ s.duration_ms ?? '—' }}</td>
              <td class="text-right">{{ s.timeout_ms ?? '—' }}</td>
              <td>
                <q-badge v-if="s.timed_out" color="negative">
                  超限 {{ s.duration_ms }} &gt; {{ s.timeout_ms }}
                </q-badge>
                <q-badge v-else-if="s.status === 'success'" color="positive">未超限</q-badge>
                <span v-else class="text-grey-6">—</span>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
      <q-card-section v-else class="text-grey-6">
        输入作业 ID 查询其四阶段服务端耗时；也可直接从下方超时清单点“详情”。
      </q-card-section>
    </q-card>

    <!-- 4. 超时清单 -->
    <div class="text-subtitle1 q-mb-sm">
      ④ 超时作业清单
      <span class="text-caption text-grey-7 q-ml-sm">行内标出超限阶段（{{ timeoutJobs.length }}）</span>
    </div>
    <q-card flat bordered>
      <q-card-section>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left">作业</th>
              <th class="text-left">样例</th>
              <th class="text-left">提交人</th>
              <th class="text-left">超限阶段</th>
              <th class="text-left">时间</th>
              <th class="text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="j in timeoutJobs" :key="j.id">
              <td>
                <q-badge color="negative">#{{ j.id }}</q-badge>
                <q-badge :color="statusColor(j.status)" class="q-ml-sm">{{ statusLabel(j.status) }}</q-badge>
              </td>
              <td>{{ j.sample_name }}</td>
              <td>{{ j.created_by }}</td>
              <td>
                <div v-for="s in j.over_stages" :key="s.actor_name">
                  <q-badge color="negative" class="text-caption">
                    {{ s.actor_name }}：{{ s.duration_ms }} / {{ s.timeout_ms }} ms
                  </q-badge>
                </div>
              </td>
              <td class="text-grey-8">{{ fmt(j.created_at) }}</td>
              <td>
                <q-btn
                  dense
                  flat
                  color="primary"
                  label="详情"
                  :to="`/jobs/${j.id}`"
                  @click="queryJobId = j.id"
                />
              </td>
            </tr>
            <tr v-if="!timeoutJobs.length">
              <td colspan="6" class="text-grey-6 text-center q-pa-md">暂无超时作业</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import {
  getJobTiming,
  getTimeoutConfigs,
  getTimeoutJobs,
  getTimingOverview,
  updateTimeoutConfigs,
} from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const $q = useQuasar()

const loading = ref(false)
const saving = ref(false)
const configs = ref([])
const draft = reactive({})
const windowSize = ref(10)
const overview = ref({
  success_window: 10,
  job_count: 0,
  averages: [],
  recent_success_job_ids: [],
})
const timeoutJobs = ref([])
const queryJobId = ref(null)
const jobTiming = ref(null)
const timingLoading = ref(false)

const ACTOR_ORDER = ['ParseActor', 'QualityHistActor', 'NContentActor', 'ReportActor']
function actorOrder(name) {
  const i = ACTOR_ORDER.indexOf(name)
  return i >= 0 ? i : name
}

const configDirty = ref(false)

async function loadConfig() {
  const rows = await getTimeoutConfigs()
  configs.value = rows
  rows.forEach((r) => {
    if (!(r.actor_name in draft)) draft[r.actor_name] = r.timeout_ms
  })
}

async function loadOverview() {
  overview.value = await getTimingOverview(windowSize.value)
}

async function loadTimeouts() {
  timeoutJobs.value = await getTimeoutJobs()
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadOverview(), loadTimeouts()])
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载耗时台失败' })
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  const items = configs.value.map((c) => ({
    actor_name: c.actor_name,
    timeout_ms: Number(draft[c.actor_name]),
  }))
  if (items.some((i) => !Number.isInteger(i.timeout_ms) || i.timeout_ms < 1)) {
    $q.notify({ type: 'warning', message: '超时上限必须是正整数毫秒' })
    return
  }
  saving.value = true
  try {
    configs.value = await updateTimeoutConfigs(items)
    configDirty.value = false
    $q.notify({ type: 'positive', message: '超时配置已保存' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '保存失败' })
  } finally {
    saving.value = false
  }
}

async function loadJobTiming() {
  if (!queryJobId.value) return
  timingLoading.value = true
  try {
    jobTiming.value = await getJobTiming(Number(queryJobId.value))
  } catch (e) {
    jobTiming.value = null
    $q.notify({ type: 'negative', message: e.message || '查询失败' })
  } finally {
    timingLoading.value = false
  }
}

function statusLabel(s) {
  return (
    {
      pending: '排队中',
      running: '运行中',
      success: '成功',
      failed: '失败',
      timeout: '超时',
      skipped: '跳过',
    }[s] || s
  )
}
function statusColor(s) {
  return {
    pending: 'grey',
    running: 'info',
    success: 'positive',
    failed: 'negative',
    timeout: 'negative',
    skipped: 'warning',
  }[s] || 'grey'
}
function stageColor(s) {
  return statusColor(s)
}
function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : ''
}

watch(
  draft,
  () => {
    configDirty.value = configs.value.some(
      (c) => Number(draft[c.actor_name]) !== c.timeout_ms,
    )
  },
  { deep: true },
)

onMounted(loadAll)
</script>

<style scoped>
.row-timeout {
  background: rgba(244, 67, 54, 0.08);
}
</style>
