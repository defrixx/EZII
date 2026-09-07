"use client";
import { createContext, useContext, useEffect, useState } from "react";
export type Locale = "ru" | "en";
export type Theme = "light" | "dark" | "system";
export const ru = {
  available: "Доступна",
  unavailable: "Недоступна",
  ready: "Готов к публикации",
  approved: "Опубликован",
  processing: "Обработка",
  archived: "В архиве",
  failed: "Ошибка",
  uploadSource: "Файл",
  websiteSource: "Сайт",
  playbookSource: "GitHub playbook",
  grounded: "По источникам",
  modelOnly: "Только модель",
  degraded: "Ограниченный режим",
  ok: "Успешно",
  chats: "Чаты",
  sources: "Источники",
  glossaries: "Глоссарии",
  diagnostics: "Диагностика",
  maintenance: "Обслуживание",
  bases: "Базы знаний",
  connections: "Подключения",
  models: "Модели",
  newChat: "Новый чат",
  newBase: "Новая база",
  send: "Отправить",
  settings: "Управление",
  empty: "Пока ничего нет",
  chooseBase: "Выберите базу знаний",
  name: "Название",
  description: "Описание",
  save: "Сохранить",
  saved: "Сохранено",
  theme: "Тема",
  language: "Язык",
  manual: "Ручное подтверждение",
  automatic: "Автоматическая публикация",
  chatModel: "Модель чата",
  embeddingModel: "Модель эмбеддингов",
  syncPlaybook: "Синхронизировать рабочие плейбуки",
  apiKey: "API-ключ",
  modelId: "ID модели",
  vectorSize: "Размерность вектора",
  upload: "Загрузить",
  addWebsite: "Добавить сайт",
  approve: "Опубликовать",
  createConnectionFirst: "Сначала создайте подключение",
  system: "Системная",
  light: "Светлая",
  dark: "Тёмная",
  reindex: "Переиндексировать",
  test: "Проверить",
  term: "Термин",
  definition: "Определение",
  message: "Сообщение",
  loading: "Загрузка…",
  retry: "Повторить",
  remove: "Удалить",
  archive: "Архивировать",
  disable: "Отключить",
  enable: "Включить",
  timeout: "Таймаут, сек.",
  retries: "Повторы",
  clearKey: "Удалить сохранённый ключ",
  confirmDelete: "Удалить без возможности восстановления?",
  indexReady: "Индекс актуален",
  indexRequired: "Требуется переиндексация",
  sourcesCount: "Источников",
  chunksCount: "Чанков",
  lmHelp:
    "Локальное подключение. Запустите Local Server в LM Studio; из Docker используйте host.docker.internal:1234/v1.",
  openRouterHelp:
    "Облачное подключение OpenRouter. Используйте HTTPS и API-ключ.",
  compatibleHelp:
    "Подключение к другому OpenAI-compatible API. Используйте HTTPS и API-ключ провайдера.",
  connectionFailed:
    "Не удалось подключиться. Проверьте адрес, ключ и доступность сервера.",
  invalidInput: "Проверьте введённые данные.",
  networkError: "Сервис недоступен. Проверьте Docker и повторите попытку.",
  sourceTypeDisabled: "Этот тип источника отключён в настройках базы.",
  providerUnavailable:
    "Провайдер модели недоступен. Проверьте сервер и подключение.",
  vectorUnavailable: "Векторный поиск временно недоступен.",
  status: "Статус",
  publication: "Публикация",
  noModel: "Не выбрана",
  workPlaybook: "Рабочие плейбуки",
  retryCleanup: "Удалить остатки незавершённых удалений",
  cleanupHelp:
    "Повторно удаляет файлы и векторы, которые не удалось убрать при удалении источника. Чаты и действующие источники не затрагиваются.",
  nothingToCleanup: "Незавершённых удалений нет.",
  confirmCleanup: "Повторить безопасную очистку оставшихся файлов и векторов?",
  pendingJobs: "Незавершённых загрузок",
  pendingCleanup: "Незавершённых удалений",
  navigation: "Основная навигация",
  createBaseHint: "Сначала создайте базу знаний",
  systemPrompt: "Системный промпт",
  systemPromptPlaceholder:
    "Например: отвечай как преподаватель японского языка, приводи примеры и указывай уровень JLPT.",
  systemPromptHelp:
    "Необязательные инструкции для ответов в этой базе. Правила работы с источниками применяются автоматически.",
  savePrompt: "Сохранить промпт",
  modelIdHelp:
    "ID модели — точное техническое имя у провайдера. Загрузите доступные ID для выбранного подключения или вставьте ID из документации провайдера.",
  displayName: "Понятное название",
  displayNameHelp:
    "Необязательно: если оставить пустым, используется ID модели.",
  loadModelIds: "Загрузить ID моделей",
  modelIdsLoaded: "ID моделей загружены — выберите значение в поле ID модели",
  noModelIds: "Подключение не вернуло список моделей",
  testModel: "Проверить модель",
  modelAvailable: "Модель отвечает",
  vectorSizeHelp:
    "Нажмите «Проверить модель»: система определит размерность автоматически. Ручной ввод оставлен для нестандартных провайдеров.",
  approveAll: "Опубликовать все готовые",
  approvedCount: "Опубликовано источников",
  details: "Настройки базы",
  query: "Запрос",
  latency: "Время ответа",
  matchedChunks: "Найдено чанков",
  retrievalMethod: "Метод поиска",
  vectorSearch: "Векторный",
  textSearch: "Текстовый",
  warnings: "Предупреждения",
  tokens: "Токены",
  playbookTitle: "Рекомендуемые плейбуки",
  playbookAuthor: "Автор: defrixx",
  playbookDescription:
    "Если ваша база знаний связана с Product Security, добавьте в неё мои практические плейбуки из репозитория defrixx/Product-security-playbook.",
  playbookTarget: "База для загрузки",
  manageBases: "Базы",
  manageConnections: "Подключения",
  manageModels: "Модели",
  manageImport: "Импорт",
  search: "Поиск",
  allStatuses: "Все статусы",
  allTypes: "Все типы",
  selected: "Выбрано",
  selectAll: "Выбрать все",
  clearSelection: "Снять выбор",
  archiveSelected: "Архивировать выбранные",
  publishSelected: "Опубликовать выбранные",
  noResults: "Ничего не найдено",
  rename: "Переименовать",
  deleteChat: "Удалить чат",
  stop: "Остановить",
  awaitingAnswer: "Модель готовит ответ",
  responseDetails: "Детали ответа",
  retrievalTime: "Поиск",
  generationTime: "Генерация",
  sourceDocuments: "Документы",
  limitedTrace: "Для этой старой записи доступны не все данные",
  promptTokens: "Входные токены",
  completionTokens: "Выходные токены",
  totalTokens: "Всего токенов",
  baseIcon: "Иконка базы",
  filters: "Фильтры",
  collapse: "Свернуть",
  expand: "Развернуть",
  successNotice: "Готово",
  confirmArchive: "Архивировать выбранные источники?",
  maintenancePurpose:
    "Здесь отображается состояние локального хранилища и восстанавливаются только операции удаления, которые прервались из-за сбоя. При нормальной работе никаких действий не требуется.",
  allBases: "Все базы",
  copy: "Копировать",
  copied: "Скопировано",
  chunkSize: "Размер чанка, символов",
  chunkOverlap: "Перекрытие, символов",
  saveChunking: "Сохранить разбиение",
  chunkingHelp: "Применяется к новым и обновлённым источникам. После изменения обновите источники и индекс.",
  viewFragments: "Фрагменты",
  refreshSource: "Обновить",
  sourceRefreshed: "Источник обновлён",
  close: "Закрыть",
  totalQueries: "Запросов",
  groundedAnswers: "Ответов по источникам",
  noResultAnswers: "Без найденных данных",
  averageLatency: "Среднее время",
  qualityCheck: "Контрольные вопросы",
  qualityHelp: "По одному вопросу в строке. Проверка оценивает, находятся ли релевантные фрагменты, и не обращается к chat-модели.",
  qualityPlaceholder: "Что такое Kafka?\nКак защищать API?",
  runCheck: "Проверить покрытие",
  coverage: "Покрытие",
  indexed: "В индексе",
  hybridSearch: "Гибридный",
};
export const en: { [K in keyof typeof ru]: string } = {
  available: "Available",
  unavailable: "Unavailable",
  ready: "Ready to publish",
  approved: "Published",
  processing: "Processing",
  archived: "Archived",
  failed: "Failed",
  uploadSource: "File",
  websiteSource: "Website",
  playbookSource: "GitHub playbook",
  grounded: "Grounded",
  modelOnly: "Model only",
  degraded: "Degraded",
  ok: "Successful",
  chats: "Chats",
  sources: "Sources",
  glossaries: "Glossaries",
  diagnostics: "Diagnostics",
  maintenance: "Maintenance",
  bases: "Knowledge bases",
  connections: "Connections",
  models: "Models",
  newChat: "New chat",
  newBase: "New base",
  send: "Send",
  settings: "Manage",
  empty: "Nothing here yet",
  chooseBase: "Choose a knowledge base",
  name: "Name",
  description: "Description",
  save: "Save",
  saved: "Saved",
  theme: "Theme",
  language: "Language",
  manual: "Manual approval",
  automatic: "Automatic publishing",
  chatModel: "Chat model",
  embeddingModel: "Embedding model",
  syncPlaybook: "Sync work playbooks",
  apiKey: "API key",
  modelId: "Model ID",
  vectorSize: "Vector size",
  upload: "Upload",
  addWebsite: "Add website",
  approve: "Publish",
  createConnectionFirst: "Create a connection first",
  system: "System",
  light: "Light",
  dark: "Dark",
  reindex: "Reindex",
  test: "Test",
  term: "Term",
  definition: "Definition",
  message: "Message",
  loading: "Loading…",
  retry: "Retry",
  remove: "Delete",
  archive: "Archive",
  disable: "Disable",
  enable: "Enable",
  timeout: "Timeout, sec.",
  retries: "Retries",
  clearKey: "Remove saved key",
  confirmDelete: "Delete permanently?",
  indexReady: "Index is current",
  indexRequired: "Reindex required",
  sourcesCount: "Sources",
  chunksCount: "Chunks",
  lmHelp:
    "Local connection. Start Local Server in LM Studio; from Docker use host.docker.internal:1234/v1.",
  openRouterHelp: "OpenRouter cloud connection. Use HTTPS and an API key.",
  compatibleHelp:
    "Connection to another OpenAI-compatible API. Use HTTPS and the provider API key.",
  connectionFailed:
    "Connection failed. Check the URL, key, and server availability.",
  invalidInput: "Check the entered data.",
  networkError: "The service is unavailable. Check Docker and try again.",
  sourceTypeDisabled: "This source type is disabled for the knowledge base.",
  providerUnavailable:
    "The model provider is unavailable. Check the server and connection.",
  vectorUnavailable: "Vector retrieval is temporarily unavailable.",
  status: "Status",
  publication: "Publication",
  noModel: "Not selected",
  workPlaybook: "Work playbooks",
  retryCleanup: "Remove leftovers from incomplete deletions",
  cleanupHelp:
    "Retries deletion of files and vectors left after a source deletion failed. Chats and active sources are not affected.",
  nothingToCleanup: "There are no incomplete deletions.",
  confirmCleanup: "Retry safe removal of leftover files and vectors?",
  pendingJobs: "Pending ingestion jobs",
  pendingCleanup: "Incomplete deletions",
  navigation: "Primary navigation",
  createBaseHint: "Create a knowledge base first",
  systemPrompt: "System prompt",
  systemPromptPlaceholder:
    "For example: answer as a Japanese teacher, include examples, and specify the JLPT level.",
  systemPromptHelp:
    "Optional response instructions for this knowledge base. Source-grounding rules are applied automatically.",
  savePrompt: "Save prompt",
  modelIdHelp:
    "The model ID is the exact technical name expected by the provider. Load available IDs for the selected connection or paste one from the provider documentation.",
  displayName: "Display name",
  displayNameHelp: "Optional: the model ID is used when left empty.",
  loadModelIds: "Load model IDs",
  modelIdsLoaded: "Model IDs loaded — choose one in the Model ID field",
  noModelIds: "The connection returned no models",
  testModel: "Test model",
  modelAvailable: "Model is responding",
  vectorSizeHelp:
    "Select Test model to detect the dimension automatically. Manual input remains available for non-standard providers.",
  approveAll: "Publish all ready",
  approvedCount: "Sources published",
  details: "Knowledge base settings",
  query: "Query",
  latency: "Response time",
  matchedChunks: "Matched chunks",
  retrievalMethod: "Retrieval method",
  vectorSearch: "Vector",
  textSearch: "Text",
  warnings: "Warnings",
  tokens: "Tokens",
  playbookTitle: "Recommended playbooks",
  playbookAuthor: "Author: defrixx",
  playbookDescription:
    "If your knowledge base is related to Product Security, add my practical playbooks from the defrixx/Product-security-playbook repository.",
  playbookTarget: "Destination knowledge base",
  manageBases: "Bases",
  manageConnections: "Connections",
  manageModels: "Models",
  manageImport: "Import",
  search: "Search",
  allStatuses: "All statuses",
  allTypes: "All types",
  selected: "Selected",
  selectAll: "Select all",
  clearSelection: "Clear selection",
  archiveSelected: "Archive selected",
  publishSelected: "Publish selected",
  noResults: "No matches",
  rename: "Rename",
  deleteChat: "Delete chat",
  stop: "Stop",
  awaitingAnswer: "The model is preparing a response",
  responseDetails: "Response details",
  retrievalTime: "Retrieval",
  generationTime: "Generation",
  sourceDocuments: "Documents",
  limitedTrace: "Some details are unavailable for this older trace",
  promptTokens: "Input tokens",
  completionTokens: "Output tokens",
  totalTokens: "Total tokens",
  baseIcon: "Base icon",
  filters: "Filters",
  collapse: "Collapse",
  expand: "Expand",
  successNotice: "Done",
  confirmArchive: "Archive selected sources?",
  maintenancePurpose:
    "This page shows local storage health and resumes only deletion operations interrupted by a failure. No action is required during normal operation.",
  allBases: "All bases",
  copy: "Copy",
  copied: "Copied",
  chunkSize: "Chunk size, characters",
  chunkOverlap: "Overlap, characters",
  saveChunking: "Save chunking",
  chunkingHelp: "Applies to new and refreshed sources. Refresh sources and the index after changing it.",
  viewFragments: "Fragments",
  refreshSource: "Refresh",
  sourceRefreshed: "Source refreshed",
  close: "Close",
  totalQueries: "Queries",
  groundedAnswers: "Grounded answers",
  noResultAnswers: "No-result answers",
  averageLatency: "Average time",
  qualityCheck: "Evaluation questions",
  qualityHelp: "Enter one question per line. This checks retrieval coverage without calling the chat model.",
  qualityPlaceholder: "What is Kafka?\nHow should APIs be secured?",
  runCheck: "Check coverage",
  coverage: "Coverage",
  indexed: "Indexed",
  hybridSearch: "Hybrid",
};
type Words = { [K in keyof typeof ru]: string };
const words: Record<Locale, Words> = { ru, en };
type Context = {
  locale: Locale;
  setLocale: (value: Locale) => void;
  theme: Theme;
  setTheme: (value: Theme) => void;
  t: Words;
  errorText: (error: unknown) => string;
};
const C = createContext<Context>({
  locale: "ru",
  setLocale: () => {},
  theme: "system",
  setTheme: () => {},
  t: ru,
  errorText: () => ru.networkError,
});
export function Preferences({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() =>
    typeof window === "undefined"
      ? "ru"
      : localStorage.getItem("locale") === "en"
        ? "en"
        : "ru",
  );
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window === "undefined") return "system";
    const value = localStorage.getItem("theme");
    return value === "light" || value === "dark" ? value : "system";
  });
  useEffect(() => {
    document.documentElement.lang = locale;
    localStorage.setItem("locale", locale);
  }, [locale]);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "dark" || (theme === "system" && media.matches)
          ? "dark"
          : "light";
    };
    apply();
    media.addEventListener("change", apply);
    localStorage.setItem("theme", theme);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  const t = words[locale];
  const errorText = (error: unknown) => {
    const code = error instanceof Error ? error.message : String(error);
    if (code.includes("validation") || code.includes("invalid_"))
      return t.invalidInput;
    if (code.includes("provider_")) return t.providerUnavailable;
    if (code.includes("vector_")) return t.vectorUnavailable;
    if (code.includes("source_type_disabled")) return t.sourceTypeDisabled;
    return code.startsWith("HTTP") ? t.networkError : code;
  };
  return (
    <C.Provider value={{ locale, setLocale, theme, setTheme, t, errorText }}>
      {children}
    </C.Provider>
  );
}
export const usePreferences = () => useContext(C);
export function PreferenceControls() {
  const { locale, setLocale, theme, setTheme, t } = usePreferences();
  return (
    <div className="prefs">
      <label className="pref-control">
        <span className="sr-only">{t.language}</span>
        <select
          aria-label={t.language}
          value={locale}
          onChange={(event) => setLocale(event.target.value as Locale)}
        >
          <option value="ru">🇷🇺 Русский</option>
          <option value="en">🇬🇧 English</option>
        </select>
      </label>
      <label className="pref-control">
        <span className="sr-only">{t.theme}</span>
        <select
          aria-label={t.theme}
          value={theme}
          onChange={(event) => setTheme(event.target.value as Theme)}
        >
          <option value="system">💻 {t.system}</option>
          <option value="light">☀️ {t.light}</option>
          <option value="dark">🌙 {t.dark}</option>
        </select>
      </label>
    </div>
  );
}
