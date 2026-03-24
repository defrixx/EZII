"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, getAuthHeaders } from "@/lib/api";
import { clearSession, redirectToAuth, showReloginNoticeOnce } from "@/lib/auth";
import { useToast } from "@/components/ui/toast-provider";

type Glossary = { id: string; term: string; definition: string; priority: number; status: string };
type GlossarySet = {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  enabled: boolean;
  is_default: boolean;
};
type KnowledgeStatus = "draft" | "processing" | "approved" | "archived" | "failed";
type KnowledgeSourceType = "upload" | "website_snapshot";
type EmptyRetrievalMode = "strict_fallback" | "model_only_fallback" | "clarifying_fallback";
type KnowledgeItem = {
  id: string;
  tenant_id: string;
  title: string;
  source_type: KnowledgeSourceType;
  mime_type: string | null;
  file_name: string | null;
  storage_path: string | null;
  status: KnowledgeStatus;
  enabled_in_retrieval: boolean;
  checksum: string | null;
  created_by: string | null;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  metadata_json: Record<string, unknown>;
  chunk_count: number;
};
type KnowledgeDetail = KnowledgeItem & {
  chunks: Array<{
    id: string;
    chunk_index: number;
    content: string;
    token_count: number;
    created_at: string;
  }>;
};
type GlossaryCsvImportResult = { created: number; updated: number };
type Trace = { id: string; model: string; status: string; latency_ms: number; created_at: string; knowledge_mode: KnowledgeMode; answer_mode: string };
type KnowledgeMode = "glossary_only" | "glossary_documents" | "glossary_documents_web";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
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
  knowledge_mode: KnowledgeMode;
  empty_retrieval_mode: EmptyRetrievalMode;
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
  knowledge_mode: KnowledgeMode;
  empty_retrieval_mode: EmptyRetrievalMode;
  strict_glossary_mode: boolean;
  web_enabled: boolean;
  show_confidence: boolean;
  show_source_tags: boolean;
  response_tone: "consultative_supportive" | "neutral_reference";
  max_user_messages_total: number;
};

type LogItem = { id: string; type: string; message: string; created_at: string };
type KnowledgeSourceFilter = "all" | KnowledgeSourceType;

const PAGE_SIZE_OPTIONS = [5, 10] as const;
const DEFAULT_PROVIDER_DRAFT: ProviderDraft = {
  base_url: "https://openrouter.ai/api/v1",
  api_key: "",
  model_name: "openai/gpt-4o-mini",
  embedding_model: "text-embedding-3-small",
  timeout_s: 30,
  retry_policy: 2,
  knowledge_mode: "glossary_documents",
  empty_retrieval_mode: "model_only_fallback",
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
  const [traces, setTraces] = useState<Trace[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [pendingRegistrations, setPendingRegistrations] = useState<PendingRegistration[]>([]);
  const [glossaryName, setGlossaryName] = useState("");
  const [glossaryDescription, setGlossaryDescription] = useState("");
  const [glossaryPriority, setGlossaryPriority] = useState<number>(100);
  const [term, setTerm] = useState("");
  const [definition, setDefinition] = useState("");
  const [glossaryImportBusy, setGlossaryImportBusy] = useState(false);
  const [glossaryImportFile, setGlossaryImportFile] = useState<File | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [providerDraft, setProviderDraft] = useState<ProviderDraft>(DEFAULT_PROVIDER_DRAFT);
  const [providerSaving, setProviderSaving] = useState(false);
  const [providerSaveStatus, setProviderSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [knowledgeTab, setKnowledgeTab] = useState<"documents" | "sites">("documents");
  const [knowledgeFilter, setKnowledgeFilter] = useState<"all" | KnowledgeStatus>("all");
  const [knowledgeSourceFilter, setKnowledgeSourceFilter] = useState<KnowledgeSourceFilter>("all");
  const [knowledgeSearch, setKnowledgeSearch] = useState("");
  const [knowledgeTagFilter, setKnowledgeTagFilter] = useState("all");
  const [documents, setDocuments] = useState<KnowledgeItem[]>([]);
  const [sites, setSites] = useState<KnowledgeItem[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeVisibleCount, setKnowledgeVisibleCount] = useState(10);
  const [knowledgeTagDrafts, setKnowledgeTagDrafts] = useState<Record<string, string>>({});
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [documentTitle, setDocumentTitle] = useState("");
  const [documentTags, setDocumentTags] = useState("");
  const [documentUploadBusy, setDocumentUploadBusy] = useState(false);
  const [siteUrl, setSiteUrl] = useState("");
  const [siteTitle, setSiteTitle] = useState("");
  const [siteTags, setSiteTags] = useState("");
  const [siteCreateBusy, setSiteCreateBusy] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const documentFileInputRef = useRef<HTMLInputElement | null>(null);
  const glossaryImportInputRef = useRef<HTMLInputElement | null>(null);
  const { pushToast } = useToast();

  const [glossaryPage, setGlossaryPage] = useState(1);
  const [glossaryPageSize, setGlossaryPageSize] = useState<number>(5);
  const [glossarySetPage, setGlossarySetPage] = useState(1);
  const [glossarySetPageSize, setGlossarySetPageSize] = useState<number>(5);

  const [editingGlossary, setEditingGlossary] = useState<Glossary | null>(null);
  const [editTerm, setEditTerm] = useState("");
  const [editDefinition, setEditDefinition] = useState("");

  const reportError = useCallback(
    (message: string, title = "Ошибка админки") => {
      pushToast({ tone: "error", title, description: message });
    },
    [pushToast]
  );

  const reportSuccess = useCallback(
    (title: string, description?: string) => {
      pushToast({ tone: "success", title, description });
    },
    [pushToast]
  );

  const glossaryTotalPages = Math.max(1, Math.ceil(glossaryEntries.length / glossaryPageSize));
  const glossarySetTotalPages = Math.max(1, Math.ceil(glossarySets.length / glossarySetPageSize));

  useEffect(() => {
    if (glossaryPage > glossaryTotalPages) setGlossaryPage(glossaryTotalPages);
  }, [glossaryPage, glossaryTotalPages]);

  useEffect(() => {
    if (glossarySetPage > glossarySetTotalPages) setGlossarySetPage(glossarySetTotalPages);
  }, [glossarySetPage, glossarySetTotalPages]);

  const glossaryRows = useMemo(() => {
    const start = (glossaryPage - 1) * glossaryPageSize;
    return glossaryEntries.slice(start, start + glossaryPageSize);
  }, [glossaryEntries, glossaryPage, glossaryPageSize]);

  const glossarySetRows = useMemo(() => {
    const start = (glossarySetPage - 1) * glossarySetPageSize;
    return glossarySets.slice(start, start + glossarySetPageSize);
  }, [glossarySets, glossarySetPage, glossarySetPageSize]);
  const selectedGlossary = useMemo(
    () => glossarySets.find((g) => g.id === selectedGlossaryId) || null,
    [glossarySets, selectedGlossaryId],
  );
  const knowledgeRows = useMemo(
    () =>
      [...documents, ...sites].sort(
        (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
      ),
    [documents, sites],
  );
  const knowledgeAvailableTags = useMemo(() => {
    const tags = new Map<string, string>();
    for (const item of knowledgeRows) {
      const raw = item.metadata_json?.tags;
      if (!Array.isArray(raw)) continue;
      for (const entry of raw) {
        const tag = String(entry || "").trim();
        if (!tag) continue;
        const lowered = tag.toLowerCase();
        if (!tags.has(lowered)) {
          tags.set(lowered, tag);
        }
      }
    }
    return Array.from(tags.values()).sort((a, b) => a.localeCompare(b, "ru"));
  }, [knowledgeRows]);
  const filteredKnowledgeRows = useMemo(() => {
    const normalizedQuery = knowledgeSearch.trim().toLowerCase();
    return knowledgeRows.filter((item) => {
      if (knowledgeFilter !== "all" && item.status !== knowledgeFilter) return false;
      if (knowledgeSourceFilter !== "all" && item.source_type !== knowledgeSourceFilter) return false;
      const itemTags = getKnowledgeTags(item);
      if (knowledgeTagFilter !== "all" && !itemTags.map((tag) => tag.toLowerCase()).includes(knowledgeTagFilter.toLowerCase())) {
        return false;
      }
      if (!normalizedQuery) return true;
      const haystack = [item.title, item.file_name || "", String(item.metadata_json?.url || ""), ...itemTags].join(" ").toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [knowledgeFilter, knowledgeRows, knowledgeSearch, knowledgeSourceFilter, knowledgeTagFilter, getKnowledgeTags]);
  const visibleKnowledgeRows = useMemo(
    () => filteredKnowledgeRows.slice(0, knowledgeVisibleCount),
    [filteredKnowledgeRows, knowledgeVisibleCount],
  );

  function glossaryLabel(row: GlossarySet): string {
    const suffix = row.is_default ? "по умолчанию" : `приоритет ${row.priority}`;
    return `${row.name} (${suffix})`;
  }

  function knowledgeStatusLabel(status: KnowledgeStatus): string {
    switch (status) {
      case "approved":
        return "Одобрен";
      case "archived":
        return "В архиве";
      case "failed":
        return "Ошибка";
      case "processing":
        return "В обработке";
      case "draft":
      default:
        return "Черновик";
    }
  }

  function knowledgeStatusClass(status: KnowledgeStatus): string {
    switch (status) {
      case "approved":
        return "border-emerald-200 bg-emerald-50 text-emerald-700";
      case "archived":
        return "border-slate-200 bg-slate-100 text-slate-700";
      case "failed":
        return "border-red-200 bg-red-50 text-red-700";
      case "processing":
        return "border-amber-200 bg-amber-50 text-amber-700";
      case "draft":
      default:
        return "border-sky-200 bg-sky-50 text-sky-700";
    }
  }

  function knowledgeSourceLabel(sourceType: KnowledgeSourceType): string {
    return sourceType === "website_snapshot" ? "Сайт" : "Документ";
  }

  function parseTagsInput(value: string): string[] {
    const seen = new Set<string>();
    return value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => {
        if (!item) return false;
        const lowered = item.toLowerCase();
        if (seen.has(lowered)) return false;
        seen.add(lowered);
        return true;
      });
  }

  const getKnowledgeTags = useCallback((item: KnowledgeItem): string[] => {
    const raw = item.metadata_json?.tags;
    if (!Array.isArray(raw)) return [];
    return raw.map((tag) => String(tag || "").trim()).filter(Boolean);
  }, []);

  const formatKnowledgeTags = useCallback(
    (item: KnowledgeItem): string => getKnowledgeTags(item).join(", "),
    [getKnowledgeTags],
  );

  const loadKnowledgeData = useCallback(async () => {
    setKnowledgeLoading(true);
    try {
      const [docs, siteRows] = await Promise.all([
        api<KnowledgeItem[]>("/admin/documents?source_type=upload"),
        api<KnowledgeItem[]>("/admin/documents?source_type=website_snapshot"),
      ]);
      setDocuments(docs);
      setSites(siteRows);
    } catch (e: any) {
      reportError(e?.message || "Не удалось загрузить базу знаний", "База знаний");
    } finally {
      setKnowledgeLoading(false);
    }
  }, [reportError]);

  const loadAll = useCallback(async () => {
    try {
      const [g, t, l, pending] = await Promise.all([
        api<GlossarySet[]>("/glossary"),
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
      reportError(e.message || "Не удалось загрузить данные админки");
    }
  }, [reportError, selectedGlossaryId]);

  useEffect(() => {
    void loadKnowledgeData();
  }, [loadKnowledgeData]);

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

  useEffect(() => {
    setKnowledgeVisibleCount(10);
  }, [knowledgeFilter, knowledgeSearch, knowledgeSourceFilter, knowledgeTagFilter]);

  useEffect(() => {
    setKnowledgeTagDrafts((prev) => {
      const next: Record<string, string> = {};
      for (const item of knowledgeRows) {
        next[item.id] = prev[item.id] ?? formatKnowledgeTags(item);
      }
      return next;
    });
  }, [knowledgeRows, formatKnowledgeTags]);

  async function uploadKnowledgeDocument() {
    if (!documentFile) {
      reportError("Выберите PDF, MD или TXT файл", "Документы");
      return;
    }
    setDocumentUploadBusy(true);
    try {
      const form = new FormData();
      form.append("file", documentFile);
      if (documentTitle.trim()) {
        form.append("title", documentTitle.trim());
      }
      const tags = parseTagsInput(documentTags);
      if (tags.length > 0) {
        form.append("metadata_json", JSON.stringify({ tags }));
      }
      form.append("enabled_in_retrieval", "true");
      const res = await fetch(`${API_BASE}/admin/documents/upload`, {
        method: "POST",
        body: form,
        headers: {
          ...getAuthHeaders(),
        },
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error((await res.text()) || `HTTP ${res.status}`);
      }
      setDocumentFile(null);
      if (documentFileInputRef.current) {
        documentFileInputRef.current.value = "";
      }
      setDocumentTitle("");
      setDocumentTags("");
      await loadKnowledgeData();
      reportSuccess("Документ загружен", "Файл поставлен в очередь ingestion.");
    } catch (e: any) {
      reportError(e?.message || "Не удалось загрузить документ", "Документы");
    } finally {
      setDocumentUploadBusy(false);
    }
  }

  async function createWebsiteSnapshot() {
    if (!siteUrl.trim()) {
      reportError("Укажите URL сайта", "Сайты");
      return;
    }
    setSiteCreateBusy(true);
    try {
      await api("/admin/sites", {
        method: "POST",
        body: JSON.stringify({
          url: siteUrl.trim(),
          title: siteTitle.trim() || null,
          enabled_in_retrieval: true,
          tags: parseTagsInput(siteTags),
        }),
      });
      setSiteUrl("");
      setSiteTitle("");
      setSiteTags("");
      await loadKnowledgeData();
      reportSuccess("Сайт добавлен", "Snapshot поставлен в очередь ingestion.");
    } catch (e: any) {
      reportError(e?.message || "Не удалось добавить сайт", "Сайты");
    } finally {
      setSiteCreateBusy(false);
    }
  }

  async function loadKnowledgePreview(documentId: string) {
    setPreviewId(documentId);
    setPreviewLoading(true);
    try {
      const detail = await api<KnowledgeDetail>(`/admin/documents/${documentId}`);
      const excerpt = detail.chunks
        .slice(0, 6)
        .map((chunk) => chunk.content.trim())
        .filter(Boolean)
        .join("\n\n");
      setPreviewText(excerpt || "Для этого источника пока нет извлеченного текста.");
    } catch (e: any) {
      setPreviewText("");
      reportError(e?.message || "Не удалось загрузить preview", "База знаний");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function runKnowledgeAction(
    item: KnowledgeItem,
    action: "approve" | "archive" | "reindex" | "delete" | "toggle",
    enabled?: boolean
  ) {
    try {
      if (action === "delete") {
        const confirmed = window.confirm(`Удалить источник "${item.title}"?`);
        if (!confirmed) {
          return;
        }
      }
      if (action === "approve") {
        await api(`/admin/documents/${item.id}/approve`, { method: "POST" });
      }
      if (action === "archive") {
        await api(`/admin/documents/${item.id}/archive`, { method: "POST" });
      }
      if (action === "reindex") {
        await api(`/admin/documents/${item.id}/reindex`, { method: "POST" });
      }
      if (action === "delete") {
        await api(`/admin/documents/${item.id}`, { method: "DELETE" });
        if (previewId === item.id) {
          setPreviewId(null);
          setPreviewText("");
        }
      }
      if (action === "toggle") {
        await api(`/admin/documents/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled_in_retrieval: enabled }),
        });
      }
      await loadKnowledgeData();
      if (previewId === item.id && action !== "delete") {
        await loadKnowledgePreview(item.id);
      }
      const successTitle =
        action === "approve"
          ? "Источник одобрен"
          : action === "archive"
            ? "Источник архивирован"
            : action === "reindex"
              ? "Переиндексация запущена"
              : action === "toggle"
                ? enabled
                  ? "Источник включен в retrieval"
                  : "Источник исключен из retrieval"
                : "Источник удален";
      reportSuccess(successTitle);
    } catch (e: any) {
      const actionLabel =
        action === "approve"
          ? "одобрить"
          : action === "archive"
            ? "архивировать"
            : action === "reindex"
              ? "переиндексировать"
              : action === "toggle"
                ? "обновить"
                : "удалить";
      reportError(e?.message || `Не удалось ${actionLabel} источник`, "База знаний");
    }
  }

  async function saveKnowledgeTags(item: KnowledgeItem) {
    try {
      await api(`/admin/documents/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          metadata_json: {
            ...item.metadata_json,
            tags: parseTagsInput(knowledgeTagDrafts[item.id] || ""),
          },
        }),
      });
      await loadKnowledgeData();
      if (previewId === item.id) {
        await loadKnowledgePreview(item.id);
      }
      reportSuccess("Теги обновлены");
    } catch (e: any) {
      reportError(e?.message || "Не удалось обновить теги", "База знаний");
    }
  }

  async function importGlossaryCsv() {
    if (!selectedGlossaryId) {
      reportError("Сначала выберите глоссарий", "Глоссарий");
      return;
    }
    if (!glossaryImportFile) {
      reportError("Выберите CSV файл", "Глоссарий");
      return;
    }
    setGlossaryImportBusy(true);
    try {
      const form = new FormData();
      form.append("file", glossaryImportFile);
      const res = await fetch(`${API_BASE}/glossary/${selectedGlossaryId}/import-csv`, {
        method: "POST",
        body: form,
        headers: {
          ...getAuthHeaders(),
        },
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error((await res.text()) || `HTTP ${res.status}`);
      }
      const result = (await res.json()) as GlossaryCsvImportResult;
      setGlossaryImportFile(null);
      if (glossaryImportInputRef.current) {
        glossaryImportInputRef.current.value = "";
      }
      await loadAll();
      reportSuccess("CSV импорт завершен", `Создано: ${result.created}, обновлено: ${result.updated}.`);
    } catch (e: any) {
      reportError(e?.message || "Не удалось импортировать CSV", "Глоссарий");
    } finally {
      setGlossaryImportBusy(false);
    }
  }

  async function addGlossary() {
    if (!selectedGlossaryId) return;
    if (!term.trim() || !definition.trim()) return;
    try {
      await api(`/glossary/${selectedGlossaryId}/entries`, {
        method: "POST",
        body: JSON.stringify({ term: term.trim(), definition: definition.trim(), synonyms: [], forbidden_interpretations: [] }),
      });
      setTerm("");
      setDefinition("");
      await loadAll();
      reportSuccess("Запись глоссария добавлена");
    } catch (e: any) {
      reportError(e?.message || "Не удалось добавить запись глоссария");
    }
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
    try {
      await api(`/glossary/${selectedGlossaryId}/entries/${editingGlossary.id}`, {
        method: "PATCH",
        body: JSON.stringify({ term: editTerm.trim(), definition: editDefinition.trim() }),
      });
      closeGlossaryModal();
      await loadAll();
      reportSuccess("Запись глоссария обновлена");
    } catch (e: any) {
      reportError(e?.message || "Не удалось обновить запись глоссария");
    }
  }

  async function deleteGlossary(id: string) {
    if (!selectedGlossaryId) return;
    const ok = window.confirm("Удалить запись глоссария?");
    if (!ok) return;
    try {
      await api(`/glossary/${selectedGlossaryId}/entries/${id}`, { method: "DELETE" });
      await loadAll();
      reportSuccess("Запись глоссария удалена");
    } catch (e: any) {
      reportError(e?.message || "Не удалось удалить запись глоссария");
    }
  }

  async function addGlossarySet() {
    if (!glossaryName.trim()) return;
    try {
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
      reportSuccess("Глоссарий создан");
    } catch (e: any) {
      reportError(e?.message || "Не удалось создать глоссарий");
    }
  }

  async function saveGlossarySet(row: GlossarySet) {
    try {
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
      reportSuccess("Глоссарий обновлен");
    } catch (e: any) {
      reportError(e?.message || "Не удалось обновить глоссарий");
    }
  }

  async function deleteGlossarySet(id: string) {
    const ok = window.confirm("Удалить глоссарий целиком вместе с его записями?");
    if (!ok) return;
    try {
      await api(`/glossary/${id}`, { method: "DELETE" });
      await loadAll();
      reportSuccess("Глоссарий удален");
    } catch (e: any) {
      reportError(e?.message || "Не удалось удалить глоссарий");
    }
  }

  async function saveProvider() {
    const source = provider
      ? {
          base_url: provider.base_url,
          model_name: provider.model_name,
          embedding_model: provider.embedding_model,
          timeout_s: provider.timeout_s,
          retry_policy: provider.retry_policy,
          knowledge_mode: provider.knowledge_mode,
          empty_retrieval_mode: provider.empty_retrieval_mode,
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
      reportError("Укажите API-ключ для первичной настройки провайдера", "Настройки провайдера");
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
      reportSuccess("Настройки провайдера сохранены");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: any) {
      setProviderSaveStatus("error");
      reportError(e?.message || "Не удалось сохранить настройки", "Настройки провайдера");
    } finally {
      setProviderSaving(false);
    }
  }

  async function saveLimits() {
    if (!provider) {
      reportError("Сначала сохраните базовые настройки провайдера", "Лимиты пользователей");
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
          knowledge_mode: provider.knowledge_mode,
          empty_retrieval_mode: provider.empty_retrieval_mode,
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
      reportSuccess("Лимиты пользователей сохранены");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: any) {
      setProviderSaveStatus("error");
      reportError(e?.message || "Не удалось сохранить лимиты", "Лимиты пользователей");
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
      reportSuccess("Пользователь подтвержден");
    } catch (e: any) {
      reportError(e?.message || "Не удалось подтвердить пользователя", "Ожидающие регистрации");
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
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900">Панель администратора</h1>
              <p className="mt-1 text-sm text-slate-600">Управление глоссарием, источниками и настройками ответов.</p>
            </div>
            <Link
              href="/chat"
              className="inline-flex items-center justify-center rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Вернуться в чат
            </Link>
          </div>
        </div>
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
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
              <label className="text-sm">
                <span className="mb-1 block text-slate-700">Импорт CSV с upsert по term</span>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  ref={glossaryImportInputRef}
                  onChange={(e) => setGlossaryImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </label>
              <button
                onClick={() => void importGlossaryCsv()}
                disabled={!selectedGlossaryId || glossaryImportBusy}
                className="rounded bg-ink px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {glossaryImportBusy ? "Импорт..." : "Импортировать CSV"}
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Только CSV, максимум 10 MB. Обязательные колонки: <code>term</code>, <code>definition</code>. Дополнительно можно передать
              <code>synonyms</code>, <code>forbidden_interpretations</code>, <code>tags</code>, <code>metadata_json</code>. Списки в ячейках разделяются через <code>;</code>.
            </p>
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
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold">База знаний</h2>
              <p className="mt-1 text-sm text-slate-600">Загрузка, ingestion, preview и approval документов и website snapshots.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setKnowledgeTab("documents")}
                className={`rounded-full px-3 py-1.5 text-sm ${knowledgeTab === "documents" ? "bg-ink text-white" : "border border-slate-300 text-slate-700"}`}
              >
                Документы
              </button>
              <button
                onClick={() => setKnowledgeTab("sites")}
                className={`rounded-full px-3 py-1.5 text-sm ${knowledgeTab === "sites" ? "bg-ink text-white" : "border border-slate-300 text-slate-700"}`}
              >
                Сайты
              </button>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            {knowledgeTab === "documents" ? (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-[1.2fr_1fr_1fr_auto] md:items-end">
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Файл</span>
                    <input
                      type="file"
                      accept=".pdf,.md,.txt,text/plain,text/markdown,application/pdf"
                      ref={documentFileInputRef}
                      onChange={(e) => setDocumentFile(e.target.files?.[0] || null)}
                      className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Заголовок</span>
                    <input
                      value={documentTitle}
                      onChange={(e) => setDocumentTitle(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      placeholder="Название документа"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Теги</span>
                    <input
                      value={documentTags}
                      onChange={(e) => setDocumentTags(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      placeholder="security, policies, onboarding"
                    />
                  </label>
                  <button
                    onClick={() => void uploadKnowledgeDocument()}
                    disabled={documentUploadBusy}
                    className="rounded bg-ink px-4 py-2 text-sm text-white disabled:opacity-70"
                  >
                    {documentUploadBusy ? "Загрузка..." : "Загрузить"}
                  </button>
                </div>
                <p className="text-xs text-slate-500">Поддерживаются только `PDF`, `MD` и `TXT`. Максимальный размер файла: `50 MB`.</p>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-[1.4fr_1fr_1fr_auto] md:items-end">
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">URL</span>
                    <input
                      value={siteUrl}
                      onChange={(e) => setSiteUrl(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      placeholder="https://example.com/page"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Заголовок</span>
                    <input
                      value={siteTitle}
                      onChange={(e) => setSiteTitle(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      placeholder="Название snapshot"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Теги</span>
                    <input
                      value={siteTags}
                      onChange={(e) => setSiteTags(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      placeholder="ai, security, owasp"
                    />
                  </label>
                  <button
                    onClick={() => void createWebsiteSnapshot()}
                    disabled={siteCreateBusy}
                    className="rounded bg-ink px-4 py-2 text-sm text-white disabled:opacity-70"
                  >
                    {siteCreateBusy ? "Добавление..." : "Добавить URL"}
                  </button>
                </div>
                <p className="text-xs text-slate-500">
                  Поиск по сайтам идет строго по странице, URL которой вы добавили. EZII не обходит весь домен и не ищет по содержимому внутренних страниц автоматически.
                </p>
              </div>
            )}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-[1.5fr_repeat(3,minmax(0,220px))_auto] md:items-end">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Поиск по названию</span>
              <input
                value={knowledgeSearch}
                onChange={(e) => setKnowledgeSearch(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="Название документа, URL или тег"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Фильтр по статусу</span>
              <select
                value={knowledgeFilter}
                onChange={(e) => setKnowledgeFilter(e.target.value as "all" | KnowledgeStatus)}
                className="rounded border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="all">Все</option>
                <option value="approved">Approved</option>
                <option value="draft">Draft</option>
                <option value="failed">Failed</option>
                <option value="archived">Archived</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Тип источника</span>
              <select
                value={knowledgeSourceFilter}
                onChange={(e) => setKnowledgeSourceFilter(e.target.value as KnowledgeSourceFilter)}
                className="rounded border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="all">Все</option>
                <option value="upload">Документы</option>
                <option value="website_snapshot">Сайты</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Тег</span>
              <select
                value={knowledgeTagFilter}
                onChange={(e) => setKnowledgeTagFilter(e.target.value)}
                className="rounded border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="all">Все теги</option>
                {knowledgeAvailableTags.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => void loadKnowledgeData()}
              disabled={knowledgeLoading}
              className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-60"
            >
              {knowledgeLoading ? "Обновление..." : "Обновить список"}
            </button>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.25fr_0.95fr]">
            <div className="space-y-3">
              {knowledgeLoading && knowledgeRows.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-600">
                  Загружаю источники базы знаний...
                </div>
              )}

              {!knowledgeLoading && filteredKnowledgeRows.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-600">
                  <p>По текущим фильтрам источники не найдены.</p>
                  <button
                    onClick={() => void loadKnowledgeData()}
                    className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
                  >
                    Повторить
                  </button>
                </div>
              )}

              {visibleKnowledgeRows.map((item) => (
                <div key={item.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-base font-semibold text-slate-900">{item.title}</div>
                        <span className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium ${knowledgeStatusClass(item.status)}`}>
                          {knowledgeStatusLabel(item.status)}
                        </span>
                        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                          {knowledgeSourceLabel(item.source_type)}
                        </span>
                        {item.enabled_in_retrieval && (
                          <span className="inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">
                            В retrieval
                          </span>
                        )}
                      </div>
                      <div className="mt-2 text-xs text-slate-500">
                        {item.file_name || item.metadata_json?.url?.toString() || "Без имени файла"} | чанков: {item.chunk_count} | обновлен {formatDateTime(item.updated_at)}
                      </div>
                      {getKnowledgeTags(item).length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {getKnowledgeTags(item).map((tag) => (
                            <span key={`${item.id}-${tag}`} className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={item.enabled_in_retrieval}
                        onChange={(e) => void runKnowledgeAction(item, "toggle", e.target.checked)}
                      />
                      Участвует в retrieval
                    </label>
                  </div>

                  <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto] md:items-end">
                    <label className="text-sm">
                      <span className="mb-1 block text-slate-700">Теги</span>
                      <input
                        value={knowledgeTagDrafts[item.id] ?? formatKnowledgeTags(item)}
                        onChange={(e) => setKnowledgeTagDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))}
                        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                        placeholder="security, policies, ai"
                      />
                    </label>
                    <button
                      onClick={() => void saveKnowledgeTags(item)}
                      className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
                    >
                      Сохранить теги
                    </button>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      onClick={() => void loadKnowledgePreview(item.id)}
                      className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
                    >
                      Preview
                    </button>
                    <button
                      onClick={() => void runKnowledgeAction(item, "approve")}
                      disabled={item.status === "approved" || item.status === "processing"}
                      className="rounded border border-emerald-300 px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => void runKnowledgeAction(item, "archive")}
                      disabled={item.status === "archived"}
                      className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
                    >
                      Archive
                    </button>
                    <button
                      onClick={() => void runKnowledgeAction(item, "reindex")}
                      className="rounded border border-amber-300 px-3 py-2 text-sm text-amber-700 hover:bg-amber-50"
                    >
                      {item.status === "failed" ? "Retry" : "Reindex"}
                    </button>
                    <button
                      onClick={() => void runKnowledgeAction(item, "delete")}
                      className="rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}

              {filteredKnowledgeRows.length > visibleKnowledgeRows.length && (
                <button
                  onClick={() => setKnowledgeVisibleCount((prev) => prev + 10)}
                  className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm font-medium hover:bg-slate-50"
                >
                  Показать еще
                </button>
              )}
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-slate-900">Preview извлеченного текста</h3>
                {previewId && (
                  <button
                    onClick={() => {
                      setPreviewId(null);
                      setPreviewText("");
                    }}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-white"
                  >
                    Очистить
                  </button>
                )}
              </div>
              {!previewId && (
                <p className="mt-3 text-sm text-slate-600">
                  Выберите документ или сайт и нажмите <code>Preview</code>, чтобы увидеть извлеченный текст, который попадает в chunks.
                </p>
              )}
              {previewLoading && previewId && (
                <div className="mt-3 rounded border border-slate-200 bg-white px-3 py-4 text-sm text-slate-600">
                  Загружаю preview...
                </div>
              )}
              {!previewLoading && previewId && (
                <pre className="mt-3 max-h-[28rem] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white px-3 py-4 text-sm text-slate-800">
                  {previewText || "Для этого источника preview пока пуст."}
                </pre>
              )}
            </div>
          </div>
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
                <span className="min-w-0 flex-1">
                  <span className="mb-1 block">Режим источников знаний</span>
                  <select
                    value={providerDraft.knowledge_mode}
                    onChange={(e) =>
                      setProviderDraft({
                        ...providerDraft,
                        knowledge_mode: e.target.value as KnowledgeMode,
                        web_enabled: e.target.value === "glossary_documents_web",
                      })
                    }
                    className="mt-1 w-full border rounded px-2 py-1"
                  >
                    <option value="glossary_only">Только глоссарий</option>
                    <option value="glossary_documents">Глоссарий + документы</option>
                    <option value="glossary_documents_web">Глоссарий + документы + сайты</option>
                  </select>
                </span>
              </label>
              <p className="text-xs text-slate-500">Режим жестко ограничивает, какими источниками ИИ может пользоваться во время retrieval.</p>
              <label className="block">
                Поведение при пустом retrieval
                <select
                  value={providerDraft.empty_retrieval_mode}
                  onChange={(e) => setProviderDraft({ ...providerDraft, empty_retrieval_mode: e.target.value as EmptyRetrievalMode })}
                  className="mt-1 w-full border rounded px-2 py-1"
                >
                  <option value="strict_fallback">Строгий fallback</option>
                  <option value="model_only_fallback">Ответ модели без базы знаний</option>
                  <option value="clarifying_fallback">Уточняющий вопрос</option>
                </select>
              </label>
              <p className="text-xs text-slate-500">Рекомендуемый режим для production: ответ модели без базы знаний с явной маркировкой.</p>
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
                <span className="min-w-0 flex-1">
                  <span className="mb-1 block">Режим источников знаний</span>
                  <select
                    value={provider.knowledge_mode}
                    onChange={(e) =>
                      setProvider({
                        ...provider,
                        knowledge_mode: e.target.value as KnowledgeMode,
                        web_enabled: e.target.value === "glossary_documents_web",
                      })
                    }
                    className="mt-1 w-full border rounded px-2 py-1"
                  >
                    <option value="glossary_only">Только глоссарий</option>
                    <option value="glossary_documents">Глоссарий + документы</option>
                    <option value="glossary_documents_web">Глоссарий + документы + сайты</option>
                  </select>
                </span>
              </label>
              <p className="text-xs text-slate-500">Режим жестко задает, участвуют ли approved documents и approved website snapshots в ответах ИИ.</p>
              <label className="block">
                Поведение при пустом retrieval
                <select
                  value={provider.empty_retrieval_mode}
                  onChange={(e) => setProvider({ ...provider, empty_retrieval_mode: e.target.value as EmptyRetrievalMode })}
                  className="mt-1 w-full border rounded px-2 py-1"
                >
                  <option value="strict_fallback">Строгий fallback</option>
                  <option value="model_only_fallback">Ответ модели без базы знаний</option>
                  <option value="clarifying_fallback">Уточняющий вопрос</option>
                </select>
              </label>
              <p className="text-xs text-slate-500">Trace будет фиксировать `fallback_reason=no_retrieval_context` и реальный `answer_mode`.</p>
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
                <div className="mt-1 text-xs text-slate-600">knowledge mode: {t.knowledge_mode}</div>
                <div className="mt-1 text-xs text-slate-600">answer mode: {t.answer_mode}</div>
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
