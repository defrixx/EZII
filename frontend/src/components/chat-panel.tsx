"use client";

import {useEffect,useState} from "react";
import {api,streamMessage} from "@/lib/api";
import {usePreferences} from "./app-preferences";

type KB={id:string;name:string};
type Chat={id:string;title:string;knowledge_base_id:string};
type Msg={id:string;role:string;content:string;source_types?:string[];metadata_json?:{warning_codes?:string[];sources?:{id:string;title:string;source_type:string}[]}};

export function ChatPanel(){
 const{t,locale,errorText}=usePreferences();
 const[kbs,setKbs]=useState<KB[]>([]);const[selectedKb,setSelectedKb]=useState("");
 const[chats,setChats]=useState<Chat[]>([]);const[current,setCurrent]=useState<Chat|null>(null);
 const[msgs,setMsgs]=useState<Msg[]>([]);const[input,setInput]=useState("");
 const[busy,setBusy]=useState(false);const[loading,setLoading]=useState(true);const[error,setError]=useState("");
 useEffect(()=>{Promise.all([api<KB[]>("/knowledge-bases"),api<Chat[]>("/chats")]).then(([bases,rows])=>{setKbs(bases);setSelectedKb(bases[0]?.id||"");setChats(rows);if(rows[0])void open(rows[0]);else setLoading(false)}).catch(e=>{setError(errorText(e));setLoading(false)})},[errorText]);
 async function open(chat:Chat){setCurrent(chat);const detail=await api<{messages:Msg[]}>(`/chats/${chat.id}`);setMsgs(detail.messages);setLoading(false)}
 async function create(){if(!selectedKb)return;const chat=await api<Chat>("/chats",{method:"POST",body:JSON.stringify({title:t.newChat,knowledge_base_id:selectedKb})});setChats(rows=>[chat,...rows]);await open(chat)}
 async function send(){if(!current||!input.trim())return;const content=input;setInput("");setMsgs(rows=>[...rows,{id:crypto.randomUUID(),role:"user",content}]);setBusy(true);setError("");try{await streamMessage(`/messages/${current.id}/stream`,content,locale,value=>setMsgs(rows=>[...rows,value as Msg]))}catch(e){setError(errorText(e))}finally{setBusy(false)}}
 if(loading)return <p role="status">{t.loading}</p>;
 const currentBase=kbs.find(k=>k.id===current?.knowledge_base_id)?.name;
 return <div className="grid"><aside className="panel stack"><label>{t.chooseBase}<select value={selectedKb} onChange={e=>setSelectedKb(e.target.value)} disabled={!kbs.length}>{kbs.map(k=><option key={k.id} value={k.id}>{k.name}</option>)}</select></label><button className="primary" onClick={create} disabled={!selectedKb}>{t.newChat}</button>{!kbs.length&&<div className="empty-action"><p>{t.createBaseHint}</p><a href="/manage" className="button-link primary">＋ {t.newBase}</a></div>}{kbs.map(base=>{const rows=chats.filter(chat=>chat.knowledge_base_id===base.id);return rows.length?<section className="chat-group stack" key={base.id}><h2>📚 {base.name}</h2>{rows.map(chat=><button className={current?.id===chat.id?"selected":undefined} aria-pressed={current?.id===chat.id} key={chat.id} onClick={()=>void open(chat)}>💬 {chat.title}</button>)}</section>:null})}</aside><section className="panel stack"><h1>{current?.title||t.chats}{currentBase&&<small className="muted"> · {currentBase}</small>}</h1>{error&&<p role="alert">{error}</p>}<div className="messages stack">{msgs.length?msgs.map(message=><div key={message.id} className={`message ${message.role}`}>{message.content}{message.metadata_json?.sources?.length?<small className="muted">{t.sources}: {message.metadata_json.sources.map(source=>source.title).join(", ")}</small>:null}{message.metadata_json?.warning_codes?.length?<small className="warning">{t.vectorUnavailable}</small>:null}</div>):<p className="muted">{t.empty}</p>}</div><div className="row"><textarea aria-label={t.message} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();void send()}}} rows={2} style={{flex:1}}/><button className="primary" disabled={busy||!current} onClick={send}>{busy?"…":t.send}</button></div></section></div>
}
