"use client";

import Link from "next/link";
import { KeyboardEvent, useEffect, useState } from "react";
import { ApiError, api, getAuthHeaders } from "@/lib/api";
import { backendLogout, clearSession, loadSession, redirectToAuth, showReloginNoticeOnce } from "@/lib/auth";
import { SourceBadges } from "@/components/source-badges";
import { BrandTitle } from "@/components/brand-title";

type Chat = { id: string; title: string; created_at: string; updated_at: string };
type Message = { id: string; role: string; content: string; source_types: string[]; created_at: string };
const DEFAULT_CHAT_TITLE = "Новый чат";
const CHAT_TITLE_PREVIEW_LIMIT = 48;

export function ChatPanel() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState<"admin" | "user" | null>(null);
  const [showSourceTags, setShowSourceTags] = useState(true);

  useEffect(() => {
    const session = loadSession();
    setRole(session?.role || null);
    void loadChats().catch(handleLoadError);
    void refreshRole();
  }, []);

  async function refreshRole() {
    try {
      const session = await api<{ role: "admin" | "user"; show_source_tags?: boolean }>("/auth/session");
      setRole(session.role);
      setShowSourceTags(session.show_source_tags ?? true);
    } catch (err) {
      handleLoadError(err);
    }
  }

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
    const message = err instanceof Error ? err.message : "Ошибка запроса";
    setError(message);
  }

  async function loadChats() {
    const data = await api<Chat[]>("/chats");
    setChats(data);
    if (!chatId && data.length > 0) {
      await openChat(data[0].id);
    }
  }

  async function createChat() {
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
    try {
      const d = await api<{ chat: Chat; messages: Message[] }>(`/chats/${id}`);
      setChatId(id);
      setMessages(d.messages);
    } catch (err) {
      handleLoadError(err);
    }
  }

  async function removeChat(id: string) {
    const target = chats.find((chat) => chat.id === id);
    const title = target?.title || "этот чат";
    const confirmed = window.confirm(`Удалить чат "${title}"? Это действие необратимо.`);
    if (!confirmed) return;

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

  async function send() {
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
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
      content: input,
      source_types: [],
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    const content = input;
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
          source_types: ["glossary", "model"],
          created_at: new Date().toISOString(),
        },
      ]);

      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "/api/v1"}/messages/${activeChatId}/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ content }),
      });
      if (res.status === 401 || res.status === 403) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      if (!res.ok || !res.body) throw new Error("Ошибка потокового ответа");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      while (!done) {
        const chunk = await reader.read();
        done = chunk.done;
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const event of events) {
          const lines = event.split("\n");
          const eventType = lines.find((line) => line.startsWith("event: "))?.slice(7).trim() || "message";
          const data = lines
            .filter((line) => line.startsWith("data: "))
            .map((line) => line.slice(6))
            .join("\n");

          if (!data || data === "[DONE]") continue;

          if (eventType === "error") {
            setMessages((m) => m.filter((msg) => msg.id !== assistantId));
            setError(data);
            continue;
          }

          setMessages((m) =>
            m.map((msg) => (msg.id === assistantId ? { ...msg, content: `${msg.content}${data}` } : msg)),
          );
        }
      }
      await loadChats();
    } catch (e: any) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        clearSession();
        showReloginNoticeOnce();
        redirectToAuth();
        return;
      }
      if (assistantId) {
        setMessages((m) => m.filter((msg) => msg.id !== assistantId));
        setError(e?.message || "Не удалось получить ответ ассистента");
      } else {
        setError(e.message || "Не удалось отправить сообщение");
      }
    } finally {
      setLoading(false);
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key !== "Enter") return;
    if (event.ctrlKey || event.metaKey) return;
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

  function renderAssistantContent(content: string) {
    if (content) {
      return <p className="whitespace-pre-wrap text-sm">{content}</p>;
    }
    return (
      <div className="inline-flex items-center gap-1 py-1" aria-label="EZII печатает">
        <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.3s]" />
        <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.15s]" />
        <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] min-h-screen">
      <aside className="border-r border-[var(--line)] bg-white/80 backdrop-blur">
        <div className="h-full flex flex-col">
          <div className="p-4 border-b border-[var(--line)]">
            <h1 className="text-lg font-semibold">
              <BrandTitle />
            </h1>
          </div>

          {role === "admin" && (
            <div className="p-3 border-b border-[var(--line)]">
              <Link
                href="/admin"
                className="block w-full rounded border border-slate-300 px-3 py-2 text-center text-sm text-slate-700 hover:bg-slate-50"
              >
                Админка
              </Link>
            </div>
          )}

          <div className="p-3 border-b border-[var(--line)]">
            <button
              onClick={createChat}
              className="w-full rounded bg-emerald-600 hover:bg-emerald-700 text-white py-2 text-sm"
            >
              Новый чат
            </button>
          </div>

          <div className="flex-1 overflow-auto p-3 space-y-2">
            {chats.map((c) => (
              <div
                key={c.id}
                onClick={() => openChat(c.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void openChat(c.id);
                  }
                }}
                role="button"
                tabIndex={0}
                className={`group w-full text-left rounded border px-3 py-2 text-sm transition-colors ${
                  chatId === c.id
                    ? "border-emerald-700 bg-emerald-50 text-emerald-900"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate">{c.title}</span>
                  <button
                    type="button"
                    aria-label={`Удалить чат ${c.title}`}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      void removeChat(c.id);
                    }}
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-red-600 opacity-0 translate-x-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-x-0 hover:bg-red-100"
                  >
                    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 6h18" />
                      <path d="M8 6V4h8v2" />
                      <path d="M19 6l-1 14H6L5 6" />
                      <path d="M10 11v6M14 11v6" />
                    </svg>
                  </button>
                </span>
              </div>
            ))}
          </div>

          <div className="p-3 border-t border-[var(--line)]">
            <button
              onClick={() => void logout()}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Выйти
            </button>
          </div>
        </div>
      </aside>

      <div className="flex flex-col">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.map((m) => (
            <div key={m.id} className={`max-w-3xl ${m.role === "user" ? "ml-auto" : "mr-auto"}`}>
              <div className={`rounded-xl px-4 py-3 ${m.role === "user" ? "bg-ink text-white" : "bg-white border border-[var(--line)]"}`}>
                {m.role === "assistant" ? renderAssistantContent(m.content) : <p className="whitespace-pre-wrap text-sm">{m.content}</p>}
                {m.role === "assistant" && showSourceTags && <SourceBadges sources={m.source_types || []} />}
              </div>
            </div>
          ))}
        </div>
        <div className="border-t border-[var(--line)] p-3">
          {error && <p className="text-sm text-red-600 mb-2">{error}</p>}
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder="Спросите ассистента"
              rows={2}
              className="flex-1 border border-slate-300 rounded px-3 py-2 text-sm resize-none"
            />
            <button
              disabled={loading}
              onClick={send}
              className="rounded bg-amber-500 hover:bg-amber-600 text-slate-950 px-4 py-2 text-sm disabled:opacity-70"
            >
              {loading ? "Отправка..." : "Отправить"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
