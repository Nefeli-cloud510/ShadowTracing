import { loadTimelineBundle } from './src/data/realStateLoader.ts'
loadTimelineBundle().then(console.log).catch(console.error)