// 暗涌 · 独立运行器
//
// 复用 dsh-longing 原版的引擎（src/curve.js、events.js、prompt.js…），
// 不依赖 DSH，给 AstrBot 侧提供三件事：
//   1. 每 60 秒 tick 一次：衰减 / 高峰加成 / 耦合
//   2. 生成注入块（欲望注入.txt、欲望注入.<通道>.txt）
//   3. 一个只监听 127.0.0.1 的小 HTTP 接口，给 AstrBot 插件读写
//
// 启动：node runner.mjs
// 数据目录：与本文件同级的 data/

import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildBlock } from './dsh-longing/src/prompt.js'
import { nextState, DIMS, num } from './dsh-longing/src/curve.js'
import { applyEvent } from './dsh-longing/src/events.js'
import { detectAndRefine, isSafetyWord } from './dsh-longing/src/auto-event.js'

const here = dirname(fileURLToPath(import.meta.url))
const DATA = join(here, 'data')
const STATE_FILE = join(DATA, '欲望状态.json')
const CONFIG_FILE = join(DATA, '暗涌配置.json')

const CONFIG_DEFAULTS = {
  enabled: true,
  channel: 'qq',
  host: '127.0.0.1',
  port: 6399,
  activeHours: '08:00-02:00',
  scheduleEnabled: true,
  peakWindow: '22:00-01:00',
  decayPerHour: 3,
  nightDecayPerHour: 6,
  peakBonus: 6,
  pauseWord: '停',
  couplingEnabled: true,
  couplingRate: 1,
  tickSeconds: 60,
}

const STATE_DEFAULTS = {
  lust: 30, lewd: 15, possess: 20, shame: 60, resist: 80, fatigue: 20, affection: 50,
  pausedUntil: 0, lastPeak: '', events: [], updatedAt: 0, tickedAt: 0,
}

function readJson(path, fallback) {
  try {
    return JSON.parse(readFileSync(path, 'utf-8'))
  } catch {
    return { ...fallback }
  }
}

function writeJsonAtomic(path, value) {
  const tmp = path + '.tmp'
  writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf-8')
  renameSync(tmp, path)
}

mkdirSync(DATA, { recursive: true })

let config = { ...CONFIG_DEFAULTS, ...readJson(CONFIG_FILE, {}) }
let state = { ...STATE_DEFAULTS, ...readJson(STATE_FILE, {}) }

// 首次运行把默认值落盘，方便手工改
if (!existsSync(CONFIG_FILE)) writeJsonAtomic(CONFIG_FILE, config)

function saveState() {
  state.updatedAt = Date.now()
  writeJsonAtomic(STATE_FILE, state)
}

function tick() {
  if (config.enabled === false) return
  const before = state.lust
  state = { ...state, ...nextState(state, config, Date.now()) }
  state.holding = state.holding || {}
  saveState()
  const moved = Math.abs(num(state.lust, 0) - num(before, 0)) >= 0.01
  if (moved) {
    console.log(`[tick] lust ${before.toFixed(2)} -> ${num(state.lust, 0).toFixed(2)}`)
  }
  writeBlocks()
}

function buildFor(channel) {
  try {
    return buildBlock(state, { ...config, channels: [channel] }, { channel, now: Date.now() })
  } catch (error) {
    console.error('[buildBlock] 失败:', error?.message || error)
    return ''
  }
}

function writeBlocks() {
  try {
    const channel = String(config.channel || 'qq')
    const text = buildFor(channel)
    writeFileSync(join(DATA, '欲望注入.txt'), text, 'utf-8')
    writeFileSync(join(DATA, `欲望注入.${channel}.txt`), text, 'utf-8')
  } catch (error) {
    console.error('[writeBlocks] 失败:', error?.message || error)
  }
}

function note(text, channel) {
  const raw = String(text || '').trim()
  if (!raw) return { applied: null }
  // 安全词整句 → 立即刹停
  if (isSafetyWord(raw, String(config.pauseWord || '停'))) {
    state.pausedUntil = Date.now() + 30 * 60_000
    saveState()
    console.log('[note] 命中安全词，暂停 30 分钟')
    return { applied: 'safety', pausedUntil: state.pausedUntil }
  }
  const hit = detectAndRefine(raw, String(config.pauseWord || '停'))
  if (!hit?.name) return { applied: null }
  state = applyEvent(state, hit.name, config, Date.now())
  // 事件记录：保留事件名与原文片段，供注入块引用
  state.lastEvent = { name: hit.name, text: raw.slice(0, 80), at: Date.now() }
  saveState()
  writeBlocks()
  console.log('[note] 事件:', hit.name)
  return { applied: hit.name }
}

function pause(minutes) {
  const mins = Math.max(0, Number(minutes) || 0)
  state.pausedUntil = mins > 0 ? Date.now() + mins * 60_000 : 0
  saveState()
  writeBlocks()
  return { pausedUntil: state.pausedUntil }
}

function publicState() {
  return {
    dims: Object.fromEntries(DIMS.map((key) => [key, num(state[key], 0)])),
    pausedUntil: num(state.pausedUntil, 0),
    lastEvent: state.lastEvent || null,
    block: buildFor(String(config.channel || 'qq')),
    enabled: config.enabled !== false,
    channel: config.channel || 'qq',
  }
}

function send(res, code, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  })
  res.end(body)
}

async function readBody(req) {
  const chunks = []
  for await (const chunk of req) {
    chunks.push(chunk)
    if (chunks.reduce((sum, c) => sum + c.length, 0) > 64 * 1024) throw new Error('body too large')
  }
  if (!chunks.length) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf-8'))
  } catch {
    return {}
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  const path = url.pathname
  try {
    if (path === '/health') return send(res, 200, { ok: true, enabled: config.enabled !== false })
    if (path === '/block') {
      const channel = url.searchParams.get('channel') || config.channel || 'qq'
      return send(res, 200, { ok: true, block: buildFor(channel) })
    }
    if (path === '/state') return send(res, 200, { ok: true, ...publicState() })
    if (path === '/config' && req.method === 'GET') return send(res, 200, { ok: true, config })
    if (path === '/config' && req.method === 'POST') {
      const body = await readBody(req)
      config = { ...config, ...body }
      writeJsonAtomic(CONFIG_FILE, config)
      writeBlocks()
      return send(res, 200, { ok: true, config })
    }
    if (path === '/note' && req.method === 'POST') {
      const body = await readBody(req)
      return send(res, 200, { ok: true, ...note(body.text, body.channel) })
    }
    if (path === '/event' && req.method === 'POST') {
      const body = await readBody(req)
      const name = String(body.name || '')
      if (!name) return send(res, 400, { ok: false, error: 'name required' })
      state = applyEvent(state, name, config, Date.now())
      saveState()
      writeBlocks()
      return send(res, 200, { ok: true, applied: name })
    }
    if (path === '/pause' && req.method === 'POST') {
      const body = await readBody(req)
      return send(res, 200, { ok: true, ...pause(body.minutes) })
    }
    return send(res, 404, { ok: false, error: 'not found' })
  } catch (error) {
    return send(res, 500, { ok: false, error: String(error?.message || error) })
  }
})

// ── WATCHDOG：AstrBot 不在就自己退出 ──
// 点窗口 X / 任务管理器结束 / 崩溃，terminate 都跑不到；
// 所以由引擎反向探测：AstrBot 的 6185 连续两次连不上（约 30 秒）就自尽。
// 短暂重启（40 秒内）会先被杀掉，但新实例开卡片时会重新拉起，不影响。
import { connect } from 'node:net'

const ASTRBOT_HOST = '127.0.0.1'
const ASTRBOT_PORT = 6185
const WATCH_INTERVAL_MS = 15_000
const WATCH_MISS_LIMIT = 2
let watchMiss = 0

function astrbotAlive() {
  return new Promise((resolve) => {
    const socket = connect({ host: ASTRBOT_HOST, port: ASTRBOT_PORT })
    const done = (result) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(result)
    }
    socket.setTimeout(2000, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

setInterval(async () => {
  const alive = await astrbotAlive()
  if (alive) {
    watchMiss = 0
    return
  }
  watchMiss += 1
  console.log(`[watchdog] AstrBot 不在（${watchMiss}/${WATCH_MISS_LIMIT}）`)
  if (watchMiss >= WATCH_MISS_LIMIT) {
    console.log('[watchdog] AstrBot 已离线，引擎退出')
    process.exit(0)
  }
}, WATCH_INTERVAL_MS)

server.on('error', (error) => {
  if (error && error.code === 'EADDRINUSE') {
    console.log(`[暗涌] 端口 ${config.port} 已被占用——多半是引擎已经在跑了。`)
    console.log('[暗涌] 这一份先退出，不影响正在运行的那一份。')
    process.exit(0)
  }
  console.error('[暗涌] 启动失败:', error?.message || error)
  process.exit(1)
})

server.listen(num(config.port, 6399), String(config.host || '127.0.0.1'), () => {
  console.log(`[暗涌] 监听 http://${config.host}:${config.port}  数据目录:${DATA}`)
  writeBlocks()
  tick()
  setInterval(tick, Math.max(15, num(config.tickSeconds, 60)) * 1000)
})
