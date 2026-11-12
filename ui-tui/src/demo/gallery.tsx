// SPDX-License-Identifier: MIT
// Copyright (c) 2026 EverMind.
//
// 组件画廊是独立预览和调整 TUI 组件样式的工具，无需将演示参数接入主程序。
// 通过 `npm run demo` 运行（参见 package.json）。
//
// 布局：左侧栏列出页面（支持鼠标点击与 Tab/←/→ 切换），主区域使用 ScrollBox
// 在 AlternateScreen 中渲染所选页面，确保高度自适应终端窗口、不留残影、并支持
// SessionPanel 等点击折叠交互。Prompts 页每次只聚焦挂载单个示例组件，避免多组件
// 并发抢占键盘输入。

import type { ScrollBoxHandle } from '@hermes/ink'
import type { ReactNode } from 'react'

import { AlternateScreen, Box, render, ScrollBox, Text, useApp, useInput, useStdout } from '@hermes/ink'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Theme } from '../theme.js'
import type { ClarifyReq, ConfirmReq, PanelSection, SessionInfo, Usage } from '../types.js'

import { FloatBox, StatusRule } from '../components/appChrome.js'
import { Banner, Panel, SessionPanel } from '../components/branding.js'
import { ClarifyPrompt, ConfirmPrompt } from '../components/prompts.js'
import { setupGracefulExit } from '../lib/gracefulExit.js'
import { resetTerminalModes } from '../lib/terminalModes.js'
import { DARK_THEME, DEFAULT_THEME, LIGHT_THEME } from '../theme.js'

const SIDEBAR_W = 24

if (!process.stdin.isTTY) {
  process.stderr.write('component-gallery: run in an interactive terminal (needs a TTY)\n')
  process.exit(0)
}

// ── 模拟数据 ────────────────────────────────────────────────────────

const clarifyChoicesReq: ClarifyReq = {
  choices: ['pnpm', 'npm', 'yarn'],
  question: 'Which package manager should I use?',
  requestId: 'demo-clarify-choices'
}

const clarifyFreeReq: ClarifyReq = {
  choices: null,
  question: 'Describe what went wrong:',
  requestId: 'demo-clarify-free'
}

const confirmReq: ConfirmReq = {
  cancelLabel: 'No',
  confirmLabel: 'Yes',
  detail: 'Edits src/theme.ts and 2 more files',
  title: 'Apply 3 changes?'
}

const confirmDangerReq: ConfirmReq = {
  cancelLabel: 'Cancel',
  confirmLabel: 'Delete',
  danger: true,
  detail: 'This cannot be undone',
  title: 'Delete workspace?'
}

const usage: Usage = {
  calls: 12,
  compressions: 2,
  context_max: 200000,
  context_percent: 42,
  context_used: 84210,
  cost_usd: 0.1234,
  input: 60000,
  output: 24210,
  total: 84210
}

const sessionInfo: SessionInfo = {
  cwd: '~/orangecode',
  mcp_servers: [
    { connected: true, name: 'chrome-devtools', tools: 12, transport: 'stdio' },
    { connected: false, name: 'figma', tools: 0, transport: 'sse' }
  ],
  model: 'anthropic/claude-opus-4-8',
  provider: 'anthropic',
  release_date: '2026-06-18',
  skills: {
    cli: ['init', 'review', 'security-review'],
    figma: ['figma-use', 'figma-generate-design']
  },
  system_prompt: 'You are OrangeCode, a general-purpose agent…',
  tools: {
    core_tools: ['read', 'write', 'edit', 'bash'],
    search_tools: ['grep', 'glob']
  },
  version: '0.0.1'
}

const panelSections: PanelSection[] = [
  {
    rows: [
      ['Model', 'claude-opus-4-8'],
      ['Provider', 'Anthropic']
    ],
    title: 'Overview'
  },
  { items: ['first item', 'second item', 'third item'] },
  { text: 'A free-form text section, e.g. a help blurb.' }
]

const PROMPT_DEMOS = [
  { id: 'clarify-choices', label: 'Clarify (choices)' },
  { id: 'clarify-free', label: 'Clarify (free text)' },
  { id: 'confirm', label: 'Confirm' },
  { id: 'confirm-danger', label: 'Confirm (danger)' }
] as const

type PromptOutcome =
  | null
  | {
      kind: 'answered' | 'cancelled' | 'confirmed'
      message: string
    }

// ── 分区包装器 ──────────────────────────────────────────────────

function Demo({ children, t, title }: { children: ReactNode; t: Theme; title: string }) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color={t.color.label}>{`▸ ${title}`}</Text>
      <Box marginTop={1}>{children}</Box>
    </Box>
  )
}

// ── 页面 ────────────────────────────────────────────────────────────

function PromptsPage({
  cols,
  onTypingChange,
  t
}: {
  cols: number
  onTypingChange: (typing: boolean) => void
  t: Theme
}) {
  const [selectedDemo, setSelectedDemo] = useState(0)
  const [outcome, setOutcome] = useState<PromptOutcome>(null)
  const [resetEpoch, setResetEpoch] = useState(0)
  const [isPromptTyping, setIsPromptTyping] = useState(false)

  const activeDemo = PROMPT_DEMOS[selectedDemo] ?? PROMPT_DEMOS[0]

  const reportTyping = useCallback(
    (typing: boolean) => {
      setIsPromptTyping(typing)
      onTypingChange(typing)
    },
    [onTypingChange]
  )

  const switchDemo = useCallback(
    (nextIndex: number) => {
      const wrapped = (nextIndex + PROMPT_DEMOS.length) % PROMPT_DEMOS.length
      setSelectedDemo(wrapped)
      setOutcome(null)
      setResetEpoch(e => e + 1)
      reportTyping(false)
    },
    [reportTyping]
  )

  const resetActive = useCallback(() => {
    setOutcome(null)
    setResetEpoch(e => e + 1)
  }, [])

  useEffect(() => {
    return () => {
      onTypingChange(false)
    }
  }, [onTypingChange])

  useInput((ch, key) => {
    if (outcome !== null) {
      if (key.return || ch.toLowerCase() === 'r' || ch === ' ') {
        resetActive()

        return
      }
    }

    if (isPromptTyping && outcome === null) {
      return
    }

    if (ch === '[') {
      switchDemo(selectedDemo - 1)
    } else if (ch === ']') {
      switchDemo(selectedDemo + 1)
    }
  })

  return (
    <Box flexDirection="column">
      <Text color={t.color.muted}>
        {isPromptTyping && outcome === null
          ? 'Typing mode active — press Enter to submit, Esc to unlock shortcuts, or click another tab:'
          : 'Select an interactive prompt (click tabs or press [ / ]):'}
      </Text>

      <Box flexWrap="wrap" gap={1} marginTop={1}>
        {PROMPT_DEMOS.map((item, idx) => {
          const active = idx === selectedDemo
          return (
            <Box
              backgroundColor={active ? t.color.surfaceRaised : undefined}
              key={item.id}
              onClick={() => switchDemo(idx)}
              paddingX={1}
            >
              <Text bold={active} color={active ? t.color.accent : t.color.muted}>
                {active ? '▸ ' : '  '}
                {item.label}
              </Text>
            </Box>
          )
        })}
      </Box>

      <Demo t={t} title={activeDemo.label}>
        {outcome !== null ? (
          <Box borderColor={outcome.kind === 'cancelled' ? t.color.warn : t.color.ok} borderStyle="round" flexDirection="column" paddingX={1}>
            <Text bold color={outcome.kind === 'cancelled' ? t.color.warn : t.color.ok}>
              {outcome.message}
            </Text>
            <Box marginTop={1} onClick={resetActive}>
              <Text color={t.color.accent}>▸ Press Enter / R or click here to test again</Text>
            </Box>
          </Box>
        ) : activeDemo.id === 'clarify-choices' ? (
          <ClarifyPrompt
            cols={cols}
            key={`choices-${resetEpoch}`}
            onAnswer={ans => {
              reportTyping(false)
              setOutcome({ kind: 'answered', message: `Answered: "${ans}"` })
            }}
            onCancel={() => {
              reportTyping(false)
              setOutcome({ kind: 'cancelled', message: 'Cancelled clarify (choices)' })
            }}
            onTypingChange={reportTyping}
            req={clarifyChoicesReq}
            t={t}
          />
        ) : activeDemo.id === 'clarify-free' ? (
          <ClarifyPrompt
            cols={cols}
            key={`free-${resetEpoch}`}
            onAnswer={ans => {
              reportTyping(false)
              setOutcome({ kind: 'answered', message: `Submitted text: "${ans || '(empty)'}"` })
            }}
            onCancel={() => {
              reportTyping(false)
              setOutcome({ kind: 'cancelled', message: 'Cancelled clarify (free text)' })
            }}
            onTypingChange={reportTyping}
            req={clarifyFreeReq}
            t={t}
          />
        ) : activeDemo.id === 'confirm' ? (
          <ConfirmPrompt
            key={`confirm-${resetEpoch}`}
            onCancel={() => setOutcome({ kind: 'cancelled', message: 'Declined (No / Cancelled)' })}
            onConfirm={() => setOutcome({ kind: 'confirmed', message: 'Confirmed (Yes — applied 3 changes)' })}
            req={confirmReq}
            t={t}
          />
        ) : (
          <ConfirmPrompt
            key={`confirm-danger-${resetEpoch}`}
            onCancel={() => setOutcome({ kind: 'cancelled', message: 'Aborted dangerous action' })}
            onConfirm={() => setOutcome({ kind: 'confirmed', message: 'Confirmed dangerous action (Delete)' })}
            req={confirmDangerReq}
            t={t}
          />
        )}
      </Demo>
    </Box>
  )
}

function AppChromePage({ cols, t }: { cols: number; t: Theme }) {
  const [liveBusy, setLiveBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useInput(ch => {
    if (ch === ' ') {
      setLiveBusy(b => !b)
      setNow(Date.now())
    }
  })

  return (
    <Box flexDirection="column">
      <Demo t={t} title="StatusRule — interactive (click button or press Space to toggle)">
        <Box flexDirection="column" gap={1}>
          <Box onClick={() => setLiveBusy(b => !b)}>
            <Text color={t.color.accent}>
              ▸ Toggle state (current: <Text bold>{liveBusy ? 'working' : 'ready'}</Text>)
            </Text>
          </Box>
          <StatusRule
            bgCount={liveBusy ? 0 : 1}
            busy={liveBusy}
            cols={cols}
            cwdLabel="~/orangecode"
            model="anthropic/claude-opus-4-8"
            modelReasoningEffort="high"
            sessionStartedAt={now - 125_000}
            showCost={!liveBusy}
            status={liveBusy ? 'working' : 'ready'}
            statusColor={liveBusy ? t.color.statusWarn : t.color.statusGood}
            t={t}
            turnStartedAt={liveBusy ? now - 5_000 : null}
            usage={usage}
          />
        </Box>
      </Demo>

      <Demo t={t} title="StatusRule — static busy (animated)">
        <StatusRule
          bgCount={0}
          busy
          cols={cols}
          cwdLabel="~/orangecode"
          model="anthropic/claude-opus-4-8"
          sessionStartedAt={now - 125_000}
          showCost={false}
          status="working"
          statusColor={t.color.statusWarn}
          t={t}
          turnStartedAt={now - 5_000}
          usage={usage}
        />
      </Demo>

      <Demo t={t} title="FloatBox">
        <FloatBox color={t.color.border}>
          <Text color={t.color.text}>Floating panel content</Text>
          <Text color={t.color.muted}>rendered inside a rounded FloatBox</Text>
        </FloatBox>
      </Demo>
    </Box>
  )
}

function BrandingPage({ cols, t }: { cols: number; t: Theme }) {
  return (
    <Box flexDirection="column">
      <Demo t={t} title="Banner (logo)">
        <Banner maxCols={cols} t={t} />
      </Demo>
      <Demo t={t} title="SessionPanel (click ▸ sections to expand/collapse)">
        <SessionPanel info={sessionInfo} maxCols={cols} sid="a1b2c3d4" t={t} />
      </Demo>
      <Demo t={t} title="Panel">
        <Panel sections={panelSections} t={t} title="Example Panel" />
      </Demo>
    </Box>
  )
}

const PAGES: { id: 'branding' | 'chrome' | 'prompts'; title: string }[] = [
  { id: 'branding', title: 'Branding' },
  { id: 'chrome', title: 'App Chrome' },
  { id: 'prompts', title: 'Prompts' }
]

// ── 外壳 ────────────────────────────────────────────────────────────

function Gallery() {
  const [page, setPage] = useState(0)
  const [scheme, setScheme] = useState<'dark' | 'light'>(DEFAULT_THEME === LIGHT_THEME ? 'light' : 'dark')
  const [typingLocked, setTypingLocked] = useState(false)
  const scrollRef = useRef<ScrollBoxHandle | null>(null)
  const { exit } = useApp()
  const cols = Math.max(36, (useStdout().stdout?.columns ?? 100) - SIDEBAR_W - 6)

  const t = scheme === 'dark' ? DARK_THEME : LIGHT_THEME

  const quit = useCallback(() => {
    exit()
    resetTerminalModes()
    process.exit(0)
  }, [exit])

  const goToPage = useCallback((nextIdx: number) => {
    const wrapped = (nextIdx + PAGES.length) % PAGES.length
    setPage(wrapped)
    setTypingLocked(false)
    scrollRef.current?.scrollTo(0)
  }, [])

  useInput((ch, key) => {
    if (key.ctrl && ch.toLowerCase() === 'c') {
      quit()

      return
    }

    if (key.tab) {
      goToPage(page + (key.shift ? -1 : 1))

      return
    }

    if (key.pageUp) {
      scrollRef.current?.scrollBy(-6)

      return
    }

    if (key.pageDown) {
      scrollRef.current?.scrollBy(6)

      return
    }

    // 当子组件处于文本输入态时，不抢占字母和左右方向键。
    if (typingLocked) {
      return
    }

    if (ch === 'q') {
      quit()
    } else if (ch === 't') {
      setScheme(s => (s === 'dark' ? 'light' : 'dark'))
    } else if (key.rightArrow) {
      goToPage(page + 1)
    } else if (key.leftArrow) {
      goToPage(page - 1)
    }
  })

  const activeId = PAGES[page]?.id ?? 'branding'

  return (
    <AlternateScreen mouseTracking>
      <Box backgroundColor={t.color.surface} flexDirection="row" flexGrow={1} paddingX={1} paddingY={1}>
        <Box
          borderColor={t.color.border}
          borderLeft={false}
          borderBottom={false}
          borderStyle="single"
          borderTop={false}
          flexDirection="column"
          flexShrink={0}
          marginRight={2}
          paddingRight={1}
          width={SIDEBAR_W}
        >
          <Text bold color={t.color.primary}>
            {t.brand.icon} Orange Gallery
          </Text>
          <Box marginTop={1} onClick={() => setScheme(s => (s === 'dark' ? 'light' : 'dark'))}>
            <Text color={t.color.muted}>
              Theme: <Text color={t.color.accent}>{scheme}</Text>
            </Text>
          </Box>
          <Text />

          {PAGES.map((p, i) => (
            <Box key={p.id} onClick={() => goToPage(i)}>
              <Text bold={i === page} color={i === page ? t.color.accent : t.color.muted}>
                {i === page ? '▸ ' : '  '}
                {p.title}
              </Text>
            </Box>
          ))}

          <Box flexGrow={1} />

          <Text color={t.color.muted}>Tab / Shift+Tab  page</Text>
          {!typingLocked && <Text color={t.color.muted}>←/→ page · t theme</Text>}
          <Text color={t.color.muted}>PgUp/PgDn scroll</Text>
          <Text color={t.color.muted}>{typingLocked ? 'Ctrl+C quit' : 'Ctrl+C / q quit'}</Text>
        </Box>

        <ScrollBox flexDirection="column" flexGrow={1} flexShrink={1} key={activeId} ref={scrollRef}>
          <Box flexDirection="column" paddingRight={1}>
            {activeId === 'branding' ? (
              <BrandingPage cols={cols} t={t} />
            ) : activeId === 'chrome' ? (
              <AppChromePage cols={cols} t={t} />
            ) : (
              <PromptsPage cols={cols} onTypingChange={setTypingLocked} t={t} />
            )}
          </Box>
        </ScrollBox>
      </Box>
    </AlternateScreen>
  )
}

setupGracefulExit({
  cleanups: [
    () => {
      resetTerminalModes()
    }
  ],
  onSignal: () => {
    resetTerminalModes()
  }
})
process.on('exit', () => {
  resetTerminalModes()
})

render(<Gallery />, { exitOnCtrlC: false })
