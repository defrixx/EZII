"use client";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
import { knowledgeBaseIcon } from "@/lib/knowledge-base-visual";
type KB = { id: string; name: string };
type Source = {
  id: string;
  title: string;
  source_type: string;
  status: string;
  enabled_in_retrieval: boolean;
};
type SourceDetail = { source: Source; chunks: { id: string; chunk_index: number; content: string }[] };
type Operations = { jobs:{id:string;kind:string;status:string;error_code?:string}[]; index:{total:number;indexed:number;required:boolean} };
export function SourcesPanel() {
  const { t, errorText } = usePreferences();
  const [bases, setBases] = useState<KB[]>([]),
    [kb, setKb] = useState(""),
    [items, setItems] = useState<Source[]>([]),
    [selected, setSelected] = useState<string[]>([]);
  const [detail, setDetail] = useState<SourceDetail | null>(null), [targetChunk, setTargetChunk] = useState("");
  const [operations,setOperations]=useState<Operations|null>(null);
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [type, setType] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  async function refresh(id: string) {
    const [sources,ops]=await Promise.all([api<Source[]>(`/knowledge-bases/${id}/sources`),api<Operations>(`/knowledge-bases/${id}/operations`)]);setItems(sources);setOperations(ops);
    setSelected([]);
    setLoading(false);
  }
  useEffect(() => {
    api<KB[]>("/knowledge-bases")
      .then((rows) => {
        setBases(rows);
        const params=new URLSearchParams(window.location.search), requested=params.get("kb") || "";
        const selectedBase=rows.some((row)=>row.id===requested)?requested:rows[0]?.id || "";setKb(selectedBase);
        const source=params.get("source");setTargetChunk(params.get("chunk") || "");
        if (source && selectedBase) void api<SourceDetail>(`/knowledge-bases/${selectedBase}/sources/${source}`).then(setDetail).catch((error)=>setError(errorText(error)));
        if (!rows.length) setLoading(false);
      })
      .catch((error) => {
        setError(errorText(error));
        setLoading(false);
      });
  }, [errorText]);
  useEffect(() => {
    if (kb)
      void refresh(kb).catch((error) => {
        setError(errorText(error));
        setLoading(false);
      });
  }, [kb, errorText]);
  useEffect(()=>{ if(detail && targetChunk) window.setTimeout(()=>document.getElementById(`chunk-${targetChunk}`)?.scrollIntoView({block:"center"}),0); },[detail,targetChunk]);
  async function perform(
    action: () => Promise<unknown>,
    success = t.successNotice,
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh(kb);
      setNotice(success);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  const statusLabel = (value: string) =>
    ({
      ready: t.ready,
      approved: t.approved,
      processing: t.processing,
      archived: t.archived,
      failed: t.failed,
    })[value] || value;
  const typeLabel = (value: string) =>
    ({
      upload: t.uploadSource,
      website_snapshot: t.websiteSource,
      github_playbook: t.playbookSource,
    })[value] || value;
  const filtered = useMemo(
    () =>
      items.filter(
        (source) =>
          (!query ||
            source.title
              .toLocaleLowerCase()
              .includes(query.toLocaleLowerCase())) &&
          (!status || source.status === status) &&
          (!type || source.source_type === type),
      ),
    [items, query, status, type],
  );
  const counts = useMemo(
    () =>
      Object.fromEntries(
        ["ready", "approved", "archived", "failed"].map((value) => [
          value,
          items.filter((source) => source.status === value).length,
        ]),
      ),
    [items],
  );
  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void perform(async () => {
      await api(`/knowledge-bases/${kb}/sources/upload`, {
        method: "POST",
        body: new FormData(form),
      });
      form.reset();
    });
  }
  function site(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void perform(async () => {
      await api(`/knowledge-bases/${kb}/sources/site`, {
        method: "POST",
        body: JSON.stringify({ url: data.get("url") }),
      });
      form.reset();
    });
  }
  function bulk(action: "approve" | "archive" | "enable" | "disable") {
    if (action === "archive" && !window.confirm(t.confirmArchive)) return;
    void perform(() =>
      api(`/knowledge-bases/${kb}/sources/bulk`, {
        method: "POST",
        body: JSON.stringify({ source_ids: selected, action }),
      }),
    );
  }
  async function openDetail(source: Source) { setTargetChunk(""); setDetail(await api<SourceDetail>(`/knowledge-bases/${kb}/sources/${source.id}`)); }
  if (loading) return <p role="status">{t.loading}</p>;
  const currentBase = bases.find((base) => base.id === kb);
  return (
    <div className="stack page-shell">
      <div className="page-heading">
        <div>
          <h1>📄 {t.sources}</h1>
          {currentBase && (
            <p>
              {knowledgeBaseIcon(currentBase.id, currentBase.name)}{" "}
              {currentBase.name}
            </p>
          )}
        </div>
      </div>
      {error && (
        <ErrorToast
          message={error}
          onClose={() => setError("")}
          onRetry={() => kb && void refresh(kb)}
          retryLabel={t.retry}
        />
      )}{" "}
      {notice && (
        <ErrorToast
          kind="success"
          message={notice}
          onClose={() => setNotice("")}
        />
      )}
      <section className="panel stack">
        {bases.length ? (
          <>
            <div className="toolbar">
              <label>
                {t.chooseBase}
                <select
                  value={kb}
                  onChange={(event) => setKb(event.target.value)}
                >
                  {bases.map((base) => (
                    <option value={base.id} key={base.id}>
                      {base.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="source-ingestion-grid">
              <form className="row wrap" onSubmit={upload}>
                <input
                  aria-label={t.upload}
                  type="file"
                  name="file"
                  accept=".txt,.md,.pdf"
                  required
                />
                <button disabled={busy || !kb} className="primary">
                  ↑ {t.upload}
                </button>
              </form>
              <form className="row wrap" onSubmit={site}>
                <input
                  aria-label="URL"
                  name="url"
                  type="url"
                  placeholder="https://…"
                  required
                />
                <button disabled={busy || !kb} className="primary">
                  ＋ {t.addWebsite}
                </button>
              </form>
            </div>
            {(busy || operations) && <div className="operation-progress" role="status"><div className={busy?"progress-bar indeterminate":"progress-bar"}><span style={!busy && operations?.index.total?{width:`${Math.round(operations.index.indexed*100/operations.index.total)}%`}:undefined}/></div><span>{busy?t.processing:`${t.indexed}: ${operations?.index.indexed || 0}/${operations?.index.total || 0}`}</span></div>}
            <div className="source-stats" aria-label={t.status}>
              {["ready", "approved", "archived", "failed"].map((value) => (
                <button
                  type="button"
                  key={value}
                  className={status === value ? "selected" : ""}
                  onClick={() => setStatus(status === value ? "" : value)}
                >
                  <strong>{counts[value] || 0}</strong>
                  <span>{statusLabel(value)}</span>
                </button>
              ))}
            </div>
            <div className="toolbar source-filters">
              <label>
                <span>{t.search}</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t.search}
                />
              </label>
              <label>
                <span>{t.status}</span>
                <select
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                >
                  <option value="">{t.allStatuses}</option>
                  {[
                    "ready",
                    "approved",
                    "processing",
                    "archived",
                    "failed",
                  ].map((value) => (
                    <option value={value} key={value}>
                      {statusLabel(value)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>{t.sources}</span>
                <select
                  value={type}
                  onChange={(event) => setType(event.target.value)}
                >
                  <option value="">{t.allTypes}</option>
                  {["upload", "website_snapshot", "github_playbook"].map(
                    (value) => (
                      <option value={value} key={value}>
                        {typeLabel(value)}
                      </option>
                    ),
                  )}
                </select>
              </label>
            </div>
            {selected.length > 0 && (
              <div className="bulk-bar">
                <strong>
                  {t.selected}: {selected.length}
                </strong>
                <button disabled={busy} onClick={() => bulk("approve")}>
                  ✓ {t.publishSelected}
                </button>
                <button disabled={busy} onClick={() => bulk("archive")}>
                  {t.archiveSelected}
                </button>
                <button onClick={() => setSelected([])}>
                  {t.clearSelection}
                </button>
              </div>
            )}
            {filtered.length ? (
              <div className="source-list">
                <label className="select-all">
                  <input
                    type="checkbox"
                    checked={
                      filtered.length > 0 &&
                      filtered.every((source) => selected.includes(source.id))
                    }
                    onChange={(event) =>
                      setSelected(
                        event.target.checked
                          ? Array.from(
                              new Set([
                                ...selected,
                                ...filtered.map((source) => source.id),
                              ]),
                            )
                          : selected.filter(
                              (id) =>
                                !filtered.some((source) => source.id === id),
                            ),
                      )
                    }
                  />
                  {t.selectAll} · {filtered.length}
                </label>
                {filtered.map((source) => (
                  <article className="source-row" key={source.id}>
                    <input
                      aria-label={`${t.selected}: ${source.title}`}
                      type="checkbox"
                      checked={selected.includes(source.id)}
                      onChange={(event) =>
                        setSelected((rows) =>
                          event.target.checked
                            ? [...rows, source.id]
                            : rows.filter((id) => id !== source.id),
                        )
                      }
                    />
                    <div className="source-main">
                      <strong>{source.title}</strong>
                      <span className="muted">
                        {typeLabel(source.source_type)}
                      </span>
                    </div>
                    <span className={`status-badge status-${source.status}`}>
                      {statusLabel(source.status)}
                    </span>
                    <div className="source-actions">
                      <button disabled={busy} onClick={() => void openDetail(source).catch((error)=>setError(errorText(error)))}>{t.viewFragments}</button>
                      {["website_snapshot","github_playbook"].includes(source.source_type) && <button disabled={busy} onClick={() => void perform(() => api(`/knowledge-bases/${kb}/sources/${source.id}/refresh`,{method:"POST"}),t.sourceRefreshed)}>{t.refreshSource}</button>}
                      {source.status === "ready" && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void perform(() =>
                              api(
                                `/knowledge-bases/${kb}/sources/${source.id}/approve`,
                                { method: "POST" },
                              ),
                            )
                          }
                        >
                          {t.approve}
                        </button>
                      )}
                      {source.status === "approved" && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void perform(() =>
                              api(
                                `/knowledge-bases/${kb}/sources/${source.id}/retrieval?enabled=${!source.enabled_in_retrieval}`,
                                { method: "POST" },
                              ),
                            )
                          }
                        >
                          {source.enabled_in_retrieval ? t.disable : t.enable}
                        </button>
                      )}
                      <button
                        disabled={busy}
                        onClick={() =>
                          void perform(() =>
                            api(
                              `/knowledge-bases/${kb}/sources/${source.id}/archive`,
                              { method: "POST" },
                            ),
                          )
                        }
                      >
                        {t.archive}
                      </button>
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() =>
                          window.confirm(t.confirmDelete) &&
                          void perform(() =>
                            api(`/knowledge-bases/${kb}/sources/${source.id}`, {
                              method: "DELETE",
                            }),
                          )
                        }
                      >
                        {t.remove}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-action">
                <p>{items.length ? t.noResults : t.empty}</p>
              </div>
            )}
          </>
        ) : (
          <div className="empty-action">
            <p>{t.createBaseHint}</p>
            <a href="/manage" className="button-link primary">
              ＋ {t.newBase}
            </a>
          </div>
        )}
      </section>
      {detail && <div className="source-modal-backdrop" role="presentation" onMouseDown={(event)=>{if(event.target===event.currentTarget)setDetail(null);}}><section className="source-modal panel stack" role="dialog" aria-modal="true" aria-label={detail.source.title}><div className="row spread"><h2>{detail.source.title}</h2><button onClick={()=>setDetail(null)} aria-label={t.close}>×</button></div><div className="source-chunks">{detail.chunks.map((chunk)=><article id={`chunk-${chunk.id}`} className={targetChunk===chunk.id?"target-chunk":""} key={chunk.id}><strong>§{chunk.chunk_index+1}</strong><pre>{chunk.content}</pre></article>)}</div></section></div>}
    </div>
  );
}
