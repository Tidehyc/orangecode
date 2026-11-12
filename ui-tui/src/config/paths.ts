import { homedir } from 'node:os'
import { join } from 'node:path'

export const getOrangeCodeHome = (env: NodeJS.ProcessEnv = process.env) => env.ORANGECODE_HOME?.trim() || join(homedir(), '.orangecode')

export const getOrangeCodeHomeLabel = (env: NodeJS.ProcessEnv = process.env) => env.ORANGECODE_HOME?.trim() || '~/.orangecode'
