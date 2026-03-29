"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { clearSession, redirectToAuth, showReloginNoticeOnce } from "@/lib/auth";
import { KNOWLEDGE_STATUS_FILTER_OPTIONS, type KnowledgeStatus, knowledgeStatusLabel } from "@/lib/knowledge-status";
import { useToast } from "@/components/ui/toast-provider";
import { ConfirmModal } from "@/components/ui/confirm-modal";

type Glossary = { id: string; term: string; definition: string; priority: number; status: string };
type GlossarySet = {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  enabled: boolean;
  is_default: boolean;
};
type KnowledgeSourceType = "upload" | "website_snapshot";
type EmptyRetrievalMode = "strict_fallback" | "model_only_fallback" | "clarifying_fallback";
type KnowledgeItem = {
  id: string;
  tenant_id: string;
  title: string;
  source_type: KnowledgeSourceType;
  mime_type: string | null;
  file_name: string | null;
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
  ingestion_error?: string | null;
  ingestion_error_at?: string | null;
};
type KnowledgeListResponse = {
  items: KnowledgeItem[];
  total: number;
  page: number;
  page_size: number;
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
type GlossaryClearResult = { glossary_id: string; deleted: number };
type Trace = {
  id: string;
  model: string;
  status: string;
  latency_ms: number;
  created_at: string;
  knowledge_mode: KnowledgeMode;
  answer_mode: string;
  chat_context_enabled: boolean;
  rewrite_used: boolean;
  rewritten_query?: string | null;
  history_messages_used: number;
  history_token_estimate: number;
  history_trimmed: boolean;
  token_usage?: {
    rewritten_query?: string;
    rewrite_used?: boolean;
    chat_context_enabled?: boolean;
    history_messages_used?: number;
    history_token_estimate?: number;
    history_trimmed?: boolean;
  };
};
type KnowledgeMode = "glossary_only" | "glossary_documents" | "glossary_documents_web";
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
  show_confidence: boolean;
  show_source_tags: boolean;
  response_tone: string;
  max_user_messages_total: number;
  chat_context_enabled: boolean;
  history_user_turn_limit: number;
  history_message_limit: number;
  history_token_budget: number;
  rewrite_history_message_limit: number;
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
  show_confidence: boolean;
  show_source_tags: boolean;
  response_tone: "consultative_supportive" | "neutral_reference";
  max_user_messages_total: number;
  chat_context_enabled: boolean;
  history_user_turn_limit: number;
  history_message_limit: number;
  history_token_budget: number;
  rewrite_history_message_limit: number;
};
type QdrantResetResult = {
  deleted_collections: string[];
  recreated_collections: string[];
  embedding_vector_size: number;
};

type LogItem = { id: string; type: string; message: string; created_at: string };
type ConfirmState = {
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "neutral";
};
type KnowledgeItemBusyAction = "approve" | "archive" | "reindex" | "delete" | "toggle" | "tags";
type PreviewStatus = "idle" | "loading" | "not_indexed" | "no_chunks" | "ready" | "error";

const PAGE_SIZE_OPTIONS = [5, 10, 20] as const;
const RECENT_ACTIVITY_DEFAULT_LIMIT = 3;
const CUSTOM_MODEL_OPTION = "__custom__";
const CHAT_MODEL_OPTIONS = [
  "openai/gpt-4o-mini",
  "openai/gpt-4.1-mini",
  "openai/gpt-4.1",
  "anthropic/claude-3.5-sonnet",
  "anthropic/claude-3.7-sonnet",
  "google/gemini-2.0-flash-001",
] as const;
const EMBEDDING_MODEL_OPTIONS = [
  "Embeddings",
  "EmbeddingsGigaR",
  "openai/text-embedding-3-small",
  "openai/text-embedding-3-large",
  "text-embedding-3-small",
] as const;
const QDRANT_RESET_CONFIRM_PHRASE = "DELETE ALL QDRANT COLLECTIONS";
const EMBEDDING_MODEL_LABELS: Record<string, string> = {
  Embeddings: "GigaChat Embeddings (default, 1024)",
  EmbeddingsGigaR: "GigaChat EmbeddingsGigaR (extended, 2560)",
  "openai/text-embedding-3-small": "OpenAI text-embedding-3-small via OpenRouter (1536)",
  "openai/text-embedding-3-large": "OpenAI text-embedding-3-large via OpenRouter (3072)",
  "text-embedding-3-small": "OpenAI text-embedding-3-small (legacy alias)",
};
const DEFAULT_PROVIDER_DRAFT: ProviderDraft = {
  base_url: "https://openrouter.ai/api/v1",
  api_key: "",
  model_name: "openai/gpt-4o-mini",
  embedding_model: "Embeddings",
  timeout_s: 30,
  retry_policy: 2,
  knowledge_mode: "glossary_documents",
  empty_retrieval_mode: "model_only_fallback",
  strict_glossary_mode: false,
  show_confidence: false,
  show_source_tags: true,
  response_tone: "consultative_supportive",
  max_user_messages_total: 5,
  chat_context_enabled: true,
  history_user_turn_limit: 6,
  history_message_limit: 12,
  history_token_budget: 1200,
  rewrite_history_message_limit: 8,
};

export function AdminPanel() {
  const [glossarySets, setGlossarySets] = useState<GlossarySet[]>([]);
  const [selectedGlossaryId, setSelectedGlossaryId] = useState<string>("");
  const [glossaryEntries, setGlossaryEntries] = useState<Glossary[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [recentTracesOpen, setRecentTracesOpen] = useState(false);
  const [recentErrorsOpen, setRecentErrorsOpen] = useState(false);
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
  const [qdrantVectorSizeDraft, setQdrantVectorSizeDraft] = useState<number>(1024);
  const [qdrantConfirmPhrase, setQdrantConfirmPhrase] = useState("");
  const [qdrantConfirmPhraseRepeat, setQdrantConfirmPhraseRepeat] = useState("");
  const [qdrantResetBusy, setQdrantResetBusy] = useState(false);
  const [knowledgeTab, setKnowledgeTab] = useState<"documents" | "sites">("documents");
  const [knowledgeFilter, setKnowledgeFilter] = useState<"all" | KnowledgeStatus>("all");
  const [knowledgeSearch, setKnowledgeSearch] = useState("");
  const [knowledgeTagFilter, setKnowledgeTagFilter] = useState("all");
  const [knowledgeTagOptions, setKnowledgeTagOptions] = useState<string[]>([]);
  const [documents, setDocuments] = useState<KnowledgeItem[]>([]);
  const [sites, setSites] = useState<KnowledgeItem[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgePage, setKnowledgePage] = useState(1);
  const [knowledgePageSize, setKnowledgePageSize] = useState<number>(5);
  const [knowledgeTotalCount, setKnowledgeTotalCount] = useState(0);
  const [knowledgeTagDrafts, setKnowledgeTagDrafts] = useState<Record<string, string>>({});
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [documentTitle, setDocumentTitle] = useState("");
  const [documentTags, setDocumentTags] = useState("");
  const [documentUploadBusy, setDocumentUploadBusy] = useState(false);
  const [siteUrl, setSiteUrl] = useState("");
  const [siteTitle, setSiteTitle] = useState("");
  const [siteTags, setSiteTags] = useState("");
  const [siteCreateBusy, setSiteCreateBusy] = useState(false);
  const [knowledgeItemBusy, setKnowledgeItemBusy] = useState<Record<string, KnowledgeItemBusyAction | undefined>>({});
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string>("");
  const [previewStatus, setPreviewStatus] = useState<PreviewStatus>("idle");
  const [previewError, setPreviewError] = useState<string>("");
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
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const confirmResolverRef = useRef<((confirmed: boolean) => void) | null>(null);

  function getErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return fallback;
  }

  function closeConfirmDialog(confirmed: boolean) {
    const resolve = confirmResolverRef.current;
    confirmResolverRef.current = null;
    setConfirmState(null);
    if (resolve) resolve(confirmed);
  }

  function askForConfirmation(config: ConfirmState): Promise<boolean> {
    if (confirmResolverRef.current) {
      confirmResolverRef.current(false);
      confirmResolverRef.current = null;
    }
    setConfirmState(config);
    return new Promise((resolve) => {
      confirmResolverRef.current = resolve;
    });
  }

  function setKnowledgeBusy(itemId: string, action: KnowledgeItemBusyAction | null) {
    setKnowledgeItemBusy((prev) => {
      const next = { ...prev };
      if (!action) {
        delete next[itemId];
      } else {
        next[itemId] = action;
      }
      return next;
    });
  }

  const reportError = useCallback(
    (message: string, title = "Admin error") => {
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

  useEffect(() => {
    setKnowledgePage(1);
  }, [knowledgeFilter, knowledgeSearch, knowledgeTab, knowledgeTagFilter, knowledgePageSize]);

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
    () => (knowledgeTab === "documents" ? documents : sites),
    [documents, knowledgeTab, sites],
  );

  const getKnowledgeTags = useCallback((item: KnowledgeItem): string[] => {
    const raw = item.metadata_json?.tags;
    if (!Array.isArray(raw)) return [];
    return raw.map((tag) => String(tag || "").trim()).filter(Boolean);
  }, []);

  const formatKnowledgeTags = useCallback(
    (item: KnowledgeItem): string => getKnowledgeTags(item).join(", "),
    [getKnowledgeTags],
  );

  const knowledgeTotalPages = Math.max(1, Math.ceil(knowledgeTotalCount / knowledgePageSize));

  useEffect(() => {
    if (knowledgePage > knowledgeTotalPages) setKnowledgePage(knowledgeTotalPages);
  }, [knowledgePage, knowledgeTotalPages]);

  function glossaryLabel(row: GlossarySet): string {
    const suffix = row.is_default ? "default" : `priority ${row.priority}`;
    return `${row.name} (${suffix})`;
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
    return sourceType === "website_snapshot" ? "Website" : "Document";
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

  function modelSelectValue(value: string, options: readonly string[]): string {
    return options.includes(value) ? value : CUSTOM_MODEL_OPTION;
  }

  function embeddingModelLabel(value: string): string {
    return EMBEDDING_MODEL_LABELS[value] || value;
  }

  const loadKnowledgeData = useCallback(async () => {
    setKnowledgeLoading(true);
    try {
      const sourceType: KnowledgeSourceType =
        knowledgeTab === "documents" ? "upload" : "website_snapshot";
      const params = new URLSearchParams();
      params.set("source_type", sourceType);
      params.set("page", String(knowledgePage));
      params.set("page_size", String(knowledgePageSize));
      if (knowledgeFilter !== "all") {
        params.set("status", knowledgeFilter);
      }
      const searchValue = knowledgeSearch.trim();
      if (searchValue) {
        params.set("search", searchValue);
      }
      const tagValue = knowledgeTagFilter.trim();
      if (tagValue && tagValue !== "all") {
        params.set("tag", tagValue);
      }
      const response = await api<KnowledgeListResponse>(`/admin/documents?${params.toString()}`);
      const rows = Array.isArray(response.items) ? response.items : [];
      const total = Number(response.total) || 0;

      if (knowledgeTab === "documents") {
        setDocuments(rows);
        setSites([]);
      } else {
        setSites(rows);
        setDocuments([]);
      }
      setKnowledgeTotalCount(total);
    } catch (e: unknown) {
      setKnowledgeTotalCount(0);
      if (knowledgeTab === "documents") {
        setDocuments([]);
      } else {
        setSites([]);
      }
      reportError(getErrorMessage(e, "Failed to load knowledge sources"), "Knowledge Base");
    } finally {
      setKnowledgeLoading(false);
    }
  }, [
    knowledgeFilter,
    knowledgePage,
    knowledgePageSize,
    knowledgeSearch,
    knowledgeTab,
    knowledgeTagFilter,
    reportError,
  ]);

  const loadKnowledgeTags = useCallback(async () => {
    try {
      const sourceType: KnowledgeSourceType =
        knowledgeTab === "documents" ? "upload" : "website_snapshot";
      const params = new URLSearchParams();
      params.set("source_type", sourceType);
      if (knowledgeFilter !== "all") {
        params.set("status", knowledgeFilter);
      }
      const searchValue = knowledgeSearch.trim();
      if (searchValue) {
        params.set("search", searchValue);
      }
      const tags = await api<string[]>(`/admin/documents/tags?${params.toString()}`);
      const options = Array.isArray(tags) ? tags : [];
      setKnowledgeTagOptions(options);
      setKnowledgeTagFilter((prev) => (prev === "all" || options.includes(prev) ? prev : "all"));
    } catch (e: unknown) {
      setKnowledgeTagOptions([]);
      setKnowledgeTagFilter("all");
      reportError(getErrorMessage(e, "Failed to load tag filters"), "Knowledge Base");
    }
  }, [
    knowledgeFilter,
    knowledgeSearch,
    knowledgeTab,
    reportError,
  ]);

  const loadAll = useCallback(async () => {
    try {
      const tracesParams = new URLSearchParams();
      tracesParams.set("limit", String(RECENT_ACTIVITY_DEFAULT_LIMIT));
      const logsParams = new URLSearchParams();
      logsParams.set("limit", String(RECENT_ACTIVITY_DEFAULT_LIMIT));
      const [g, t, l, pending] = await Promise.all([
        api<GlossarySet[]>("/glossary"),
        api<Trace[]>(`/admin/traces?${tracesParams.toString()}`),
        api<LogItem[]>(`/admin/logs?${logsParams.toString()}`),
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
      setTraces(t);
      setLogs(l);
      setPendingRegistrations(pending);
      try {
        const p = await api<Provider>("/admin/provider");
        setProvider(p);
      } catch (providerError: unknown) {
        if (providerError instanceof ApiError && providerError.status === 404) {
          setProvider(null);
        } else {
          throw providerError;
        }
      }
    } catch (e: unknown) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      reportError(getErrorMessage(e, "Failed to load admin data"));
    }
  }, [reportError, selectedGlossaryId]);

  useEffect(() => {
    void loadKnowledgeData();
  }, [loadKnowledgeData]);

  useEffect(() => {
    void loadKnowledgeTags();
  }, [loadKnowledgeTags]);

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
      reportError("Select a PDF, MD, or TXT file", "Documents");
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
      await api<KnowledgeItem>("/admin/documents/upload", {
        method: "POST",
        body: form,
      });
      setDocumentFile(null);
      if (documentFileInputRef.current) {
        documentFileInputRef.current.value = "";
      }
      setDocumentTitle("");
      setDocumentTags("");
      await loadKnowledgeData();
      reportSuccess("Document uploaded", "The file has been queued for ingestion.");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to upload document"), "Documents");
    } finally {
      setDocumentUploadBusy(false);
    }
  }

  async function createWebsiteSnapshot() {
    if (!siteUrl.trim()) {
      reportError("Enter a website URL", "Websites");
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
      reportSuccess("Website added", "The snapshot has been queued for ingestion.");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to add website"), "Websites");
    } finally {
      setSiteCreateBusy(false);
    }
  }

  async function loadKnowledgePreview(documentId: string) {
    setPreviewId(documentId);
    setPreviewLoading(true);
    setPreviewStatus("loading");
    setPreviewError("");
    setPreviewText("");
    try {
      const detail = await api<KnowledgeDetail>(`/admin/documents/${documentId}`);
      if (detail.status === "draft" || detail.status === "processing") {
        setPreviewStatus("not_indexed");
        return;
      }
      if (!Array.isArray(detail.chunks) || detail.chunks.length === 0) {
        setPreviewStatus("no_chunks");
        return;
      }
      const excerpt = detail.chunks
        .slice(0, 6)
        .map((chunk) => chunk.content.trim())
        .filter(Boolean)
        .join("\n\n");
      if (!excerpt) {
        setPreviewStatus("no_chunks");
        return;
      }
      setPreviewText(excerpt);
      setPreviewStatus("ready");
    } catch (e: unknown) {
      setPreviewStatus("error");
      setPreviewError(getErrorMessage(e, "Failed to load preview"));
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
      if (knowledgeItemBusy[item.id]) {
        return;
      }
      if (action === "delete") {
        const confirmed = await askForConfirmation({
          title: "Delete source",
          description: `Delete source "${item.title}"? This action cannot be undone.`,
          confirmLabel: "Delete",
          tone: "danger",
        });
        if (!confirmed) {
          return;
        }
      }
      if (action === "approve") {
        const confirmed = await askForConfirmation({
          title: "Approve source",
          description: `Approve source "${item.title}" and include it in the approved knowledge base?`,
          confirmLabel: "Approve",
          tone: "neutral",
        });
        if (!confirmed) {
          return;
        }
      }
      setKnowledgeBusy(item.id, action);
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
          setPreviewStatus("idle");
          setPreviewError("");
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
          ? "Source approved"
          : action === "archive"
            ? "Source archived"
            : action === "reindex"
              ? "Reindex started"
              : action === "toggle"
                ? enabled
                  ? "Source included in retrieval"
                  : "Source excluded from retrieval"
                : "Source deleted";
      reportSuccess(successTitle);
    } catch (e: unknown) {
      const actionLabel =
        action === "approve"
          ? "approve"
          : action === "archive"
            ? "archive"
            : action === "reindex"
              ? "reindex"
              : action === "toggle"
                ? "update"
                : "delete";
      reportError(getErrorMessage(e, `Failed to ${actionLabel} source`), "Knowledge Base");
    } finally {
      setKnowledgeBusy(item.id, null);
    }
  }

  async function saveKnowledgeTags(item: KnowledgeItem) {
    if (knowledgeItemBusy[item.id]) {
      return;
    }
    try {
      setKnowledgeBusy(item.id, "tags");
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
      reportSuccess("Tags updated");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to update tags"), "Knowledge Base");
    } finally {
      setKnowledgeBusy(item.id, null);
    }
  }

  async function importGlossaryCsv() {
    if (!selectedGlossaryId) {
      reportError("Select a glossary first", "Glossary");
      return;
    }
    if (!glossaryImportFile) {
      reportError("Select a CSV file", "Glossary");
      return;
    }
    setGlossaryImportBusy(true);
    try {
      const form = new FormData();
      form.append("file", glossaryImportFile);
      const result = await api<GlossaryCsvImportResult>(`/glossary/${selectedGlossaryId}/import-csv`, {
        method: "POST",
        body: form,
      });
      setGlossaryImportFile(null);
      if (glossaryImportInputRef.current) {
        glossaryImportInputRef.current.value = "";
      }
      await loadAll();
      reportSuccess("CSV import completed", `Created: ${result.created}, updated: ${result.updated}.`);
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to import CSV"), "Glossary");
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
      reportSuccess("Glossary entry added");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to add glossary entry"));
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
      reportSuccess("Glossary entry updated");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to update glossary entry"));
    }
  }

  async function deleteGlossary(id: string) {
    if (!selectedGlossaryId) return;
    const ok = await askForConfirmation({
      title: "Delete glossary entry",
      description: "Delete this glossary entry permanently?",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api(`/glossary/${selectedGlossaryId}/entries/${id}`, { method: "DELETE" });
      await loadAll();
      reportSuccess("Glossary entry deleted");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to delete glossary entry"));
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
      reportSuccess("Glossary created");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to create glossary"));
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
      reportSuccess("Glossary updated");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to update glossary"));
    }
  }

  async function deleteGlossarySet(id: string) {
    const ok = await askForConfirmation({
      title: "Delete glossary",
      description: "Delete the entire glossary together with all entries?",
      confirmLabel: "Delete glossary",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api(`/glossary/${id}`, { method: "DELETE" });
      await loadAll();
      reportSuccess("Glossary deleted");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to delete glossary"));
    }
  }

  async function clearDefaultGlossary() {
    const ok = await askForConfirmation({
      title: "Clear default glossary entries",
      description: "Delete all entries from the default glossary? The glossary itself will remain.",
      confirmLabel: "Clear entries",
      tone: "danger",
    });
    if (!ok) return;
    try {
      const result = await api<GlossaryClearResult>("/glossary/default/clear", { method: "POST" });
      await loadAll();
      reportSuccess("Default glossary cleared", `Deleted entries: ${result.deleted}.`);
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to clear default glossary"), "Glossary");
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
          show_confidence: provider.show_confidence,
          show_source_tags: provider.show_source_tags,
          response_tone: provider.response_tone,
          max_user_messages_total: provider.max_user_messages_total,
          chat_context_enabled: provider.chat_context_enabled,
          history_user_turn_limit: provider.history_user_turn_limit,
          history_message_limit: provider.history_message_limit,
          history_token_budget: provider.history_token_budget,
          rewrite_history_message_limit: provider.rewrite_history_message_limit,
          api_key: providerDraft.api_key.trim() || undefined,
        }
      : {
          ...providerDraft,
          api_key: providerDraft.api_key.trim(),
        };

    if (!provider && !source.api_key) {
      reportError("Enter an API key for the initial provider setup", "Provider Settings");
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
      reportSuccess("Provider settings saved");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: unknown) {
      setProviderSaveStatus("error");
      reportError(getErrorMessage(e, "Failed to save settings"), "Provider Settings");
    } finally {
      setProviderSaving(false);
    }
  }

  async function saveLimits() {
    if (!provider) {
      reportError("Save the basic provider settings first", "User Limits");
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
          show_confidence: provider.show_confidence,
          show_source_tags: provider.show_source_tags,
          response_tone: provider.response_tone,
          max_user_messages_total: provider.max_user_messages_total,
          chat_context_enabled: provider.chat_context_enabled,
          history_user_turn_limit: provider.history_user_turn_limit,
          history_message_limit: provider.history_message_limit,
          history_token_budget: provider.history_token_budget,
          rewrite_history_message_limit: provider.rewrite_history_message_limit,
        }),
      });
      await loadAll();
      setProviderSaveStatus("success");
      reportSuccess("User limits saved");
      window.setTimeout(() => setProviderSaveStatus("idle"), 2200);
    } catch (e: unknown) {
      setProviderSaveStatus("error");
      reportError(getErrorMessage(e, "Failed to save limits"), "User Limits");
    } finally {
      setProviderSaving(false);
    }
  }

  async function resetAllQdrantCollections() {
    if (qdrantResetBusy) {
      return;
    }
    if (qdrantConfirmPhrase.trim() !== QDRANT_RESET_CONFIRM_PHRASE) {
      reportError("First confirmation phrase does not match", "Qdrant maintenance");
      return;
    }
    if (qdrantConfirmPhraseRepeat.trim() !== QDRANT_RESET_CONFIRM_PHRASE) {
      reportError("Second confirmation phrase does not match", "Qdrant maintenance");
      return;
    }
    const confirmed = await askForConfirmation({
      title: "Reset all Qdrant collections",
      description:
        "This deletes every collection in Qdrant and recreates default collections. Existing vectors will be lost.",
      confirmLabel: "Reset Qdrant",
      tone: "danger",
    });
    if (!confirmed) {
      return;
    }
    setQdrantResetBusy(true);
    try {
      const response = await api<QdrantResetResult>("/admin/qdrant/reset-all", {
        method: "POST",
        body: JSON.stringify({
          embedding_vector_size: qdrantVectorSizeDraft,
          confirm_phrase: qdrantConfirmPhrase.trim(),
          confirm_phrase_repeat: qdrantConfirmPhraseRepeat.trim(),
        }),
      });
      setQdrantConfirmPhrase("");
      setQdrantConfirmPhraseRepeat("");
      reportSuccess(
        "Qdrant collections recreated",
        `Deleted ${response.deleted_collections.length} collections; vector size: ${response.embedding_vector_size}.`,
      );
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to reset Qdrant collections"), "Qdrant maintenance");
    } finally {
      setQdrantResetBusy(false);
    }
  }

  function formatDateTime(value: string): string {
    return new Date(value).toLocaleString("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  async function approveRegistration(userId: string) {
    const ok = await askForConfirmation({
      title: "Approve registration",
      description: "Approve registration for this user?",
      confirmLabel: "Approve",
      tone: "neutral",
    });
    if (!ok) return;
    try {
      await api(`/admin/registrations/${userId}/approve`, { method: "POST" });
      await loadAll();
      reportSuccess("User approved");
    } catch (e: unknown) {
      reportError(getErrorMessage(e, "Failed to approve user"), "Pending Registrations");
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
        <span className="text-slate-600">Per page:</span>
        <select
          value={props.pageSize}
          onChange={(e) => props.onPageSizeChange(Number(e.target.value))}
          className="input-base w-auto px-2 py-1"
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
          className="btn btn-secondary px-2 py-1"
        >
          Back
        </button>
        <span className="text-slate-600">{props.page} / {props.totalPages}</span>
        <button
          onClick={props.onNext}
          disabled={props.page >= props.totalPages}
          className="btn btn-secondary px-2 py-1"
        >
          Next
        </button>
      </div>
    );
  }

  const activeTabLabel = knowledgeTab === "documents" ? "documents" : "website snapshots";
  const activeTabNoun = knowledgeTab === "documents" ? "documents" : "websites";

  return (
    <div className="safe-x safe-top safe-bottom min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl space-y-4 p-3 pb-8 md:p-6">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900">Admin Console</h1>
              <p className="mt-1 text-sm text-slate-600">Manage glossaries, knowledge sources, and response settings.</p>
            </div>
            <Link
              href="/chat"
              className="inline-flex items-center justify-center rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Return to Chat
            </Link>
          </div>
        </div>
        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Glossaries</h2>
          <p className="mt-1 text-sm text-slate-600">
            Priority defines glossary precedence: the lower the number, the higher the priority. A value of <code>100</code> is the standard default.
          </p>
          <div className="mt-3 grid gap-2 md:grid-cols-[2fr_2fr_120px_auto]">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Glossary name</span>
              <input
                value={glossaryName}
                onChange={(e) => setGlossaryName(e.target.value)}
                className="input-base"
                placeholder="Glossary name"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Description</span>
              <input
                value={glossaryDescription}
                onChange={(e) => setGlossaryDescription(e.target.value)}
                className="input-base"
                placeholder="Description"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Priority</span>
              <input
                type="number"
                min={1}
                max={1000}
                value={glossaryPriority}
                onChange={(e) => setGlossaryPriority(Number(e.target.value))}
                className="input-base"
                placeholder="Priority (1-1000)"
                title="The lower the number, the higher the priority. 100 is the default."
              />
            </label>
            <button onClick={addGlossarySet} className="btn btn-primary">Create</button>
          </div>

          <div className="mt-3 space-y-3 md:hidden">
            {glossarySetRows.map((g) => (
              <div key={g.id} className="rounded-lg border border-slate-200 p-3">
                <div className="space-y-2">
                  <input
                    value={g.name}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, name: e.target.value } : row)))}
                    className="input-base"
                    placeholder="Name"
                    aria-label={`Glossary name for ${g.name}`}
                  />
                  <input
                    value={g.description || ""}
                    onChange={(e) =>
                      setGlossarySets((prev) =>
                        prev.map((row) => (row.id === g.id ? { ...row, description: e.target.value || null } : row)),
                      )
                    }
                    className="input-base"
                    placeholder="Description"
                    aria-label={`Glossary description for ${g.name}`}
                  />
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={g.priority}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, priority: Number(e.target.value) } : row)))}
                    className="input-base"
                    title="The lower the number, the higher the priority."
                    aria-label={`Glossary priority for ${g.name}`}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={g.enabled}
                        disabled={g.is_default}
                        onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, enabled: e.target.checked } : row)))}
                      />
                      Enabled
                    </label>
                    {g.is_default && (
                      <span className="inline-flex items-center rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700">
                        default
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <button onClick={() => void saveGlossarySet(g)} className="btn btn-secondary">Save</button>
                    <button
                      disabled={g.is_default}
                      onClick={() => void deleteGlossarySet(g.id)}
                      className="btn btn-danger disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {glossarySets.length === 0 && <p className="px-1 py-2 text-sm text-slate-600">No glossaries found.</p>}
          </div>

          <div className="mt-3 hidden overflow-x-auto rounded-lg border border-slate-200 md:block">
            <div className="min-w-[980px]">
              <div className="grid grid-cols-[1.3fr_1.7fr_120px_220px_230px] items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <span>Name</span>
                <span>Description</span>
                <span>Priority</span>
                <span>Status</span>
                <span>Actions</span>
              </div>
              {glossarySetRows.map((g) => (
                <div key={g.id} className="grid grid-cols-[1.3fr_1.7fr_120px_220px_230px] items-center gap-2 border-b border-slate-100 px-3 py-2 last:border-b-0">
                  <input
                    value={g.name}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, name: e.target.value } : row)))}
                    className="input-base"
                    aria-label={`Glossary name for ${g.name}`}
                  />
                  <input
                    value={g.description || ""}
                    onChange={(e) =>
                      setGlossarySets((prev) =>
                        prev.map((row) => (row.id === g.id ? { ...row, description: e.target.value || null } : row)),
                      )
                    }
                    className="input-base"
                    placeholder="Description"
                    aria-label={`Glossary description for ${g.name}`}
                  />
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={g.priority}
                    onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, priority: Number(e.target.value) } : row)))}
                    className="input-base"
                    title="The lower the number, the higher the priority."
                    aria-label={`Glossary priority for ${g.name}`}
                  />
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={g.enabled}
                        disabled={g.is_default}
                        onChange={(e) => setGlossarySets((prev) => prev.map((row) => (row.id === g.id ? { ...row, enabled: e.target.checked } : row)))}
                      />
                      Enabled
                    </label>
                    {g.is_default && (
                      <span className="inline-flex items-center rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700">
                        default
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => void saveGlossarySet(g)} className="btn btn-secondary">Save</button>
                    <button
                      disabled={g.is_default}
                      onClick={() => void deleteGlossarySet(g.id)}
                      className="btn btn-danger disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
              {glossarySets.length === 0 && <p className="px-3 py-3 text-sm text-slate-600">No glossaries found.</p>}
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

          <h3 className="mt-6 text-base font-semibold">Entries in the selected glossary</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-[minmax(240px,420px)_1fr] items-end">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Glossary to edit</span>
              <select
                value={selectedGlossaryId}
                onChange={(e) => {
                  setSelectedGlossaryId(e.target.value);
                  setGlossaryPage(1);
                }}
                className="input-base"
              >
                {glossarySets.length === 0 ? (
                  <option value="">No glossaries available</option>
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
            {selectedGlossary ? `Selected: ${selectedGlossary.name}` : "Create or select a glossary first."}
          </div>
          {selectedGlossary?.is_default && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => void clearDefaultGlossary()}
                className="btn btn-danger"
              >
                Clear Default Glossary Entries
              </button>
            </div>
          )}
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
              <label className="text-sm">
                <span className="mb-1 block text-slate-700">CSV import with upsert by term</span>
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
                className="rounded bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                {glossaryImportBusy ? "Importing..." : "Import CSV"}
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              CSV only, up to 10 MB. Required columns: <code>term</code>, <code>definition</code>. Optional columns:
              <code>synonyms</code>, <code>forbidden_interpretations</code>, <code>tags</code>, <code>metadata_json</code>. List values inside a cell must be separated by <code>;</code>.
            </p>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-[1fr_2fr_auto]">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Term</span>
              <input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                className="input-base"
                placeholder="Term"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Definition</span>
              <input
                value={definition}
                onChange={(e) => setDefinition(e.target.value)}
                className="input-base"
                placeholder="Definition"
              />
            </label>
            <button
              onClick={addGlossary}
              disabled={!selectedGlossaryId}
              className="btn btn-primary disabled:opacity-50"
            >
              Add
            </button>
          </div>

          <div className="mt-3 space-y-2">
            {glossaryRows.map((g) => (
              <div key={g.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="text-sm flex-1">
                    <div className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 border-l-4 border-l-amber-500">
                      <div className="text-[11px] uppercase tracking-wide font-semibold text-amber-800">Term</div>
                      <div className="mt-0.5 text-base font-extrabold text-slate-900">{g.term}</div>
                      <div className="my-2 border-t border-amber-200" />
                      <div className="text-slate-700">{g.definition}</div>
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => openGlossaryModal(g)} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">Edit</button>
                    <button onClick={() => void deleteGlossary(g.id)} className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50">Delete</button>
                  </div>
                </div>
              </div>
            ))}
            {glossaryRows.length === 0 && <p className="text-sm text-slate-600">No entries found.</p>}
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
              <h2 className="text-lg font-semibold">Knowledge Base</h2>
              <p className="mt-1 text-sm text-slate-600">Upload, ingestion, preview, and approval for documents and website snapshots.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => {
                  setKnowledgeTab("documents");
                }}
                className={`rounded-full px-3 py-1.5 text-sm ${knowledgeTab === "documents" ? "bg-emerald-600 text-white" : "border border-slate-300 text-slate-700"}`}
              >
                Documents
              </button>
              <button
                onClick={() => {
                  setKnowledgeTab("sites");
                }}
                className={`rounded-full px-3 py-1.5 text-sm ${knowledgeTab === "sites" ? "bg-emerald-600 text-white" : "border border-slate-300 text-slate-700"}`}
              >
                Websites
              </button>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            {knowledgeTab === "documents" ? (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-[1.2fr_1fr_1fr_auto] md:items-end">
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">File</span>
                    <input
                      type="file"
                      accept=".pdf,.md,.txt,text/plain,text/markdown,application/pdf"
                      ref={documentFileInputRef}
                      onChange={(e) => setDocumentFile(e.target.files?.[0] || null)}
                      className="input-base w-full bg-white text-sm"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Title</span>
                    <input
                      value={documentTitle}
                      onChange={(e) => setDocumentTitle(e.target.value)}
                      className="input-base w-full text-sm"
                      placeholder="Document title"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Tags</span>
                    <input
                      value={documentTags}
                      onChange={(e) => setDocumentTags(e.target.value)}
                      className="input-base w-full text-sm"
                      placeholder="security, policies, onboarding"
                    />
                  </label>
                  <button
                    onClick={() => void uploadKnowledgeDocument()}
                    disabled={documentUploadBusy}
                    className="btn btn-primary disabled:opacity-70"
                  >
                    {documentUploadBusy ? "Uploading..." : "Upload"}
                  </button>
                </div>
                <p className="text-xs text-slate-500">Only `PDF`, `MD`, and `TXT` files are supported. Maximum file size: `50 MB`.</p>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-[1.4fr_1fr_1fr_auto] md:items-end">
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">URL</span>
                    <input
                      value={siteUrl}
                      onChange={(e) => setSiteUrl(e.target.value)}
                      className="input-base w-full text-sm"
                      placeholder="https://example.com/page"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Title</span>
                    <input
                      value={siteTitle}
                      onChange={(e) => setSiteTitle(e.target.value)}
                      className="input-base w-full text-sm"
                      placeholder="Snapshot title"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-700">Tags</span>
                    <input
                      value={siteTags}
                      onChange={(e) => setSiteTags(e.target.value)}
                      className="input-base w-full text-sm"
                      placeholder="ai, security, owasp"
                    />
                  </label>
                  <button
                    onClick={() => void createWebsiteSnapshot()}
                    disabled={siteCreateBusy}
                    className="btn btn-primary disabled:opacity-70"
                  >
                    {siteCreateBusy ? "Adding..." : "Add URL"}
                  </button>
                </div>
                <p className="text-xs text-slate-500">
                  Website search is limited to the exact page URL you add. EZII does not crawl the entire domain or search linked internal pages automatically.
                </p>
              </div>
            )}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-[1.5fr_repeat(2,minmax(0,220px))_auto] md:items-end">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Search by title</span>
              <input
                value={knowledgeSearch}
                onChange={(e) => setKnowledgeSearch(e.target.value)}
                className="input-base w-full text-sm"
                placeholder="Document title, URL, or tag"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Status filter</span>
              <select
                value={knowledgeFilter}
                onChange={(e) => setKnowledgeFilter(e.target.value as "all" | KnowledgeStatus)}
                className="input-base text-sm"
              >
                {KNOWLEDGE_STATUS_FILTER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Tag</span>
              <select
                value={knowledgeTagFilter}
                onChange={(e) => setKnowledgeTagFilter(e.target.value)}
                className="input-base text-sm"
              >
                <option value="all">All tags</option>
                {knowledgeTagOptions.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => void loadKnowledgeData()}
              disabled={knowledgeLoading}
              className="btn btn-secondary disabled:opacity-60"
            >
              {knowledgeLoading ? "Refreshing..." : "Refresh list"}
            </button>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.25fr_0.95fr]">
            <div className="min-w-0">
              <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900">Knowledge sources ({activeTabLabel})</div>
                  <div className="mt-1 text-sm text-slate-700">
                    Showing {knowledgeRows.length} of {knowledgeTotalCount} | page {knowledgePage} of {knowledgeTotalPages}
                  </div>
                </div>
                <div className="text-xs uppercase tracking-wide text-slate-600">
                  internal pagination
                </div>
              </div>

              <div className="space-y-3 lg:max-h-[72vh] lg:overflow-y-auto lg:pr-2">
                {knowledgeLoading && knowledgeRows.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-600">
                    Loading {activeTabNoun}...
                  </div>
                )}

                {!knowledgeLoading && knowledgeTotalCount === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-600">
                    <p>No {activeTabNoun} match the current filters.</p>
                    <button
                      onClick={() => void loadKnowledgeData()}
                      className="btn btn-secondary mt-3"
                    >
                      Retry
                    </button>
                  </div>
                )}

                {knowledgeRows.map((item) => (
                  <div key={item.id} className="rounded-xl border border-slate-200 p-4">
                    {(() => {
                      const busyAction = knowledgeItemBusy[item.id] ?? null;
                      const isBusy = Boolean(busyAction);
                      return (
                        <>
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
                              In retrieval
                            </span>
                          )}
                        </div>
                        <div className="mt-2 grid gap-x-4 gap-y-1 text-sm text-slate-600 sm:grid-cols-2">
                          <div className="min-w-0">
                            <span className="font-medium text-slate-700">File:</span>{" "}
                            <span className="break-words">{item.file_name || item.metadata_json?.url?.toString() || "No file name"}</span>
                          </div>
                          <div>
                            <span className="font-medium text-slate-700">Updated:</span>{" "}
                            <span className="font-mono tabular-nums">{formatDateTime(item.updated_at)}</span>
                          </div>
                          <div>
                            <span className="font-medium text-slate-700">Chunks:</span>{" "}
                            <span className="font-mono tabular-nums">{item.chunk_count}</span>
                          </div>
                        </div>
                        {item.status === "failed" && item.ingestion_error && (
                          <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                            <div className="font-medium">Processing error</div>
                            <div className="mt-1 whitespace-pre-wrap break-words">{item.ingestion_error}</div>
                            {item.ingestion_error_at && (
                              <div className="mt-1 text-xs text-red-800">Updated {formatDateTime(item.ingestion_error_at)}</div>
                            )}
                          </div>
                        )}
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
                          disabled={isBusy}
                          onChange={(e) => void runKnowledgeAction(item, "toggle", e.target.checked)}
                        />
                        Included in retrieval
                      </label>
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto] md:items-end">
                      <label className="text-sm">
                        <span className="mb-1 block text-slate-700">Tags</span>
                        <input
                          value={knowledgeTagDrafts[item.id] ?? formatKnowledgeTags(item)}
                          onChange={(e) => setKnowledgeTagDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))}
                          className="input-base"
                          placeholder="security, policies, ai"
                        />
                      </label>
                      <button
                        onClick={() => void saveKnowledgeTags(item)}
                        disabled={isBusy}
                        className="btn btn-secondary disabled:opacity-50"
                      >
                        {busyAction === "tags" ? "Saving..." : "Save tags"}
                      </button>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        onClick={() => void loadKnowledgePreview(item.id)}
                        className="btn btn-secondary"
                      >
                        Preview
                      </button>
                      <button
                        onClick={() => void runKnowledgeAction(item, "approve")}
                        disabled={isBusy || item.status === "approved" || item.status === "processing"}
                        className="btn btn-secondary border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                      >
                        {busyAction === "approve" ? "Approving..." : "Approve"}
                      </button>
                      <button
                        onClick={() => void runKnowledgeAction(item, "archive")}
                        disabled={isBusy || item.status === "archived"}
                        className="btn btn-secondary disabled:opacity-50"
                      >
                        {busyAction === "archive" ? "Archiving..." : "Archive"}
                      </button>
                      <button
                        onClick={() => void runKnowledgeAction(item, "reindex")}
                        disabled={isBusy}
                        className="btn btn-secondary border-amber-300 text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                      >
                        {busyAction === "reindex" ? "Starting..." : (item.status === "failed" ? "Retry" : "Reindex")}
                      </button>
                      <button
                        onClick={() => void runKnowledgeAction(item, "delete")}
                        disabled={isBusy}
                        className="btn btn-danger disabled:opacity-50"
                      >
                        {busyAction === "delete" ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                        </>
                      );
                    })()}
                  </div>
                ))}

                {knowledgeTotalCount > 0 && (
                  <div className="sticky bottom-0 rounded-xl border border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-slate-600">Per page:</span>
                        <select
                          value={knowledgePageSize}
                          onChange={(e) => setKnowledgePageSize(Number(e.target.value))}
                          className="input-base w-auto px-2 py-1"
                        >
                          {PAGE_SIZE_OPTIONS.map((size) => (
                            <option key={size} value={size}>
                              {size}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <button
                          onClick={() => setKnowledgePage((prev) => Math.max(1, prev - 1))}
                          disabled={knowledgePage <= 1}
                          className="btn btn-secondary disabled:opacity-50"
                        >
                          Back
                        </button>
                        <span className="text-slate-600">{knowledgePage} / {knowledgeTotalPages}</span>
                        <button
                          onClick={() => setKnowledgePage((prev) => Math.min(knowledgeTotalPages, prev + 1))}
                          disabled={knowledgePage >= knowledgeTotalPages}
                          className="btn btn-secondary disabled:opacity-50"
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 lg:sticky lg:top-4 lg:self-start">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-slate-900">Extracted text preview</h3>
                {previewId && (
                  <button
                    onClick={() => {
                      setPreviewId(null);
                      setPreviewText("");
                      setPreviewStatus("idle");
                      setPreviewError("");
                    }}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-white"
                  >
                    Clear
                  </button>
                )}
              </div>
              {!previewId && (
                <p className="mt-3 text-sm text-slate-600">
                  Select a document or website and click <code>Preview</code> to inspect the extracted text that is stored in chunks.
                </p>
              )}
              {previewLoading && previewId && (
                <div className="mt-3 rounded border border-slate-200 bg-white px-3 py-4 text-sm text-slate-600">
                  Loading preview...
                </div>
              )}
              {!previewLoading && previewId && previewStatus === "not_indexed" && (
                <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-4 text-sm text-amber-900">
                  <div className="font-medium">Not indexed yet</div>
                  <div className="mt-1">
                    This source is still in draft/processing state. Approve it after ingestion to inspect extracted chunks.
                  </div>
                </div>
              )}
              {!previewLoading && previewId && previewStatus === "no_chunks" && (
                <div className="mt-3 rounded border border-slate-200 bg-white px-3 py-4 text-sm text-slate-700">
                  <div className="font-medium text-slate-900">No chunks extracted</div>
                  <div className="mt-1">This source does not contain extracted chunk text yet.</div>
                </div>
              )}
              {!previewLoading && previewId && previewStatus === "error" && (
                <div className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-4 text-sm text-red-900">
                  <div className="font-medium">Fetch failed</div>
                  <div className="mt-1 whitespace-pre-wrap break-words">{previewError || "Failed to load preview."}</div>
                </div>
              )}
              {!previewLoading && previewId && previewStatus === "ready" && (
                <pre className="mt-3 max-h-[28rem] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white px-3 py-4 text-sm text-slate-800">
                  {previewText || "Preview is empty for this source."}
                </pre>
              )}
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Response Settings</h2>
          {!provider ? (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-slate-600">The provider is not configured yet. Fill in the parameters for the initial setup.</p>
              <label className="block">
                Base URL
                <input
                  value={providerDraft.base_url}
                  onChange={(e) => setProviderDraft({ ...providerDraft, base_url: e.target.value })}
                  className="input-base mt-1 w-full"
                />
              </label>
              <label className="block">
                API key
                <input
                  type="password"
                  value={providerDraft.api_key}
                  onChange={(e) => setProviderDraft({ ...providerDraft, api_key: e.target.value })}
                  className="input-base mt-1 w-full"
                />
              </label>
              <label className="block">
                Chat model
                <select
                  value={modelSelectValue(providerDraft.model_name, CHAT_MODEL_OPTIONS)}
                  onChange={(e) =>
                    setProviderDraft({
                      ...providerDraft,
                      model_name: e.target.value === CUSTOM_MODEL_OPTION ? "" : e.target.value,
                    })
                  }
                  className="input-base mt-1 w-full"
                >
                  {CHAT_MODEL_OPTIONS.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                  <option value={CUSTOM_MODEL_OPTION}>Custom</option>
                </select>
                {modelSelectValue(providerDraft.model_name, CHAT_MODEL_OPTIONS) === CUSTOM_MODEL_OPTION && (
                  <input
                    value={providerDraft.model_name}
                    onChange={(e) => setProviderDraft({ ...providerDraft, model_name: e.target.value })}
                    className="input-base mt-2 w-full"
                    placeholder="provider/model-id"
                  />
                )}
              </label>
              <label className="block">
                Embedding model
                <select
                  value={modelSelectValue(providerDraft.embedding_model, EMBEDDING_MODEL_OPTIONS)}
                  onChange={(e) =>
                    setProviderDraft({
                      ...providerDraft,
                      embedding_model: e.target.value === CUSTOM_MODEL_OPTION ? "" : e.target.value,
                    })
                  }
                  className="input-base mt-1 w-full"
                >
                  {EMBEDDING_MODEL_OPTIONS.map((model) => (
                    <option key={model} value={model}>
                      {embeddingModelLabel(model)}
                    </option>
                  ))}
                  <option value={CUSTOM_MODEL_OPTION}>Custom</option>
                </select>
                {modelSelectValue(providerDraft.embedding_model, EMBEDDING_MODEL_OPTIONS) === CUSTOM_MODEL_OPTION && (
                  <input
                    value={providerDraft.embedding_model}
                    onChange={(e) => setProviderDraft({ ...providerDraft, embedding_model: e.target.value })}
                    className="input-base mt-2 w-full"
                    placeholder="provider/embedding-model-id"
                  />
                )}
              </label>
              <p className="text-xs text-slate-500">
                Chat model is used for answer generation and query rewriting. Embedding model is used for glossary/doc/site indexing and retrieval.
              </p>
              <div className="grid gap-2 md:grid-cols-2">
                <label className="block">
                  Timeout (seconds)
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={providerDraft.timeout_s}
                    onChange={(e) => setProviderDraft({ ...providerDraft, timeout_s: Number(e.target.value) })}
                    className="input-base mt-1 w-full"
                  />
                </label>
                <label className="block">
                  Retries
                  <input
                    type="number"
                    min={0}
                    max={5}
                    value={providerDraft.retry_policy}
                    onChange={(e) => setProviderDraft({ ...providerDraft, retry_policy: Number(e.target.value) })}
                    className="input-base mt-1 w-full"
                  />
                </label>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.strict_glossary_mode}
                  onChange={(e) => setProviderDraft({ ...providerDraft, strict_glossary_mode: e.target.checked })}
                />
                Strict glossary mode
              </label>
              <label className="flex items-center gap-2">
                <span className="min-w-0 flex-1">
                  <span className="mb-1 block">Knowledge source mode</span>
                  <select
                    value={providerDraft.knowledge_mode}
                    onChange={(e) =>
                      setProviderDraft({
                        ...providerDraft,
                        knowledge_mode: e.target.value as KnowledgeMode,
                      })
                    }
                    className="input-base mt-1 w-full"
                  >
                    <option value="glossary_only">Glossary only</option>
                    <option value="glossary_documents">Glossary + documents</option>
                    <option value="glossary_documents_web">Glossary + documents + websites</option>
                  </select>
                </span>
              </label>
              <p className="text-xs text-slate-500">This mode strictly limits which approved sources can be used during retrieval.</p>
              <label className="block">
                Empty Retrieval Behavior
                <select
                  value={providerDraft.empty_retrieval_mode}
                  onChange={(e) => setProviderDraft({ ...providerDraft, empty_retrieval_mode: e.target.value as EmptyRetrievalMode })}
                  className="input-base mt-1 w-full"
                >
                  <option value="strict_fallback">Strict fallback</option>
                  <option value="model_only_fallback">Model answer without knowledge base</option>
                  <option value="clarifying_fallback">Clarifying question</option>
                </select>
              </label>
              <p className="text-xs text-slate-500">Recommended for production: allow a model-only answer, but label it clearly.</p>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.show_confidence}
                  onChange={(e) => setProviderDraft({ ...providerDraft, show_confidence: e.target.checked })}
                />
                Show confidence level to the user
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.show_source_tags}
                  onChange={(e) => setProviderDraft({ ...providerDraft, show_source_tags: e.target.checked })}
                />
                Show source tags in chat
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={providerDraft.chat_context_enabled}
                  onChange={(e) => setProviderDraft({ ...providerDraft, chat_context_enabled: e.target.checked })}
                />
                Use conversational chat context globally
              </label>
              <p className="text-xs text-slate-500">
                If disabled, chat history is not used for follow-up query rewriting or the final model prompt.
              </p>
              <label className="block">
                Response tone
                <select
                  value={providerDraft.response_tone}
                  onChange={(e) => setProviderDraft({ ...providerDraft, response_tone: e.target.value as ProviderDraft["response_tone"] })}
                  className="input-base mt-1 w-full"
                >
                  <option value="consultative_supportive">Consultative and supportive</option>
                  <option value="neutral_reference">Neutral and reference-focused</option>
                </select>
              </label>
              <button
                onClick={saveProvider}
                disabled={providerSaving}
                className="rounded bg-emerald-600 text-white px-3 py-2 hover:bg-emerald-700 disabled:opacity-70"
              >
                {providerSaving ? "Saving..." : "Save provider settings"}
              </button>
            </div>
          ) : (
            <div className="mt-3 space-y-3 text-sm">
              <label className="block">
                Chat model
                <select
                  value={modelSelectValue(provider.model_name, CHAT_MODEL_OPTIONS)}
                  onChange={(e) =>
                    setProvider({
                      ...provider,
                      model_name: e.target.value === CUSTOM_MODEL_OPTION ? "" : e.target.value,
                    })
                  }
                  className="input-base mt-1 w-full"
                >
                  {CHAT_MODEL_OPTIONS.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                  <option value={CUSTOM_MODEL_OPTION}>Custom</option>
                </select>
                {modelSelectValue(provider.model_name, CHAT_MODEL_OPTIONS) === CUSTOM_MODEL_OPTION && (
                  <input
                    value={provider.model_name}
                    onChange={(e) => setProvider({ ...provider, model_name: e.target.value })}
                    className="input-base mt-2 w-full"
                    placeholder="provider/model-id"
                  />
                )}
              </label>
              <label className="block">
                Embedding model
                <select
                  value={modelSelectValue(provider.embedding_model, EMBEDDING_MODEL_OPTIONS)}
                  onChange={(e) =>
                    setProvider({
                      ...provider,
                      embedding_model: e.target.value === CUSTOM_MODEL_OPTION ? "" : e.target.value,
                    })
                  }
                  className="input-base mt-1 w-full"
                >
                  {EMBEDDING_MODEL_OPTIONS.map((model) => (
                    <option key={model} value={model}>
                      {embeddingModelLabel(model)}
                    </option>
                  ))}
                  <option value={CUSTOM_MODEL_OPTION}>Custom</option>
                </select>
                {modelSelectValue(provider.embedding_model, EMBEDDING_MODEL_OPTIONS) === CUSTOM_MODEL_OPTION && (
                  <input
                    value={provider.embedding_model}
                    onChange={(e) => setProvider({ ...provider, embedding_model: e.target.value })}
                    className="input-base mt-2 w-full"
                    placeholder="provider/embedding-model-id"
                  />
                )}
              </label>
              <p className="text-xs text-slate-500">
                These models apply to all request areas: answer generation, query rewriting, and all embeddings for retrieval/indexing.
              </p>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.strict_glossary_mode}
                  onChange={(e) => setProvider({ ...provider, strict_glossary_mode: e.target.checked })}
                />
                Strict glossary mode
              </label>
              <label className="flex items-center gap-2">
                <span className="min-w-0 flex-1">
                  <span className="mb-1 block">Knowledge source mode</span>
                  <select
                    value={provider.knowledge_mode}
                    onChange={(e) =>
                      setProvider({
                        ...provider,
                        knowledge_mode: e.target.value as KnowledgeMode,
                      })
                    }
                    className="input-base mt-1 w-full"
                  >
                    <option value="glossary_only">Glossary only</option>
                    <option value="glossary_documents">Glossary + documents</option>
                    <option value="glossary_documents_web">Glossary + documents + websites</option>
                  </select>
                </span>
              </label>
              <p className="text-xs text-slate-500">This mode explicitly controls whether approved documents and website snapshots can be used in responses.</p>
              <label className="block">
                Empty Retrieval Behavior
                <select
                  value={provider.empty_retrieval_mode}
                  onChange={(e) => setProvider({ ...provider, empty_retrieval_mode: e.target.value as EmptyRetrievalMode })}
                  className="input-base mt-1 w-full"
                >
                  <option value="strict_fallback">Strict fallback</option>
                  <option value="model_only_fallback">Model answer without knowledge base</option>
                  <option value="clarifying_fallback">Clarifying question</option>
                </select>
              </label>
              <p className="text-xs text-slate-500">Trace records will include `fallback_reason=no_retrieval_context` together with the final `answer_mode`.</p>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.show_confidence}
                  onChange={(e) => setProvider({ ...provider, show_confidence: e.target.checked })}
                />
                Show confidence level to the user
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.show_source_tags}
                  onChange={(e) => setProvider({ ...provider, show_source_tags: e.target.checked })}
                />
                Show source tags in chat
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={provider.chat_context_enabled}
                  onChange={(e) => setProvider({ ...provider, chat_context_enabled: e.target.checked })}
                />
                Use conversational chat context globally
              </label>
              <p className="text-xs text-slate-500">
                If disabled, the backend will not use chat history for query rewriting or conversational prompt context.
              </p>
              <label className="block">
                Response tone
                <select
                  value={provider.response_tone}
                  onChange={(e) => setProvider({ ...provider, response_tone: e.target.value })}
                  className="input-base mt-1 w-full"
                >
                  <option value="consultative_supportive">Consultative and supportive</option>
                  <option value="neutral_reference">Neutral and reference-focused</option>
                </select>
              </label>
              <div className="flex items-center gap-3">
                <button
                  onClick={saveProvider}
                  disabled={providerSaving}
                  className="rounded bg-emerald-600 text-white px-3 py-2 hover:bg-emerald-700 disabled:opacity-70"
                >
                  {providerSaving ? "Saving..." : "Save settings"}
                </button>
                {providerSaveStatus === "success" && (
                  <span className="inline-flex items-center rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 animate-pulse">
                    Saved
                  </span>
                )}
                {providerSaveStatus === "error" && (
                  <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-700 animate-pulse">
                    Save failed
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">User Limits</h2>
          {!provider ? (
            <p className="mt-2 text-sm text-slate-600">Available after the initial provider setup.</p>
          ) : (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-slate-600">This limit applies only to the `user` role. It does not affect admins.</p>
              <label className="block">
                Total user message limit
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={provider.max_user_messages_total}
                  onChange={(e) =>
                    setProvider({ ...provider, max_user_messages_total: Number(e.target.value) || 1 })
                  }
                  className="input-base mt-1 w-full"
                />
              </label>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-medium text-slate-900">Conversational context</div>
                <p className="mt-1 text-xs text-slate-600">
                  These limits apply only when the global chat context toggle is enabled in response settings.
                </p>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="block">
                    User-turn limit in history
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={provider.history_user_turn_limit}
                      onChange={(e) =>
                        setProvider({ ...provider, history_user_turn_limit: Number(e.target.value) || 1 })
                      }
                      className="input-base mt-1 w-full"
                    />
                  </label>
                  <label className="block">
                    History message limit
                    <input
                      type="number"
                      min={1}
                      max={40}
                      value={provider.history_message_limit}
                      onChange={(e) =>
                        setProvider({ ...provider, history_message_limit: Number(e.target.value) || 1 })
                      }
                      className="input-base mt-1 w-full"
                    />
                  </label>
                  <label className="block">
                    Token budget for history
                    <input
                      type="number"
                      min={100}
                      max={8000}
                      step={50}
                      value={provider.history_token_budget}
                      onChange={(e) =>
                        setProvider({ ...provider, history_token_budget: Number(e.target.value) || 100 })
                      }
                      className="input-base mt-1 w-full"
                    />
                  </label>
                  <label className="block">
                    Rewrite message limit
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={provider.rewrite_history_message_limit}
                      onChange={(e) =>
                        setProvider({ ...provider, rewrite_history_message_limit: Number(e.target.value) || 1 })
                      }
                      className="input-base mt-1 w-full"
                    />
                  </label>
                </div>
              </div>
              <button
                onClick={saveLimits}
                disabled={providerSaving}
                className="rounded bg-emerald-600 text-white px-3 py-2 hover:bg-emerald-700 disabled:opacity-70"
              >
                {providerSaving ? "Saving..." : "Save limits"}
              </button>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-red-200 bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold text-red-900">Qdrant Maintenance</h2>
          <p className="mt-1 text-sm text-red-800">
            Danger zone. This operation deletes all Qdrant collections across tenants and recreates the default collections.
          </p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">EMBEDDING_VECTOR_SIZE</span>
              <input
                type="number"
                min={64}
                max={8192}
                value={qdrantVectorSizeDraft}
                onChange={(e) => setQdrantVectorSizeDraft(Math.max(64, Number(e.target.value) || 64))}
                className="input-base"
              />
            </label>
          </div>
          <p className="mt-2 text-xs text-slate-600">
            Keep this value aligned with backend env <code>EMBEDDING_VECTOR_SIZE</code>, otherwise startup can fail with a vector size mismatch.
          </p>
          <p className="mt-1 text-xs text-amber-700">
            After reset, update GitHub Secret <code>EMBEDDING_VECTOR_SIZE</code> to the same value before the next deploy.
          </p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Type confirmation phrase (1/2)</span>
              <input
                value={qdrantConfirmPhrase}
                onChange={(e) => setQdrantConfirmPhrase(e.target.value)}
                className="input-base"
                placeholder={QDRANT_RESET_CONFIRM_PHRASE}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-700">Type confirmation phrase again (2/2)</span>
              <input
                value={qdrantConfirmPhraseRepeat}
                onChange={(e) => setQdrantConfirmPhraseRepeat(e.target.value)}
                className="input-base"
                placeholder={QDRANT_RESET_CONFIRM_PHRASE}
              />
            </label>
          </div>
          <button
            onClick={() => void resetAllQdrantCollections()}
            disabled={
              qdrantResetBusy
              || qdrantConfirmPhrase.trim() !== QDRANT_RESET_CONFIRM_PHRASE
              || qdrantConfirmPhraseRepeat.trim() !== QDRANT_RESET_CONFIRM_PHRASE
            }
            className="btn btn-danger mt-3 disabled:opacity-60"
          >
            {qdrantResetBusy ? "Resetting..." : "Clear all Qdrant collections"}
          </button>
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <h2 className="text-lg font-semibold">Pending Registrations</h2>
          <p className="mt-1 text-sm text-slate-600">Users waiting for manual approval by an administrator.</p>
          <div className="mt-3 space-y-2">
            {pendingRegistrations.length === 0 && (
              <p className="text-sm text-slate-600">No approval requests.</p>
            )}
            {pendingRegistrations.map((user) => (
              <div key={user.id} className="rounded border border-slate-200 px-3 py-2 text-sm">
                <div className="font-medium text-slate-900">{user.email || user.username}</div>
                <div className="mt-1 text-xs text-slate-500">
                  username: {user.username} | created: {user.created_at ? formatDateTime(user.created_at) : "—"}
                </div>
                <div className="mt-2">
                  <button
                    onClick={() => void approveRegistration(user.id)}
                    className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-700"
                  >
                    Approve
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <button
            type="button"
            onClick={() => setRecentTracesOpen((prev) => !prev)}
            className="flex w-full items-center justify-between gap-3 text-left"
            aria-expanded={recentTracesOpen}
          >
            <h2 className="text-lg font-semibold">Recent Traces (last 3)</h2>
            <span className="text-sm text-slate-600">{recentTracesOpen ? "Hide" : "Show"}</span>
          </button>
          {recentTracesOpen && (
            <div className="mt-2 space-y-2 text-sm">
              {traces.length === 0 && <p className="text-slate-600">No data.</p>}
              {traces.map((t) => (
                <div key={t.id} className="rounded border border-slate-200 px-3 py-2">
                  <div>{t.model} | {t.status} | {Math.round(t.latency_ms)} ms</div>
                  <div className="mt-1 text-sm text-slate-700">knowledge mode: {t.knowledge_mode}</div>
                  <div className="mt-1 text-sm text-slate-700">answer mode: {t.answer_mode}</div>
                  <div className="mt-1 text-sm text-slate-700">
                    chat context: {t.chat_context_enabled ? "on" : "off"}
                  </div>
                  <div className="mt-1 text-sm text-slate-700">
                    rewrite used: {t.rewrite_used ? "yes" : "no"} | history messages: {t.history_messages_used}
                  </div>
                  <div className="mt-1 text-sm text-slate-700">
                    history tokens: {t.history_token_estimate} | trimmed: {t.history_trimmed ? "yes" : "no"}
                  </div>
                  {t.rewritten_query && (
                    <div className="mt-1 text-sm text-slate-600 break-words">
                      rewritten query: {t.rewritten_query}
                    </div>
                  )}
                  <div className="text-sm text-slate-600 mt-1">{formatDateTime(t.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[var(--line)] bg-white p-4 md:p-5">
          <button
            type="button"
            onClick={() => setRecentErrorsOpen((prev) => !prev)}
            className="flex w-full items-center justify-between gap-3 text-left"
            aria-expanded={recentErrorsOpen}
          >
            <h2 className="text-lg font-semibold">Recent Errors (last 3)</h2>
            <span className="text-sm text-slate-600">{recentErrorsOpen ? "Hide" : "Show"}</span>
          </button>
          {recentErrorsOpen && (
            <div className="mt-2 space-y-2 text-sm">
              {logs.length === 0 && <p className="text-slate-600">No data.</p>}
              {logs.map((l) => (
                <div key={l.id} className="rounded border border-slate-200 px-3 py-2">
                  <div>{l.type}: {l.message}</div>
                  <div className="text-sm text-slate-600 mt-1">{formatDateTime(l.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {editingGlossary && (
        <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-[var(--line)] bg-white p-5 shadow-lg">
            <h3 className="text-lg font-semibold">Edit glossary entry</h3>
            <div className="mt-3 space-y-2">
              <input value={editTerm} onChange={(e) => setEditTerm(e.target.value)} className="input-base w-full text-sm" placeholder="Term" />
              <textarea
                value={editDefinition}
                onChange={(e) => setEditDefinition(e.target.value)}
                className="input-base w-full min-h-32 text-sm"
                placeholder="Definition"
              />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={closeGlossaryModal} className="btn btn-secondary text-sm">Cancel</button>
              <button onClick={() => void saveGlossaryModal()} className="btn btn-primary text-sm">Save</button>
            </div>
          </div>
        </div>
      )}
      <ConfirmModal
        open={Boolean(confirmState)}
        title={confirmState?.title || ""}
        description={confirmState?.description || ""}
        confirmLabel={confirmState?.confirmLabel || "Confirm"}
        cancelLabel={confirmState?.cancelLabel || "Cancel"}
        tone={confirmState?.tone || "neutral"}
        onCancel={() => closeConfirmDialog(false)}
        onConfirm={() => closeConfirmDialog(true)}
      />
    </div>
  );
}
