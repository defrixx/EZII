import {describe,expect,it} from "vitest";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {en,ru} from "./app-preferences";

const read=(path:string)=>readFileSync(resolve(path),"utf8");

describe("local UI contract",()=>{
 it("keeps complete Russian and English dictionaries",()=>{expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());expect(ru.bases).toBe("Базы знаний");expect(en.bases).toBe("Knowledge bases")});
 it("supports and persists every theme",()=>{const preferences=read("src/components/app-preferences.tsx");const layout=read("src/app/layout.tsx");expect(preferences).toContain('type Theme="light"|"dark"|"system"');expect(preferences).toContain('localStorage.setItem("theme",theme)');expect(layout).toContain("document.documentElement.dataset.theme")});
 it("updates and preloads the document locale",()=>{expect(read("src/components/app-preferences.tsx")).toContain("document.documentElement.lang=locale");expect(read("src/app/layout.tsx")).toContain("document.documentElement.lang=l==='en'?'en':'ru'")});
 it("has no auth flow",()=>{const api=read("src/lib/api.ts");expect(api).not.toContain("refreshAuthSession");expect(api).not.toContain("Authorization")});
 it("chooses a base only when creating a chat",()=>{const panel=read("src/components/chat-panel.tsx");const send=panel.slice(panel.indexOf("async function send"),panel.indexOf("if(loading)"));expect(panel).toContain("knowledge_base_id:selectedKb");expect(send).toContain("/messages/");expect(send).not.toContain("knowledge_base_id");expect(read("src/lib/api.ts")).toContain("JSON.stringify({content,locale})")});
 it("covers loading, empty, error, and success UI states",()=>{for(const file of ["chat-panel.tsx","sources-panel.tsx","glossaries-panel.tsx","manage-panel.tsx"]){const source=read(`src/components/${file}`);expect(source).toContain("loading");expect(source).toContain('role="alert"');expect(source).toContain("t.empty")}expect(read("src/components/manage-panel.tsx")).toContain('role="status"')});
 it("marks the active navigation item and shows icons",()=>{const nav=read("src/components/app-nav.tsx");expect(nav).toContain("usePathname");expect(nav).toContain('aria-current={pathname===href?"page"');expect(nav).toContain("💬");expect(nav).toContain("⚙️")});
 it("groups chats and glossaries by knowledge base",()=>{expect(read("src/components/chat-panel.tsx")).toContain("chats.filter(chat=>chat.knowledge_base_id===base.id)");expect(read("src/components/glossaries-panel.tsx")).toContain("bases.map(base=><BaseGlossaries")});
 it("separates provider setup and explains maintenance cleanup",()=>{const manage=read("src/components/manage-panel.tsx");const maintenance=read("src/components/maintenance-panel.tsx");expect(manage).toContain("provider-tabs");expect(manage).toContain("openRouterHelp");expect(maintenance).toContain("cleanupHelp");expect(maintenance).toContain("pending_cleanup_tasks?")});
 it("uses prominent create-base actions and labelled preferences",()=>{for(const file of ["chat-panel.tsx","sources-panel.tsx","glossaries-panel.tsx"]){expect(read(`src/components/${file}`)).toContain('button-link primary')}const preferences=read("src/components/app-preferences.tsx");expect(preferences).toContain("🇷🇺 Русский");expect(preferences).toContain("🌙")});
 it("offers the authored playbook in one collapsible section at the bottom",()=>{const manage=read("src/components/manage-panel.tsx");expect(manage.match(/playbook\/sync/g)).toHaveLength(1);expect(manage).toContain('<details className="panel playbook-card">');expect(manage).toContain('className="playbook-summary"');expect(manage).toContain("playbookAuthor");expect(manage).toContain("playbookTarget");expect(manage.lastIndexOf("playbook-card")).toBeGreaterThan(manage.lastIndexOf("t.models"))});
});
