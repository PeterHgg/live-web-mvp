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

const searchKeyword = ref('');
const searchPlatform = ref('all');
const searchLoading = ref(false);
const searchResults = ref<SearchRoom[]>([]);
const searchErrors = ref<Record<string, string>>({});

const selectedStream = computed(() => result.value?.streams[selectedIndex.value]);

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
  const stream = selectedStream.value;
  if (!video || !stream) return;
  error.value = '';
  try {
    await playStream(video, {
      url: stream.url,
      type: stream.type,
    });
    playing.value = true;
  } catch (err) {
    playing.value = false;
    error.value = `播放失败：${err instanceof Error ? err.message : String(err)}。当前已关闭后端代理，直播源需要浏览器可直连且允许跨域。`;
  }
}

function chooseStream(index: number) {
  selectedIndex.value = index;
  void playSelected();
}

function stop() {
  if (videoRef.value) cleanupPlayer(videoRef.value);
  playing.value = false;
}

function example(value: string, platformKey = 'auto') {
  target.value = value;
  platform.value = platformKey;
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

loadPlatforms().catch((err) => {
  error.value = `平台列表加载失败：${err instanceof Error ? err.message : String(err)}`;
});

onBeforeUnmount(() => {
  if (videoRef.value) cleanupPlayer(videoRef.value);
});
</script>

<template>
  <main class="page">
    <section class="hero">
      <div>
        <p class="eyebrow">Live Web MVP</p>
        <h1>网页多平台直播播放器</h1>
        <p class="subtitle">搜索斗鱼、虎牙、B站、抖音直播间，点击结果即可自动解析播放。</p>
      </div>
      <div class="status" :class="{ online: playing }">{{ playing ? '播放中' : '待播放' }}</div>
    </section>

    <section class="card search-card">
      <div class="search-title">
        <div>
          <p class="eyebrow">Search</p>
          <h2>聚合搜索直播间</h2>
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
          关键词 / 主播名
          <input
            v-model="searchKeyword"
            placeholder="例如：旭旭宝宝、英雄联盟、王者荣耀"
            @keydown.enter="searchRooms"
          />
        </label>
        <button class="primary search-button" :disabled="searchLoading || !searchKeyword.trim()" @click="searchRooms">
          {{ searchLoading ? '搜索中...' : '搜索' }}
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
          <img class="cover" :src="room.cover || room.avatar || ''" alt="" />
          <div class="result-main">
            <div class="result-meta">
              <span class="platform-pill">{{ room.platform_name }}</span>
              <span class="live-dot" :class="{ off: !room.is_live }">{{ room.is_live ? '直播中' : '未开播' }}</span>
              <span v-if="room.area">{{ room.area }}</span>
              <span v-if="room.watching">{{ room.watching }}</span>
            </div>
            <h3>{{ room.title || '未获取标题' }}</h3>
            <p>{{ room.anchor_name || '未知主播' }}</p>
          </div>
          <button :disabled="loading" @click="playSearchRoom(room)">播放</button>
        </article>
      </div>
    </section>

    <section class="card form-card">
      <div class="grid">
        <label>
          平台
          <select v-model="platform">
            <option value="auto">自动识别 URL</option>
            <option v-for="item in platforms" :key="item.key" :value="item.key">{{ item.name }}</option>
          </select>
        </label>
        <label>
          清晰度
          <select v-model="quality">
            <option value="OD">原画</option>
            <option value="UHD">超清</option>
            <option value="HD">高清</option>
            <option value="SD">标清</option>
            <option value="LD">流畅</option>
          </select>
        </label>
      </div>

      <label>
        直播间 URL / 房间号
        <input
          v-model="target"
          placeholder="例如：https://www.huya.com/52333 或 52333"
          @keydown.enter="resolveRoom"
        />
      </label>

      <div class="toolbar">
        <button class="primary" :disabled="loading || !target.trim()" @click="resolveRoom">
          {{ loading ? '解析中...' : '解析并播放' }}
        </button>
        <button :disabled="!playing" @click="stop">停止</button>
      </div>

      <div class="examples">
        <span>示例：</span>
        <button @click="example('https://www.huya.com/52333')">虎牙 URL</button>
        <button @click="example('https://www.douyu.com/3637778')">斗鱼 URL</button>
        <button @click="example('https://live.bilibili.com/6')">B站 URL</button>
        <button @click="example('52333', 'huya')">虎牙房间号</button>
      </div>
    </section>

    <section class="player-shell">
      <video ref="videoRef" controls playsinline autoplay muted></video>
    </section>

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="result" class="card info-card">
      <div class="room-info">
        <div>
          <p class="eyebrow">{{ result.platform_name }}</p>
          <h2>{{ result.title || '未获取标题' }}</h2>
          <p>主播：{{ result.anchor_name || '未知' }}</p>
          <p v-if="result.live_url">房间：<a :href="result.live_url" target="_blank">{{ result.live_url }}</a></p>
        </div>
        <span class="live-badge" :class="{ off: !result.is_live }">{{ result.is_live ? '直播中' : '未开播' }}</span>
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
  </main>
</template>
