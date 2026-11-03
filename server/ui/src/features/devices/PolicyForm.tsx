// 허용 규칙 바꾸기(옛 policyForm) — 받을 행동·받을 자료·붙일 축(분류 자료 종류의 항목). 자유 글은 받지 않는다. 저장 = expected_revision
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { postMsg, RELOAD } from "../../shared/postErr";
import type { Item } from "../../shared/state";
import { devApi, type Choices, type Device, type Policy } from "./devApi";
import { DONE } from "./text";
import css from "./Devices.module.css";

type Props = { d: Device; ch: Choices; items: Item[]; done: (t: string) => Promise<void>; fail: (t: string) => Promise<void> };

export function PolicyForm({ d, ch, items, done, fail }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const pol = d.policy || { actions: [], transform_versions: [], axes: [] };
  const axes = ch.axis_object_id ? items.filter(it => it.object_id === ch.axis_object_id) : [];
  const box = (name: keyof Policy, v: string, l: string) => (
    <label key={v}><input type="checkbox" name={name} value={v} defaultChecked={(pol[name] || []).includes(v)} /> {l}</label>
  );
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = e.currentTarget, vals = (n: string) => [...f.querySelectorAll<HTMLInputElement>(`input[name="${n}"]:checked`)].map(i => i.value);
    setErr(""); setBusy(true);
    try {
      await devApi.policy(d.id, { actions: vals("actions"), transform_versions: vals("transform_versions"), axes: vals("axes") }, d.policy_revision);
    } catch (x) {
      const er = apiErr(x);
      setBusy(false);
      if (RELOAD.has(er.code)) return fail(postMsg(er));
      return setErr(postMsg(er));
    }
    setBusy(false);
    await done(DONE.policy);
  }
  return (
    <details className={css.pol}><summary>허용 규칙 바꾸기</summary>
      <form className="fform" noValidate onSubmit={save}>
        <fieldset><legend>받을 행동</legend>{(ch.actions || []).map(x => box("actions", x.key, x.label))}</fieldset>
        <fieldset><legend>받을 자료</legend>{(ch.transforms || []).map(x => box("transform_versions", x.key, x.label))}</fieldset>
        <fieldset><legend>붙일 축 <span className="tech">최대 {ch.max_axes}개</span></legend>{axes.length ? axes.map(it => box("axes", it.id, it.title || "(제목 없음)"))
          : <span className="hint">분류(축) 자료 종류의 항목이 없어요.</span>}</fieldset>
        <p className="hint">PC 경로·주소 같은 자유 글은 받지 않아요. 바꾸면 다음 업로드부터 적용돼요.</p>
        <div className="frow"><button className="primary" type="submit" disabled={busy}>허용 규칙 저장</button></div>
        <p className="ferr" role="alert" aria-atomic="true">{err}</p></form>
    </details>
  );
}
