"use client";

import Link from "next/link";
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { ApiError, api, getAuthHeaders } from "@/lib/api";
import { AuthSession, backendLogout, clearSession, loadSession, redirectToAuth, refreshAuthSession, saveSession, showReloginNoticeOnce } from "@/lib/auth";
import { SourceBadges } from "@/components/source-badges";
import { BrandTitle } from "@/components/brand-title";
import { useToast } from "@/components/ui/toast-provider";
import { ConfirmModal } from "@/components/ui/confirm-modal";

type Chat = {
  id: string;
  title: string;
  is_pinned: boolean;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
};
type AnswerMode = "grounded" | "strict_fallback" | "model_only" | "clarifying" | "error";
type Message = {
  id: string;
  role: string;
  content: string;
  trusted_html?: string;
  source_types: string[];
  source_tooltips?: Partial<Record<string, string>>;
  created_at: string;
  trace_id?: string;
  answer_mode?: AnswerMode;
};
const DEFAULT_CHAT_TITLE = "New chat";
const CHAT_TITLE_PREVIEW_LIMIT = 48;
const DEMO_CHAT_ID = "demo-chat";
const DEMO_CHATS: Chat[] = [
  {
    id: DEMO_CHAT_ID,
    title: "Demo chat",
    is_pinned: false,
    is_archived: false,
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  },
];
const DEMO_MESSAGES: Message[] = [
  {
    id: "demo-assistant-1",
    role: "assistant",
    content:
      "Hi! This is a demo of the knowledge assistant. After signing in, you will be able to start real conversations, keep chat history, and use approved knowledge sources.",
    trusted_html:
      "<p>Hi! This is a demo of the knowledge assistant. After signing in, you will be able to start real conversations, keep chat history, and use approved knowledge sources.</p>",
    source_types: ["demo"],
    created_at: new Date(0).toISOString(),
  },
];

export function ChatPanel() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState<"admin" | "user" | null>(null);
  const [showSourceTags, setShowSourceTags] = useState(true);
  const [isGuest, setIsGuest] = useState(false);
  const [showGuestModal, setShowGuestModal] = useState(false);
  const [selectedDemoPrompt, setSelectedDemoPrompt] = useState("");
  const [initializing, setInitializing] = useState(true);
  const [chatLoading, setChatLoading] = useState(false);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [chatPendingDelete, setChatPendingDelete] = useState<Chat | null>(null);
  const { pushToast } = useToast();
  const messagesViewportRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const [showArchivedChats, setShowArchivedChats] = useState(false);
  const [messageLimitTotal, setMessageLimitTotal] = useState<number | null>(null);
  const [messageLimitRemaining, setMessageLimitRemaining] = useState<number | null>(null);
  const [messageLimitResetAt, setMessageLimitResetAt] = useState<string | null>(null);

  function applySessionState(session: AuthSession) {
    setRole(session.role);
    setShowSourceTags(session.show_source_tags ?? true);
    if (session.role === "admin") {
      setMessageLimitTotal(null);
      setMessageLimitRemaining(null);
      setMessageLimitResetAt(null);
      return;
    }
    setMessageLimitTotal(typeof session.message_limit_total === "number" ? session.message_limit_total : 5);
    setMessageLimitRemaining(
      typeof session.message_limit_remaining_today === "number" ? session.message_limit_remaining_today : null,
    );
    setMessageLimitResetAt(session.message_limit_resets_at ?? null);
  }

  function formatLimitReset(value: string | null): string {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    const yyyy = parsed.getUTCFullYear();
    const mm = String(parsed.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(parsed.getUTCDate()).padStart(2, "0");
    const hh = String(parsed.getUTCHours()).padStart(2, "0");
    const min = String(parsed.getUTCMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
  }

  async function refreshSessionState() {
    const sessionData = await api<AuthSession>("/auth/session", { retryOn401: false });
    saveSession(sessionData);
    applySessionState(sessionData);
  }

  function isNearBottom(container: HTMLDivElement): boolean {
    const thresholdPx = 96;
    const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
    return remaining <= thresholdPx;
  }

  function scrollMessagesToBottom(behavior: ScrollBehavior = "auto") {
    const container = messagesViewportRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  }

  function openGuestLoginModal(prompt?: string) {
    setSelectedDemoPrompt(prompt || "");
    setShowGuestModal(true);
  }

  function sortChatsByPriority(items: Chat[]): Chat[] {
    return [...items].sort((a, b) => {
      if (a.is_pinned !== b.is_pinned) {
        return Number(b.is_pinned) - Number(a.is_pinned);
      }
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    });
  }

  useEffect(() => {
    let active = true;

    function showGuestDemo() {
      if (!active) return;
      setIsGuest(true);
      setRole(null);
      setChats(DEMO_CHATS);
      setChatId(DEMO_CHAT_ID);
      setMessages(DEMO_MESSAGES);
      setShowSourceTags(true);
      setInitializing(false);
    }

    async function loadAuthenticatedUi() {
      try {
        const sessionData = await api<AuthSession>("/auth/session", { retryOn401: false });
        if (!active) return;
        saveSession(sessionData);
        setIsGuest(false);
        applySessionState(sessionData);
        const data = await api<Chat[]>("/chats?include_archived=true");
        if (!active) return;
        setChats(sortChatsByPriority(data));
        const initialChatId = data.find((chat) => !chat.is_archived)?.id ?? data[0]?.id;
        if (initialChatId) {
          setChatLoading(true);
          const detail = await api<{ chat: Chat; messages: Message[] }>(`/chats/${initialChatId}`);
          if (!active) return;
          setChatId(initialChatId);
          setMessages(detail.messages);
        } else {
          setChatId(null);
          setMessages([]);
        }
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearSession();
          showGuestDemo();
          return;
        }
        const message = err instanceof Error ? err.message : "Request failed";
        if (!active) return;
        pushToast({ tone: "error", title: "Failed to load chat", description: message });
      } finally {
        if (!active) return;
        setInitializing(false);
        setChatLoading(false);
      }
    }

    const session = loadSession();
    if (session) {
      applySessionState(session);
    } else {
      setRole(null);
    }
    void loadAuthenticatedUi();

    return () => {
      active = false;
    };
  }, [pushToast]);

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;
    scrollMessagesToBottom("auto");
  }, [messages, loading]);

  function handleAuthError(err: unknown): boolean {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      clearSession();
      showReloginNoticeOnce();
      redirectToAuth();
      return true;
    }
    return false;
  }

  function handleLoadError(err: unknown) {
    if (handleAuthError(err)) return;
    const message = err instanceof Error ? err.message : "Request failed";
    pushToast({ tone: "error", title: "Request failed", description: message });
  }

  async function loadChats() {
    if (isGuest) return;
    const data = await api<Chat[]>("/chats?include_archived=true");
    setChats(sortChatsByPriority(data));
    if (!chatId && data.length > 0) {
      const initialChatId = data.find((chat) => !chat.is_archived)?.id ?? data[0]?.id;
      if (initialChatId) {
        await openChat(initialChatId);
      }
    }
  }

  async function createChat() {
    if (isGuest) {
      redirectToAuth();
      return null;
    }
    try {
      const c = await api<Chat>("/chats", {
        method: "POST",
        body: JSON.stringify({ title: DEFAULT_CHAT_TITLE }),
      });
      await loadChats();
      await openChat(c.id);
      return c.id;
    } catch (err) {
      handleLoadError(err);
      return null;
    }
  }

  async function openChat(id: string) {
    if (isGuest) return;
    try {
      setChatLoading(true);
      const d = await api<{ chat: Chat; messages: Message[] }>(`/chats/${id}`);
      setChatId(id);
      setMessages(d.messages);
      setChats((prev) =>
        sortChatsByPriority(
          prev.map((chat) => (chat.id === id ? { ...chat, ...d.chat } : chat)),
        ),
      );
      shouldAutoScrollRef.current = true;
    } catch (err) {
      handleLoadError(err);
    } finally {
      setChatLoading(false);
    }
  }

  async function removeChat(id: string) {
    if (isGuest) return;
    const target = chats.find((chat) => chat.id === id);
    if (!target) return;
    setChatPendingDelete(target);
  }

  async function confirmRemoveChat() {
    if (!chatPendingDelete) return;
    const id = chatPendingDelete.id;
    setChatPendingDelete(null);

    try {
      await api<void>(`/chats/${id}`, { method: "DELETE" });
    } catch (err) {
      handleLoadError(err);
      return;
    }

    const nextChats = sortChatsByPriority(chats.filter((chat) => chat.id !== id));
    setChats(nextChats);

    if (chatId === id) {
      const nextOpenChatId = nextChats.find((chat) => !chat.is_archived)?.id ?? nextChats[0]?.id;
      if (nextOpenChatId) {
        await openChat(nextOpenChatId);
      } else {
        setChatId(null);
        setMessages([]);
      }
    }
  }

  async function updateChatFlags(id: string, payload: { is_pinned?: boolean; is_archived?: boolean }) {
    if (isGuest) return;
    try {
      const updated = await api<Chat>(`/chats/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setChats((prev) =>
        sortChatsByPriority(
          prev.map((chat) => (chat.id === id ? { ...chat, ...updated } : chat)),
        ),
      );
    } catch (err) {
      handleLoadError(err);
    }
  }

  async function send(contentOverride?: string, isRetry = false) {
    if (isGuest) {
      pushToast({ tone: "info", title: "Sign-in required", description: "Sign in to send messages." });
      openGuestLoginModal(input.trim() || undefined);
      return;
    }
    const nextContent = (contentOverride ?? input).trim();
    if (!nextContent) return;
    setLoading(true);
    setRetryMessage(null);
    setRetryError(null);
    let activeChatId = chatId;
    if (!activeChatId) {
      activeChatId = await createChat();
      if (!activeChatId) {
        setLoading(false);
        return;
      }
    }
    const selectedChat = chats.find((chat) => chat.id === activeChatId);
    if (selectedChat?.is_archived) {
      setLoading(false);
      pushToast({ tone: "error", title: "Chat archived", description: "Unarchive this chat before sending new messages." });
      return;
    }

    let assistantId = "";
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: nextContent,
      source_types: [],
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    const content = nextContent;
    setInput("");
    try {
      const currentChat = chats.find((c) => c.id === activeChatId);
      const isUntitled = !currentChat || currentChat.title === DEFAULT_CHAT_TITLE;
      if (isUntitled) {
        const nextTitle = content.trim().slice(0, CHAT_TITLE_PREVIEW_LIMIT);
        await api<Chat>(`/chats/${activeChatId}`, {
          method: "PATCH",
          body: JSON.stringify({ title: nextTitle || DEFAULT_CHAT_TITLE }),
        });
        setChats((prev) =>
          sortChatsByPriority(
            prev.map((chat) =>
              chat.id === activeChatId ? { ...chat, title: nextTitle || DEFAULT_CHAT_TITLE } : chat,
            ),
          ),
        );
      }

      assistantId = crypto.randomUUID();
      setMessages((m) => [
        ...m,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          source_types: [],
          answer_mode: "grounded",
          created_at: new Date().toISOString(),
        },
      ]);

      const makeStreamRequest = () =>
        fetch(`${process.env.NEXT_PUBLIC_API_BASE || "/api/v1"}/messages/${activeChatId}/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            ...getAuthHeaders(),
          },
          cache: "no-store",
          credentials: "include",
          body: JSON.stringify({ content, is_retry: isRetry }),
        });
      let res = await makeStreamRequest();
      if (res.status === 401) {
        const refreshed = await refreshAuthSession();
        if (refreshed) {
          res = await makeStreamRequest();
        }
      }
      if (res.status === 401) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      if (res.status === 403) {
        const body = await res.text();
        let detail = "Access denied";
        try {
          const parsed = JSON.parse(body) as { detail?: string };
          detail = parsed.detail || detail;
        } catch {
          if (body) {
            detail = body;
          }
        }
        throw new Error(detail);
      }
      if (!res.ok || !res.body) throw new Error("Streaming response failed");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      let streamFinished = false;
      const processEvent = (event: string) => {
        const lines = event.split("\n");
        const eventType = lines.find((line) => line.startsWith("event: "))?.slice(7).trim() || "message";
        const data = lines
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");

        if (data === "[DONE]") {
          streamFinished = true;
          return;
        }

        if (eventType === "error") {
          if (!data) {
            throw new Error("Streaming response failed");
          }
          throw new Error(data);
        }
        if (eventType === "sources") {
          if (!data) return;
          try {
            const parsed = JSON.parse(data) as string[];
            setMessages((m) =>
              m.map((msg) => (msg.id === assistantId ? { ...msg, source_types: Array.isArray(parsed) ? parsed : [] } : msg)),
            );
          } catch {
            // ignore malformed source metadata
          }
          return;
        }
        if (eventType === "retrieval") {
          if (!data) return;
          try {
            const parsed = JSON.parse(data) as { answer_mode?: AnswerMode; document_titles?: string[] };
            const docTitles = Array.isArray(parsed?.document_titles)
              ? parsed.document_titles
                  .map((title) => String(title || "").trim())
                  .filter((title) => Boolean(title))
              : [];
            if (parsed?.answer_mode || docTitles.length > 0) {
              setMessages((m) =>
                m.map((msg) => {
                  if (msg.id !== assistantId) return msg;
                  const nextTooltips = { ...(msg.source_tooltips || {}) };
                  if (docTitles.length > 0) {
                    nextTooltips.upload = `Source: ${docTitles.join(", ")}`;
                  }
                  return {
                    ...msg,
                    answer_mode: parsed.answer_mode || msg.answer_mode,
                    source_tooltips: nextTooltips,
                  };
                }),
              );
            }
          } catch {
            // ignore malformed retrieval metadata
          }
          return;
        }
        if (eventType === "trace") {
          if (!data) return;
          setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, trace_id: data } : msg)));
          return;
        }
        if (eventType === "trusted_html") {
          if (!data) return;
          setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, trusted_html: data } : msg)));
          return;
        }

        setMessages((m) =>
          m.map((msg) => (msg.id === assistantId ? { ...msg, content: `${msg.content}${data}`, trusted_html: undefined } : msg)),
        );
      };
      while (!done) {
        const chunk = await reader.read();
        done = chunk.done;
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !done });
        const normalizedBuffer = buffer.replace(/\r\n/g, "\n");
        const events = normalizedBuffer.split("\n\n");
        buffer = events.pop() || "";
        for (const event of events) {
          processEvent(event);
          if (streamFinished) {
            done = true;
            break;
          }
        }
      }
      const finalEvent = buffer.replace(/\r\n/g, "\n").trim();
      if (finalEvent) {
        processEvent(finalEvent);
      }
      if (streamFinished) {
        await reader.cancel();
      }
      await loadChats();
    } catch (e: unknown) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      if (assistantId) {
        setMessages((m) => m.filter((msg) => msg.id !== assistantId));
        const message = e instanceof Error && e.message ? e.message : "Failed to receive assistant response";
        const isMessageLimitError = message.toLowerCase().includes("message limit reached");
        setRetryMessage(isMessageLimitError ? null : content);
        setRetryError(message);
        if (!isMessageLimitError) {
          setInput((current) => current || content);
        }
        if (isMessageLimitError) {
          pushToast({
            tone: "error",
            title: "Daily message limit reached",
            description: message,
          });
        } else {
          pushToast({
            tone: "error",
            title: "Response not received",
            description: "The message was returned to the input field. You can try sending it again.",
          });
        }
      } else {
        const message = e instanceof Error && e.message ? e.message : "Failed to send message";
        const isMessageLimitError = message.toLowerCase().includes("message limit reached");
        setRetryMessage(isMessageLimitError ? null : content);
        setRetryError(message);
        if (!isMessageLimitError) {
          setInput((current) => current || content);
        }
        pushToast({
          tone: "error",
          title: isMessageLimitError ? "Daily message limit reached" : "Failed to send message",
          description: message,
        });
      }
    } finally {
      setLoading(false);
      if (!isGuest) {
        try {
          await refreshSessionState();
        } catch {
          // Ignore limit refresh issues; normal error handling remains in place for send.
        }
      }
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key !== "Enter") return;
    if (event.shiftKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    if (!loading) {
      void send();
    }
  }

  async function logout() {
    try {
      await backendLogout();
    } catch {
      // Local session is still cleared to avoid lock-in on transient IdP failures.
    }
    clearSession();
    window.location.href = "/logout";
  }

  function renderAssistantContent(content: string, trustedHtml?: string, isStreaming = false) {
    if (trustedHtml && !isStreaming) {
      return (
        <div className="space-y-2">
          <div className="trusted-markdown text-sm leading-6 text-slate-900" dangerouslySetInnerHTML={{ __html: trustedHtml }} />
        </div>
      );
    }
    if (content) {
      return (
        <div className="space-y-2">
          <p className="whitespace-pre-wrap text-sm leading-6 text-slate-900">{content}</p>
          {isStreaming && <span className="ml-1 inline-block h-4 w-0.5 animate-pulse rounded bg-emerald-500 align-[-2px]" aria-hidden="true" />}
        </div>
      );
    }
    return (
      <div className="space-y-3 py-1" aria-label="Assistant is typing">
        <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-900">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-bounce [animation-delay:-0.3s]" />
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-bounce [animation-delay:-0.15s]" />
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-bounce" />
          </span>
          Assistant is thinking...
        </div>
        <div className="space-y-2">
          <div className="h-3 w-5/6 animate-pulse rounded-full bg-slate-200" />
          <div className="h-3 w-2/3 animate-pulse rounded-full bg-slate-200 [animation-delay:120ms]" />
        </div>
      </div>
    );
  }

  function renderMessageSkeleton() {
    return (
      <div className="max-w-3xl space-y-3">
        <div className="h-16 animate-pulse rounded-2xl border border-slate-200 bg-white/70" />
        <div className="ml-auto h-12 w-2/3 animate-pulse rounded-2xl bg-slate-200/80" />
        <div className="h-24 animate-pulse rounded-2xl border border-slate-200 bg-white/70" />
      </div>
    );
  }

  const activeChat = chats.find((chat) => chat.id === chatId);
  const isActiveChatArchived = Boolean(activeChat?.is_archived);
  const pinnedChats = chats.filter((chat) => chat.is_pinned && !chat.is_archived);
  const regularChats = chats.filter((chat) => !chat.is_pinned && !chat.is_archived);
  const archivedChats = chats.filter((chat) => chat.is_archived);

  function renderChatRow(c: Chat) {
    const isArchived = c.is_archived;
    return (
      <div
        key={c.id}
        className={`group flex items-center gap-1 rounded border px-2 py-2 text-sm transition-colors ${
          chatId === c.id
            ? "border-emerald-700 bg-emerald-50 text-emerald-900"
            : isArchived
              ? "border-slate-200 bg-slate-50/80 text-slate-600 hover:bg-slate-100"
              : "border-slate-200 hover:bg-slate-50"
        }`}
      >
        <button
          type="button"
          disabled={isGuest}
          onClick={() => {
            if (!isGuest) void openChat(c.id);
          }}
          className="min-w-0 flex-1 rounded px-1 py-1 text-left disabled:cursor-not-allowed"
        >
          <span className="block truncate">{c.title}</span>
        </button>
        {!isArchived && (
          <button
            type="button"
            aria-label={c.is_pinned ? `Unpin chat ${c.title}` : `Pin chat ${c.title}`}
            disabled={isGuest}
            onClick={() => {
              void updateChatFlags(c.id, { is_pinned: !c.is_pinned });
            }}
            className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded transition-colors ${
              c.is_pinned ? "text-amber-600 hover:bg-amber-100" : "text-slate-500 hover:bg-slate-200"
            } disabled:cursor-not-allowed`}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true">
              <path d="M14 2h-4v2H8v6l3 3v7l1-1 1 1v-7l3-3V4h-2V2z" />
            </svg>
          </button>
        )}
        <button
          type="button"
          aria-label={isArchived ? `Unarchive chat ${c.title}` : `Archive chat ${c.title}`}
          disabled={isGuest}
          onClick={() => {
            void updateChatFlags(c.id, { is_archived: !isArchived });
          }}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <rect x="3.5" y="4.5" width="17" height="4.5" rx="1.2" />
            <path d="M5 9v9.5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9" />
            <path d="M10 13h4" />
          </svg>
        </button>
        <button
          type="button"
          aria-label={`Delete chat ${c.title}`}
          disabled={isGuest}
          onClick={() => {
            void removeChat(c.id);
          }}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded text-red-600 transition-colors hover:bg-red-100 disabled:cursor-not-allowed"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18" />
            <path d="M8 6V4h8v2" />
            <path d="M19 6l-1 14H6L5 6" />
            <path d="M10 11v6M14 11v6" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="safe-x safe-top flex min-h-[100dvh] flex-col md:grid md:h-[100dvh] md:grid-cols-[320px_1fr] md:overflow-hidden">
      <aside className="border-r border-[var(--line)] bg-white/80 backdrop-blur md:min-h-0">
        <div className="h-full flex flex-col">
          <div className="p-4 border-b border-[var(--line)]">
            <div className="flex items-center justify-between gap-2">
              <h1 className="text-lg font-semibold">
                <BrandTitle />
              </h1>
              {!isGuest && (
                <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700" aria-label="Daily message limit counter">
                  {role === "admin"
                    ? "∞"
                    : `${Math.max(0, messageLimitRemaining ?? 0)}/${Math.max(1, messageLimitTotal ?? 5)}`}
                </span>
              )}
            </div>
          </div>

          {role === "admin" && !isGuest && (
            <div className="p-3 border-b border-[var(--line)]">
              <Link
                href="/admin"
                className="btn btn-secondary block w-full text-center"
              >
                Admin
              </Link>
            </div>
          )}

          <div className="p-3 border-b border-[var(--line)]">
            <button
              onClick={createChat}
              disabled={isGuest}
              className="btn btn-primary w-full"
            >
              New chat
            </button>
          </div>

          <div className="flex-1 overflow-auto p-3 space-y-2">
            {!isGuest && chats.length === 0 && !initializing && (
              <div className="rounded border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-sm text-slate-600">
                No chats yet. Create your first chat to begin.
              </div>
            )}
            {pinnedChats.length > 0 && (
              <div className="space-y-2">
                <p className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Pinned</p>
                {pinnedChats.map((chat) => renderChatRow(chat))}
              </div>
            )}
            {regularChats.length > 0 && (
              <div className="space-y-2">
                <p className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Chats</p>
                {regularChats.map((chat) => renderChatRow(chat))}
              </div>
            )}
            {archivedChats.length > 0 && (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setShowArchivedChats((value) => !value)}
                  className="flex w-full items-center justify-between rounded px-1 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-100"
                >
                  <span>Archived ({archivedChats.length})</span>
                  <svg
                    viewBox="0 0 20 20"
                    className={`h-4 w-4 transition-transform ${showArchivedChats ? "rotate-180" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    aria-hidden="true"
                  >
                    <path d="M5 8l5 5 5-5" />
                  </svg>
                </button>
                {showArchivedChats && archivedChats.map((chat) => renderChatRow(chat))}
              </div>
            )}
          </div>

          <div className="p-3 border-t border-[var(--line)]">
            {isGuest ? (
              <button
                onClick={redirectToAuth}
                className="btn btn-primary w-full"
              >
                Sign In
              </button>
            ) : (
              <button
                onClick={() => void logout()}
                className="btn btn-secondary w-full"
              >
                Sign Out
              </button>
            )}
          </div>
        </div>
      </aside>

      <div className="min-h-0 flex flex-1 flex-col">
        <div
          ref={messagesViewportRef}
          onScroll={() => {
            const container = messagesViewportRef.current;
            if (!container) return;
            shouldAutoScrollRef.current = isNearBottom(container);
          }}
          className="min-h-0 flex-1 overflow-y-auto p-4 space-y-4"
        >
          {isGuest && (
            <>
              <section className="max-w-3xl rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-slate-50 p-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">What You Unlock After Sign In</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">A production knowledge assistant with your own data</h2>
                <ul className="mt-3 space-y-1 text-sm text-slate-700">
                  <li>Grounded context from glossaries, documents, and approved sources.</li>
                  <li>Saved conversations and real-time streaming responses.</li>
                  <li>Support for internal terms, policies, and working documents.</li>
                </ul>
              </section>
            </>
          )}
          {!isGuest && (initializing || chatLoading) ? renderMessageSkeleton() : messages.map((m, index) => {
            const isStreamingAssistant = loading && m.role === "assistant" && index === messages.length - 1;
            return (
              <div key={m.id} className={`max-w-3xl ${m.role === "user" ? "ml-auto" : "mr-auto"}`}>
                <div className={`rounded-xl px-4 py-3 ${m.role === "user" ? "bg-ink text-white" : "bg-white border border-[var(--line)]"}`}>
                  {m.role === "assistant"
                    ? renderAssistantContent(m.content, m.trusted_html, isStreamingAssistant)
                    : <p className="whitespace-pre-wrap text-sm">{m.content}</p>}
                  {m.role === "assistant" && m.answer_mode === "model_only" && (
                    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                      This answer was generated without knowledge-base context.
                    </div>
                  )}
                  {m.role === "assistant" && showSourceTags && <SourceBadges sources={m.source_types || []} tooltips={m.source_tooltips} />}
                </div>
              </div>
            );
          })}
        </div>
        <div className="safe-bottom border-t border-[var(--line)] p-3">
          {isGuest && (
            <p className="mb-2 text-sm text-slate-600">
              Demo mode is read-only. Sign in to start a real conversation.
            </p>
          )}
          {retryError && !isGuest && (
            <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-sm text-amber-950">
                {retryError.toLowerCase().includes("message limit reached")
                  ? (() => {
                    const resetAtLabel = formatLimitReset(messageLimitResetAt);
                    return resetAtLabel
                      ? `Message limit reached (${Math.max(1, messageLimitTotal ?? 5)}). Limit will reset on ${resetAtLabel}.`
                      : `Message limit reached (${Math.max(1, messageLimitTotal ?? 5)}).`;
                  })()
                  : retryError}
              </p>
              {retryMessage && (
                <button
                  type="button"
                  onClick={() => void send(retryMessage, true)}
                  disabled={loading}
                  className="shrink-0 rounded border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-950 hover:bg-amber-100 disabled:opacity-60"
                >
                  Retry
                </button>
              )}
            </div>
          )}
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder={isActiveChatArchived ? "Unarchive this chat to continue" : "Ask the assistant"}
              rows={2}
              disabled={isGuest || chatLoading || initializing || isActiveChatArchived}
              className="input-base flex-1 resize-none"
            />
            <button
              disabled={loading || isGuest || chatLoading || initializing || isActiveChatArchived}
              onClick={() => void send()}
              className="btn btn-primary"
            >
              {loading ? "Sending..." : "Send"}
            </button>
          </div>
        </div>
      </div>
      {showGuestModal && (
        <div className="modal-overlay">
          <div className="modal-panel">
            <h3 className="text-base font-semibold text-slate-900">Sign in to send a message</h3>
            <p className="mt-2 text-sm text-slate-700">
              {selectedDemoPrompt
                ? `Example prompt: "${selectedDemoPrompt}"`
                : "Keycloak authentication is required before you can send requests."}
            </p>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowGuestModal(false)}
                className="btn btn-secondary"
              >
                Later
              </button>
              <button
                type="button"
                onClick={redirectToAuth}
                className="btn btn-primary"
              >
                Sign In
              </button>
            </div>
          </div>
        </div>
      )}
      <ConfirmModal
        open={Boolean(chatPendingDelete)}
        title="Delete chat"
        description={`Delete chat "${chatPendingDelete?.title || "this chat"}"? This action cannot be undone.`}
        confirmLabel="Delete"
        tone="danger"
        onCancel={() => setChatPendingDelete(null)}
        onConfirm={() => void confirmRemoveChat()}
      />
    </div>
  );
}
