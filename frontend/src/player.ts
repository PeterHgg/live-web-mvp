import Hls from 'hls.js';
import mpegts from 'mpegts.js';

export type StreamType = 'hls' | 'flv' | 'native';

export interface PlayOptions {
  url: string;
  type: StreamType;
}

let hls: Hls | null = null;
let flvPlayer: mpegts.Player | null = null;

export function cleanupPlayer(video: HTMLVideoElement) {
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
  const sourceUrl = options.url;

  if (options.type === 'hls') {
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = sourceUrl;
      await video.play();
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
    await video.play();
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
        enableStashBuffer: false,
        liveBufferLatencyChasing: true,
      },
    );
    flvPlayer.attachMediaElement(video);
    flvPlayer.load();
    await video.play();
    return;
  }

  video.src = sourceUrl;
  await video.play();
}
