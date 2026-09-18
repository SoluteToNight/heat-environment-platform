<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue';
import AppDialog from './AppDialog.vue';
import AppIcon from './AppIcon.vue';
import { api, errorMessage } from '../services/api';
import { useWorkspace } from '../stores/workspace';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const store = useWorkspace();
const exportType = ref<'environment_table' | 'my_check_ins' | 'public_check_ins'>('environment_table');
const fileFormat = ref<'csv' | 'geojson'>('csv');
const loading = ref(false);
const error = ref('');
const activeExportId = ref('');
const exportStatus = ref<'idle' | 'processing' | 'ready' | 'failed'>('idle');
const downloadUrl = ref('');

let pollTimer: ReturnType<typeof setInterval> | undefined;

function reset() {
  clearInterval(pollTimer);
  loading.value = false;
  error.value = '';
  activeExportId.value = '';
  exportStatus.value = 'idle';
  downloadUrl.value = '';
}

async function startExport() {
  reset();
  if (exportType.value === 'my_check_ins' && !store.session.authenticated) {
    error.value = '导出个人打卡记录需要先登录账号。';
    return;
  }
  if (exportType.value === 'environment_table' && !store.view) {
    error.value = '请先选择场景环境视图再导出气象数据。';
    return;
  }

  loading.value = true;
  const key = crypto.randomUUID();
  const body = {
    export_type: exportType.value,
    file_format: fileFormat.value,
    scene_id: store.scene?.scene_id || 'scene_shanghai',
    view_id: exportType.value === 'environment_table' ? store.view?.view_id : undefined,
  };

  try {
    const res = await api.export(body, key);
    activeExportId.value = res.export_id;
    exportStatus.value = 'processing';
    pollStatus(res.export_id);
  } catch (err) {
    error.value = errorMessage(err);
    loading.value = false;
    exportStatus.value = 'failed';
  }
}

function pollStatus(exportId: string) {
  pollTimer = setInterval(async () => {
    try {
      const res = await api.exportStatus(exportId);
      if (res.status === 'succeeded') {
        clearInterval(pollTimer);
        exportStatus.value = 'ready';
        loading.value = false;
        downloadUrl.value = res.download_url || api.downloadUrl(exportId);
      } else if (res.status === 'failed' || res.status === 'cancelled') {
        clearInterval(pollTimer);
        exportStatus.value = 'failed';
        loading.value = false;
        error.value = '导出任务执行失败，请稍后重试。';
      }
    } catch (err) {
      clearInterval(pollTimer);
      loading.value = false;
      exportStatus.value = 'failed';
      error.value = errorMessage(err);
    }
  }, 1200);
}

onBeforeUnmount(() => {
  clearInterval(pollTimer);
});
</script>

<template>
  <AppDialog :open="open" title="数据导出中心" @close="emit('close')">
    <div class="space-y-6">
      <section>
        <label class="field-label mb-2">导出类型</label>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <button
            type="button"
            class="button justify-start text-xs"
            :class="exportType === 'environment_table' ? 'border-accent bg-green-soft font-semibold text-accent' : ''"
            @click="exportType = 'environment_table'"
          >
            <AppIcon name="temperature" :size="16" />
            环境气象表格
          </button>
          <button
            type="button"
            class="button justify-start text-xs"
            :class="exportType === 'my_check_ins' ? 'border-accent bg-green-soft font-semibold text-accent' : ''"
            @click="exportType = 'my_check_ins'"
          >
            <AppIcon name="pin" :size="16" />
            我的打卡记录
          </button>
          <button
            type="button"
            class="button justify-start text-xs"
            :class="exportType === 'public_check_ins' ? 'border-accent bg-green-soft font-semibold text-accent' : ''"
            @click="exportType = 'public_check_ins'"
          >
            <AppIcon name="layers" :size="16" />
            公开体感数据集
          </button>
        </div>
      </section>

      <section>
        <label class="field-label mb-2">文件格式</label>
        <div class="flex gap-4">
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input v-model="fileFormat" type="radio" value="csv" name="fileFormat" />
            <span>CSV (UTF-8-SIG · 带防注入保护)</span>
          </label>
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input v-model="fileFormat" type="radio" value="geojson" name="fileFormat" />
            <span>GeoJSON (空间矢量格式)</span>
          </label>
        </div>
      </section>

      <div v-if="exportStatus === 'processing'" class="rounded-xl border border-line bg-canvas p-4 text-center">
        <span class="loader mx-auto mb-2" />
        <p class="text-sm font-medium">后台任务处理中...</p>
        <p class="text-xs text-muted mt-1">正在打包空间与时序数据，请稍候</p>
      </div>

      <div v-if="exportStatus === 'ready'" class="rounded-xl border border-line bg-green-soft p-4 text-center">
        <div class="mx-auto mb-2 grid size-10 place-items-center rounded-full bg-accent text-white">
          <AppIcon name="check" :size="20" />
        </div>
        <h4 class="text-sm font-semibold text-accent">导出文件已生成就绪！</h4>
        <p class="text-xs text-muted mt-1 mb-4">有效期 24 小时，下载后请妥善保存</p>
        <a
          :href="downloadUrl"
          target="_blank"
          download
          class="button-primary mx-auto inline-flex items-center gap-2 text-sm"
        >
          <AppIcon name="download" :size="16" />
          立即下载文件
        </a>
      </div>

      <div v-if="error" class="status-warning" role="alert">
        {{ error }}
      </div>

      <div class="flex items-center justify-between border-t border-line pt-4">
        <span class="text-xs text-muted">
          {{ exportType === 'environment_table' ? '绑定当前所选视图时间与版本' : '导出经过隐私脱敏的有效记录' }}
        </span>
        <div class="flex gap-2">
          <button type="button" class="button" @click="emit('close')">关闭</button>
          <button
            type="button"
            class="button-primary"
            :disabled="loading || exportStatus === 'processing'"
            @click="startExport"
          >
            <AppIcon name="download" :size="16" />
            开始导出
          </button>
        </div>
      </div>
    </div>
  </AppDialog>
</template>
