// 자료군 × 개수 표(옛 migUnitTable·영수증 결과표) — cols = 열 키, label = 열 이름. 0 은 옅게
import css from "./Migration.module.css";

type T = Record<string, number>;
type Props = { caption: string; cols: string[]; label: Record<string, string>; units: Record<string, T>; total: T };

export function UnitTable({ caption, cols, label, units, total }: Props) {
  const names = Object.keys(units || {}).sort();
  const cell = (o: T, k: string) => (o?.[k] ? o[k] : <span className="tech">0</span>);
  return (
    <div className={css.wrap}><table className={css.tbl}><caption className="sh">{caption}</caption>
      <thead><tr><th scope="col">자료군</th>{cols.map(k => <th key={k} scope="col">{label[k] || k}</th>)}</tr></thead>
      <tbody>{names.map(u => <tr key={u}><th scope="row"><code>{u}</code></th>{cols.map(k => <td key={k}>{cell(units[u], k)}</td>)}</tr>)}</tbody>
      <tfoot><tr><th scope="row">합계</th>{cols.map(k => <td key={k}>{cell(total || {}, k)}</td>)}</tr></tfoot></table></div>
  );
}
