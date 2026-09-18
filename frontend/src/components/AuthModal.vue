<script setup lang="ts">
import { ref } from 'vue';
import AppDialog from './AppDialog.vue';
import AppIcon from './AppIcon.vue';
import { api, errorMessage } from '../services/api';
import { useWorkspace } from '../stores/workspace';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; success: [] }>();

const store = useWorkspace();
const username = ref('user_test');
const password = ref('user123456');
const loading = ref(false);
const error = ref('');

function fillTestUser(u: string, p: string) {
  username.value = u;
  password.value = p;
  error.value = '';
}

async function handleLogin() {
  if (!username.value || !password.value) {
    error.value = '请填写账号和密码';
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    const session = await api.login(username.value, password.value);
    store.session = session;
    emit('success');
    emit('close');
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function handleLogout() {
  loading.value = true;
  try {
    await api.logout();
    store.session = { authenticated: false, user: null };
    emit('close');
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AppDialog :open="open" :title="store.session.authenticated ? '用户会话' : '登录热环境平台'" @close="emit('close')">
    <div v-if="store.session.authenticated" class="space-y-5">
      <div class="rounded-xl border border-line bg-canvas p-5 text-center">
        <div class="mx-auto grid size-12 place-items-center rounded-full bg-green-soft text-accent">
          <AppIcon name="pin" :size="24" />
        </div>
        <h3 class="mt-3 text-lg font-semibold">{{ store.session.user?.alias || store.session.user?.user_id }}</h3>
        <div class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs border border-line text-muted">
          <span>账号：{{ store.session.user?.user_id }}</span>
          <span class="text-ink font-medium">· 已登录</span>
        </div>
      </div>
      <button class="button text-terracotta w-full justify-center" :disabled="loading" @click="handleLogout">
        <AppIcon name="close" :size="16" />
        退出登录
      </button>
    </div>

    <form v-else class="space-y-5" @submit.prevent="handleLogin">
      <div>
        <label class="field-label">账号
          <input v-model="username" class="input" required placeholder="例如：user_test" />
        </label>
      </div>
      <div>
        <label class="field-label">密码
          <input v-model="password" type="password" class="input" required placeholder="请输入密码" />
        </label>
      </div>

      <div class="rounded-lg border border-line bg-canvas p-3">
        <p class="text-xs text-muted mb-2 font-medium">快速体验测试账号：</p>
        <div class="flex gap-2">
          <button type="button" class="button text-xs py-1 px-2.5" @click="fillTestUser('user_test', 'user123456')">
            测试用户 (user_test)
          </button>
          <button type="button" class="button text-xs py-1 px-2.5" @click="fillTestUser('admin_test', 'admin123456')">
            管理员 (admin_test)
          </button>
        </div>
      </div>

      <div v-if="error" class="status-warning" role="alert">
        {{ error }}
      </div>

      <div class="flex justify-end gap-3 pt-2">
        <button type="button" class="button" @click="emit('close')">取消</button>
        <button type="submit" class="button-primary" :disabled="loading">
          <span v-if="loading" class="loader size-3.5 border-white/30 border-t-white" />
          {{ loading ? '登录中...' : '确认登录' }}
        </button>
      </div>
    </form>
  </AppDialog>
</template>
