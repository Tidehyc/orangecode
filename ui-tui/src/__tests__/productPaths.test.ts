import { homedir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { getOrangeCodeHome, getOrangeCodeHomeLabel } from '../config/paths.js'

describe('OrangeCode product paths', () => {
  it('uses the OrangeCode home override for persistent TUI state', () => {
    expect(getOrangeCodeHome({ ORANGECODE_HOME: '/tmp/orangecode-home' })).toBe('/tmp/orangecode-home')
    expect(getOrangeCodeHomeLabel({ ORANGECODE_HOME: '/tmp/orangecode-home' })).toBe('/tmp/orangecode-home')
  })

  it('uses ~/.orangecode when the override is empty', () => {
    expect(getOrangeCodeHome({ ORANGECODE_HOME: '  ' })).toBe(join(homedir(), '.orangecode'))
    expect(getOrangeCodeHomeLabel({ ORANGECODE_HOME: '  ' })).toBe('~/.orangecode')
  })
})
