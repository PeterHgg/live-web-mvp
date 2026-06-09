<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue';
import { cleanupPlayer, playStream, type StreamType } from './player';

interface Platform {
  key: string;
  name: string;
}

interface ResolvedStream {
  type: StreamType;
  quality: string;
  quality_label: string;
  url: string;
}

interface ResolveResponse {
  platform: string;
  platform_name: string;
  anchor_name?: string;
  title?: string;
  is_live: boolean;
  live_url?: string;
  streams: ResolvedStream[];
  raw: Record<string, unknown>;
}

interface SearchRoom {
  platform: string;
  platform_name: string;
  room_id: string;
  title: string;
  anchor_name: string;
  live_url: string;
  is_live: boolean;
  cover?: string;
  avatar?: string;
  watching?: string;
  area?: string;
}

interface SearchResponse {
  keyword: string;
  platform: string;
  results: SearchRoom[];
  errors: Record<string, string>;
}

interface DanmakuMessage {
  id: number;
  user_name: string;
  message: string;
  color?: string;
  top: number;
  duration: number;
}

type Page = 'home' | 'player';

const platforms = ref<Platform[]>([]);
const platform = ref('auto');
const target = ref('');
const quality = ref('OD');
const loading = ref(false);
const playing = ref(false);
const error = ref('');
const result = ref<ResolveResponse | null>(null);
const selectedIndex = ref(0);
const videoRef = ref<HTMLVideoElement | null>(null);
const page = ref<Page>('home');
const danmakuEnabled = ref(true);
const danmakuStatus = ref('弹幕未连接');
const danmakuMessages = ref<DanmakuMessage[]>([]);
const danmakuLog = ref<DanmakuMessage[]>([]);
const danmakuFontSize = ref(20);
const danmakuFontWeight = ref(700);
const danmakuOpacity = ref(1);
const danmakuSpeed = ref(1);
const danmakuArea = ref(60);
const danmakuDensity = ref(8);
const danmakuMaxOnScreen = ref(30);
const onlineCount = ref<number | null>(null);
let danmakuSocket: WebSocket | null = null;
let danmakuId = 0;
let stallTimer: number | null = null;
let stallStartedAt = 0;

const searchKeyword = ref('');
const searchPlatform = ref('all');
const searchLoading = ref(false);
const searchResults = ref<SearchRoom[]>([]);
const searchErrors = ref<Record<string, string>>({});

const selectedStream = computed(() => result.value?.streams[selectedIndex.value]);
const danmakuBaseDuration = computed(() => 10 / danmakuSpeed.value);
const danmakuLineCount = computed(() => Math.max(1, Math.floor(danmakuArea.value / 8)));
const danmakuMinGap = computed(() => 1000 / danmakuDensity.value);
let lastDanmakuAt = 0;

async function loadPlatforms() {
  const response = await fetch('/api/platforms');
  platforms.value = await response.json();
}

async function searchRooms() {
  const keyword = searchKeyword.value.trim();
  if (!keyword) return;

  error.value = '';
  searchLoading.value = true;
  searchResults.value = [];
  searchErrors.value = {};

  try {
    if (isLiveUrl(keyword)) {
      searchResults.value = [await buildUrlResult(keyword)];
      return;
    }

    const params = new URLSearchParams({
      keyword,
      platform: searchPlatform.value,
      page: '1',
      page_size: '20',
    });
    const response = await fetch(`/api/search?${params.toString()}`);
    const data: SearchResponse | { detail?: string } = await response.json();
    if (!response.ok) {
      throw new Error('detail' in data ? data.detail || '搜索失败' : '搜索失败');
    }
    searchResults.value = (data as SearchResponse).results || [];
    const errors = (data as SearchResponse).errors || {};
    searchErrors.value = searchResults.value.length ? {} : errors;
    if (!searchResults.value.length && !Object.keys(errors).length) {
      error.value = '没有搜索到直播间';
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    searchLoading.value = false;
  }
}

async function resolveRoom() {
  error.value = '';
  loading.value = true;
  playing.value = false;
  result.value = null;
  selectedIndex.value = 0;
  if (videoRef.value) cleanupPlayer(videoRef.value);

  try {
    const response = await fetch('/api/resolve', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        target: target.value.trim(),
        platform: platform.value === 'auto' ? null : platform.value,
        quality: quality.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || '解析失败');
    }
    result.value = data;
    if (!data.is_live) {
      error.value = '主播当前未开播';
      return;
    }
    if (!data.streams?.length) {
      error.value = '没有拿到可播放的直播流；可尝试降低清晰度或换平台/房间';
      return;
    }
    if (data.platform === 'huya') {
      const flvIndex = data.streams.findIndex((stream: ResolvedStream) => stream.type === 'flv');
      if (flvIndex >= 0) selectedIndex.value = flvIndex;
    }
    page.value = 'player';
    await nextTick();
    await playSelected();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

async function playSelected() {
  const video = videoRef.value;
  const streams = result.value?.streams || [];
  const firstStream = selectedStream.value;
  if (!video || !firstStream) return;
  error.value = '';

  const candidates = [
    firstStream,
    ...streams.filter((stream) => stream.url !== firstStream.url),
  ];
  const failures: string[] = [];

  for (const stream of candidates) {
    try {
      await playStream(video, {
        url: stream.url,
        type: stream.type,
      });
      selectedIndex.value = streams.findIndex((item) => item.url === stream.url);
      playing.value = true;
      startStallWatch();
      connectDanmaku();
      return;
    } catch (err) {
      failures.push(`${stream.type.toUpperCase()}：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  playing.value = false;
  error.value = `播放失败：${failures.join('；')}。这不是必须开启后端代理；当前策略是浏览器直连，不占用服务器视频带宽。该直播源可能被浏览器协议、CORS 或防盗链限制。`;
}

function chooseStream(index: number) {
  selectedIndex.value = index;
  void playSelected();
}

function startStallWatch() {
  stopStallWatch();
  const video = videoRef.value;
  if (!video) return;
  stallStartedAt = video.currentTime;
  stallTimer = window.setInterval(() => {
    const current = selectedStream.value;
    const streams = result.value?.streams || [];
    const videoEl = videoRef.value;
    if (!videoEl || !playing.value || videoEl.paused || videoEl.readyState < 2) return;

    const stuck = Math.abs(videoEl.currentTime - stallStartedAt) < 0.2;
    stallStartedAt = videoEl.currentTime;
    if (!stuck || current?.type !== 'hls') return;

    const flvIndex = streams.findIndex((stream) => stream.type === 'flv');
    if (flvIndex >= 0 && flvIndex !== selectedIndex.value) {
      error.value = 'HLS 直连播放卡顿，已自动切换到 FLV 线路尝试。';
      selectedIndex.value = flvIndex;
      void playSelected();
    }
  }, 5000);
}

function stopStallWatch() {
  if (stallTimer !== null) {
    window.clearInterval(stallTimer);
    stallTimer = null;
  }
}

function stop() {
  stopStallWatch();
  if (videoRef.value) cleanupPlayer(videoRef.value);
  closeDanmaku();
  playing.value = false;
}

function backHome() {
  stop();
  page.value = 'home';
}

function isLiveUrl(value: string) {
  return /^https?:\/\//i.test(value) || /(douyu\.com|huya\.com)/i.test(value);
}

function detectPlatformFromUrl(value: string) {
  const text = value.toLowerCase();
  if (text.includes('douyu.com')) return 'douyu';
  if (text.includes('huya.com')) return 'huya';
  return 'auto';
}

async function buildUrlResult(value: string): Promise<SearchRoom> {
  const liveUrl = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  const platformKey = detectPlatformFromUrl(liveUrl);
  const roomId = extractRoomId(liveUrl);
  const fallback: SearchRoom = {
    platform: platformKey,
    platform_name: platformKey === 'auto' ? '自动识别' : platformName(platformKey),
    room_id: roomId || liveUrl,
    title: '识别到直播间链接',
    anchor_name: liveUrl,
    live_url: liveUrl,
    is_live: false,
    area: 'URL 识别',
  };

  if (platformKey === 'auto') return fallback;

  const searched = roomId ? await searchRoomById(platformKey, roomId, liveUrl) : null;
  if (searched) return { ...searched, area: searched.area || 'URL 识别' };

  try {
    const response = await fetch('/api/resolve', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ target: liveUrl, platform: platformKey, quality: quality.value }),
    });
    const data: ResolveResponse | { detail?: string } = await response.json();
    if (!response.ok) return fallback;
    const resolved = data as ResolveResponse;
    const enriched = await searchRoomByText(
      resolved.platform || platformKey,
      resolved.anchor_name || resolved.title || '',
      resolved.live_url || liveUrl,
      roomId,
    );
    if (enriched) return enriched;

    return {
      ...fallback,
      platform: resolved.platform,
      platform_name: resolved.platform_name || fallback.platform_name,
      title: resolved.title || fallback.title,
      anchor_name: resolved.anchor_name || fallback.anchor_name,
      live_url: resolved.live_url || liveUrl,
      is_live: resolved.is_live,
    };
  } catch {
    return fallback;
  }
}

function extractRoomId(value: string) {
  try {
    const url = new URL(value);
    return url.pathname.split('/').filter(Boolean).pop() || '';
  } catch {
    return '';
  }
}

async function searchRoomById(platformKey: string, roomId: string, liveUrl: string) {
  return searchRoomByText(platformKey, roomId, liveUrl, roomId);
}

async function searchRoomByText(platformKey: string, keyword: string, liveUrl: string, roomId = '') {
  if (!keyword.trim()) return null;
  const params = new URLSearchParams({
    keyword,
    platform: platformKey,
    page: '1',
    page_size: '10',
  });
  const response = await fetch(`/api/search?${params.toString()}`);
  if (!response.ok) return null;
  const data = (await response.json()) as SearchResponse;
  const normalizedUrl = liveUrl.replace(/\/$/, '');
  return (
    data.results.find((item) => roomId && item.room_id === roomId)
    || data.results.find((item) => item.live_url.replace(/\/$/, '') === normalizedUrl)
    || data.results[0]
    || null
  );
}

async function playSearchRoom(room: SearchRoom) {
  target.value = room.live_url;
  platform.value = room.platform;
  await nextTick();
  await resolveRoom();
}

function platformName(key: string) {
  return platforms.value.find((item) => item.key === key)?.name || key;
}

function danmakuUrl() {
  const current = result.value;
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const params = new URLSearchParams({
    target: current?.live_url || target.value,
    platform: current?.platform || platform.value,
  });
  return `${wsProtocol}//${window.location.host}/api/danmaku?${params.toString()}`;
}

function connectDanmaku() {
  closeDanmaku();
  danmakuMessages.value = [];
  danmakuLog.value = [];
  onlineCount.value = null;
  const current = result.value;
  if (!danmakuEnabled.value || !current?.is_live) {
    danmakuStatus.value = danmakuEnabled.value ? '弹幕未连接' : '弹幕已关闭';
    return;
  }

  danmakuStatus.value = '弹幕连接中...';
  const socket = new WebSocket(danmakuUrl());
  danmakuSocket = socket;

  socket.onopen = () => {
    danmakuStatus.value = '弹幕已连接';
  };
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data) as {
      type: string;
      user_name?: string;
      message?: string;
      color?: string;
      online?: number;
    };
    if (data.type === 'chat' && data.message) {
      pushDanmaku(data.user_name || '匿名用户', data.message, data.color);
    } else if (data.type === 'online') {
      onlineCount.value = data.online ?? null;
    } else if (data.type === 'status') {
      danmakuStatus.value = data.message || '弹幕已连接';
    } else if (data.type === 'error') {
      danmakuStatus.value = data.message || '弹幕连接失败';
    }
  };
  socket.onerror = () => {
    danmakuStatus.value = '弹幕连接失败';
  };
  socket.onclose = () => {
    if (danmakuSocket === socket) {
      danmakuSocket = null;
      if (danmakuEnabled.value) danmakuStatus.value = '弹幕已断开';
    }
  };
}

function closeDanmaku() {
  if (danmakuSocket) {
    danmakuSocket.close();
    danmakuSocket = null;
  }
  danmakuMessages.value = [];
  danmakuLog.value = [];
  danmakuStatus.value = danmakuEnabled.value ? '弹幕未连接' : '弹幕已关闭';
}

function toggleDanmaku() {
  danmakuEnabled.value = !danmakuEnabled.value;
  if (danmakuEnabled.value && playing.value) {
    connectDanmaku();
  } else {
    closeDanmaku();
  }
}

function pushDanmaku(userName: string, message: string, color?: string) {
  const id = ++danmakuId;
  const item = {
    id,
    user_name: userName,
    message,
    color,
    top: 4 + (id % danmakuLineCount.value) * 8,
    duration: danmakuBaseDuration.value + (id % 3),
  };
  const now = window.performance.now();
  if (now - lastDanmakuAt >= danmakuMinGap.value && danmakuMessages.value.length < danmakuMaxOnScreen.value) {
    danmakuMessages.value.push(item);
    lastDanmakuAt = now;
  }
  danmakuLog.value.unshift(item);
  if (danmakuMessages.value.length > 80) {
    danmakuMessages.value.splice(0, danmakuMessages.value.length - 80);
  }
  if (danmakuLog.value.length > 30) {
    danmakuLog.value.splice(30);
  }
  window.setTimeout(() => {
    danmakuMessages.value = danmakuMessages.value.filter((item) => item.id !== id);
  }, 12000);
}

loadPlatforms().catch((err) => {
  error.value = `平台列表加载失败：${err instanceof Error ? err.message : String(err)}`;
});

onBeforeUnmount(() => {
  if (videoRef.value) cleanupPlayer(videoRef.value);
  closeDanmaku();
});
</script>

<template>
  <main class="page">
    <section class="hero">
      <div>
        <p class="eyebrow">Live Web MVP</p>
        <h1>网页多平台直播播放器</h1>
        <p class="subtitle">搜索斗鱼、虎牙直播间，点击结果进入播放页。</p>
      </div>
      <div class="status" :class="{ online: playing }">{{ playing ? '播放中' : '待播放' }}</div>
    </section>

    <template v-if="page === 'home'">
      <section class="card search-card">
        <div class="search-title">
          <div>
            <p class="eyebrow">Search</p>
            <h2>搜索或粘贴直播间链接</h2>
          </div>
          <span v-if="searchResults.length" class="count">{{ searchResults.length }} 个结果</span>
        </div>

        <div class="search-row">
          <label>
            搜索范围
            <select v-model="searchPlatform">
              <option value="all">全部平台</option>
              <option v-for="item in platforms" :key="item.key" :value="item.key">{{ item.name }}</option>
            </select>
          </label>
          <label class="search-input">
            关键词 / 主播名 / 直播间 URL
            <input
              v-model="searchKeyword"
              placeholder="例如：旭旭宝宝、英雄联盟、https://www.douyu.com/3637778"
              @keydown.enter="searchRooms"
            />
          </label>
          <label class="quality-select">
            清晰度
            <select v-model="quality">
              <option value="OD">原画</option>
              <option value="UHD">超清</option>
              <option value="HD">高清</option>
              <option value="SD">标清</option>
              <option value="LD">流畅</option>
            </select>
          </label>
          <button class="primary search-button" :disabled="searchLoading || !searchKeyword.trim()" @click="searchRooms">
            {{ searchLoading ? '处理中...' : '搜索 / 识别' }}
          </button>
        </div>

        <div v-if="!searchResults.length && Object.keys(searchErrors).length" class="search-errors">
          <span>没有搜索到直播间，部分平台返回错误：</span>
          <span v-for="(message, key) in searchErrors" :key="key">
            {{ platformName(key) }}：{{ message }}
          </span>
        </div>

        <div v-if="searchResults.length" class="result-list">
          <article v-for="room in searchResults" :key="`${room.platform}-${room.room_id}`" class="result-item">
            <img v-if="room.cover || room.avatar" class="cover" :src="room.cover || room.avatar" alt="" />
            <div v-else class="cover placeholder">{{ room.platform_name }}</div>
            <div class="result-main">
              <div class="result-meta">
                <span class="platform-pill">{{ room.platform_name }}</span>
                <span class="live-dot" :class="{ off: !room.is_live }">{{ room.is_live ? '直播中' : '待识别' }}</span>
                <span v-if="room.area">{{ room.area }}</span>
                <span v-if="room.watching">{{ room.watching }}</span>
              </div>
              <h3>{{ room.title || '未获取标题' }}</h3>
              <p>{{ room.anchor_name || '未知主播' }}</p>
            </div>
            <button :disabled="loading" @click="playSearchRoom(room)">进入直播间</button>
          </article>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="player-header">
        <button @click="backHome">返回搜索</button>
        <div v-if="result">
          <p class="eyebrow">{{ result.platform_name }}</p>
          <h2>{{ result.title || '未获取标题' }}</h2>
          <p>主播：{{ result.anchor_name || '未知' }}</p>
        </div>
      </section>

      <section class="player-shell">
        <video ref="videoRef" controls playsinline autoplay muted></video>
        <div v-if="danmakuEnabled" class="danmaku-layer">
          <span
            v-for="item in danmakuMessages"
            :key="item.id"
            class="danmaku-item"
            :style="{
              top: `${item.top}%`,
              color: item.color || '#ffffff',
              fontSize: `${danmakuFontSize}px`,
              fontWeight: danmakuFontWeight,
              opacity: danmakuOpacity,
              animationDuration: `${item.duration}s`,
            }"
          >
            {{ item.user_name }}：{{ item.message }}
          </span>
        </div>
      </section>

      <section v-if="result" class="card info-card">
        <div class="room-info">
          <div>
            <p v-if="result.live_url">房间：<a :href="result.live_url" target="_blank">{{ result.live_url }}</a></p>
            <p>
              弹幕：{{ danmakuStatus }}
              <span v-if="onlineCount !== null"> · 人气 {{ onlineCount }}</span>
            </p>
          </div>
          <span class="live-badge" :class="{ off: !result.is_live }">{{ result.is_live ? '直播中' : '未开播' }}</span>
        </div>

        <div class="danmaku-toolbar">
          <button :class="{ active: danmakuEnabled }" @click="toggleDanmaku">
            {{ danmakuEnabled ? '关闭弹幕' : '开启弹幕' }}
          </button>
          <button @click="pushDanmaku('测试', '这是一条本地测试弹幕')">测试弹幕</button>
          <span>斗鱼、虎牙弹幕已接入。如果顶部没看到滚动弹幕，可看下方弹幕列表。</span>
        </div>

        <div v-if="danmakuEnabled" class="danmaku-settings">
          <label>
            字体 {{ danmakuFontSize }}px
            <input v-model.number="danmakuFontSize" type="range" min="14" max="36" step="1" />
          </label>
          <label>
            粗细 {{ danmakuFontWeight }}
            <input v-model.number="danmakuFontWeight" type="range" min="400" max="900" step="100" />
          </label>
          <label>
            透明度 {{ Math.round(danmakuOpacity * 100) }}%
            <input v-model.number="danmakuOpacity" type="range" min="0.2" max="1" step="0.05" />
          </label>
          <label>
            速度 {{ danmakuSpeed.toFixed(1) }}x
            <input v-model.number="danmakuSpeed" type="range" min="0.5" max="2" step="0.1" />
          </label>
          <label>
            显示区域 {{ danmakuArea }}%
            <input v-model.number="danmakuArea" type="range" min="20" max="100" step="10" />
          </label>
          <label>
            密度 {{ danmakuDensity }} 条/秒
            <input v-model.number="danmakuDensity" type="range" min="1" max="20" step="1" />
          </label>
          <label>
            同屏上限 {{ danmakuMaxOnScreen }} 条
            <input v-model.number="danmakuMaxOnScreen" type="range" min="5" max="60" step="5" />
          </label>
        </div>

        <div v-if="danmakuEnabled" class="danmaku-log">
          <p v-if="!danmakuLog.length">暂未收到弹幕。冷门房间可能长时间没人发言，可以换热门房间测试。</p>
          <p v-for="item in danmakuLog" :key="`log-${item.id}`">
            <strong>{{ item.user_name }}</strong>：{{ item.message }}
          </p>
        </div>

        <div v-if="result.streams.length" class="streams">
          <button
            v-for="(stream, index) in result.streams"
            :key="stream.type + stream.url"
            :class="{ active: index === selectedIndex }"
            @click="chooseStream(index)"
          >
            {{ stream.type.toUpperCase() }} · {{ stream.quality_label || stream.quality }}
          </button>
        </div>

        <details>
          <summary>查看解析结果</summary>
          <pre>{{ JSON.stringify(result.raw, null, 2) }}</pre>
        </details>
      </section>
    </template>

    <p v-if="error" class="error">{{ error }}</p>
  </main>
</template>
