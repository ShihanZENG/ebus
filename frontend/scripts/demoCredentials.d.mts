export interface AdminCredentials {
  username: string
  password: string
}

export function parseAdminCredentials(contents: string): AdminCredentials | null
export function loadAdminCredentials(envPath: string): AdminCredentials | null
