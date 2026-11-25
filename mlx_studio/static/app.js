'use strict';
const $ = (s) => document.querySelector(s);
const escapeHTML = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let apiKey = '', status = {loaded:{},enabled:true}, localModels = [], page = 'chat', modelTab = 'discover';
let searchResults = [
 {id:'mlx-community/Qwen2.5-0.5B-Instruct-4bit',kind:'chat'},
 {id:'mlx-community/all-MiniLM-L6-v2-4bit',kind:'embedding'},
 {id:'mlx-community/Qwen3-0.6B-4bit',kind:'chat'}
];
let conversations;
try { conversations = JSON.parse(localStorage.getItem('mlx-conversations') || '[]'); } catch { conversations = []; }
if (!Array.isArray(conversations)) conversations = [];
conversations = conversations.filter(c => c && typeof c.id==='string' && Array.isArray(c.messages));
let current = conversations[0]?.id, generating = false, controller, busyModels = new Set(), toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').classList.remove('hidden'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),6500); }
function save() { try { localStorage.setItem('mlx-conversations',JSON.stringify(conversations)); } catch { toast('浏览器存储已满，当前会话无法保存'); } renderHistory(); }
async function api(path, body, signal) {
 const response = await fetch(path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(apiKey?{Authorization:`Bearer ${apiKey}`}:{})},body:body===undefined?undefined:JSON.stringify(body),signal});
 if(!response.ok) { const data=await response.json().catch(()=>({})); if(response.status===401 && !$('#auth-dialog').open) $('#auth-dialog').showModal(); throw new Error(data.error?.message || `请求失败 (${response.status})`); }
 return response;
}
async function json(path,body) { return (await api(path,body)).json(); }
function go(next) { page=next; document.querySelectorAll('.page').forEach(e=>e.classList.toggle('hidden',e.id!==`page-${next}`));document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.page===next));$('#page-title').textContent={chat:'对话工作台',models:'模型库',embedding:'Embedding',service:'本地服务'}[next]; if(next==='models')renderModels(); if(next==='service')renderService(); }
document.querySelectorAll('[data-page]').forEach(e=>e.onclick=()=>go(e.dataset.page));
document.querySelectorAll('[data-goto]').forEach(e=>e.onclick=()=>go(e.dataset.goto));
function conversation() { return conversations.find(c=>c.id===current); }
function newChat() { if(generating) {toast('请先停止当前生成'); return;} const c={id:crypto.randomUUID(),title:'新对话',messages:[]};conversations.unshift(c);current=c.id;save();renderMessages();go('chat'); }
$('#new-chat').onclick=newChat;$('#clear-chat').onclick=newChat;
function renderHistory() {
 const root=$('#history');root.replaceChildren();
 for(const c of conversations) {const row=document.createElement('div');row.className='history-item'+(c.id===current?' active':'');const button=document.createElement('button');button.textContent='◌  '+c.title;button.title=c.title;button.onclick=()=>{if(generating){toast('请先停止当前生成');return;}current=c.id;renderHistory();renderMessages();go('chat');};const del=document.createElement('button');del.className='icon-button';del.textContent='×';del.title='删除对话';del.onclick=()=>{if(generating)return;conversations=conversations.filter(x=>x.id!==c.id);if(current===c.id)current=conversations[0]?.id;save();renderMessages();};row.append(button,del);root.append(row);}
}
function renderMessages() {
 const messages=conversation()?.messages||[];const root=$('#messages');root.replaceChildren();
 if(!messages.length){root.innerHTML='<div class="welcome"><div class="welcome-symbol">✳</div><h2>你好，有什么新想法？</h2><p>选择一个本地模型，让灵感从这里开始。<br>每一次对话，都只属于你。</p><div class="suggestions"><button>✦ 帮我梳理一个想法</button><button>⌘ 写一段 Python 代码</button><button>◈ 解释一个复杂概念</button></div></div>';root.querySelectorAll('.suggestions button').forEach(b=>b.onclick=()=>{$('#prompt').value=b.textContent.slice(2).trim();$('#prompt').focus();});return;}
 messages.forEach(m=>{const el=document.createElement('div');el.className='message '+m.role;el.innerHTML=`<div class="avatar">${m.role==='user'?'你':'✳'}</div><div class="message-body"><div class="message-name">${m.role==='user'?'你':'MLX Assistant'}</div><div class="message-content"></div></div>`;el.querySelector('.message-content').textContent=m.content;root.append(el);});root.scrollTop=root.scrollHeight;
}
$('#temperature').oninput=e=>$('#temperature-value').textContent=e.target.value;
$('#prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}};
$('#stop').onclick=()=>controller?.abort();
$('#chat-form').onsubmit=async e=>{
 e.preventDefault();if(generating)return;
 const text=$('#prompt').value.trim(), model=$('#chat-model').value;
 if(!model){toast('请先在模型库下载并加载对话模型');go('models');return;}
 if(!status.enabled){toast('请先在本地服务页开启推理服务');return;}if(!text)return;
 if(!conversation())newChat();const c=conversation();
 c.messages.push({role:'user',content:text});if(c.messages.length===1)c.title=text.slice(0,22);
 const system=$('#system-prompt').value.trim();const history=c.messages.filter(m=>m.content.trim()).map(m=>({role:m.role,content:m.content}));
 const body={model,messages:[...(system?[{role:'system',content:system}]:[]),...history],temperature:Number($('#temperature').value),max_tokens:Number($('#max-tokens').value),stream:true};
 const assistant={role:'assistant',content:''};c.messages.push(assistant);$('#prompt').value='';generating=true;controller=new AbortController();$('#send').classList.add('hidden');$('#stop').classList.remove('hidden');renderMessages();
 try {
  const response=await api('/v1/chat/completions',body,controller.signal);const reader=response.body.getReader(), decoder=new TextDecoder();let pending='';
  while(true){const {value,done}=await reader.read();pending+=decoder.decode(value||new Uint8Array(),{stream:!done});const frames=pending.split('\n\n');pending=frames.pop();for(const frame of frames){for(const line of frame.split('\n')){if(!line.startsWith('data: '))continue;const payload=line.slice(6);if(payload==='[DONE]')continue;const data=JSON.parse(payload);if(data.error)throw new Error(data.error.message);assistant.content+=data.choices?.[0]?.delta?.content||'';const last=$('#messages .message:last-child .message-content');if(last)last.textContent=assistant.content;$('#messages').scrollTop=$('#messages').scrollHeight;}}if(done)break;}
 }catch(err){if(err.name!=='AbortError')toast(err.message);else toast('已停止生成');}
 finally{if(!assistant.content)c.messages=c.messages.filter(m=>m!==assistant);generating=false;controller=null;$('#send').classList.remove('hidden');$('#stop').classList.add('hidden');save();renderMessages();refresh();}
};
function fillSelect(selector,repo,empty){const el=$(selector);if(el.value===repo && el.options.length===(repo?1:1))return;el.replaceChildren();const option=new Option(repo?repo.split('/')[1]:empty,repo||'');el.add(option);}
async function refresh(silent=false){try{const [s,models]=await Promise.all([json('/api/status'),json('/api/models')]);status=s;localModels=models;$('#platform').textContent=s.platform;$('#footer-status').textContent=s.enabled?'● 推理服务已开启':'○ 推理服务已停止';$('#local-count').textContent=models.filter(m=>m.status==='ready').length;fillSelect('#chat-model',s.loaded.chat,'尚未加载对话模型');fillSelect('#embedding-model',s.loaded.embedding,'尚未加载向量模型');if(page==='models')renderModels();if(page==='service')renderService();}catch(err){$('#footer-status').textContent='○ 服务未连接';if(!silent)toast(err.message);}}
$('#refresh').onclick=()=>refresh();
function size(bytes){if(!bytes)return '等待文件…';const u=bytes>1024**3?'GB':'MB';return (bytes/(u==='GB'?1024**3:1024**2)).toFixed(1)+' '+u;}
function renderModels(){const root=$('#model-list');root.replaceChildren();let rows=modelTab==='local'?localModels:searchResults;const kind=$('#model-kind').value;rows=rows.filter(m=>!kind||m.kind===kind);if(!rows.length){root.innerHTML='<div class="card muted">'+(modelTab==='local'?'还没有本地模型。去「发现模型」下载一个。':'未找到模型，请调整关键词或类型。')+'</div>';return;}
 for(const model of rows){const local=localModels.find(m=>m.id===model.id),loaded=status.loaded[model.kind]===model.id,busy=busyModels.has(model.id);const card=document.createElement('div');card.className='model-card';let label=loaded?'卸载':local?.status==='ready'?'加载模型':local?.status==='downloading'?'下载中…':local?.status==='error'?'重试下载':'↓ 下载模型';const state=loaded?'● 已加载':local?.status==='ready'?'✓ 已下载':local?.status==='downloading'?size(local.bytes)+' · 下载中':local?.status==='error'?'下载失败':model.downloads?`${Number(model.downloads).toLocaleString()} 次下载`:'MLX 原生模型';card.innerHTML=`<div class="model-card-top"><span class="model-icon">${model.kind==='chat'?'◈':'⠿'}</span><span class="tag">${model.kind==='chat'?'对话模型':'Embedding'}</span></div><h3>${escapeHTML(model.id.split('/')[1])}</h3><span class="org">mlx-community</span><div class="model-card-bottom"><span class="status">${escapeHTML(state)}</span><button class="${loaded?'secondary':'primary'}" ${busy||local?.status==='downloading'?'disabled':''}>${busy?'处理中…':label}</button></div>${local?.error?`<div class="model-error">${escapeHTML(local.error)}</div>`:''}`;
 card.querySelector('button').onclick=async()=>{busyModels.add(model.id);renderModels();try{if(loaded)await json('/api/models/unload',{kind:model.kind});else if(local?.status==='ready')await json('/api/models/load',{id:model.id,kind:model.kind});else await json('/api/models/download',{id:model.id,kind:model.kind});toast(loaded?'模型已卸载':local?.status==='ready'?'模型加载完成':'下载任务已创建');}catch(err){toast(err.message);}finally{busyModels.delete(model.id);await refresh();}};root.append(card);}
}
document.querySelectorAll('[data-model-tab]').forEach(e=>e.onclick=()=>{modelTab=e.dataset.modelTab;document.querySelectorAll('[data-model-tab]').forEach(b=>b.classList.toggle('active',b===e));renderModels();});
$('#model-kind').onchange=renderModels;
$('#model-query').onkeydown=e=>{if(e.key==='Enter')$('#search-models').click();};
$('#search-models').onclick=async()=>{const button=$('#search-models');button.disabled=true;const q=$('#model-query').value.trim(),kind=$('#model-kind').value;try{if(q.startsWith('mlx-community/')){if(!kind){toast('按标识添加时，请先选择对话或 Embedding 类型');return;}searchResults=[{id:q,kind}];$('#catalog-note').textContent='显式模型标识，下载前请核实架构与所选用途。';}else{searchResults=await json('/api/search?q='+encodeURIComponent(q)+(kind?'&kind='+kind:''));$('#catalog-note').textContent=`在线搜索找到 ${searchResults.length} 个模型（最多50个）。用途为推测，请核实模型说明。`; }modelTab='discover';document.querySelectorAll('[data-model-tab]').forEach(b=>b.classList.toggle('active',b.dataset.modelTab==='discover'));renderModels();}catch(err){toast(err.message);}finally{button.disabled=false;}};
$('#embedding-form').onsubmit=async e=>{e.preventDefault();const model=$('#embedding-model').value;if(!model){toast('请先在模型库下载并加载 Embedding 模型');go('models');return;}const texts=$('#embedding-input').value.split('\n').map(s=>s.trim()).filter(Boolean);if(!texts.length){toast('请输入至少一条文本');return;}const button=$('#embed-submit');button.disabled=true;button.textContent='正在生成…';const start=performance.now();try{const result=await json('/v1/embeddings',{model,input:texts});const vectors=result.data.map(d=>d.embedding);const elapsed=((performance.now()-start)/1000).toFixed(2);const root=$('#embedding-result');root.classList.remove('result-placeholder');const cosine=(a,b)=>{let dot=0,aa=0,bb=0;for(let i=0;i<a.length;i++){dot+=a[i]*b[i];aa+=a[i]*a[i];bb+=b[i]*b[i];}return aa&&bb?dot/Math.sqrt(aa*bb):0;};root.innerHTML=`<div class="panel-title">向量结果 <span class="tag">${elapsed} s</span></div><div class="result-summary"><div><strong>${vectors.length}</strong><span>条文本</span></div><div><strong>${vectors[0].length}</strong><span>向量维度</span></div><div><strong>${result.usage.total_tokens}</strong><span>输入 Token</span></div></div><div class="panel-title">余弦相似度</div><div style="overflow:auto"><table class="matrix"><thead><tr><th></th>${texts.map((_,i)=>`<th>#${i+1}</th>`).join('')}</tr></thead><tbody>${vectors.map((a,i)=>`<tr><th>#${i+1}</th>${vectors.map(b=>{const s=cosine(a,b);return `<td style="background:rgba(60,140,105,${0.07+Math.max(0,s)*0.2})">${s.toFixed(3)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>${vectors.map((v,i)=>`<details class="vector-detail"><summary>#${i+1} · ${escapeHTML(texts[i].slice(0,70))}</summary><pre>${escapeHTML(JSON.stringify(v))}</pre></details>`).join('')}`;}catch(err){toast(err.message);}finally{button.disabled=false;button.textContent='生成向量 ↗';refresh();}};
function renderService(){$('#service-state').textContent=status.enabled?'运行中':'已停止';$('#loaded-count').innerHTML=Object.keys(status.loaded).length+' <small>个</small>';$('#request-count').textContent=status.requests||0;$('#error-count').textContent=(status.errors||0)+' 次错误';$('#toggle-service').textContent=status.enabled?'■ 停止推理服务':'▶ 开启推理服务';$('#toggle-service').className=status.enabled?'secondary':'primary';$('#base-url').textContent=location.origin+'/v1';const auth=apiKey?'\n  -H "Authorization: Bearer $MLX_STUDIO_API_KEY" \\':'';const model=status.loaded.chat||'mlx-community/你的对话模型';$('#api-example').textContent=`curl ${location.origin}/v1/chat/completions \\${auth}\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify({model,messages:[{role:'user',content:'你好！'}],stream:true},null,2)}'`;}
$('#toggle-service').onclick=async()=>{const b=$('#toggle-service');b.disabled=true;try{await json('/api/service',{enabled:!status.enabled});await refresh();}catch(err){toast(err.message);}finally{b.disabled=false;}};
async function copy(text){try{await navigator.clipboard.writeText(text);toast('已复制');}catch{toast('复制失败，请手动选择文本复制');}}
$('#copy-url').onclick=()=>copy($('#base-url').textContent);$('#copy-example').onclick=()=>copy($('#api-example').textContent);
$('#auth-button').onclick=()=>$('#auth-dialog').showModal();$('#cancel-auth').onclick=()=>$('#auth-dialog').close();$('#auth-form').onsubmit=async e=>{e.preventDefault();apiKey=$('#api-key').value;$('#api-key').value='';$('#auth-dialog').close();await refresh();};
renderHistory();renderMessages();refresh();setInterval(()=>refresh(true),2500);
