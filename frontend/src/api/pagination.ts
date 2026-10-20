/** 分页读取基础资料；任何一页失败都抛错，避免把部分选项当作全部。 */
export async function loadAllPages<T>(fetchPage: (page: number) => Promise<{ items: T[]; total: number }>): Promise<T[]> {
  const result: T[] = []
  for (let page = 1; ; page += 1) {
    const response = await fetchPage(page)
    result.push(...response.items)
    if (result.length >= response.total) return result
    if (!response.items.length) throw new Error('分页结果不完整，请刷新重试')
  }
}
