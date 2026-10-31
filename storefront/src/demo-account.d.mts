import type { Customer } from './customer-api'
export const demoCredentials: { username: string; password: string }
export function signInDemoCustomer(request: (path: string, options: RequestInit) => Promise<{ customer: Customer }>): Promise<{ customer: Customer }>
