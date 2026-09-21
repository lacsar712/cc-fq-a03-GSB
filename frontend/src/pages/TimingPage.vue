<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">耗时与超时门禁台</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="loadAll" :loading="loading" />
    </div>

    <!-- 超时上限配置：运维可改，审计员只读 -->
    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Actor 超时上限配置(ms)</div>
        <q-banner v-if="!isOps" rounded class="bg-grey-2 text-dark q-mb-sm">
          审计员只读:可查看清单与耗时,不能修改超时配置。
        </q-banner>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left">Actor</th>
              <th class="text-left">超时上限 (ms)</th>
              <th class="text-left">最近修改</th>
              <th v-if="isOps" class="text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in configs" :key="c.actor_name">
              <td>{{ c.actor_name }}</td>
              <td>
                <q-input
                  v-if="isOps"
                  v-model.number="editTimeouts[c.actor_name]"
                  type="number"
                  dense
                  outlined
                  min="0"
                  max="3600000"
                  style="max-width: 160px"
                />
                <span v-else>{{ c.timeout_ms }}</span>
              </td>
              <td>{{ c.updated_by }} · {{ fmtTime(c.updated_at) }}</td>
              <td v-if="isOps">
                <q-btn
                  dense
                  color="primary"
                  label="保存"
                  :loading="saving[c.actor_name]"
                  @click="saveConfig(c.actor_name)"
                />
              </td>
            </tr>
          </tbody>
        </q-markup-table>
        <div class="text-caption text-grey-7 q-mt-sm">
          提示:0 ms 表示"任何非零耗时即判超时",可用于门禁自测。耗时与超时判定均由服务端在流水线运行时计算落库。
        </div>
      </q-card-section>
    </q-card>

    <!-- 最近 N 个成功作业各阶段平均耗时 -->
    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="text-subtitle1">最近成功作业各阶段平均耗时</div>
          <q-space />
          <q-select
            v-model="windowSize"
            :options="windowOptions"
            dense
            outlined
            label="统计窗口 N"
            emit-value
            map-options
            style="width: 150px"
            @update:model-value="loadSummary"
          />
        </div>
        <div class="text-caption text-grey-7 q-mb-sm">
          窗口内成功作业数:{{ summary.job_count }}
        </div>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left">阶段</th>
              <th class="text-left">平均耗时 (ms)</th>
              <th class="text-left">最大耗时 (ms)</th>
              <th class="text-left">样本数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in summary.stages" :key="s.actor_name">
              <td>{{ s.actor_name }}</td>
              <td>{{ fmtMs(s.avg_duration_ms) }}</td>
              <td>{{ fmtMs(s.max_duration_ms) }}</td>
              <td>{{ s.sample_size }}</td>
            </tr>
            <tr v-if="!summary.stages.length">
              <td colspan="4" class="text-grey-6">暂无成功作业耗时数据</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
    </q-card>

    <!-- 单作业四阶段耗时 -->
    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">单作业四阶段耗时</div>
        <div class="row q-col-gutter-sm items-center q-mb-sm">
          <q-select
            v-model="selectedJobId"
            :options="jobOptions"
            label="选择作业"
            dense
            outlined
            emit-value
            map-options
            class="col-12 col-sm-6"
            @update:model-value="loadJobTiming"
          />
          <q-btn
            v-if="selectedJobId"
            flat
            color="primary"
            label="查看作业详情"
            :to="`/jobs/${selectedJobId}`"
          />
        </div>
        <q-markup-table v-if="jobTiming" flat dense>
          <thead>
            <tr>
              <th class="text-left">阶段</th>
              <th class="text-left">状态</th>
              <th class="text-left">耗时 (ms)</th>
              <th class="text-left">超时上限 (ms)</th>
              <th class="text-left">是否超限</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in jobTiming.stages"
              :key="s.actor_name"
              :class="s.timed_out ? 'bg-red-1' : ''"
            >
              <td>{{ s.actor_name }}</td>
              <td>{{ statusLabel(s.status) }}</td>
              <td>{{ fmtMs(s.duration_ms) }}</td>
              <td>{{ s.timeout_ms_limit ?? '—' }}</td>
              <td>
                <q-badge v-if="s.timed_out" color="negative">超限</q-badge>
                <span v-else class="text-grey-6">否</span>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td class="text-weight-bold">合计</td>
              <td></td>
              <td class="text-weight-bold">{{ fmtMs(jobTiming.total_duration_ms) }}</td>
              <td colspan="2">
                <q-badge v-if="jobTiming.timed_out" color="negative">该作业已超时</q-badge>
              </td>
            </tr>
          </tfoot>
        </q-markup-table>
        <div v-else class="text-grey-6">请选择作业查看各阶段耗时</div>
      </q-card-section>
    </q-card>

    <!-- 超时清单 -->
    <q-card flat bordered>
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">超时清单</div>
        <q-markup-table flat dense>
          <thead>
            <tr>
              <th class="text-left">作业</th>
              <th class="text-left">样例</th>
              <th class="text-left">状态</th>
              <th class="text-left">提交人</th>
              <th class="text-left">超限阶段</th>
              <th class="text-left">完成时间</th>
              <th class="text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in timeoutJobs" :key="t.job_id">
              <td>#{{ t.job_id }}</td>
              <td>{{ t.sample_name }}</td>
              <td>
                <q-badge :color="statusColor(t.status)">{{ statusLabel(t.status) }}</q-badge>
              </td>
              <td>{{ t.created_by }}</td>
              <td>
                <q-badge
                  v-for="s in t.exceeded_stages"
                  :key="s.actor_name"
                  color="negative"
                  class="q-mr-xs"
                >
                  {{ s.actor_name }} {{ s.duration_ms }}ms / 上限 {{ s.timeout_ms_limit }}ms
                </q-badge>
              </td>
              <td>{{ fmtTime(t.finished_at) }}</td>
              <td>
                <q-btn dense flat color="primary" label="详情" :to="`/jobs/${t.job_id}`" />
              </td>
            </tr>
            <tr v-if="!timeoutJobs.length">
              <td colspan="7" class="text-grey-6">暂无超时作业</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import {
  getJobTiming,
  getTimingSummary,
  getTimeoutConfigs,
  listJobs,
  listTimeoutJobs,
  updateTimeoutConfig,
} from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const $q = useQuasar()

const loading = ref(false)
const configs = ref([])
const editTimeouts = reactive({})
const saving = reactive({})
const summary = ref({ window: 0, job_count: 0, stages: [] })
const windowSize = ref(20)
const windowOptions = [
  { label: '最近 5 个', value: 5 },
  { label: '最近 10 个', value: 10 },
  { label: '最近 20 个', value: 20 },
  { label: '最近 50 个', value: 50 },
  { label: '最近 100 个', value: 100 },
]
const jobs = ref([])
const selectedJobId = ref(null)
const jobTiming = ref(null)
const timeoutJobs = ref([])

const isOps = computed(() => auth.role === 'bioops')

const jobOptions = computed(() =>
  jobs.value.map((j) => ({
    label: `#${j.id} ${j.sample_name}(${statusLabel(j.status)}${j.timed_out ? ' · 超时' : ''})`,
    value: j.id,
  })),
)

function statusLabel(s) {
  return { pending: '排队中', running: '运行中', success: '成功', failed: '失败' }[s] || s
}

function statusColor(s) {
  return { pending: 'grey', running: 'info', success: 'positive', failed: 'negative' }[s] || 'grey'
}

// 仅做展示格式化,不做任何耗时推算:数值全部来自服务端
function fmtMs(v) {
  return v === null || v === undefined ? '—' : `${v}`
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function loadConfigs() {
  configs.value = await getTimeoutConfigs()
  configs.value.forEach((c) => {
    editTimeouts[c.actor_name] = c.timeout_ms
  })
}

async function loadSummary() {
  summary.value = await getTimingSummary(windowSize.value)
}

async function loadJobs() {
  jobs.value = await listJobs()
  if (!selectedJobId.value && jobs.value.length) {
    selectedJobId.value = jobs.value[0].id
    await loadJobTiming()
  }
}

async function loadJobTiming() {
  if (!selectedJobId.value) return
  jobTiming.value = await getJobTiming(selectedJobId.value)
}

async function loadTimeouts() {
  timeoutJobs.value = await listTimeoutJobs()
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadConfigs(), loadSummary(), loadJobs(), loadTimeouts()])
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

async function saveConfig(actorName) {
  const val = Number(editTimeouts[actorName])
  if (!Number.isFinite(val) || val < 0) {
    $q.notify({ type: 'warning', message: '超时上限需为不小于 0 的整数毫秒' })
    return
  }
  saving[actorName] = true
  try {
    await updateTimeoutConfig(actorName, Math.trunc(val))
    $q.notify({ type: 'positive', message: `${actorName} 超时上限已保存` })
    await loadConfigs()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '保存失败' })
  } finally {
    saving[actorName] = false
  }
}

onMounted(loadAll)
</script>
