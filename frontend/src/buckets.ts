import type { Bucket } from './api'

export const BUCKET_INFO: Record<Bucket, { label: string; blurb: string }> = {
  covered: { label: 'Covered', blurb: 'Your resume shows you doing this.' },
  underemphasized: { label: 'Underemphasized', blurb: 'You have it, but only list it or mention it in passing.' },
  transferable: { label: 'Transferable', blurb: "Not shown directly, but you've done something close." },
  gap: { label: 'Gap', blurb: 'Nothing on your resume supports this yet.' },
}
