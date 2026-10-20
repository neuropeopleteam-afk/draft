// Юридические документы «Драфта»: /privacy, /consent, /terms, /cookies, /recommendations.
// Тексты — frontend/src/legal/*.md (единый источник; та же редакция — в docs/legal/). Простой разбор Markdown:
// заголовки, абзацы, списки (вложенность — 2 пробела), таблицы, **жирный**, `код`, [ссылка](url) и голые https-адреса.
import { Fragment, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { usePageTitle } from "../../lib/meta";
import consent from "../../legal/consent.md?raw";
import cookies from "../../legal/cookies.md?raw";
import privacy from "../../legal/privacy.md?raw";
import recommendations from "../../legal/recommendations.md?raw";
import terms from "../../legal/terms.md?raw";

export const LEGAL_DOCS: { path: string; title: string; text: string }[] = [
  { path: "/privacy", title: "Политика обработки персональных данных", text: privacy },
  { path: "/consent", title: "Согласие на обработку персональных данных", text: consent },
  { path: "/terms", title: "Пользовательское соглашение", text: terms },
  { path: "/cookies", title: "Политика cookie", text: cookies },
  { path: "/recommendations", title: "Правила применения рекомендательных технологий", text: recommendations },
];

function inline(s: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|https:\/\/[^\s)<>|,;]+[^\s)<>|,;.])/g;
  let last = 0; let m: RegExpExecArray | null; let i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const t = m[0]; const k = `${key}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k} className="font-semibold text-brand-night">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k} className="rounded bg-[#F3F2FB] px-1 text-[0.9em]">{t.slice(1, -1)}</code>);
    else {
      const md = t.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const label = md ? md[1] : t; const href = md ? md[2] : t;
      const local = href.replace(/^https:\/\/fsp-draft\.ru/, "");
      out.push(local.startsWith("/") && local !== href
        ? <Link key={k} to={local} className="font-semibold text-brand-plum underline-offset-2 hover:underline">{md ? label : t}</Link>
        : <a key={k} href={href} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-plum underline-offset-2 hover:underline">{label}</a>);
    }
    last = m.index + t.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

function List({ items }: { items: { depth: number; text: string }[] }) {
  const nodes: ReactNode[] = []; let i = 0;
  while (i < items.length) {
    const it = items[i]; const kids: { depth: number; text: string }[] = []; let j = i + 1;
    while (j < items.length && items[j].depth > it.depth) { kids.push({ ...items[j], depth: items[j].depth - 1 }); j++; }
    nodes.push(<li key={i}>{inline(it.text, i)}{kids.length > 0 && <List items={kids} />}</li>);
    i = j;
  }
  return <ul className="mt-2 list-disc space-y-1.5 pl-5 marker:text-brand">{nodes}</ul>;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n"); const out: ReactNode[] = []; let i = 0; let k = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const lvl = h[1].length; const c = inline(h[2], k);
      out.push(lvl === 1 ? <h1 key={k++} className="text-2xl font-extrabold leading-tight text-brand-night sm:text-3xl">{c}</h1>
        : lvl === 2 ? <h2 key={k++} className="mt-8 text-xl font-bold text-brand-night">{c}</h2>
        : <h3 key={k++} className="mt-5 font-bold text-brand-night">{c}</h3>);
      i++; continue;
    }
    if (l.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      out.push(
        <div key={k++} className="mt-3 space-y-2 md:hidden">
          {body.map((r, n) => (
            <dl key={n} className="rounded-xl border border-brand-night/10 bg-white p-3 text-[13px] leading-snug">
              {r.map((c, m) => (
                <div key={m} className={m ? "mt-1.5" : ""}>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-brand-plum">{head[m]}</dt>
                  <dd>{inline(c, m)}</dd>
                </div>
              ))}
            </dl>
          ))}
        </div>);
      out.push(
        <div key={k++} className="mt-3 hidden overflow-x-auto rounded-xl border border-brand-night/10 md:block">
          <table className="w-full min-w-[48rem] text-left text-[13px] leading-snug">
            <thead className="bg-[#F3F2FB] text-brand-night"><tr>{head.map((c, n) => <th key={n} className="px-3 py-2 font-semibold">{inline(c, n)}</th>)}</tr></thead>
            <tbody>{body.map((r, n) => <tr key={n} className="border-t border-brand-night/10 align-top">{r.map((c, m) => <td key={m} className="px-3 py-2">{inline(c, m)}</td>)}</tr>)}</tbody>
          </table>
        </div>);
      continue;
    }
    if (/^\s*- /.test(l)) {
      const items: { depth: number; text: string }[] = [];
      while (i < lines.length && /^\s*- /.test(lines[i])) {
        const m = lines[i].match(/^(\s*)- (.*)$/)!; items.push({ depth: Math.floor(m[1].length / 2), text: m[2] }); i++;
      }
      out.push(<List key={k++} items={items} />); continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*- |\s*\|)/.test(lines[i])) { para.push(lines[i].trim()); i++; }
    out.push(<p key={k++} className="mt-3 leading-relaxed">{inline(para.join(" "), k)}</p>);
  }
  return <Fragment>{out}</Fragment>;
}

export default function LegalPage() {
  const { pathname } = useLocation();
  const doc = LEGAL_DOCS.find((d) => d.path === pathname) ?? LEGAL_DOCS[0];
  usePageTitle(doc.title);
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-6 px-4 py-10 sm:px-6" data-testid="legal-page">
        <nav aria-label="Юридические документы">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-plum">Документы</p>
          <ul className="flex flex-wrap gap-2">
            {LEGAL_DOCS.map((d) => (
              <li key={d.path}>
                <Link to={d.path} aria-current={d.path === doc.path ? "page" : undefined}
                  className={`block rounded-full px-3 py-1.5 text-sm ring-1 ${d.path === doc.path ? "bg-brand-blush/50 font-semibold text-brand-night ring-brand/30" : "text-brand-ink/75 ring-brand-night/10 hover:bg-white"}`}>{d.title}</Link>
              </li>
            ))}
          </ul>
        </nav>
        <article className="card min-w-0 text-[15px] text-brand-ink/90 sm:!p-8">
          <Markdown text={doc.text} />
        </article>
      </main>
      <SiteFooter />
    </div>
  );
}
