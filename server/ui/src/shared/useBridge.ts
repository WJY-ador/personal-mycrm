// 앱 다리 값 구독 — get() 한 번 + onChange. 값 검사(parse)가 틀리면 null. undefined = 아직 못 받음. 다리가 없으면 늘 undefined
import { useEffect, useState } from "react";

type Readable = { get(): Promise<unknown>; onChange(cb: (v: unknown) => void): unknown };

export function useBridge<T>(bridge: Readable | null, parse: (x: unknown) => T | null): T | null | undefined {
  const [v, setV] = useState<T | null | undefined>(undefined);
  useEffect(() => {
    if (!bridge) return;
    let live = true;
    const put = (x: unknown) => { if (live) setV(parse(x)); };
    let off: unknown;
    try {
      off = bridge.onChange(put);
      void Promise.resolve(bridge.get()).then(put, () => {});
    } catch { /* 다리 오류 — 값 없음 그대로 */ }
    return () => { live = false; if (typeof off === "function") try { off(); } catch { /* 이미 닫힘 */ } };
  }, [bridge, parse]);
  return v;
}
