"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { clearSession, redirectToAuth, showReloginNoticeOnce } from "@/lib/auth";

type Glossary = { id: string; term: string; definition: string; priority: number; status: string };
type GlossarySet = {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  enabled: boolean;
  is_default: boolean;
};
type Domain = { id: string; domain: string; notes: string | null; enabled: boolean };
type Trace = { id: string; model: string; status: string; latency_ms: number; created_at: string };
type PendingRegistration = {
  id: string;
  username: string;
  email: string | null;
  tenant_id: string;
  enabled: boolean;
  created_at: string | null;
};
type Provider = {
  id: string;
  base_url: string;
  api_key: string;
  model_name: string;
  embedding_model: string;
  timeout_s: number;
  retry_policy: number;
  strict_glossary_mode: boolean;
  web_enabled: boolean;
  show_confidence: boolean;
  show_source_tags: boolean;
  response_tone: string;
  max_user_messages_total: number;
};
type ProviderDraft = {
  base_url: string;
  api_key: string;
  model_name: string;
  embedding_model: string;
  timeout_s: number;
  retry_policy: number;
  strict_glossary_mode: boolean;
  web_enabled: boolean;
  show_confidence: boolean;
  show_source_tags: boolean;
  response_tone: "consultative_supportive" | "neutral_reference";
  max_user_messages_total: number;
};

type LogItem = { id: string; type: string; message: string; created_at: string };

const PAGE_SIZE_OPTIONS = [5, 10] as const;
const DEFAULT_PROVIDER_DRAFT: ProviderDraft = {
  base_url: "https://openrouter.ai/api/v1",
  api_key: "",
  model_name: "openai/gpt-4o-mini",
  embedding_model: "text-embedding-3-small",
  timeout_s: 30,
  retry_policy: 2,
  strict_glossary_mode: false,
  web_enabled: false,
  show_confidence: false,
  show_source_tags: true,
  response_tone: "consultative_supportive",
  max_user_messages_total: 5,
};

export function AdminPanel() {
  const [glossarySets, setGlossarySets] = useState<GlossarySet[]>([]);
  const [selectedGlossaryId, setSelectedGlossaryId] = useState<string>("");
  const [glossaryEntries, setGlossaryEntries] = useState<Glossary[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [pendingRegistrations, setPendingRegistrations] = useState<PendingRegistration[]>([]);
  const [glossaryName, setGlossaryName] = useState("");
  const [glossaryDescription, setGlossaryDescription] = useState("");
  const [glossaryPriority, setGlossaryPriority] = useState<number>(100);
  const [term, setTerm] = useState("");
  const [definition, setDefinition] = useState("");
  const [domain, setDomain] = useState("");
  const [domainNotes, setDomainNotes] = useState("");
  const [provider, setProvider] = useState<Provider | null>(null);
  const [providerDraft, setProviderDraft] = useState<ProviderDraft>(DEFAULT_PROVIDER_DRAFT);
  const [error, setError] = useState<string | null>(null);
  const [providerSaving, setProviderSaving] = useState(false);
  const [providerSaveStatus, setProviderSaveStatus] = useState<"idle" | "success" | "error">("idle");

  const [glossaryPage, setGlossaryPage] = useState(1);
  const [glossaryPageSize, setGlossaryPageSize] = useState<number>(5);
  const [glossarySetPage, setGlossarySetPage] = useState(1);
  const [glossarySetPageSize, setGlossarySetPageSize] = useState<number>(5);
  const [allowlistPage, setAllowlistPage] = useState(1);
  const [allowlistPageSize, setAllowlistPageSize] = useState<number>(5);

  const [editingGlossary, setEditingGlossary] = useState<Glossary | null>(null);
  const [editTerm, setEditTerm] = useState("");
  const [editDefinition, setEditDefinition] = useState("");

  const glossaryTotalPages = Math.max(1, Math.ceil(glossaryEntries.length / glossaryPageSize));
  const glossarySetTotalPages = Math.max(1, Math.ceil(glossarySets.length / glossarySetPageSize));
  const allowlistTotalPages = Math.max(1, Math.ceil(domains.length / allowlistPageSize));

  useEffect(() => {
    if (glossaryPage > glossaryTotalPages) setGlossaryPage(glossaryTotalPages);
  }, [glossaryPage, glossaryTotalPages]);

  useEffect(() => {
    if (glossarySetPage > glossarySetTotalPages) setGlossarySetPage(glossarySetTotalPages);
  }, [glossarySetPage, glossarySetTotalPages]);

  useEffect(() => {
    if (allowlistPage > allowlistTotalPages) setAllowlistPage(allowlistTotalPages);
  }, [allowlistPage, allowlistTotalPages]);

  const glossaryRows = useMemo(() => {
    const start = (glossaryPage - 1) * glossaryPageSize;
    return glossaryEntries.slice(start, start + glossaryPageSize);
  }, [glossaryEntries, glossaryPage, glossaryPageSize]);

  const glossarySetRows = useMemo(() => {
    const start = (glossarySetPage - 1) * glossarySetPageSize;
    return glossarySets.slice(start, start + glossarySetPageSize);
  }, [glossarySets, glossarySetPage, glossarySetPageSize]);

  const allowlistRows = useMemo(() => {
    const start = (allowlistPage - 1) * allowlistPageSize;
    return domains.slice(start, start + allowlistPageSize);
  }, [domains, allowlistPage, allowlistPageSize]);
  const selectedGlossary = useMemo(
    () => glossarySets.find((g) => g.id === selectedGlossaryId) || null,
    [glossarySets, selectedGlossaryId],
  );

  function glossaryLabel(row: GlossarySet): string {
    const suffix = row.is_default ? "по умолчанию" : `приоритет ${row.priority}`;
    return `${row.name} (${suffix})`;
  }

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [g, d, t, l, pending] = await Promise.all([
        api<GlossarySet[]>("/glossary"),
        api<Domain[]>("/admin/allowlist"),
        api<Trace[]>("/admin/traces"),
        api<LogItem[]>("/admin/logs"),
        api<PendingRegistration[]>("/admin/registrations/pending"),
      ]);
      setGlossarySets(g);
      const selected = g.find((x) => x.id === selectedGlossaryId) || g[0];
      const nextGlossaryId = selected?.id || "";
      setSelectedGlossaryId(nextGlossaryId);
      if (nextGlossaryId) {
        const entries = await api<Glossary[]>(`/glossary/${nextGlossaryId}/entries`);
        setGlossaryEntries(entries);
      } else {
        setGlossaryEntries([]);
      }
      setDomains(d);
      setTraces(t.slice(0, 3));
      setLogs(l.slice(0, 10));
      setPendingRegistrations(pending);
      try {
        const p = await api<Provider>("/admin/provider");
        setProvider(p);
      } catch {
        setProvider(null);
      }
    } catch (e: any) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      setError(e.message || "Не удалось загрузить данные админки");
    }
  }, [selectedGlossaryId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!selectedGlossaryId) {
      setGlossaryEntries([]);
      return;
    }
    void api<Glossary[]>(`/glossary/${selectedGlossaryId}/entries`)
      .then((rows) => setGlossaryEntries(rows))
      .catch(() => setGlossaryEntries([]));
  }, [selectedGlossaryId]);

  async function addGlossary() {
    if (!selectedGlossaryId) return;
    if (!term.trim() || !definition.trim()) return;
    await api(`/glossary/${selectedGlossaryId}/entries`, {
      method: "POST",
      body: JSON.stringify({ term: term.trim(), definition: definition.trim(), synonyms: [], forbidden_interpretations: [] }),
    });
    setTerm("");
    setDefinition("");
    await loadAll();
  }

  function openGlossaryModal(entry: Glossary) {
    setEditingGlossary(entry);
    setEditTerm(entry.term);
    setEditDefinition(entry.definition);
  }

  function closeGlossaryModal() {
    setEditingGlossary(null);
    setEditTerm("");
    setEditDefinition("");
  }

  async function saveGlossaryModal() {
    if (!editingGlossary || !selectedGlossaryId) return;
    await api(`/glossary/${selectedGlossaryId}/entries/${editingGlossary.id}`, {
      method: "PATCH",
      body: JSON.stringify({ term: editTerm.trim(), definition: editDefinition.trim() }),
    });
    closeGlossaryModal();
    await loadAll();
  }

  async function deleteGlossary(id: string) {
    if (!selectedGlossaryId) return;
    const ok = window.confirm("Удалить запись глоссария?");
    if (!ok) return;
    await api(`/glossary/${selectedGlossaryId}/entries/${id}`, { method: "DELETE" });
    await loadAll();
  }

  async function addGlossarySet() {
    if (!glossaryName.trim()) return;
    await api("/glossary", {
      method: "POST",
      body: JSON.stringify({
        name: glossaryName.trim(),
        description: glossaryDescription.trim() || null,
        priority: glossaryPriority,
        enabled: true,
      }),
    });
    setGlossaryName("");
    setGlossaryDescription("");
    setGlossaryPriority(100);
    await loadAll();
  }

  async function saveGlossarySet(row: GlossarySet) {
    await api(`/glossary/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: row.name.trim(),
        description: row.description,
        priority: row.priority,
        enabled: row.enabled,
      }),
    });
    await loadAll();
  }

  async function deleteGlossarySet(id: string) {
    const ok = window.confirm("Удалить глоссарий целиком вместе с его записями?");
    if (!ok) return;
    await api(`/glossary/${id}`, { method: "DELETE" });
    await loadAll();
  }

  async function addDomain() {
    if (!domain.trim()) return;
    await api("/admin/allowlist", {
      method: "POST",
      body: JSON.stringify({ domain: domain.trim(), notes: domainNotes.trim() || null, enabled: true }),
    });
    setDomain("");
    setDomainNotes("");
    await loadAll();
  }

  async function saveDomain(row: Domain) {
    await api(`/admin/allowlist/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify({ domain: row.domain.trim(), notes: row.notes || null, enabled: row.enabled }),
    });
    await loadAll();
  }

  async function deleteDomain(id: string) {
    const ok = window.confirm("Удалить домен из allowlist?");
    if (!ok) return;
    await api(`/admin/allowlist/${id}`, { method: "DELETE" });
    await loadAll();
  }

  async function saveProvider() {
    const source = provider
      ? {
          base_url: provider.base_url,
          model_name: provider.model_name,
          embedding_model: provider.embedding_model,
          timeout_s: provider.timeout_s,
          retry_policy: provider.retry_policy,
          strict_glossary_mode: provider.strict_glossary_mode,
          web_enabled: provider.web_enabled,
          show_confidence: provider.show_confidence,
          show_source_tags: provider.show_source_tags,
          response_tone: provider.response_tone,
          max_user_messages_total: provider.max_user_messages_total,
          api_key: providerDraft.api_key.trim() || undefined,
        }
      : {
          ...providerDraft,
          api_key: providerDraft.api_key.trim(),
        };

    if (!provider && !source.api_key) {
      setError("Укажите API-ключ для первичной настройки провайдера");
      return;
    }

    setProviderSaving(true);
    setProviderSaveStatus("idle");
    try {
      await api("/admin/provider", {
        method: "PUT",
        body: JSON.stringify(source),
      });
      await loadAll();
      setProviderDraft((prev) => ({ ...prev, api_key: "" }));
      setProviderSaveStatus("success");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: any) {
      setProviderSaveStatus("error");
      setError(e?.message || "Не удалось сохранить настройки");
    } finally {
      setProviderSaving(false);
    }
  }

  async function saveLimits() {
    if (!provider) {
      setError("Сначала сохраните базовые настройки провайдера");
      return;
    }
    setProviderSaving(true);
    setProviderSaveStatus("idle");
    try {
      await api("/admin/provider", {
        method: "PUT",
        body: JSON.stringify({
          base_url: provider.base_url,
          model_name: provider.model_name,
          embedding_model: provider.embedding_model,
          timeout_s: provider.timeout_s,
          retry_policy: provider.retry_policy,
          strict_glossary_mode: provider.strict_glossary_mode,
          web_enabled: provider.web_enabled,
          show_confidence: provider.show_confidence,
          show_source_tags: provider.show_source_tags,
          response_tone: provider.response_tone,
          max_user_messages_total: provider.max_user_messages_total,
        }),
      });
      await loadAll();
      setProviderSaveStatus("success");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: any) {
      setProviderSaveStatus("error");
      setError(e?.message || "Не удалось сохранить лимиты");
    } finally {
      setProviderSaving(false);
    }
  }

  function formatDateTime(value: string): string {
    return new Date(value).toLocaleString("ru-RU", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  async function approveRegistration(userId: string) {
    const ok = window.confirm("Подтвердить регистрацию этого пользователя?");
    if (!ok) return;
    try {
      await api(`/admin/registrations/${userId}/approve`, { method: "POST" });
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "Не удалось подтвердить пользователя");
    }
  }

  function PaginationControls(props: {
    page: number;
    totalPages: number;
    pageSize: number;
    onPageSizeChange: (value: number) => void;
    onPrev: () => void;
    onNext: () => void;
  }) {
    return (
      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-slate-600">На странице:</span>
        <select
          value={props.pageSize}
          onChange={(e) => props.onPageSizeChange(Number(e.target.value))}
          className="border rounded px-2 py-1"
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
        <button
          onClick={props.onPrev}
          disabled={props.page <= 1}
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
        >
          Назад
        </button>
        <span className="text-slate-600">{props.page} / {props.totalPages}</span>
        <button
          onClick={props.onNext}
          disabled={props.page >= props.totalPages}
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
        >
          Вперёд
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5">
          <h1 className="text-2xl font-semibold text-slate-900">Панель администратора</h1>
          <p className="mt-1 text-sm text-slate-600">Управление глоссарием, источниками и настройками ответов.</p>
        </div>

        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Глоссарии</h2>
          <p className="mt-1 text-sm text-slate-600">
            Приоритет определяет порядок применения глоссариев: чем меньше число, тем выше приоритет. Значение <code>100</code> — стандартное.
          </p>
          <div className="mt-3 grid gap-2 md:grid-cols-[2fr_2fr_120px_auto]">
            <input value={glossaryName} onChange={(e) => setGlossaryName(e.target.value)} className="border rounded px-3 py-2 text-sm" placeholder="Название глоссария" />
            <input
              value={glossaryDescription}
              onChange={(e) => setGlossaryDescription(e.target.value)}
              className="border rounded px-3 py-2 text-sm"
              placeholder="Описание"
            />
            <input
              type="number"
              min={1}
              max={1000}
              value={glossaryPriority}
              onChange={(e) => setGlossaryPriority(Number(e.target.value))}
              className="border rounded px-3 py-2 text-sm"
              placeholder="Приоритет (1-1000)"
              title="Чем меньше число, тем выше приоритет. 100 — стандарт."
            />
            <button onClick={addGlossarySet} className="rounded bg-ink text-white px-3 py-2 text-sm">Создать</button>
          </div>

          <div className="mt-3 space-y-3 md:hidden">
            {glossarySetRows.map((g) => (
              <div key={g.id} className="rounded-lg border border-slate-200 p-3">
                <div className="space-y-2">
                  <input
                    value={g.name}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, name: e.target.value } : row)))}
                    className="w-full border rounded px-2 py-2 text-sm"
                    placeholder="Название"
                  />
                  <input
                    value={g.description || ""}
                    onChange={(e) =>
                      setGlossarySets((prev) =>
                        prev.map((row) => (row.id === g.id ? { ...row, description: e.target.value || null } : row)),
                      )
                    }
                    className="w-full border rounded px-2 py-2 text-sm"
                    placeholder="Описание"
                  />
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={g.priority}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, priority: Number(e.target.value) } : row)))}
                    className="w-full border rounded px-2 py-2 text-sm"
                    title="Чем меньше число, тем выше приоритет."
                  />
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={g.enabled}
                        disabled={g.is_default}
                        onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, enabled: e.target.checked } : row)))}
                      />
                      Включен
                    </label>
                    {g.is_default && (
                      <span className="inline-flex items-center rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700">
                        по умолчанию
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <button onClick={() => void saveGlossarySet(g)} className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50">Сохранить</button>
                    <button
                      disabled={g.is_default}
                      onClick={() => void deleteGlossarySet(g.id)}
                      className="rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Удалить
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {glossarySets.length === 0 && <p className="px-1 py-2 text-sm text-slate-600">Нет глоссариев.</p>}
          </div>

          <div className="mt-3 hidden overflow-x-auto rounded-lg border border-slate-200 md:block">
            <div className="min-w-[980px]">
              <div className="grid grid-cols-[1.3fr_1.7fr_120px_220px_230px] items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <span>Название</span>
                <span>Описание</span>
                <span>Приоритет</span>
                <span>Статус</span>
                <span>Действия</span>
              </div>
              {glossarySetRows.map((g) => (
                <div key={g.id} className="grid grid-cols-[1.3fr_1.7fr_120px_220px_230px] items-center gap-2 border-b border-slate-100 px-3 py-2 last:border-b-0">
                  <input
                    value={g.name}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, name: e.target.value } : row)))}
                    className="border rounded px-2 py-1 text-sm"
                  />
                  <input
                    value={g.description || ""}
                    onChange={(e) =>
                      setGlossarySets((prev) =>
                        prev.map((row) => (row.id === g.id ? { ...row, description: e.target.value || null } : row)),
                      )
                    }
                    className="border rounded px-2 py-1 text-sm"
                    placeholder="Описание"
                  />
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={g.priority}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, priority: Number(e.target.value) } : row)))}
                    className="border rounded px-2 py-1 text-sm"
                    title="Чем меньше число, тем выше приоритет."
                  />
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={g.enabled}
                        disabled={g.is_default}
                        onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, enabled: e.target.checked } : row)))}
                      />
                      Включен
                    </label>
                    {g.is_default && (
                      <span className="inline-flex items-center rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700">
                        по умолчанию
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => void saveGlossarySet(g)} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">Сохранить</button>
                    <button
                      disabled={g.is_default}
                      onClick={() => void deleteGlossarySet(g.id)}
                      className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Удалить
                    </button>
                  </div>
                </div>
              ))}
              {glossarySets.length === 0 && <p className="px-3 py-3 text-sm text-slate-600">Нет глоссариев.</p>}
            </div>
          </div>

          <PaginationControls
            page={glossarySetPage}
            totalPages={glossarySetTotalPages}
            pageSize={glossarySetPageSize}
            onPageSizeChange={(value) => {
              setGlossarySetPageSize(value);
              setGlossarySetPage(1);
            }}
            onPrev={() => setGlossarySetPage((p) => Math.max(1, p - 1))}
            onNext={() => setGlossarySetPage((p) => Math.min(glossarySetTotalPages, p + 1))}
          />

          <h3 className="mt-6 text-base font-semibold">Записи выбранного глоссария</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-[minmax(240px,420px)_1fr] items-end">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Глоссарий для редактирования</span>
              <select
                value={selectedGlossaryId}
                onChange={(e) => {
                  setSelectedGlossaryId(e.target.value);
                  setGlossaryPage(1);
                }}
                className="w-full border rounded px-3 py-2 text-sm"
              >
                {glossarySets.length === 0 ? (
                  <option value="">Нет доступных глоссариев</option>
                ) : (
                  glossarySets.map((g) => (
                    <option key={g.id} value={g.id}>
                      {glossaryLabel(g)}
                    </option>
                  ))
                )}
              </select>
            </label>
          </div>
          <div className="mt-2 text-sm text-slate-600">
            {selectedGlossary ? `Выбран: ${selectedGlossary.name}` : "Сначала создайте или выберите глоссарий."}
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-[1fr_2fr_auto]">
            <input value={term} onChange={(e) => setTerm(e.target.value)} className="border rounded px-3 py-2 text-sm" placeholder="Термин" />
            <input value={definition} onChange={(e) => setDefinition(e.target.value)} className="border rounded px-3 py-2 text-sm" placeholder="Определение" />
            <button
              onClick={addGlossary}
              disabled={!selectedGlossaryId}
              className="rounded bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 text-sm disabled:opacity-50"
            >
              Добавить
            </button>
          </div>

          <div className="mt-3 space-y-2">
            {glossaryRows.map((g) => (
              <div key={g.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="text-sm flex-1">
                    <div className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 border-l-4 border-l-amber-500">
                      <div className="text-[11px] uppercase tracking-wide font-semibold text-amber-800">Термин</div>
                      <div className="mt-0.5 text-base font-extrabold text-slate-900">{g.term}</div>
                      <div className="my-2 border-t border-amber-200" />
                      <div className="text-slate-700">{g.definition}</div>
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => openGlossaryModal(g)} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">Редактировать</button>
                    <button onClick={() => void deleteGlossary(g.id)} className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50">Удалить</button>
                  </div>
                </div>
              </div>
            ))}
            {glossaryRows.length === 0 && <p className="text-sm text-slate-600">Нет записей.</p>}
          </div>

          <PaginationControls
            page={glossaryPage}
            totalPages={glossaryTotalPages}
            pageSize={glossaryPageSize}
            onPageSizeChange={(value) => {
              setGlossaryPageSize(value);
              setGlossaryPage(1);
            }}
            onPrev={() => setGlossaryPage((p) => Math.max(1, p - 1))}
            onNext={() => setGlossaryPage((p) => Math.min(glossaryTotalPages, p + 1))}
          />
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Разрешенные веб-домены (белый список)</h2>
          <div className="mt-3 grid gap-2 md:grid-cols-[1fr_2fr_auto]">
            <input value={domain} onChange={(e) => setDomain(e.target.value)} className="border rounded px-3 py-2 text-sm" placeholder="example.com" />
            <input value={domainNotes} onChange={(e) => setDomainNotes(e.target.value)} className="border rounded px-3 py-2 text-sm" placeholder="Примечание о содержании сайта" />
            <button onClick={addDomain} className="rounded bg-ink text-white px-3 py-2 text-sm">Добавить</button>
          </div>

          <div className="mt-3 space-y-2">
            {allowlistRows.map((d) => (
              <div key={d.id} className="rounded-lg border border-slate-200 p-3">
                <div className="grid gap-2 md:grid-cols-[1fr_2fr_auto_auto_auto] items-center">
                  <input
                    value={d.domain}
                    onChange={(e) => setDomains((prev) => prev.map((row) => (row.id === d.id ? { ...row, domain: e.target.value } : row)))}
                    className="border rounded px-2 py-1 text-sm"
                  />
                  <input
                    value={d.notes || ""}
                    onChange={(e) => setDomains((prev) => prev.map((row) => (row.id === d.id ? { ...row, notes: e.target.value } : row)))}
                    className="border rounded px-2 py-1 text-sm"
                    placeholder="О чем этот сайт"
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={d.enabled}
                      onChange={(e) => setDomains((prev) => prev.map((row) => (row.id === d.id ? { ...row, enabled: e.target.checked } : row)))}
                    />
                    Включен
                  </label>
                  <button onClick={() => void saveDomain(d)} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">Сохранить</button>
                  <button onClick={() => void deleteDomain(d.id)} className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50">Удалить</button>
                </div>
              </div>
            ))}
            {allowlistRows.length === 0 && <p className="text-sm text-slate-600">Нет доменов.</p>}
          </div>

          <PaginationControls
            page={allowlistPage}
            totalPages={allowlistTotalPages}
            pageSize={allowlistPageSize}
            onPageSizeChange={(value) => {
              setAllowlistPageSize(value);
              setAllowlistPage(1);
            }}
            onPrev={() => setAllowlistPage((p) => Math.max(1, p - 1))}
            onNext={() => setAllowlistPage((p) => Math.min(allowlistTotalPages, p + 1))}
          />
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Настройки ответов</h2>
          {!provider ? (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-slate-600">Провайдер пока не настроен. Заполните параметры для первичной конфигурации.</p>
              <label className="block">
                Базовый URL
                <input
                  value={providerDraft.base_url}
                  onChange={(e) => setProviderDraft({ ...providerDraft, base_url: e.target.value })}
                  className="mt-1 w-full border rounded px-2 py-1"
                />
              </label>
              <label className="block">
                API-ключ
                <input
                  type="password"
                  value={providerDraft.api_key}
                  onChange={(e) => setProviderDraft({ ...providerDraft, api_key: e.target.value })}
                  className="mt-1 w-full border rounded px-2 py-1"
                />
              </label>
              <label className="block">
                Модель чата
                <input
                  value={providerDraft.model_name}
                  onChange={(e) => setProviderDraft({ ...providerDraft, model_name: e.target.value })}
                  className="mt-1 w-full border rounded px-2 py-1"
                />
              </label>
              <label className="block">
                Модель эмбеддингов
                <input
                  value={providerDraft.embedding_model}
                  onChange={(e) => setProviderDraft({ ...providerDraft, embedding_model: e.target.value })}
                  className="mt-1 w-full border rounded px-2 py-1"
                />
              </label>
              <div className="grid gap-2 md:grid-cols-2">
                <label className="block">
                  Таймаут (сек)
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={providerDraft.timeout_s}
                    onChange={(e) => setProviderDraft({ ...providerDraft, timeout_s: Number(e.target.value) })}
                    className="mt-1 w-full border rounded px-2 py-1"
                  />
                </label>
                <label className="block">
                  Повторы
                  <input
                    type="number"
                    min={0}
                    max={5}
                    value={providerDraft.retry_policy}
                    onChange={(e) => setProviderDraft({ ...providerDraft, retry_policy: Number(e.target.value) })}
                    className="mt-1 w-full border rounded px-2 py-1"
                  />
                </label>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.strict_glossary_mode}
                  onChange={(e) => setProviderDraft({ ...providerDraft, strict_glossary_mode: e.target.checked })}
                />
                Строгий режим глоссария
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.web_enabled}
                  onChange={(e) => setProviderDraft({ ...providerDraft, web_enabled: e.target.checked })}
                />
                Включить веб-поиск (белый список)
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.show_confidence}
                  onChange={(e) => setProviderDraft({ ...providerDraft, show_confidence: e.target.checked })}
                />
                Показывать уровень уверенности пользователю
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.show_source_tags}
                  onChange={(e) => setProviderDraft({ ...providerDraft, show_source_tags: e.target.checked })}
                />
                Показывать теги источников в чате
              </label>
              <label className="block">
                Тон ответа
                <select
                  value={providerDraft.response_tone}
                  onChange={(e) => setProviderDraft({ ...providerDraft, response_tone: e.target.value as ProviderDraft["response_tone"] })}
                  className="mt-1 w-full border rounded px-2 py-1"
                >
                  <option value="consultative_supportive">Консультативно-поддерживающий</option>
                  <option value="neutral_reference">Нейтрально-справочный</option>
                </select>
              </label>
              <button
                onClick={saveProvider}
                disabled={providerSaving}
                className="rounded bg-ink text-white px-3 py-2 disabled:opacity-70"
              >
                {providerSaving ? "Сохранение..." : "Сохранить настройки провайдера"}
              </button>
            </div>
          ) : (
            <div className="mt-3 space-y-3 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.strict_glossary_mode}
                  onChange={(e) => setProvider({ ...provider, strict_glossary_mode: e.target.checked })}
                />
                Строгий режим глоссария
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.web_enabled}
                  onChange={(e) => setProvider({ ...provider, web_enabled: e.target.checked })}
                />
                Включить веб-поиск (белый список)
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.show_confidence}
                  onChange={(e) => setProvider({ ...provider, show_confidence: e.target.checked })}
                />
                Показывать уровень уверенности пользователю
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.show_source_tags}
                  onChange={(e) => setProvider({ ...provider, show_source_tags: e.target.checked })}
                />
                Показывать теги источников в чате
              </label>
              <label className="block">
                Тон ответа
                <select
                  value={provider.response_tone}
                  onChange={(e) => setProvider({ ...provider, response_tone: e.target.value })}
                  className="mt-1 w-full border rounded px-2 py-1"
                >
                  <option value="consultative_supportive">Консультативно-поддерживающий</option>
                  <option value="neutral_reference">Нейтрально-справочный</option>
                </select>
              </label>
              <div className="flex items-center gap-3">
                <button
                  onClick={saveProvider}
                  disabled={providerSaving}
                  className="rounded bg-ink text-white px-3 py-2 disabled:opacity-70"
                >
                  {providerSaving ? "Сохранение..." : "Сохранить настройки"}
                </button>
                {providerSaveStatus === "success" && (
                  <span className="inline-flex items-center rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 animate-pulse">
                    Сохранено
                  </span>
                )}
                {providerSaveStatus === "error" && (
                  <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-700 animate-pulse">
                    Ошибка сохранения
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Лимиты пользователей</h2>
          {!provider ? (
            <p className="mt-2 text-sm text-slate-600">Доступно после первичной настройки провайдера.</p>
          ) : (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-slate-600">Ограничение применяется только к роли user. На admin не влияет.</p>
              <label className="block">
                Лимит сообщений пользователя (всего)
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={provider.max_user_messages_total}
                  onChange={(e) =>
                    setProvider({ ...provider, max_user_messages_total: Number(e.target.value) || 1 })
                  }
                  className="mt-1 w-full border rounded px-2 py-1"
                />
              </label>
              <button
                onClick={saveLimits}
                disabled={providerSaving}
                className="rounded bg-ink text-white px-3 py-2 disabled:opacity-70"
              >
                {providerSaving ? "Сохранение..." : "Сохранить лимиты"}
              </button>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Ожидающие регистрации</h2>
          <p className="mt-1 text-sm text-slate-600">Пользователи, ожидающие ручного одобрения администратором.</p>
          <div className="mt-3 space-y-2">
            {pendingRegistrations.length === 0 && (
              <p className="text-sm text-slate-600">Нет заявок на одобрение.</p>
            )}
            {pendingRegistrations.map((user) => (
              <div key={user.id} className="rounded border border-slate-200 px-3 py-2 text-sm">
                <div className="font-medium text-slate-900">{user.email || user.username}</div>
                <div className="mt-1 text-xs text-slate-500">
                  username: {user.username} | создан: {user.created_at ? formatDateTime(user.created_at) : "—"}
                </div>
                <div className="mt-2">
                  <button
                    onClick={() => void approveRegistration(user.id)}
                    className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-700"
                  >
                    Одобрить
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Последние трассировки</h2>
          <div className="mt-2 space-y-2 text-sm">
            {traces.length === 0 && <p className="text-slate-600">Нет данных.</p>}
            {traces.map((t) => (
              <div key={t.id} className="rounded border border-slate-200 px-3 py-2">
                <div>{t.model} | {t.status} | {Math.round(t.latency_ms)} мс</div>
                <div className="text-xs text-slate-500 mt-1">{formatDateTime(t.created_at)}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Последние ошибки</h2>
          <div className="mt-2 space-y-2 text-sm">
            {logs.map((l) => (
              <div key={l.id} className="rounded border border-slate-200 px-3 py-2">
                <div>{l.type}: {l.message}</div>
                <div className="text-xs text-slate-500 mt-1">{formatDateTime(l.created_at)}</div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {editingGlossary && (
        <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-[var(--line)] bg-white p-5 shadow-lg">
            <h3 className="text-lg font-semibold">Редактирование записи глоссария</h3>
            <div className="mt-3 space-y-2">
              <input value={editTerm} onChange={(e) => setEditTerm(e.target.value)} className="w-full border rounded px-3 py-2 text-sm" placeholder="Термин" />
              <textarea
                value={editDefinition}
                onChange={(e) => setEditDefinition(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm min-h-32"
                placeholder="Определение"
              />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={closeGlossaryModal} className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50">Отмена</button>
              <button onClick={() => void saveGlossaryModal()} className="rounded bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 text-sm">Сохранить</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
