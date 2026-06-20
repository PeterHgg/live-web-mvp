import Hls from 'hls.js';
import mpegts from 'mpegts.js';

export type StreamType = 'hls' | 'flv' | 'native';

export interface PlayOptions {
  url: string;
  type: StreamType;
  bufferDuration: number;
  onBufferProgress?: (bufferedSeconds: number, targetSeconds: number) => void;
}

let hls: Hls | null = null;
let flvPlayer: mpegts.Player | null = null;
let playToken = 0;

export function cleanupPlayer(video: HTMLVideoElement) {
  playToken += 1;
  if (hls) {
    hls.destroy();
    hls = null;
  }
  if (flvPlayer) {
    flvPlayer.destroy();
    flvPlayer = null;
  }
  video.pause();
  video.removeAttribute('src');
  video.load();
}

export async function playStream(video: HTMLVideoElement, options: PlayOptions) {
  cleanupPlayer(video);
  const token = playToken;
  const sourceUrl = options.url;

  if (options.type === 'hls') {
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = sourceUrl;
      await safePlay(video, token);
      return;
    }
    if (!Hls.isSupported()) {
      throw new Error('当前浏览器不支持 HLS 播放');
    }
    const targetLatency = options.bufferDuration;
    hls = new Hls({
      lowLatencyMode: targetLatency <= 3,
      backBufferLength: 30,
      liveSyncDuration: targetLatency > 0 ? targetLatency : undefined,
      liveMaxLatencyDuration: targetLatency > 0 ? targetLatency + 6 : undefined,
    });
    hls.loadSource(sourceUrl);
    hls.attachMedia(video);
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        cleanup();
        reject(new Error('加载 HLS 媒体源超时'));
      }, 6000);
      const cleanup = () => {
        window.clearTimeout(timer);
        hls?.off(Hls.Events.MANIFEST_PARSED, onReady);
        hls?.off(Hls.Events.ERROR, onError);
      };
      const onReady = () => {
        cleanup();
        resolve();
      };
      const onError = (_event: string, data: { fatal?: boolean; details?: string; type?: string }) => {
        if (data.fatal) {
          cleanup();
          reject(new Error(data.details || data.type));
        }
      };
      hls?.once(Hls.Events.MANIFEST_PARSED, onReady);
      hls?.on(Hls.Events.ERROR, onError);
    });
    await safePlay(video, token);
    return;
  }

  if (options.type === 'flv') {
    if (!mpegts.isSupported()) {
      throw new Error('当前浏览器不支持 FLV/MPEG-TS 播放');
    }
    const targetLatency = options.bufferDuration;
    flvPlayer = mpegts.createPlayer(
      {
        type: 'flv',
        isLive: true,
        url: sourceUrl,
      },
      {
        enableWorker: true,
        enableStashBuffer: true,
        stashInitialSize: 384 * 1024,
        liveBufferLatencyChasing: targetLatency > 0,
        liveBufferLatencyMinRemain: targetLatency > 0 ? targetLatency : undefined,
        liveBufferLatencyMaxLatency: targetLatency > 0 ? targetLatency + 1.5 : undefined,
      },
    );
    flvPlayer.attachMediaElement(video);
    flvPlayer.load();
    await waitForCanPlay(video, token);

    // Wait for buffer to build up if needed
    if (targetLatency > 0) {
      const timeoutMs = (targetLatency + 6) * 1000;
      const start = window.performance.now();
      await new Promise<void>((resolve) => {
        const check = () => {
          if (token !== playToken) {
            resolve();
            return;
          }
          const now = window.performance.now();
          if (now - start >= timeoutMs) {
            options.onBufferProgress?.(targetLatency, targetLatency);
            resolve();
            return;
          }
          const buffered = video.buffered;
          if (buffered.length > 0) {
            const bufferEnd = buffered.end(buffered.length - 1);
            const current = video.currentTime;
            const bufferLen = Math.max(0, bufferEnd - current);
            options.onBufferProgress?.(bufferLen, targetLatency);
            if (bufferLen >= targetLatency) {
              resolve();
              return;
            }
          } else {
            options.onBufferProgress?.(0, targetLatency);
          }
          window.setTimeout(check, 100);
        };
        check();
      });
    }

    await safePlay(video, token);
    return;
  }

  video.src = sourceUrl;
  await safePlay(video, token);
}

async function waitForCanPlay(video: HTMLVideoElement, token: number) {
  if (video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) return;
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error('等待直播源数据超时'));
    }, 6000);
    const cleanup = () => {
      window.clearTimeout(timer);
      video.removeEventListener('canplay', onReady);
      video.removeEventListener('loadeddata', onReady);
      video.removeEventListener('error', onError);
    };
    const onReady = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error(video.error?.message || '直播源加载失败'));
    };
    video.addEventListener('canplay', onReady, { once: true });
    video.addEventListener('loadeddata', onReady, { once: true });
    video.addEventListener('error', onError, { once: true });
    window.setTimeout(() => {
      if (token !== playToken) {
        cleanup();
        resolve();
      }
    });
  });
}

async function safePlay(video: HTMLVideoElement, token: number) {
  try {
    await video.play();
  } catch (err) {
    if (token !== playToken) return;
    if (isInterruptedPlayError(err)) {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      if (token !== playToken) return;
      await video.play();
      return;
    }
    throw err;
  }
}

function isInterruptedPlayError(err: unknown) {
  return err instanceof DOMException
    && err.name === 'AbortError'
    && err.message.includes('interrupted');
}
