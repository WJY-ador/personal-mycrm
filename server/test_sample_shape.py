"""시험 도우미(이 파일만으로 도는 시험이 아니다) — React 화면이 읽는 API 응답의 손 사본 견본(server/ui/src/**/*.sample.json)과 실제 응답 대조.
쓰는 곳: test_web_home.py(state·「나」) · test_web_import.py(활동·연결 장치) · test_migration_screen.py(이관). TS 쪽은 각 *.sample.test.ts 의 satisfies(tsc)."""

FREE = ("by_source", "actions", "data", "p", "kinds", "waiting", "units", "results")   # 자유 키 사전·열거 목록(값 모양만 같은 종류)은 안으로 들어가지 않는다


def shape(v):
    return "null" if v is None else type(v).__name__


def cmp(sample, real, path, exact):
    """견본 ⊆ 실제(exact = 키 집합까지 같다) — 키가 있어야 하고, 값 타입은 둘 다 null 이 아닐 때 같아야 한다(null 허용은 TS 타입이 tsc 로 본다).
    목록은 둘 다 비지 않았을 때 첫 원소끼리. 차이 = [경로] 목록."""
    bad = []
    if isinstance(sample, dict) and isinstance(real, dict):
        if exact and set(sample) != set(real):
            bad.append(f"{path} 키 {sorted(set(sample) ^ set(real))}")
        for k, v in sample.items():
            if k not in real:
                bad.append(f"{path}.{k} 없음")
            elif "null" not in (shape(v), shape(real[k])) and shape(v) != shape(real[k]):
                bad.append(f"{path}.{k} {shape(v)}≠{shape(real[k])}")
            elif k not in FREE:
                bad += cmp(v, real[k], f"{path}.{k}", exact)
    elif isinstance(sample, list) and isinstance(real, list) and sample and real:
        bad += cmp(sample[0], real[0], path + "[0]", exact)
    return bad
