"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
import {
  knowledgeBaseIcon,
  knowledgeBaseIcons,
  saveKnowledgeBaseIcon,
} from "@/lib/knowledge-base-visual";

type KB = {
  id: string;
  name: string;
  description?: string;
  system_prompt?: string;
  publication_mode: string;
  chat_model_id?: string;
  embedding_model_id?: string;
  is_default: boolean;
  reindex_required: boolean;
  chunk_size_chars: number;
  chunk_overlap_chars: number;
};
type Conn = {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  has_api_key: boolean;
  timeout_s: number;
  retry_count: number;
  enabled: boolean;
};
type Model = {
  id: string;
  connection_id: string;
  name: string;
  model_id: string;
  capability: string;
  vector_size?: number;
  enabled: boolean;
};
type IndexStatus = {
  sources_count: number;
  chunks_count: number;
  indexed_chunks_count: number;
  reindex_required: boolean;
};

export function ManagePanel() {
  const { t, errorText } = usePreferences();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [connections, setConnections] = useState<Conn[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [indexes, setIndexes] = useState<Record<string, IndexStatus>>({});
  const [newKind, setNewKind] = useState("openrouter");
  const [playbookKb, setPlaybookKb] = useState("");
  const [modelCapability, setModelCapability] = useState("chat");
  const [availableModelIds, setAvailableModelIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [testingModelId, setTestingModelId] = useState("");
  const [probingNewModel, setProbingNewModel] = useState(false);
  const [detectedDimension, setDetectedDimension] = useState("");
  const [activeTab, setActiveTab] = useState<
    "bases" | "connections" | "models" | "import"
  >("bases");
  const [, setVisualVersion] = useState(0);
  const load = useCallback(async () => {
    const [a, b, c] = await Promise.all([
      api<KB[]>("/knowledge-bases"),
      api<Conn[]>("/settings/connections"),
      api<Model[]>("/settings/models"),
    ]);
    setKbs(a);
    setPlaybookKb((current) =>
      a.some((kb) => kb.id === current) ? current : a[0]?.id || "",
    );
    setConnections(b);
    setModels(c);
    const statuses = await Promise.all(
      a.map(
        async (kb) =>
          [
            kb.id,
            await api<IndexStatus>(`/knowledge-bases/${kb.id}/index-status`),
          ] as const,
      ),
    );
    setIndexes(Object.fromEntries(statuses));
    setLoading(false);
  }, []);
  useEffect(() => {
    const timer = setTimeout(
      () =>
        void load().catch((e) => {
          setError(errorText(e));
          setLoading(false);
        }),
      0,
    );
    return () => clearTimeout(timer);
  }, [load, errorText]);
  async function submit(
    e: FormEvent<HTMLFormElement>,
    path: string,
    payload: (form: FormData) => object,
  ) {
    e.preventDefault();
    setError("");
    setNotice("");
    const form = e.currentTarget;
    try {
      await api(path, {
        method: "POST",
        body: JSON.stringify(payload(new FormData(form))),
      });
      form.reset();
      await load();
      setNotice(t.saved);
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function mutate(path: string, method = "POST", body?: object) {
    setError("");
    setNotice("");
    try {
      const value = await api<{
        models?: string[];
        chat_available?: boolean | null;
        embeddings_available?: boolean | null;
        embedding_dimension?: number | null;
      }>(path, { method, body: body ? JSON.stringify(body) : undefined });
      const probe =
        value && ("chat_available" in value || "embeddings_available" in value)
          ? `${t.chatModel}: ${value.chat_available ? t.available : t.unavailable}; ${t.embeddingModel}: ${value.embeddings_available ? t.available : t.unavailable}${value.embedding_dimension ? ` (${value.embedding_dimension})` : ""}`
          : "";
      setNotice(probe || value?.models?.join(", ") || t.saved);
      await load();
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function patchKB(kb: KB, change: object) {
    await mutate(`/knowledge-bases/${kb.id}`, "PATCH", change);
  }
  const connectionPayload = (form: FormData) => ({
    name: form.get("name"),
    kind: form.get("kind"),
    base_url: form.get("base_url"),
    api_key: form.get("api_key") || null,
    timeout_s: Number(form.get("timeout_s")),
    retry_count: Number(form.get("retry_count")),
  });
  async function updateConnection(
    e: FormEvent<HTMLFormElement>,
    connection: Conn,
  ) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    await mutate(`/settings/connections/${connection.id}`, "PUT", {
      name: form.get("name"),
      kind: form.get("kind"),
      base_url: form.get("base_url"),
      api_key: form.get("api_key") || null,
      clear_api_key: form.get("clear_api_key") === "on",
      timeout_s: Number(form.get("timeout_s")),
      retry_count: Number(form.get("retry_count")),
      enabled: connection.enabled,
    });
  }
  async function discoverModelIds(form: HTMLFormElement) {
    setError("");
    try {
      const connectionId = String(new FormData(form).get("connection_id"));
      const value = await api<{ models: { id: string }[] }>(
        `/settings/connections/${connectionId}/models`,
      );
      setAvailableModelIds(value.models.map((model) => model.id));
      setNotice(value.models.length ? t.modelIdsLoaded : t.noModelIds);
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function testModel(model: Model) {
    setError("");
    setNotice("");
    setTestingModelId(model.id);
    try {
      const value = await api<{
        ok: boolean;
        capability: string;
        dimension?: number;
        expected_dimension?: number;
        latency_ms: number;
      }>(`/settings/models/${model.id}/test`, { method: "POST" });
      if (!value.ok) {
        if (model.capability === "embedding" && value.dimension) {
          await mutate(`/settings/models/${model.id}`, "PATCH", {
            vector_size: value.dimension,
          });
          setNotice(
            `${t.modelAvailable} · ${t.vectorSize}: ${value.dimension}`,
          );
        } else
          setError(
            `${t.vectorSize}: ${value.dimension} ≠ ${value.expected_dimension}`,
          );
        return;
      }
      setNotice(
        `${t.modelAvailable} · ${Math.round(value.latency_ms)} ms${value.dimension ? ` · ${t.vectorSize}: ${value.dimension}` : ""}`,
      );
    } catch (error) {
      setError(errorText(error));
    } finally {
      setTestingModelId("");
    }
  }
  async function probeNewModel(form: HTMLFormElement) {
    setError("");
    setNotice("");
    setProbingNewModel(true);
    try {
      const data = new FormData(form),
        capability = String(data.get("capability")),
        modelId = String(data.get("model_id") || "");
      if (!modelId) {
        form.reportValidity();
        return;
      }
      const value = await api<{
        ok: boolean;
        dimension?: number;
        latency_ms: number;
      }>("/settings/models/probe", {
        method: "POST",
        body: JSON.stringify({
          connection_id: data.get("connection_id"),
          model_id: modelId,
          capability,
        }),
      });
      if (value.dimension) {
        setDetectedDimension(String(value.dimension));
        setNotice(
          `${t.modelAvailable} · ${t.vectorSize}: ${value.dimension} · ${Math.round(value.latency_ms)} ms`,
        );
      } else
        setNotice(`${t.modelAvailable} · ${Math.round(value.latency_ms)} ms`);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setProbingNewModel(false);
    }
  }
  async function remove(path: string) {
    if (window.confirm(t.confirmDelete)) await mutate(path, "DELETE");
  }
  if (loading) return <p role="status">{t.loading}</p>;
  return (
    <div className="stack">
      <h1>⚙️ {t.settings}</h1>
      {error && (
        <ErrorToast
          message={error}
          onClose={() => setError("")}
          onRetry={() => void load()}
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
      <div className="section-tabs" role="tablist" aria-label={t.settings}>
        {[
          ["bases", "📚", t.manageBases],
          ["connections", "🔌", t.manageConnections],
          ["models", "🤖", t.manageModels],
          ["import", "↓", t.manageImport],
        ].map(([id, icon, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={activeTab === id}
            className={activeTab === id ? "selected" : ""}
            onClick={() => setActiveTab(id as typeof activeTab)}
          >
            {icon} {label}
          </button>
        ))}
      </div>
      <section
        className="panel stack manage-section"
        hidden={activeTab !== "bases"}
      >
        <h2>{t.bases}</h2>
        <form
          className="row wrap"
          onSubmit={(e) =>
            submit(e, "/knowledge-bases", (form) => ({
              name: form.get("name"),
              description: form.get("description") || null,
              publication_mode: form.get("publication_mode"),
              is_default: !kbs.length,
            }))
          }
        >
          <input
            name="name"
            aria-label={t.name}
            placeholder={t.name}
            required
          />
          <input
            name="description"
            aria-label={t.description}
            placeholder={t.description}
          />
          <select name="publication_mode" aria-label={t.publication}>
            <option value="manual">{t.manual}</option>
            <option value="automatic">{t.automatic}</option>
          </select>
          <button className="primary">{t.newBase}</button>
        </form>
        {kbs.length ? (
          kbs.map((kb) => {
            const status = indexes[kb.id];
            return (
              <details className="panel kb-card" key={kb.id}>
                <summary className="kb-summary">
                  <span>
                    <strong>
                      {knowledgeBaseIcon(kb.id, kb.name)} {kb.name}
                    </strong>
                    {kb.description && (
                      <small className="muted">{kb.description}</small>
                    )}
                  </span>
                  <span className={kb.reindex_required ? "warning" : "muted"}>
                    {kb.reindex_required ? t.indexRequired : t.indexReady} ·{" "}
                    {status?.sources_count || 0}
                  </span>
                </summary>
                <div className="stack kb-content">
                  <div className="row spread">
                    <strong>{t.details}</strong>
                    <button
                      className="danger"
                      onClick={() =>
                        void remove(`/knowledge-bases/${kb.id}?confirm=true`)
                      }
                    >
                      {t.remove}
                    </button>
                  </div>
                  <div className="row wrap">
                    <label>
                      {t.baseIcon}
                      <select
                        value={knowledgeBaseIcon(kb.id, kb.name)}
                        onChange={(event) => {
                          saveKnowledgeBaseIcon(kb.id, event.target.value);
                          setVisualVersion((value) => value + 1);
                        }}
                      >
                        {knowledgeBaseIcons.map((icon) => (
                          <option value={icon} key={icon}>
                            {icon}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t.publication}
                      <select
                        value={kb.publication_mode}
                        onChange={(e) =>
                          void patchKB(kb, { publication_mode: e.target.value })
                        }
                      >
                        <option value="manual">{t.manual}</option>
                        <option value="automatic">{t.automatic}</option>
                      </select>
                    </label>
                    <label>
                      {t.chatModel}
                      <select
                        value={kb.chat_model_id || ""}
                        onChange={(e) =>
                          void patchKB(kb, {
                            chat_model_id: e.target.value || null,
                          })
                        }
                      >
                        <option value="">{t.noModel}</option>
                        {models
                          .filter(
                            (model) =>
                              model.capability === "chat" && model.enabled,
                          )
                          .map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      {t.embeddingModel}
                      <select
                        value={kb.embedding_model_id || ""}
                        onChange={(e) =>
                          void patchKB(kb, {
                            embedding_model_id: e.target.value || null,
                          })
                        }
                      >
                        <option value="">{t.noModel}</option>
                        {models
                          .filter(
                            (model) =>
                              model.capability === "embedding" && model.enabled,
                          )
                          .map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.name}
                            </option>
                          ))}
                      </select>
                    </label>
                  </div>
                  <form
                    className="stack"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = new FormData(e.currentTarget);
                      void patchKB(kb, {
                        system_prompt: form.get("system_prompt") || null,
                      });
                    }}
                  >
                    <label>
                      {t.systemPrompt}
                      <textarea
                        name="system_prompt"
                        defaultValue={kb.system_prompt || ""}
                        placeholder={t.systemPromptPlaceholder}
                        maxLength={12000}
                        rows={5}
                      />
                    </label>
                    <p className="muted">{t.systemPromptHelp}</p>
                    <div>
                      <button>{t.savePrompt}</button>
                    </div>
                  </form>
                  <form className="row wrap" onSubmit={(event) => { event.preventDefault(); const form=new FormData(event.currentTarget); void patchKB(kb,{chunk_size_chars:Number(form.get("chunk_size_chars")),chunk_overlap_chars:Number(form.get("chunk_overlap_chars"))}); }}>
                    <label>{t.chunkSize}<input name="chunk_size_chars" type="number" min="200" max="8000" defaultValue={kb.chunk_size_chars}/></label>
                    <label>{t.chunkOverlap}<input name="chunk_overlap_chars" type="number" min="0" max="4000" defaultValue={kb.chunk_overlap_chars}/></label>
                    <button>{t.saveChunking}</button>
                    <small className="muted">{t.chunkingHelp}</small>
                  </form>
                  <p className={kb.reindex_required ? "warning" : "muted"}>
                    {kb.reindex_required ? t.indexRequired : t.indexReady} ·{" "}
                    {t.sourcesCount}: {status?.sources_count || 0} ·{" "}
                    {t.chunksCount}: {status?.chunks_count || 0}
                  </p>
                  <div className="row wrap">
                    <button
                      onClick={() =>
                        void mutate(`/knowledge-bases/${kb.id}/reindex`)
                      }
                    >
                      {t.reindex}
                    </button>
                  </div>
                </div>
              </details>
            );
          })
        ) : (
          <p className="muted">{t.empty}</p>
        )}
      </section>
      <section
        className="panel stack manage-section"
        hidden={activeTab !== "connections"}
      >
        <h2>🔌 {t.connections}</h2>
        <div className="provider-tabs" role="group" aria-label={t.connections}>
          {[
            ["openrouter", "☁️ OpenRouter"],
            ["lm_studio", "🖥️ LM Studio"],
            ["openai_compatible", "🔗 OpenAI compatible"],
          ].map(([kind, label]) => (
            <button
              type="button"
              className={newKind === kind ? "selected" : undefined}
              aria-pressed={newKind === kind}
              onClick={() => setNewKind(kind)}
              key={kind}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="provider-form">
          <p className="muted">
            {newKind === "lm_studio"
              ? t.lmHelp
              : newKind === "openrouter"
                ? t.openRouterHelp
                : t.compatibleHelp}
          </p>
          <form
            className="row wrap"
            key={newKind}
            onSubmit={(e) =>
              submit(e, "/settings/connections", connectionPayload)
            }
          >
            <input type="hidden" name="kind" value={newKind} />
            <input
              name="name"
              aria-label={t.name}
              placeholder={t.name}
              required
            />
            <input
              name="base_url"
              aria-label="Base URL"
              defaultValue={
                newKind === "lm_studio"
                  ? "http://host.docker.internal:1234/v1"
                  : newKind === "openrouter"
                    ? "https://openrouter.ai/api/v1"
                    : "https://"
              }
              required
            />
            <input
              name="api_key"
              aria-label={t.apiKey}
              type="password"
              autoComplete="off"
              placeholder={t.apiKey}
            />
            <input
              name="timeout_s"
              aria-label={t.timeout}
              type="number"
              min="1"
              max="120"
              defaultValue="30"
            />
            <input
              name="retry_count"
              aria-label={t.retries}
              type="number"
              min="0"
              max="5"
              defaultValue="2"
            />
            <button
              type="button"
              onClick={(event) => {
                const form = event.currentTarget.form;
                if (form?.reportValidity())
                  void mutate(
                    "/settings/connections/test",
                    "POST",
                    connectionPayload(new FormData(form)),
                  );
              }}
            >
              {t.test}
            </button>
            <button className="primary">{t.save}</button>
          </form>
        </div>
        {(["openrouter", "lm_studio", "openai_compatible"] as const).map(
          (kind) => {
            const rows = connections.filter(
              (connection) => connection.kind === kind,
            );
            return rows.length ? (
              <div className="connection-group stack" key={kind}>
                <h3>
                  {kind === "openrouter"
                    ? "☁️ OpenRouter"
                    : kind === "lm_studio"
                      ? "🖥️ LM Studio"
                      : "🔗 OpenAI compatible"}
                </h3>
                {rows.map((connection) => (
                  <article className="panel stack" key={connection.id}>
                    <div className="row spread">
                      <div>
                        <strong>{connection.name}</strong>
                        <span className="muted">
                          {" "}
                          · {connection.base_url} ·{" "}
                          {connection.has_api_key ? "••••••" : "—"}
                        </span>
                      </div>
                      <div className="row">
                        <button
                          onClick={() =>
                            void mutate(
                              `/settings/connections/${connection.id}/test`,
                            )
                          }
                        >
                          {t.test}
                        </button>
                        <button
                          className="danger"
                          onClick={() =>
                            void remove(
                              `/settings/connections/${connection.id}`,
                            )
                          }
                        >
                          {t.remove}
                        </button>
                      </div>
                    </div>
                    <form
                      className="row wrap"
                      onSubmit={(e) => void updateConnection(e, connection)}
                    >
                      <input
                        name="name"
                        aria-label={t.name}
                        defaultValue={connection.name}
                        required
                      />
                      <input
                        type="hidden"
                        name="kind"
                        value={connection.kind}
                      />
                      <input
                        name="base_url"
                        aria-label="Base URL"
                        defaultValue={connection.base_url}
                        required
                      />
                      <input
                        name="api_key"
                        aria-label={t.apiKey}
                        type="password"
                        autoComplete="off"
                        placeholder={t.apiKey}
                      />
                      <label>
                        <input name="clear_api_key" type="checkbox" />{" "}
                        {t.clearKey}
                      </label>
                      <input
                        name="timeout_s"
                        aria-label={t.timeout}
                        type="number"
                        min="1"
                        max="120"
                        defaultValue={connection.timeout_s}
                      />
                      <input
                        name="retry_count"
                        aria-label={t.retries}
                        type="number"
                        min="0"
                        max="5"
                        defaultValue={connection.retry_count}
                      />
                      <button>{t.save}</button>
                    </form>
                  </article>
                ))}
              </div>
            ) : null;
          },
        )}
      </section>
      <section
        className="panel stack manage-section"
        hidden={activeTab !== "models"}
      >
        <h2>{t.models}</h2>
        <p className="muted">{t.modelIdHelp}</p>
        {connections.length ? (
          <form
            className="row wrap"
            onSubmit={(e) =>
              submit(e, "/settings/models", (form) => ({
                connection_id: form.get("connection_id"),
                name: form.get("name") || form.get("model_id"),
                model_id: form.get("model_id"),
                capability: form.get("capability"),
                vector_size:
                  form.get("capability") === "embedding"
                    ? Number(form.get("vector_size"))
                    : null,
              }))
            }
          >
            <select
              name="connection_id"
              aria-label={t.connections}
              onChange={() => setAvailableModelIds([])}
            >
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={(event) => {
                const form = event.currentTarget.form;
                if (form) void discoverModelIds(form);
              }}
            >
              {t.loadModelIds}
            </button>
            <input
              name="name"
              aria-label={t.name}
              placeholder={t.displayName}
            />
            <input
              name="model_id"
              list="provider-model-ids"
              aria-label={t.modelId}
              placeholder={t.modelId}
              required
            />
            <datalist id="provider-model-ids">
              {availableModelIds.map((id) => (
                <option value={id} key={id} />
              ))}
            </datalist>
            <select
              name="capability"
              aria-label={t.models}
              value={modelCapability}
              onChange={(event) => setModelCapability(event.target.value)}
            >
              <option value="chat">Chat</option>
              <option value="embedding">Embedding</option>
            </select>
            {modelCapability === "embedding" && (
              <label className="vector-size-field">
                {t.vectorSize}
                <input
                  name="vector_size"
                  list="vector-size-options"
                  aria-label={t.vectorSize}
                  type="number"
                  min="1"
                  placeholder="—"
                  value={detectedDimension}
                  onChange={(event) => setDetectedDimension(event.target.value)}
                  required
                />
                <datalist id="vector-size-options">
                  {[384, 512, 768, 1024, 1536, 3072, 4096].map((size) => (
                    <option value={size} key={size} />
                  ))}
                </datalist>
                <small className="muted">{t.vectorSizeHelp}</small>
              </label>
            )}
            <button
              type="button"
              disabled={probingNewModel}
              onClick={(event) =>
                event.currentTarget.form &&
                void probeNewModel(event.currentTarget.form)
              }
            >
              {probingNewModel ? `${t.loading}` : `↗ ${t.testModel}`}
            </button>
            <button className="primary">{t.save}</button>
          </form>
        ) : (
          <p className="muted">{t.createConnectionFirst}</p>
        )}
        {models.map((model) => (
          <article className="row wrap" key={model.id}>
            <strong>{model.name}</strong>
            <span className="muted">
              {model.capability} · {model.model_id}
            </span>
            <button
              disabled={testingModelId === model.id}
              onClick={() => void testModel(model)}
            >
              {testingModelId === model.id ? t.loading : `↗ ${t.testModel}`}
            </button>
            <button
              className="danger"
              onClick={() => void remove(`/settings/models/${model.id}`)}
            >
              {t.remove}
            </button>
          </article>
        ))}
      </section>
      <details
        className="panel playbook-card manage-section"
        hidden={activeTab !== "import"}
        open
      >
        <summary className="playbook-summary">
          <span className="playbook-heading">
            <strong>🛡️ {t.playbookTitle}</strong>
            <small className="author">{t.playbookAuthor}</small>
          </span>
          <span className="repo-badge">
            GitHub · defrixx/Product-security-playbook
          </span>
          <span className="disclosure" aria-hidden="true">
            ⌄
          </span>
        </summary>
        <div className="playbook-content stack">
          <p className="muted">{t.playbookDescription}</p>
          {kbs.length ? (
            <div className="row wrap">
              <label>
                {t.playbookTarget}
                <select
                  value={playbookKb}
                  onChange={(event) => setPlaybookKb(event.target.value)}
                >
                  {kbs.map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                disabled={!playbookKb}
                onClick={() =>
                  void mutate(`/knowledge-bases/${playbookKb}/playbook/sync`)
                }
              >
                ↓ {t.syncPlaybook}
              </button>
            </div>
          ) : (
            <div className="empty-action">
              <p>{t.createBaseHint}</p>
              <a href="/manage" className="button-link primary">
                ＋ {t.newBase}
              </a>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
