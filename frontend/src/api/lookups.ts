import { request } from './client'

export interface ListResult {
  items: Record<string, unknown>[]
  total: number
}

/**
 * 加载「id → 展示名」映射，用于把列表里的外键 id 显示成业务名称。
 * 基础资料量有限，一次性取全量即可。
 */
export async function loadNameMap(
  resource: string,
  labelKeys: string[] = ['code', 'name'],
): Promise<Record<string, string>> {
  try {
    const res = await request<ListResult>(`/${resource}`, { params: { page: 1, page_size: 100 } })
    const map: Record<string, string> = {}
    for (const row of res.items) {
      const id = String(row.id)
      const label = labelKeys
        .map((k) => row[k])
        .filter((v) => v !== undefined && v !== null && v !== '')
        .join(' ')
      map[id] = label || id.slice(0, 8)
    }
    return map
  } catch {
    return {}
  }
}
