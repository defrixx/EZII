"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
import {MaintenancePanel} from "./maintenance-panel";
type KB = { id: string; name: string };
type Model = { id: string; name: string; model_id: string };
type Chat = { id: string; title: string };
type SourceRef = { id: string; title: string; source_type: string };
type Rank = { chunk_id: string; source_id: string; score: number };
type Trace = {
  id: string;
  chat_id: string;
  model_endpoint_id?: string;
  answer_mode: string;
  status: string;
  source_types: string[];
  source_ids: string[];
  warning_codes: string[];
  latency_ms: number;
  ranking_scores?: {
    query?: string;
    matched_chunks?: number;
    vector_ranked?: boolean;
    retrieval_method?: string;
    retrieval_ms?: number;
    sources?: SourceRef[];
    ranked_chunks?: Rank[];
  };
  token_usage?: Record<string, number>;
  created_at: string;
};
type Statistics = { queries:number; grounded:number; no_results:number; average_latency_ms:number; sources:number; chunks:number; top_sources:{id:string;title:string;uses:number}[]; recent_no_result_queries:string[] };
type Quality = { questions:number; covered:number; coverage_percent:number; results:{question:string;matched_chunks:number;top_score:number}[] };
export function DiagnosticsPanel() {
  const { t, locale, errorText } = usePreferences();
  const [bases, setBases] = useState<KB[]>([]),
    [models, setModels] = useState<Model[]>([]),
    [chats, setChats] = useState<Chat[]>([]),
    [kb, setKb] = useState(""),
    [rows, setRows] = useState<Trace[]>([]),
    [statusFilter, setStatusFilter] = useState(""),
    [query, setQuery] = useState(""),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [statistics,setStatistics]=useState<Statistics|null>(null),[quality,setQuality]=useState<Quality|null>(null),[qualityQuestions,setQualityQuestions]=useState("");
  useEffect(() => {
    Promise.all([
      api<KB[]>("/knowledge-bases"),
      api<Trace[]>("/diagnostics/traces"),
      api<Model[]>("/settings/models"),
      api<Chat[]>("/chats"),
    ])
      .then(([knowledgeBases, traces, endpoints, chatRows]) => {
        setBases(knowledgeBases);
        setRows(traces);
        setModels(endpoints);
        setChats(chatRows);
        setLoading(false);
      })
      .catch((error) => {
        setError(errorText(error));
        setLoading(false);
      });
  }, [errorText]);
  async function filter(id: string) {
    setKb(id);
    setLoading(true);
    setError("");
    try {
      setRows(
        await api<Trace[]>(
          `/diagnostics/traces${id ? `?knowledge_base_id=${id}` : ""}`,
        ),
      );
      setStatistics(id ? await api<Statistics>(`/knowledge-bases/${id}/statistics`) : null);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setLoading(false);
    }
  }
  async function checkQuality() { if(!kb)return; const questions=qualityQuestions.split("\n").map((value)=>value.trim()).filter(Boolean); if(!questions.length)return; setLoading(true);try{setQuality(await api<Quality>(`/knowledge-bases/${kb}/quality/check`,{method:"POST",body:JSON.stringify({questions})}));}catch(error){setError(errorText(error));}finally{setLoading(false);} }
  const visible = useMemo(
    () =>
      rows.filter(
        (trace) =>
          (!statusFilter || trace.status === statusFilter) &&
          (!query ||
            (trace.ranking_scores?.query || "")
              .toLocaleLowerCase()
              .includes(query.toLocaleLowerCase())),
      ),
    [rows, statusFilter, query],
  );
  const status = (value: string) =>
    value === "ok" ? t.ok : value === "degraded" ? t.degraded : value;
  const mode = (value: string) =>
    value === "grounded"
      ? t.grounded
      : value === "model_only"
        ? t.modelOnly
        : value;
  if (loading) return <p role="status">{t.loading}</p>;
  return (
    <div className="stack page-shell">
      <div className="page-heading">
        <h1>📊 {t.diagnostics}</h1>
      </div>
      {error && <ErrorToast message={error} onClose={() => setError("")} />}
      <section className="panel stack">
        {bases.length ? (
          <>
            <div className="toolbar diagnostic-toolbar">
              <label>
                {t.chooseBase}
                <select
                  value={kb}
                  onChange={(event) => void filter(event.target.value)}
                >
                  <option value="">{t.allBases}</option>
                  {bases.map((base) => (
                    <option key={base.id} value={base.id}>
                      {base.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="search-field">
                {t.search}
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <label>
                {t.status}
                <select
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value="">{t.allStatuses}</option>
                  <option value="ok">{t.ok}</option>
                  <option value="degraded">{t.degraded}</option>
                </select>
              </label>
            </div>
            {statistics && <div className="source-stats diagnostic-stats"><div><strong>{statistics.queries}</strong><span>{t.totalQueries}</span></div><div><strong>{statistics.grounded}</strong><span>{t.groundedAnswers}</span></div><div><strong>{statistics.no_results}</strong><span>{t.noResultAnswers}</span></div><div><strong>{Math.round(statistics.average_latency_ms)} ms</strong><span>{t.averageLatency}</span></div></div>}
            {kb && <details className="diagnostic-card"><summary>{t.qualityCheck}</summary><div className="stack quality-check"><p className="muted">{t.qualityHelp}</p><textarea rows={5} value={qualityQuestions} onChange={(event)=>setQualityQuestions(event.target.value)} placeholder={t.qualityPlaceholder}/><button className="primary" onClick={()=>void checkQuality()}>{t.runCheck}</button>{quality && <><strong>{t.coverage}: {quality.coverage_percent}% ({quality.covered}/{quality.questions})</strong><ul>{quality.results.map((result)=><li key={result.question}>{result.matched_chunks?"✓":"⚠"} {result.question} · {result.matched_chunks} {t.matchedChunks.toLocaleLowerCase()}</li>)}</ul></>}</div></details>}
            {visible.length ? (
              <div className="diagnostic-list">
                {visible.map((trace) => {
                  const model = models.find(
                      (item) => item.id === trace.model_endpoint_id,
                    ),
                    chat = chats.find((item) => item.id === trace.chat_id),
                    usage = trace.token_usage || {},
                    retrieval = trace.ranking_scores?.retrieval_ms,
                    generation =
                      retrieval === undefined
                        ? undefined
                        : Math.max(0, trace.latency_ms - retrieval),
                    sources = trace.ranking_scores?.sources || [],
                    ranks = trace.ranking_scores?.ranked_chunks || [],
                    limited = !trace.ranking_scores?.query;
                  return (
                    <details className="diagnostic-card" key={trace.id}>
                      <summary>
                        <div>
                          <time>
                            {new Intl.DateTimeFormat(locale, {
                              dateStyle: "short",
                              timeStyle: "medium",
                            }).format(new Date(trace.created_at))}
                          </time>
                          <strong>
                            {trace.ranking_scores?.query || chat?.title || "—"}
                          </strong>
                        </div>
                        <span className={`status-badge status-${trace.status}`}>
                          {status(trace.status)}
                        </span>
                        <span>{mode(trace.answer_mode)}</span>
                        <span aria-hidden="true">⌄</span>
                      </summary>
                      <div className="diagnostic-details">
                        {limited && <p className="warning">{t.limitedTrace}</p>}
                        <dl>
                          <div>
                            <dt>{t.chatModel}</dt>
                            <dd>
                              {model
                                ? `${model.name} · ${model.model_id}`
                                : "—"}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.retrievalTime}</dt>
                            <dd>
                              {retrieval === undefined
                                ? "—"
                                : `${Math.round(retrieval)} ms`}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.generationTime}</dt>
                            <dd>
                              {generation === undefined
                                ? "—"
                                : `${Math.round(generation)} ms`}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.latency}</dt>
                            <dd>{Math.round(trace.latency_ms)} ms</dd>
                          </div>
                          <div>
                            <dt>{t.matchedChunks}</dt>
                            <dd>
                              {trace.ranking_scores?.matched_chunks ??
                                trace.source_ids.length}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.retrievalMethod}</dt>
                            <dd>
                              {trace.ranking_scores?.retrieval_method === "hybrid" ? t.hybridSearch : trace.ranking_scores?.vector_ranked ? t.vectorSearch : t.textSearch}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.promptTokens}</dt>
                            <dd>
                              {usage.prompt_tokens ?? usage.input_tokens ?? "—"}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.completionTokens}</dt>
                            <dd>
                              {usage.completion_tokens ??
                                usage.output_tokens ??
                                "—"}
                            </dd>
                          </div>
                          <div>
                            <dt>{t.totalTokens}</dt>
                            <dd>{usage.total_tokens ?? "—"}</dd>
                          </div>
                          <div>
                            <dt>{t.warnings}</dt>
                            <dd>
                              {trace.warning_codes.length
                                ? trace.warning_codes
                                    .map((code) =>
                                      code === "vector_retrieval_unavailable"
                                        ? t.vectorUnavailable
                                        : code,
                                    )
                                    .join(", ")
                                : "—"}
                            </dd>
                          </div>
                        </dl>
                        <div>
                          <h3>{t.sourceDocuments}</h3>
                          {sources.length ? (
                            <ul>
                              {sources.map((source) => (
                                <li key={source.id}>
                                  <a href="/sources">{source.title}</a>{" "}
                                  <span className="muted">
                                    · {source.source_type}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="muted">—</p>
                          )}
                        </div>
                        {ranks.length > 0 && (
                          <details className="technical-details">
                            <summary>{t.responseDetails}</summary>
                            <ol>
                              {ranks.map((rank) => (
                                <li key={rank.chunk_id}>
                                  <code>{rank.chunk_id}</code> · {rank.score}
                                </li>
                              ))}
                            </ol>
                          </details>
                        )}
                      </div>
                    </details>
                  );
                })}
              </div>
            ) : (
              <div className="empty-action">
                <p>{rows.length ? t.noResults : t.empty}</p>
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
      <MaintenancePanel embedded/>
    </div>
  );
}
