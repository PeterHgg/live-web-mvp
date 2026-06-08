import Hls from 'hls.js';
import mpegts from 'mpegts.js';

export type StreamType = 'hls' | 'flv' | 'native';

export interface PlayOptions {
  url: string;
  type: StreamType;
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
    hls = new Hls({
      lowLatencyMode: true,
      backBufferLength: 30,
    });
    hls.loadSource(sourceUrl);
    hls.attachMedia(video);
    await new Promise<void>((resolve, reject) => {
      const onReady = () => resolve();
      const onError = (_event: string, data: { fatal?: boolean; details?: string; type?: string }) => {
        if (data.fatal) reject(new Error(data.details || data.type));
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
        liveBufferLatencyChasing: true,
      },
    );
    flvPlayer.attachMediaElement(video);
    flvPlayer.load();
    await waitForCanPlay(video, token);
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
    }, 10000);
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
