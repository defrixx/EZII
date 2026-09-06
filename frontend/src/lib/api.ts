const API_BASE=process.env.NEXT_PUBLIC_API_BASE||"/api/v1";
export class ApiError extends Error{constructor(public status:number,message:string){super(message)}}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),30000);
 try{const body=options.body; const multipart=typeof FormData!=="undefined"&&body instanceof FormData; const res=await fetch(`${API_BASE}${path}`,{...options,signal:controller.signal,cache:"no-store",headers:{...(body&&!multipart?{"Content-Type":"application/json"}:{}),...(options.headers||{})}}); if(!res.ok){let message=`HTTP ${res.status}`;try{const data=await res.json();message=data.error?.message||data.detail||message}catch{}throw new ApiError(res.status,message)}if(res.status===204)return undefined as T;return await res.json()}finally{clearTimeout(timer)}
}
export async function streamMessage(path:string,content:string,locale:"ru"|"en",onMessage:(value:unknown)=>void){
 const res=await fetch(`${API_BASE}${path}`,{method:"POST",headers:{"Content-Type":"application/json","Accept":"text/event-stream"},body:JSON.stringify({content,locale})});
 if(!res.ok||!res.body)throw new ApiError(res.status,`HTTP ${res.status}`);
 const reader=res.body.getReader();const decoder=new TextDecoder();let buffer="";
 for(;;){const{done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const frames=buffer.split("\n\n");buffer=frames.pop()||"";for(const frame of frames){const event=frame.match(/^event: (.+)$/m)?.[1];const data=frame.match(/^data: (.+)$/m)?.[1];if(event==="message"&&data)onMessage(JSON.parse(data));if(event==="error"&&data)throw new Error(JSON.parse(data).detail||"stream_error")}}
}
