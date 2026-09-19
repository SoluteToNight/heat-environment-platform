<script setup lang="ts">
import { onMounted, ref } from 'vue';

// 每个实例自成一体：独立的透视倾斜 + 独立浮动动画，互不影响
const props = withDefaults(defineProps<{ max?: number; floatClass?: string }>(), { max: 5, floatClass: '' });

const style = ref({ transform: 'perspective(1200px) rotateX(0deg) rotateY(0deg)' });
let enabled = false;

function move(event: MouseEvent) {
  if (!enabled) return;
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  const px = (event.clientX - rect.left) / rect.width - 0.5;
  const py = (event.clientY - rect.top) / rect.height - 0.5;
  style.value = { transform: `perspective(1200px) rotateX(${(-py * props.max).toFixed(2)}deg) rotateY(${(px * props.max * 1.2).toFixed(2)}deg)` };
}

function leave() {
  style.value = { transform: 'perspective(1200px) rotateX(0deg) rotateY(0deg)' };
}

onMounted(() => {
  enabled = window.matchMedia('(hover: hover) and (pointer: fine)').matches && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
});
</script>

<template>
  <div class="[perspective:1200px]">
    <div
      class="transition-transform duration-300 ease-out will-change-transform"
      :style="style"
      @mousemove="move"
      @mouseleave="leave"
    >
      <div :class="floatClass">
        <slot />
      </div>
    </div>
  </div>
</template>
