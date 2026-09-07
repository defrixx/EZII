"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
import { knowledgeBaseIcon } from "@/lib/knowledge-base-visual";

type KB = { id: string; name: string };
type Glossary = { id: string; name: string };
type Term = { id: string; term: string; definition: string };

function BaseGlossaries({ base }: { base: KB }) {
  const { t, errorText } = usePreferences();
  const [sets, setSets] = useState<Glossary[]>([]);
  const [active, setActive] = useState("");
  const [terms, setTerms] = useState<Term[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const loadSets = useCallback(async () => {
    const rows = await api<Glossary[]>(
      `/knowledge-bases/${base.id}/glossaries`,
    );
    setSets(rows);
    setActive((value) =>
      rows.some((row) => row.id === value) ? value : rows[0]?.id || "",
    );
    if (!rows.length) setTerms([]);
    setLoading(false);
  }, [base.id]);
  useEffect(() => {
    const timer = setTimeout(
      () =>
        void loadSets().catch((error) => {
          setError(errorText(error));
          setLoading(false);
        }),
      0,
    );
    return () => clearTimeout(timer);
  }, [loadSets, errorText]);
  useEffect(() => {
    if (!active) return;
    api<Term[]>(`/knowledge-bases/${base.id}/glossaries/${active}/terms`)
      .then(setTerms)
      .catch((error) => setError(errorText(error)));
  }, [active, base.id, errorText]);
  async function addSet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api(`/knowledge-bases/${base.id}/glossaries`, {
        method: "POST",
        body: JSON.stringify({ name: new FormData(form).get("name") }),
      });
      form.reset();
      await loadSets();
      setNotice(t.saved);
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function addTerm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await api(`/knowledge-bases/${base.id}/glossaries/${active}/terms`, {
        method: "POST",
        body: JSON.stringify({
          term: data.get("term"),
          definition: data.get("definition"),
          synonyms: [],
        }),
      });
      setTerms(
        await api(`/knowledge-bases/${base.id}/glossaries/${active}/terms`),
      );
      form.reset();
      setNotice(t.saved);
    } catch (error) {
      setError(errorText(error));
    }
  }
  async function removeTerm(id: string) {
    if (!window.confirm(t.confirmDelete)) return;
    try {
      await api(
        `/knowledge-bases/${base.id}/glossaries/${active}/terms/${id}`,
        { method: "DELETE" },
      );
      setTerms((rows) => rows.filter((row) => row.id !== id));
      setNotice(t.saved);
    } catch (error) {
      setError(errorText(error));
    }
  }
  return (
    <section className="panel stack glossary-base">
      <h2>
        {knowledgeBaseIcon(base.id, base.name)} {base.name}
      </h2>
      {loading && <p role="status">{t.loading}</p>}
      {error && <ErrorToast message={error} onClose={() => setError("")} />}
      {notice && (
        <ErrorToast
          kind="success"
          message={notice}
          onClose={() => setNotice("")}
        />
      )}
      <form className="row wrap" onSubmit={addSet}>
        <input name="name" aria-label={t.name} placeholder={t.name} required />
        <button className="primary">＋ {t.glossaries}</button>
      </form>
      {sets.length ? (
        <>
          <label>
            {t.glossaries}
            <select
              value={active}
              onChange={(event) => setActive(event.target.value)}
            >
              {sets.map((set) => (
                <option key={set.id} value={set.id}>
                  {set.name}
                </option>
              ))}
            </select>
          </label>
          <form className="row wrap" onSubmit={addTerm}>
            <input
              name="term"
              aria-label={t.term}
              placeholder={t.term}
              required
            />
            <input
              name="definition"
              aria-label={t.definition}
              placeholder={t.definition}
              required
            />
            <button className="primary">{t.save}</button>
          </form>
          {terms.length ? (
            terms.map((term) => (
              <article className="row spread term" key={term.id}>
                <span>
                  <strong>{term.term}</strong> — {term.definition}
                </span>
                <button
                  className="danger"
                  onClick={() => void removeTerm(term.id)}
                >
                  {t.remove}
                </button>
              </article>
            ))
          ) : (
            <p className="muted">{t.empty}</p>
          )}
        </>
      ) : (
        !loading && <p className="muted">{t.empty}</p>
      )}
    </section>
  );
}

export function GlossariesPanel() {
  const { t, errorText } = usePreferences();
  const [bases, setBases] = useState<KB[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api<KB[]>("/knowledge-bases")
      .then((rows) => {
        setBases(rows);
        setLoading(false);
      })
      .catch((error) => {
        setError(errorText(error));
        setLoading(false);
      });
  }, [errorText]);
  if (loading) return <p role="status">{t.loading}</p>;
  return (
    <div className="stack">
      <h1>📚 {t.glossaries}</h1>
      {error && <ErrorToast message={error} onClose={() => setError("")} />}
      {bases.length ? (
        <div className="base-sections">
          {bases.map((base) => (
            <BaseGlossaries base={base} key={base.id} />
          ))}
        </div>
      ) : (
        <section className="panel">
          <div className="empty-action">
            <p>{t.createBaseHint}</p>
            <a href="/manage" className="button-link primary">
              ＋ {t.newBase}
            </a>
          </div>
        </section>
      )}
    </div>
  );
}
