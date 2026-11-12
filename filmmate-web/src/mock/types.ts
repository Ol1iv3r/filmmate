/** Mock 样本数据形状（由 scripts/build-samples.mjs 从 _ref/AI-Project 生成）。 */

export interface MockSegment {
  time_start: string
  time_end: string
  description: string
  keywords: string[]
}

export interface MockSample {
  videoId: string
  title: string
  keywords: string[]
  segments: MockSegment[]
}
