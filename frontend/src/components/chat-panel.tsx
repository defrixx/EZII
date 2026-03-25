"use client";

import Link from "next/link";
import { KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";
import { ApiError, api, getAuthHeaders } from "@/lib/api";
import { backendLogout, clearSession, loadSession, redirectToAuth, refreshAuthSession, saveSession, showReloginNoticeOnce } from "@/lib/auth";
import { SourceBadges } from "@/components/source-badges";
import { BrandTitle } from "@/components/brand-title";
import { useToast } from "@/components/ui/toast-provider";
import { ConfirmModal } from "@/components/ui/confirm-modal";

type Chat = { id: string; title: string; created_at: string; updated_at: string };
type AnswerMode = "grounded" | "strict_fallback" | "model_only" | "clarifying" | "error";
type Message = {
  id: string;
  role: string;
  content: string;
  source_types: string[];
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
    source_types: ["demo"],
    created_at: new Date(0).toISOString(),
  },
];

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const chunks = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return chunks.map((chunk, index) => {
    if (chunk.startsWith("**") && chunk.endsWith("**") && chunk.length > 4) {
      return (
        <strong key={`${keyPrefix}-strong-${index}`} className="font-semibold text-slate-900">
          {chunk.slice(2, -2)}
        </strong>
      );
    }
    if (chunk.startsWith("`") && chunk.endsWith("`") && chunk.length > 2) {
      return (
        <code key={`${keyPrefix}-code-${index}`} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.92em] text-slate-900">
          {chunk.slice(1, -1)}
        </code>
      );
    }
    return <span key={`${keyPrefix}-text-${index}`}>{chunk}</span>;
  });
}

function renderMarkdownContent(content: string): ReactNode[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraphLines: string[] = [];
  let index = 0;

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    const text = paragraphLines.join("\n");
    blocks.push(
      <p key={`p-${index}`} className="whitespace-pre-wrap text-sm leading-6 text-slate-900">
        {renderInlineMarkdown(text, `p-${index}`)}
      </p>,
    );
    paragraphLines = [];
    index += 1;
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      i += 1;
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const headingText = heading[2];
      if (level === 1) {
        blocks.push(
          <h1 key={`h1-${index}`} className="text-lg font-semibold leading-7 text-slate-950">
            {renderInlineMarkdown(headingText, `h1-${index}`)}
          </h1>,
        );
      } else if (level === 2) {
        blocks.push(
          <h2 key={`h2-${index}`} className="text-base font-semibold leading-7 text-slate-950">
            {renderInlineMarkdown(headingText, `h2-${index}`)}
          </h2>,
        );
      } else {
        blocks.push(
          <h3 key={`h3-${index}`} className="text-sm font-semibold leading-6 text-slate-950">
            {renderInlineMarkdown(headingText, `h3-${index}`)}
          </h3>,
        );
      }
      index += 1;
      i += 1;
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length) {
        const listLine = lines[i].trim();
        if (!/^\d+\.\s+/.test(listLine)) break;
        items.push(listLine.replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={`ol-${index}`} className="list-decimal space-y-1 pl-5 text-sm leading-6 text-slate-900">
          {items.map((item, itemIndex) => (
            <li key={`ol-${index}-${itemIndex}`}>{renderInlineMarkdown(item, `ol-${index}-${itemIndex}`)}</li>
          ))}
        </ol>,
      );
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length) {
        const listLine = lines[i].trim();
        if (!/^[-*]\s+/.test(listLine)) break;
        items.push(listLine.replace(/^[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`} className="list-disc space-y-1 pl-5 text-sm leading-6 text-slate-900">
          {items.map((item, itemIndex) => (
            <li key={`ul-${index}-${itemIndex}`}>{renderInlineMarkdown(item, `ul-${index}-${itemIndex}`)}</li>
          ))}
        </ul>,
      );
      index += 1;
      continue;
    }

    paragraphLines.push(line);
    i += 1;
  }

  flushParagraph();
  return blocks;
}

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
        const sessionData = await api<{ user_id: string; tenant_id: string; email: string; role: "admin" | "user"; show_source_tags?: boolean }>(
          "/auth/session",
          { retryOn401: false },
        );
        if (!active) return;
        saveSession(sessionData);
        setIsGuest(false);
        setRole(sessionData.role);
        setShowSourceTags(sessionData.show_source_tags ?? true);
        const data = await api<Chat[]>("/chats");
        if (!active) return;
        setChats(data);
        const initialChatId = data[0]?.id;
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
    setRole(session?.role || null);
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
    const data = await api<Chat[]>("/chats");
    setChats(data);
    if (!chatId && data.length > 0) {
      await openChat(data[0].id);
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

    const nextChats = chats.filter((chat) => chat.id !== id);
    setChats(nextChats);

    if (chatId === id) {
      if (nextChats.length > 0) {
        await openChat(nextChats[0].id);
      } else {
        setChatId(null);
        setMessages([]);
      }
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
          prev.map((chat) =>
            chat.id === activeChatId ? { ...chat, title: nextTitle || DEFAULT_CHAT_TITLE } : chat,
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
            const parsed = JSON.parse(data) as { answer_mode?: AnswerMode };
            if (parsed?.answer_mode) {
              setMessages((m) =>
                m.map((msg) => (msg.id === assistantId ? { ...msg, answer_mode: parsed.answer_mode } : msg)),
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

        setMessages((m) =>
          m.map((msg) => (msg.id === assistantId ? { ...msg, content: `${msg.content}${data}` } : msg)),
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
        setRetryMessage(content);
        setRetryError(message);
        setInput((current) => current || content);
        pushToast({
          tone: "error",
          title: "Response not received",
          description: "The message was returned to the input field. You can try sending it again.",
        });
      } else {
        const message = e instanceof Error && e.message ? e.message : "Failed to send message";
        setRetryMessage(content);
        setRetryError(message);
        setInput((current) => current || content);
        pushToast({ tone: "error", title: "Failed to send message", description: message });
      }
    } finally {
      setLoading(false);
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

  function renderAssistantContent(content: string, isStreaming = false) {
    if (content) {
      return (
        <div className="space-y-2">
          {renderMarkdownContent(content)}
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

  return (
    <div className="safe-x flex min-h-[100dvh] flex-col md:grid md:h-[100dvh] md:grid-cols-[320px_1fr] md:overflow-hidden">
      <aside className="border-r border-[var(--line)] bg-white/80 backdrop-blur md:min-h-0">
        <div className="h-full flex flex-col">
          <div className="p-4 border-b border-[var(--line)]">
            <h1 className="text-lg font-semibold">
              <BrandTitle />
            </h1>
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
            {chats.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-2 rounded border px-2 py-2 text-sm transition-colors ${
                  chatId === c.id
                    ? "border-emerald-700 bg-emerald-50 text-emerald-900"
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
                <button
                  type="button"
                  aria-label={`Delete chat ${c.title}`}
                  disabled={isGuest}
                  onClick={() => {
                    void removeChat(c.id);
                  }}
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded text-red-600 opacity-100 md:opacity-0 md:translate-x-1 transition-all duration-200 md:group-hover:opacity-100 md:group-hover:translate-x-0 focus-visible:opacity-100 focus-visible:translate-x-0 hover:bg-red-100 disabled:cursor-not-allowed"
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 6h18" />
                    <path d="M8 6V4h8v2" />
                    <path d="M19 6l-1 14H6L5 6" />
                    <path d="M10 11v6M14 11v6" />
                  </svg>
                </button>
              </div>
            ))}
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
                    ? renderAssistantContent(m.content, isStreamingAssistant)
                    : <p className="whitespace-pre-wrap text-sm">{m.content}</p>}
                  {m.role === "assistant" && m.answer_mode === "model_only" && (
                    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                      This answer was generated without knowledge-base context.
                    </div>
                  )}
                  {m.role === "assistant" && showSourceTags && <SourceBadges sources={m.source_types || []} />}
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
          {retryMessage && retryError && !isGuest && (
            <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-sm text-amber-950">{retryError}</p>
              <button
                type="button"
                onClick={() => void send(retryMessage, true)}
                disabled={loading}
                className="shrink-0 rounded border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-950 hover:bg-amber-100 disabled:opacity-60"
              >
                Retry
              </button>
            </div>
          )}
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder="Ask the assistant"
              rows={2}
              disabled={isGuest || chatLoading || initializing}
              className="input-base flex-1 resize-none"
            />
            <button
              disabled={loading || isGuest || chatLoading || initializing}
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
