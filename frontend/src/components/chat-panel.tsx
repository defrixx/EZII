"use client";

import { useEffect, useRef, useState } from "react";
import { api, streamMessage } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
import { knowledgeBaseIcon } from "@/lib/knowledge-base-visual";
import { MarkdownMessage } from "./markdown-message";

type KB = { id: string; name: string };
type Chat = { id: string; title: string; knowledge_base_id: string };
type Msg = {
  id: string;
  role: string;
  content: string;
  source_types?: string[];
  metadata_json?: {
    warning_codes?: string[];
    sources?: { id: string; title: string; source_type: string }[];
    citations?: { chunk_id: string; chunk_index: number; source_id: string; title: string; excerpt: string }[];
  };
};

export function ChatPanel() {
  const { t, locale, errorText } = usePreferences();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [selectedKb, setSelectedKb] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [current, setCurrent] = useState<Chat | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEnd = useRef<HTMLDivElement | null>(null);
  useEffect(
    () =>
      messagesEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" }),
    [msgs, busy],
  );
  useEffect(() => {
    Promise.all([api<KB[]>("/knowledge-bases"), api<Chat[]>("/chats")])
      .then(([bases, rows]) => {
        setKbs(bases);
        setSelectedKb(bases[0]?.id || "");
        setChats(rows);
        if (rows[0]) void open(rows[0]);
        else setLoading(false);
      })
      .catch((e) => {
        setError(errorText(e));
        setLoading(false);
      });
  }, [errorText]);
  async function open(chat: Chat) {
    setCurrent(chat);
    const detail = await api<{ messages: Msg[] }>(`/chats/${chat.id}`);
    setMsgs(detail.messages);
    setLoading(false);
  }
  async function create() {
    if (!selectedKb) return;
    const chat = await api<Chat>("/chats", {
      method: "POST",
      body: JSON.stringify({ title: t.newChat, knowledge_base_id: selectedKb }),
    });
    setChats((rows) => [chat, ...rows]);
    await open(chat);
  }
  async function send() {
    if (!current || !input.trim()) return;
    const content = input;
    setInput("");
    setMsgs((rows) => [
      ...rows,
      { id: crypto.randomUUID(), role: "user", content },
    ]);
    setBusy(true);
    setError("");
    try {
      abortRef.current = new AbortController();
      await streamMessage(
        `/messages/${current.id}/stream`,
        content,
        locale,
        (value) => setMsgs((rows) => [...rows, value as Msg]),
        abortRef.current.signal,
      );
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        setError(errorText(e));
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }
  async function renameChat() {
    if (!current) return;
    const title = window.prompt(t.rename, current.title)?.trim();
    if (!title || title === current.title) return;
    try {
      const updated = await api<Chat>(`/chats/${current.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      setCurrent(updated);
      setChats((rows) =>
        rows.map((chat) => (chat.id === updated.id ? updated : chat)),
      );
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function deleteChat() {
    if (!current || !window.confirm(t.confirmDelete)) return;
    try {
      await api(`/chats/${current.id}`, { method: "DELETE" });
      const remaining = chats.filter((chat) => chat.id !== current.id);
      setChats(remaining);
      setCurrent(null);
      setMsgs([]);
      if (remaining[0]) await open(remaining[0]);
    } catch (error) {
      setError(errorText(error));
    }
  }
  if (loading) return <p role="status">{t.loading}</p>;
  const currentBase = kbs.find(
    (k) => k.id === current?.knowledge_base_id,
  )?.name;
  return (
    <div className="grid">
      <aside className="panel stack">
        <label>
          {t.chooseBase}
          <select
            value={selectedKb}
            onChange={(e) => setSelectedKb(e.target.value)}
            disabled={!kbs.length}
          >
            {kbs.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" onClick={create} disabled={!selectedKb}>
          {t.newChat}
        </button>
        <input
          type="search"
          aria-label={t.search}
          placeholder={t.search}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {!kbs.length && (
          <div className="empty-action">
            <p>{t.createBaseHint}</p>
            <a href="/manage" className="button-link primary">
              ＋ {t.newBase}
            </a>
          </div>
        )}
        {kbs.map((base) => {
          const rows = chats.filter(
            (chat) =>
              chat.knowledge_base_id === base.id &&
              chat.title
                .toLocaleLowerCase()
                .includes(query.toLocaleLowerCase()),
          );
          return rows.length ? (
            <section className="chat-group stack" key={base.id}>
              <button
                className="chat-group-heading"
                aria-expanded={!collapsed.includes(base.id)}
                onClick={() =>
                  setCollapsed((ids) =>
                    ids.includes(base.id)
                      ? ids.filter((id) => id !== base.id)
                      : [...ids, base.id],
                  )
                }
              >
                <span>
                  {knowledgeBaseIcon(base.id, base.name)} {base.name}
                </span>
                <span className="muted">
                  {rows.length} {collapsed.includes(base.id) ? "⌄" : "⌃"}
                </span>
              </button>
              {!collapsed.includes(base.id) &&
                rows.map((chat) => (
                  <button
                    className={current?.id === chat.id ? "selected" : undefined}
                    aria-pressed={current?.id === chat.id}
                    key={chat.id}
                    onClick={() => void open(chat)}
                  >
                    💬 {chat.title}
                  </button>
                ))}
            </section>
          ) : null;
        })}
      </aside>
      <section className="panel stack">
        <div className="row spread chat-title">
          <h1>
            {current?.title || t.chats}
            {currentBase && <small className="muted"> · {currentBase}</small>}
          </h1>
          {current && (
            <div className="row">
              <button onClick={() => void renameChat()}>{t.rename}</button>
              <button className="danger" onClick={() => void deleteChat()}>
                {t.deleteChat}
              </button>
            </div>
          )}
        </div>
        {error && <ErrorToast message={error} onClose={() => setError("")} />}
        <div className="messages stack">
          {msgs.length
            ? msgs.map((message) => (
                <div key={message.id} className={`message ${message.role}`}>
                  {message.role === "assistant" ? <MarkdownMessage content={message.content} copyLabel={t.copy} copiedLabel={t.copied} /> : message.content}
                  {message.metadata_json?.citations?.length ? (
                    <small className="message-sources">
                      {t.sources}:{" "}
                      {message.metadata_json.citations.map((source, index) => (
                        <span key={source.chunk_id}>
                          {index > 0 && ", "}
                          <a href={`/sources?kb=${current?.knowledge_base_id}&source=${source.source_id}&chunk=${source.chunk_id}`} title={source.excerpt}>{source.title} §{source.chunk_index + 1}</a>
                        </span>
                      ))}
                    </small>
                  ) : message.metadata_json?.sources?.length ? <small className="message-sources">{t.sources}: {message.metadata_json.sources.map((source,index)=><span key={source.id}>{index>0&&", "}<a href={`/sources?kb=${current?.knowledge_base_id}&source=${source.id}`}>{source.title}</a></span>)}</small> : null}
                  {message.metadata_json?.warning_codes?.length ? (
                    <small className="warning">{t.vectorUnavailable}</small>
                  ) : null}
                </div>
              ))
            : !busy && <p className="muted">{t.empty}</p>}
          {busy && (
            <div
              className="message assistant typing-message"
              role="status"
              aria-live="polite"
            >
              <span>{t.awaitingAnswer}</span>
              <span className="typing-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </div>
          )}
          <div ref={messagesEnd} />
        </div>
        <div className="row">
          <textarea
            aria-label={t.message}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={2}
            style={{ flex: 1 }}
          />
          {busy ? (
            <button
              className="danger"
              onClick={() => abortRef.current?.abort()}
            >
              {t.stop}
            </button>
          ) : (
            <button
              className="primary"
              disabled={busy || !current}
              onClick={send}
            >
              {t.send}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
