export function getApiBaseUrl(): string {
  return window.__APP_CONFIG__?.API_BASE_URL ?? '';
}
