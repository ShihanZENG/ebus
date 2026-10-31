export const demoCredentials = { username: 'zhijian_demo', password: 'ZhijianDemo2026!' }

export async function signInDemoCustomer(request) {
  const options = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(demoCredentials) }
  try {
    return await request('/account/login', options)
  } catch (error) {
    if (error?.status !== 401) throw error
  }
  try {
    return await request('/account/register', options)
  } catch (error) {
    if (error?.status !== 409) throw error
    return request('/account/login', options)
  }
}
