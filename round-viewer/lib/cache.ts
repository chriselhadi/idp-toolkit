// Drive reads are cached for 10 minutes in the server's memory. The refresh button clears them.
// A promise is cached, not a value, so two requests in the same moment share one Drive read.
const TTL_MS = 10 * 60 * 1000;

type Entry = { at: number; value: Promise<unknown> };
const store = new Map<string, Entry>();

export function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.value as Promise<T>;
  const value = load();
  store.set(key, { at: Date.now(), value });
  // A failed read is not kept: the next request tries again.
  value.catch(() => { if (store.get(key)?.value === value) store.delete(key); });
  return value;
}

export function clearCache(): void {
  store.clear();
}
