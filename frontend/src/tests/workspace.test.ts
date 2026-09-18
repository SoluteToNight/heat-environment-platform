import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '../services/api';
import { demoProducts, demoScene } from '../services/demo';
import type { EnvironmentView } from '../services/contracts';
import { useWorkspace } from '../stores/workspace';

vi.mock('../services/api', () => ({
  api: Object.fromEntries(['scenes', 'scene', 'layers', 'catalog', 'session', 'publicRecords', 'view', 'status', 'point', 'series'].map(name => [name, vi.fn()])),
  isDemo: true,
  aborted: (error: unknown) => error instanceof DOMException && error.name === 'AbortError',
  errorMessage: (error: unknown) => error instanceof Error ? error.message : String(error),
  ApiError: class extends Error {},
}));

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<Value>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

function frame(id: string): EnvironmentView {
  return { view_id: id, requested_time: demoProducts[0]!.times[0]!, mode: 'historical', expires_at: new Date(Date.now() + 3600_000).toISOString(), items: [] };
}

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  vi.stubGlobal('location', { search: '', href: 'http://localhost/' });
  vi.stubGlobal('history', { replaceState: vi.fn() });
  vi.stubGlobal('document', { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() });
  vi.mocked(api.scenes).mockResolvedValue({ items: [demoScene], next_cursor: null });
  vi.mocked(api.scene).mockResolvedValue(demoScene);
  vi.mocked(api.layers).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(api.catalog).mockResolvedValue({ products: demoProducts });
  vi.mocked(api.session).mockResolvedValue({ authenticated: false, user: null });
  vi.mocked(api.publicRecords).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(api.view).mockResolvedValue(frame('initial'));
  vi.mocked(api.status).mockResolvedValue({ release_ids: ['v1'], freshness: 'fresh', update_state: 'idle' });
});

afterEach(() => { useWorkspace().dispose(); vi.unstubAllGlobals(); });

describe('environment workspace lifecycle', () => {
  it('finishes loading and retains a retryable error when the scene API fails', async () => {
    vi.mocked(api.scenes).mockRejectedValueOnce(new Error('场景服务不可用'));
    const store = useWorkspace();
    await store.initialize();
    expect(store.loading).toBe(false);
    expect(store.scene).toBeNull();
    expect(store.error).toBe('场景服务不可用');
    await store.initialize();
    expect(store.scene?.scene_id).toBe(demoScene.scene_id);
    expect(store.error).toBe('');
  });
  it('restores a supported public time link without putting it into UGC filters', async () => {
    const time = demoProducts[0]!.times[2]!;
    location.search = `?variable=relative_humidity&time=${encodeURIComponent(time)}`;
    const store = useWorkspace();
    await store.initialize();
    await store.switchView();
    expect(store.timeSelection).toEqual({ kind: 'at', time });
    expect(store.committedVariable).toBe('relative_humidity');
    expect(store.ugcHours).toBe(24);
    expect(api.view).toHaveBeenCalledWith(demoScene.scene_id, expect.any(Array), { kind: 'at', time }, expect.any(AbortSignal));
  });

  it('explains unsupported link times and selects now', async () => {
    location.search = '?time=invalid';
    const store = useWorkspace();
    await store.initialize();
    expect(store.timeSelection).toEqual({ kind: 'now' });
    expect(store.message).toContain('不在当前产品的可用范围');
  });

  it('disposes a late prepared frame without overwriting the newer view', async () => {
    const store = useWorkspace();
    await store.initialize();
    const pending = deferred<{ commit: () => void; dispose: () => void }>();
    const stale = { commit: vi.fn(), dispose: vi.fn() };
    const latest = { commit: vi.fn(), dispose: vi.fn() };
    const preparing = deferred<void>();
    store.bindRenderer(async view => {
      if (view.view_id === 'old') { preparing.resolve(); return pending.promise; }
      return latest;
    });
    vi.mocked(api.view).mockResolvedValueOnce(frame('old')).mockResolvedValueOnce(frame('new'));
    const first = store.switchView();
    await preparing.promise;
    await store.chooseVariable('relative_humidity');
    pending.resolve(stale);
    await first;
    expect(store.view?.view_id).toBe('new');
    expect(store.committedProduct?.unit).toBe('%');
    expect(stale.commit).not.toHaveBeenCalled();
    expect(stale.dispose).toHaveBeenCalledOnce();
    expect(latest.commit).toHaveBeenCalledOnce();
  });

  it('keeps the prior view and legend when the next render fails', async () => {
    const store = useWorkspace();
    await store.initialize();
    await store.switchView();
    store.bindRenderer(async () => { throw new Error('图层加载失败'); });
    await store.chooseVariable('relative_humidity');
    expect(store.view?.view_id).toBe('initial');
    expect(store.committedProduct?.unit).toBe('°C');
    expect(store.error).toBe('图层加载失败');
    expect(store.busy).toBe(false);
  });

  it('ignores errors from an abandoned scene request', async () => {
    const store = useWorkspace();
    const oldScene = deferred<typeof demoScene>();
    vi.mocked(api.scene).mockReturnValueOnce(oldScene.promise);
    const first = store.selectScene('old');
    await store.selectScene(demoScene.scene_id);
    oldScene.reject(new Error('旧场景失败'));
    await first;
    expect(store.scene?.scene_id).toBe(demoScene.scene_id);
    expect(store.error).toBe('');
  });

  it('refreshes catalog on release changes while retaining a fixed historical view', async () => {
    const store = useWorkspace();
    await store.initialize();
    await store.switchView({ kind: 'at', time: demoProducts[0]!.times[0]! });
    await store.refreshStatus();
    vi.mocked(api.status).mockResolvedValue({ release_ids: ['v2'], freshness: 'fresh', update_state: 'idle' });
    const updated = { ...demoProducts[0]!, times: ['2026-09-18T00:00:00Z'] };
    vi.mocked(api.catalog).mockResolvedValue({ products: [updated] });
    await store.refreshStatus();
    expect(store.times).toEqual(updated.times);
    expect(api.view).toHaveBeenCalledTimes(1);
    expect(store.message).toContain('新的环境数据');
  });

  it('rebuilds an expired view even without a new release', async () => {
    const store = useWorkspace();
    await store.initialize();
    await store.switchView();
    store.view = { ...store.view!, expires_at: new Date(Date.now() - 1000).toISOString() };
    vi.mocked(api.view).mockResolvedValue(frame('renewed'));
    await store.refreshStatus();
    expect(store.view?.view_id).toBe('renewed');
    expect(store.expired).toBe(false);
  });

  it('plays smoothly through available time sequence without stalling', async () => {
    vi.useFakeTimers();
    const store = useWorkspace();
    await store.initialize();
    await store.switchView({ kind: 'at', time: demoProducts[0]!.times[0]! });
    expect(store.playing).toBe(false);

    vi.mocked(api.view).mockImplementation(async (_s, _v, sel) => {
      const t = sel.kind === 'at' ? sel.time : 'now';
      return frame(`frame_${t}`);
    });

    store.play();
    expect(store.playing).toBe(true);

    // Initial immediate tick advances to times[1]
    await vi.advanceTimersByTimeAsync(0);
    expect(store.timeSelection).toEqual({ kind: 'at', time: demoProducts[0]!.times[1]! });

    // Next timer tick advances to times[2]
    await vi.advanceTimersByTimeAsync(1500);
    expect(store.timeSelection).toEqual({ kind: 'at', time: demoProducts[0]!.times[2]! });

    store.stop();
    expect(store.playing).toBe(false);
    vi.useRealTimers();
  });

  it('loops back to the start of the time series when reaching the end during playback', async () => {
    vi.useFakeTimers();
    const store = useWorkspace();
    await store.initialize();
    const lastIndex = demoProducts[0]!.times.length - 1;
    await store.switchView({ kind: 'at', time: demoProducts[0]!.times[lastIndex]! });

    vi.mocked(api.view).mockImplementation(async (_s, _v, sel) => {
      const t = sel.kind === 'at' ? sel.time : 'now';
      return frame(`frame_${t}`);
    });

    store.play();
    expect(store.playing).toBe(true);

    // Should wrap around to times[0]
    await vi.advanceTimersByTimeAsync(0);
    expect(store.timeSelection).toEqual({ kind: 'at', time: demoProducts[0]!.times[0]! });

    store.stop();
    vi.useRealTimers();
  });
});

