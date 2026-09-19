import type { Directive } from 'vue';

// 进入视口后从 0 滚动到目标值；reduced-motion 直接显示终值
function easeOutCubic(p: number) {
  return 1 - Math.pow(1 - p, 3);
}

export const vCount: Directive<HTMLElement, number> = {
  mounted(el, binding) {
    const target = binding.value;
    if (!Number.isFinite(target)) return;
    if (typeof IntersectionObserver === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = String(target);
      return;
    }
    el.textContent = '0';
    const io = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      io?.disconnect();
      const start = performance.now();
      const duration = 1300;
      const step = (now: number) => {
        const progress = Math.min(1, (now - start) / duration);
        el.textContent = String(Math.round(target * easeOutCubic(progress)));
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }, { threshold: 0.5 });
    io.observe(el);
  },
};
