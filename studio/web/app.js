'use strict';

const pages = [
  ['overview', '项目概览', 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
  ['script', '剧本与拆镜', 'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7'],
  ['assets', '角色与场景', 'M3 5h18v14H3z M3 16l5-5 4 4 3-3 6 6 M15 9h.01'],
  ['shots', '分镜制作', 'M4 8h16v12H4z M4 8l-1-4 16-3 1 4-16 3z M10 12l5 2.5-5 2.5z'],
  ['jobs', '生成队列', 'M9 5h12 M9 12h12 M9 19h12 M3 5h2 M3 12h2 M3 19h2'],
  ['exports', '成片与导出', 'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5'],
];
const icons = {plus:'M12 5v14 M5 12h14', play:'M8 5l12 7-12 7z', arrow:'M4 12h15 M14 7l5 5-5 5', image:pages[2][2], download:pages[5][2]};
const kinds = {character:'角色', scene:'场景', prop:'道具'};
const states = {queued:['排队','warn'], running:['进行中','run'], done:['完成','good'], failed:['失败','fail'], cancelled:['已取消','']};
const jobKinds = {draft:'剧本',image:'参考草图',video:'图生视频',export:'导出'};
const $ = (selector, root = document) => root.querySelector(selector);
const state = { page:'projects', projects:[], project:null, shot:null, result:null, jobs:[], status:{models:[],voices:{}}, busy:false, changed:false };
const content = $('#content');
const dialog = $('#dialog');
let toastTimer;
let polling = false;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function svg(path) { return `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="${path}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`; }
function badge(text, color='') { return `<span class="tag ${color}">${esc(text)}</span>`; }
function media(file, project = state.project?.id) { return file ? `/media/${encodeURIComponent(project)}/${file.split('/').map(encodeURIComponent).join('/')}` : ''; }
function sec(value) { return `${Number(value.toFixed(2))} 秒`; }
function stamp(value) { const mins = Math.floor(value/60); return `${String(mins).padStart(2,'0')}:${(value%60).toFixed(1).padStart(4,'0')}`; }
function date(value) { return new Date(value * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}); }
function button(label, action, tone='', attrs='', icon='') { return `<button type="button" class="button ${tone}" data-action="${action}" ${attrs}>${icon ? svg(icons[icon]) : ''}${esc(label)}</button>`; }
function pageButton(label, page, tone='', icon='') { return `<button type="button" class="button ${tone}" data-page="${page}">${icon ? svg(icons[icon]) : ''}${esc(label)}</button>`; }
function field(label, input, help='') { return `<label class="field"><span>${esc(label)}</span>${input}${help ? `<small>${esc(help)}</small>` : ''}</label>`; }
function options(items, value) { return items.map(([id,label]) => `<option value="${esc(id)}"${id===value?' selected':''}>${esc(label)}</option>`).join(''); }
function textarea(name, value, rows=3, placeholder='') { return `<textarea name="${name}" rows="${rows}" placeholder="${esc(placeholder)}">${esc(value)}</textarea>`; }
function textInput(name, value, attrs='') { return `<input name="${name}" value="${esc(value)}" ${attrs}>`; }
function upload(label, slot, accept, disabled=false) { return `<label class="button quiet small upload">${esc(label)}<input type="file" data-upload="${slot}" accept="${accept}" aria-label="${esc(label)}" ${disabled?'disabled':''}></label>`; }
function title(index, label, description, actions='') { return `<div class="page-head"><div><div class="eyebrow mono">${esc(index)}</div><h1>${esc(label)}</h1>${description?`<p>${esc(description)}</p>`:''}</div><div class="actions">${actions}</div></div>`; }
function empty(label, detail, action='') { return `<div class="empty"><h2>${esc(label)}</h2><p>${esc(detail)}</p>${action}</div>`; }
function panel(label, body, action='') { return `<section class="panel"><div class="panel-head"><h2>${esc(label)}</h2>${action}</div><div class="panel-body">${body}</div></section>`; }
function thumbnail(file, project=state.project?.id) { return file ? `<img class="thumb" src="${media(file,project)}" alt="" loading="lazy">` : '<span class="thumb"></span>'; }
function selectedShot() { return state.project?.shots.find(shot=>shot.id===state.shot) || state.project?.shots[0]; }
function activeJobs(project=state.project?.id) { return state.jobs.filter(job=>['queued','running'].includes(job.state) && (!project || job.project_id===project)); }
function locked() { return activeJobs().length > 0; }
function notify(message, error=false) { const el=$('#toast');el.textContent=message;el.className=error?'on error':'on';clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',error?8000:3500); }

async function api(path, method='GET', data) {
  const form = data instanceof FormData;
  const response = await fetch('/api'+path, {method, headers:{'X-Studio-Request':'1',...(data!==undefined&&!form?{'Content-Type':'application/json'}:{})},
    body:data===undefined?undefined:form?data:JSON.stringify(data)});
  const payload = await response.json().catch(()=>null);
  if(!response.ok) throw new Error(payload?.error || `本地服务返回 HTTP ${response.status}`);
  return payload;
}
function projectPath(suffix='') { return `/projects/${state.project.id}${suffix}`; }

function chrome() {
  const allActive=state.jobs.filter(job=>['queued','running'].includes(job.state)).length;
  $('#project-switch').innerHTML=state.projects.length?`<div class="select-project"><select aria-label="切换项目" id="project-select"><option value="">所有项目</option>${options(state.projects.map(p=>[p.id,p.name]),state.project?.id)}</select></div>`:button('新建项目','new','quiet project-button','','plus');
  $('#nav').innerHTML=pages.filter(([key])=>state.project||key==='jobs').map(([key,name,path])=>`<button class="nav-item ${state.page===key?'current':''}" data-page="${key}" title="${name}" ${state.page===key?'aria-current="page"':''}>${svg(path)}<span class="nav-label">${name}</span>${key==='jobs'&&allActive?`<span class="counter">${allActive}</span>`:''}</button>`).join('');
  $('#breadcrumb').innerHTML=`<span>工作区</span><span class="slash">/</span><strong>${esc(state.project?.name || '所有项目')}</strong>`;
  $('#queue-top').textContent=allActive?`任务队列 · ${allActive}`:'任务队列';
  if(state.status.workflow===undefined) { $('#engine-status').textContent='工作台已就绪 · 检查引擎中';return; }
  $('#engine-status').innerHTML=`<span class="status-dot ${state.status.comfy?'':'idle'}"></span>${state.status.comfy?'H3 已连接':state.status.workflow?'H3 按需启动':'H3 工作流未找到'}<span class="slash">·</span>${state.status.ollama?'Ollama 已连接':'Ollama 待连接'}`;
}

function projectList() {
  const cards=state.projects.map(p=>`<button type="button" class="panel project-card" data-action="open-project" data-id="${p.id}"><div class="cover">${p.cover?`<img src="${media(p.cover,p.id)}" alt="">`:''}</div><div class="panel-body"><h2>${esc(p.name)}</h2><div class="actions">${badge(p.aspect)}${badge(`${p.shots} 镜`)}${badge(`${p.exports} 部成片`)}</div></div></button>`).join('');
  return title('WORKSPACE','项目工作区','按集管理剧本、参考图、镜头与成片。',button('导入月台机器人示例','sample','quiet')+button('新建项目','new','primary','','plus'))+
    (cards?`<div class="project-grid">${cards}</div>`:empty('从一个短剧项目开始','创建空白项目，或导入有首帧和提示词的练习镜头。',button('导入示例','sample','primary')));
}

function overview() {
  const p=state.project;
  const ready=p.shots.filter(shot=>shot.clip).length;
  const duration=p.shots.reduce((sum,shot)=>sum+shot.seconds,0);
  const cover=[...p.shots].reverse().find(shot=>shot.first)?.first;
  const recent=p.exports.at(-1);
  const steps=[['script','剧本与拆镜',p.script?'已保存剧本':'创意变成可拍分镜'],['assets','角色与场景',`${p.assets.length} 项参考素材`],['shots','分镜制作',`${ready} / ${p.shots.length} 镜已出片`],['jobs','生成队列',`${activeJobs().length} 项待处理`],['exports','成片与导出',`${p.exports.length} 个可预览版本`]];
  const summary=p.shots.slice(0,8).map((shot,i)=>`<button class="summary-row" data-action="open-shot" data-id="${shot.id}">${thumbnail(shot.first)}<span><strong>${String(i+1).padStart(2,'0')} · ${esc(shot.title)}</strong><small>${esc(shot.visual || '待填写画面说明')}</small></span>${badge(sec(shot.seconds),shot.clip?'good':'')}</button>`).join('');
  return `<section class="hero">${cover?`<div class="hero-art" style="background-image:url('${media(cover)}')"></div>`:''}<div class="hero-text"><div class="kicker mono">LOCAL PRODUCTION STUDIO</div><h1>${esc(p.name)}</h1><p>${esc(p.brief || '从剧本到成片，在同一个工作台完成镜头制作。')}</p><div class="actions">${pageButton(p.shots.length?'打开分镜':'编写剧本',p.shots.length?'shots':'script','primary','arrow')}${recent?pageButton('预览成片','exports','quiet','play'):''}${badge(`${p.aspect} · ${sec(duration)}`)}</div></div></section>
    <div class="workflow">${steps.map(([page,label,detail],i)=>`<button class="step" data-page="${page}"><span class="step-n mono">0${i+1}</span><strong>${label}</strong><small>${detail}</small></button>`).join('')}</div>
    <div class="overview-grid">${panel('分镜一览',summary?`<div class="overview-list">${summary}</div>`:empty('还没有分镜','从剧本生成草案，或手动添加镜头。'),pageButton('全部分镜','shots','quiet small'))}
    ${panel('成片预览',recent?`<video class="overview-preview" controls preload="metadata" src="${media(recent.file)}" ${cover?`poster="${media(cover)}"`:''}></video><p class="muted" style="margin-top:9px">${esc(recent.name)}</p>`:empty('还没有成片','装配镜头后，成片会显示在这里。'),recent?badge('MP4','good'):'')}</div>`;
}

function scriptPage() {
  const p=state.project;
  const models=state.status.models.filter(name=>!/embed|bge|e5-large/i.test(name));
  const preferred=models.includes('qwen2.5:7b')?'qwen2.5:7b':models[0];
  const draft=p.draft;
  const pending=activeJobs().find(job=>job.kind==='draft');
  return title('01 / SCRIPT','剧本与拆镜','写下创意或粘贴已有剧本，用本地模型整理成可编辑分镜。')+
    (pending?`<div class="notice">${esc(pending.message)}　${pageButton('查看进度','jobs','quiet small')}</div>`:'')+
    `<div class="cols">${panel('创作输入',`<form id="draft-form"><fieldset ${locked()?'disabled':''}>
      ${field('项目名称',textInput('name',p.name,'required maxlength="100"'))}
      ${field('剧情构想',textarea('brief',p.brief,7,'例如：雨夜的便利店，一位顾客遇到来自未来的自己。'))}
      <div class="field-row triple">${field('目标镜头数',textInput('count','5','type="number" min="1" max="12" required'))}${field('目标时长（秒）',textInput('seconds','30','type="number" min="5" max="120" required'))}${field('本地编剧模型',`<select name="model" aria-label="本地编剧模型">${models.length?options(models.map(m=>[m,m]),preferred):'<option value="">未连接</option>'}</select>`)}</div>
      ${models.length?'':`<div class="notice warn">请启动本机 Ollama 并安装可用的文本模型。${button('刷新连接','status','quiet small')}</div>`}
      <div class="actions"><button class="button primary" type="submit" ${models.length?'':'disabled'}>生成剧本与分镜</button>${button('保存创意','save-script','quiet')}</div>
      </fieldset></form>`)}
      ${panel('剧本文本',`<label class="field"><span>可直接编辑或粘贴</span><textarea id="script-text" class="script-editor" placeholder="粘贴已有剧本后，可直接拆成分镜。" ${locked()?'disabled':''}>${esc(p.script)}</textarea></label><div class="actions">${button('保存剧本','save-script','quiet',locked()?'disabled':'')}${button('拆分已有剧本','split-script','primary',locked()||!models.length?'disabled':'')}</div>`)}
    </div>${draft?`<div style="margin-top:16px">${panel('待导入草案',`<h3>${esc(draft.title || '生成草案')}</h3><ol class="draft-list">${draft.shots.map(shot=>`<li>${esc(shot?.title || '镜头')} · ${esc(shot?.seconds || 4)} 秒<br>${esc(shot?.visual || '')}</li>`).join('')}</ol>${button(`导入 ${draft.shots.length} 个分镜`,'apply-draft','primary',locked()?'disabled':'')}`,badge('追加到时间线','run'))}</div>`:''}`;
}

function assetsPage() {
  const p=state.project;
  const cards=p.assets.map(asset=>`<article class="panel"><div class="asset-media">${asset.image?`<img src="${media(asset.image)}" alt="${esc(asset.name)}">`:'<span class="empty-icon">▧</span>'}</div><div class="panel-body"><div class="asset-name"><h3>${esc(asset.name)}</h3>${badge(kinds[asset.kind])}</div><p class="asset-desc">${esc(asset.prompt || '还没有参考图描述')}</p><div class="actions">${button('编辑素材','asset','small',`data-id="${asset.id}" ${locked()?'disabled':''}`)}${asset.prompt?button('复制提示词','copy-asset','quiet small',`data-id="${asset.id}"`):''}${asset.prompt&&!asset.image?button('生成草图','sketch-asset','primary small',`data-id="${asset.id}" ${locked()?'disabled':''}`):''}</div></div></article>`).join('');
  return title('02 / REFERENCES','角色与场景','为同一角色和场景保存统一的参考图、描述和配音声线。',button('添加素材','asset','primary',locked()?'disabled':'','plus'))+
    '<div class="notice">可以上传参考图，或用 H3 根据描述生成概念草图。草图来自短视频抽帧。需要固定人物造型时，可导入确认过的正式图。</div>'+
    (cards?`<div class="assets-grid">${cards}</div>`:empty('素材库为空','先添加角色或场景，再到分镜选择参考图。',button('添加第一项素材','asset','primary',locked()?'disabled':'')));
}

function shotBadge(shot) {
  const job=state.jobs.find(job=>job.project_id===state.project.id&&job.shot_id===shot.id);
  if(job && ['queued','running','failed'].includes(job.state)) return badge(states[job.state][0],states[job.state][1]);
  return shot.clip?badge('已出片','good'):shot.first?badge('待生成','run'):badge('待首帧','warn');
}

function refPicker(slot, caption, file) {
  const assets=state.project.assets.filter(asset=>asset.image).map(a=>[a.image,`${kinds[a.kind]} · ${a.name}`]);
  return `<div><span class="field-label">${caption}</span><div class="ref-frame" id="preview-${slot}">${file?`<img src="${media(file)}" alt="${caption}">`:(slot==='last'?'默认沿用首帧':'等待导入首帧')}</div>
    <input type="hidden" name="${slot}" value="${esc(file)}"><div class="ref-controls"><select data-pick="${slot}" aria-label="从素材库选择${caption}"><option value="">选素材…</option>${options(assets,file)}</select>${upload('上传',slot,'image/png,image/jpeg,image/webp')}</div>
    ${file?button('清除','clear-ref','quiet small',`data-slot="${slot}"`):''}</div>`;
}

function shotsPage() {
  const p=state.project;
  const shot=selectedShot();
  let elapsed=0;
  const header=title('03 / STORYBOARD','分镜制作','逐镜设置时长、动作、台词和首尾参考帧。',button('新增镜头','add-shot','quiet',locked()?'disabled':'','plus')+button('批量生成待出片镜头','batch','primary',locked()?'disabled':'','play'));
  if(!shot) return header+empty('时间线为空','手动新增镜头，或从剧本页导入自动拆好的分镜。',button('新增镜头','add-shot','primary',locked()?'disabled':'','plus'));
  const index=p.shots.indexOf(shot);
  state.shot=shot.id;
  const timeline=p.shots.map((s,i)=>{const start=elapsed;elapsed+=s.seconds;return `<button class="timecell ${s.id===shot.id?'current':''} ${s.clip?'ready':''}" style="flex-grow:${s.seconds}" data-action="pick-shot" data-id="${s.id}" title="${esc(s.title)}">${String(i+1).padStart(2,'0')}<br>${stamp(start)}</button>`}).join('');
  const list=p.shots.map((s,i)=>`<button class="shot-row ${s.id===shot.id?'current':''}" data-action="pick-shot" data-id="${s.id}">${thumbnail(s.first)}<span><strong>${String(i+1).padStart(2,'0')} · ${esc(s.title)}</strong><small>${sec(s.seconds)}　${s.clip?'已出片':s.first?'待生成':'待首帧'}</small></span></button>`).join('');
  const output=shot.clip?`<video controls preload="metadata" src="${media(shot.clip)}" ${shot.first?`poster="${media(shot.first)}"`:''}></video>`:shot.first?`<img src="${media(shot.first)}" alt="首帧预览">`:'<span class="muted">上传首帧或导入镜头视频</span>';
  const history=shot.versions.filter(file=>file!==shot.clip).slice().reverse();
  const status=activeJobs().find(job=>job.shot_id===shot.id);
  return header+(locked()?`<div class="notice">本项目正在处理任务。${status?' 当前镜头 · '+esc(status.message):''} ${pageButton('查看任务','jobs','quiet small')}</div>`:'')+
    `<div class="timebar" aria-label="镜头时间线">${timeline}</div><div class="editor-grid">
    <section class="panel shot-index"><div class="panel-head"><h2>镜头列表</h2>${badge(`${p.shots.length} 镜`)}</div><div class="shot-list">${list}</div></section>
    <section class="panel"><div class="shot-head"><div><div class="eyebrow mono">SHOT ${String(index+1).padStart(2,'0')}</div><h2>${esc(shot.title)}</h2></div><div class="actions">${shotBadge(shot)}${button('上移','move-shot','quiet small',`data-dir="up" ${locked()||index===0?'disabled':''}`)}${button('下移','move-shot','quiet small',`data-dir="down" ${locked()||index===p.shots.length-1?'disabled':''}`)}</div></div>
    <form id="shot-form"><fieldset ${locked()?'disabled':''}><div class="shot-layout"><div class="shot-settings">
      ${field('镜头名称',textInput('title',shot.title,'maxlength="100" required'))}
      <div class="field-row triple">${field('时长（秒）',textInput('seconds',Number(shot.seconds.toFixed(3)),'type="number" min="0.5" max="12" step="any" required'))}
      ${field('生成规格',`<select name="quality">${options([['quick','试拍 · 320 边'],['normal','标准 · 480 边'],['detail','细节 · 768 边']],shot.quality)}</select>`)}
      ${field('随机种子',textInput('seed',shot.seed ?? '', 'type="number" min="0" max="4294967295" step="1" placeholder="自动"'))}</div>
      ${field('画面与运镜',textarea('visual',shot.visual,2,'人物、动作、景别、光线与运镜'))}
      ${field('图生视频提示词',textarea('prompt',shot.prompt,4,'描述参考图里的角色如何运动，建议明确镜头和动作。'))}
      ${field('台词',textarea('dialogue',shot.dialogue,3,'角色：说的话，每句一行'))}
    </div><div class="preview-col"><div class="preview-card"><header><span>${shot.clip?'镜头视频':'画面预览'}</span>${badge(p.aspect)}</header><div class="video-frame">${output}</div><footer class="actions">${upload('导入视频','clip','video/*,.mkv')}${shot.clip?`<a class="button small quiet" href="${media(shot.clip)}?download=1" download>下载片段</a>${button('清除当前片段','clear-clip','quiet small')}`:''}</footer></div>
    ${history.length?`<select class="version-select" data-version aria-label="切换历史片段"><option value="">历史片段 (${history.length})</option>${options(history.map((file,i)=>[file,`切换到历史片段 ${i+1}`]),'')}</select>`:''}
    <div class="reference-grid">${refPicker('first','首帧',shot.first)}${refPicker('last','尾帧（可选）',shot.last)}</div>
    <div class="actions">${!shot.first?button('生成首帧草图','sketch-shot','quiet small'):''}${button('复制首帧提示词','copy-frame-prompt','quiet small')}</div>
    </div></div><div class="form-end">${button('移除镜头','remove-shot','danger small')}<div class="actions"><span id="save-indicator" class="muted">已保存</span><button class="button quiet" type="submit">保存修改</button>${button(shot.clip?'重新生成镜头':'生成这个镜头','generate-shot','primary','','play')}</div></div></fieldset></form></section></div>`;
}

function jobsPage() {
  const sorted=state.jobs;
  const table=sorted.map(job=>`<tr><td><strong>${esc(job.label)}</strong><small class="job-when">${esc(job.project_name)} · ${date(job.created)}</small></td><td>${badge(jobKinds[job.kind]||job.kind)}</td><td>${badge(...states[job.state])}<div class="progress ${job.state}"><i style="width:${Number(job.progress)||0}%"></i></div><small>${Number(job.progress)||0}%</small></td><td class="job-message">${esc(job.message)}</td><td><div class="job-controls">${job.state==='failed'?button('重试','retry','small',`data-id="${job.id}"`):''}${job.state==='queued'?button('取消','cancel-job','quiet small',`data-id="${job.id}"`):''}${job.file&&job.state==='done'?`<a href="${media(job.file,job.project_id)}" target="_blank" rel="noopener" class="button quiet small">打开结果</a>`:''}${job.kind==='draft'&&job.state==='done'?button('查看草案','view-draft','quiet small',`data-id="${job.project_id}"`):''}</div></td></tr>`).join('');
  return title('04 / GENERATION','生成队列','后台按顺序处理剧本、参考草图、视频和导出任务。关闭页面后，工作台仍可继续运行。')+
    (activeJobs().length?`<section class="panel wait-invite"><div><strong>模型在忙，你可以歇一会儿</strong><p class="muted">首次加载可能较久。任务会在后台继续，完成后会在等待室提示。</p></div><button class="button quiet" data-wait-open>进入星光等待室 ↗</button></section>`:'')+
    (table?`<section class="panel table-wrap"><table><thead><tr><th>任务</th><th>类型</th><th>进度</th><th>运行详情</th><th>操作</th></tr></thead><tbody>${table}</tbody></table></section>`:empty('队列为空','提交一个剧本、图生视频或成片导出任务后，这里会显示进度。'));
}

function exportsPage() {
  const p=state.project;
  const result=p.exports.find(item=>item.id===state.result)||p.exports.at(-1);
  const total=p.shots.reduce((sum,shot)=>sum+shot.seconds,0);
  const versions=[...p.exports].reverse().map(item=>`<button class="export-row ${item.id===result?.id?'current':''}" data-action="pick-result" data-id="${item.id}"><strong>${esc(item.name)}</strong><small>${date(item.created)} · MP4</small></button>`).join('');
  return title('05 / DELIVERY','成片与导出','按时间线拼接镜头，添加字幕和音轨，导出可分享的 MP4。',badge(`${p.aspect} · ${sec(total)}`,'run')+`<button type="button" class="button quiet" data-share="open">导出分享卡</button>` )+
    `<div class="cols">${panel('导出设置',`<form id="export-form"><fieldset ${locked()?'disabled':''}>
      ${field('成片名称',textInput('name',`${p.name} · 成片`,'maxlength="100"'))}<div class="field-row">
      ${field('导出分辨率',`<select name="size">${options([['720','720p'],['1080','1080p']],'720')}</select>`)}
      ${field('声音来源',`<select name="audio">${options([['track','项目音轨'],['tts','按台词合成配音'],['source','保留镜头原声'],['silent','静音']],p.track?'track':'source')}</select>`)}</div>
      ${field('默认配音声线',`<select name="voice">${options(Object.entries(state.status.voices),'local-zh-female')}</select>`,'本地中文声线使用 Windows 已安装的中文语音，可离线运行。标注“联网”的声线调用 Edge TTS。角色素材里的同名声线优先。')}
      <label class="checkbox"><input type="checkbox" name="subtitles" checked>烧录分镜台词字幕，同时保存 SRT</label>
      <div class="notice">有视频的镜头优先使用视频。只有首帧的镜头会按设定时长导出为定帧。</div>
      <div class="actions"><button class="button primary" type="submit" ${p.shots.length?'':'disabled'}>导出成片</button>${upload(p.track?'替换项目音轨':'上传项目音轨','track','audio/*,.m4a')}${p.track?badge('音轨已就绪','good'):''}</div>
      ${p.track?`<audio controls preload="none" src="${media(p.track)}"></audio>`:''}</fieldset></form>`)}
      ${panel('成片预览',result?`<video class="result-video" controls preload="metadata" src="${media(result.file)}"></video><div class="actions" style="margin:10px 0 13px"><a class="button primary" href="${media(result.file)}?download=1" download>${svg(icons.download)}下载 MP4</a>${result.subtitle?`<a class="button quiet" href="${media(result.subtitle)}?download=1" download>下载 SRT</a>`:''}</div><div class="export-list">${versions}</div>`:empty('还没有导出结果','任务完成后可以在此播放并下载。'))}</div>`;
}

function render() {
  chrome();
  const renderers={projects:projectList,overview,script:scriptPage,assets:assetsPage,shots:shotsPage,jobs:jobsPage,exports:exportsPage};
  content.innerHTML=(renderers[state.page]||projectList)();
  state.changed=false;
  window.JingliuGuide?.render();
}
function leaveEdits() { return !state.changed || window.confirm('当前修改尚未保存，继续切换页面？'); }
function go(page) {
  if(!leaveEdits()) return;
  state.page=page==='jobs'||state.project||page==='projects'?page:'projects';
  history.replaceState(null,'',state.page==='projects'?'/':`/#${state.page}`);
  render();window.scrollTo(0,0);
}
async function loadProjects() { state.projects=await api('/projects'); }
async function openProject(id,page='overview') {
  if(!leaveEdits()) return;
  state.project=await api(`/projects/${id}`);
  state.shot=null;state.result=null;state.changed=false;
  localStorage.setItem('jingliu.project',id);
  go(page);
}
async function refreshStatus() { state.status=await api('/status');chrome(); }
async function mutate(path,data,method='POST') {
  state.project=await api(projectPath(path),method,data);
  state.changed=false;
  return state.project;
}
async function refreshJobs() { state.jobs=await api('/jobs');window.JingliuWait?.updateJobs(state.jobs); }
async function queue(data) {
  await api(projectPath('/jobs'),'POST',data);
  await refreshJobs();
  state.changed=false;go('jobs');notify('已提交到本地队列');
}
function formValues(form) { return Object.fromEntries(new FormData(form)); }
async function saveShot(extra={}, rerender=true) {
  const form=$('#shot-form');
  if(!form.reportValidity()) return false;
  await mutate('/shots',{...formValues(form),id:selectedShot().id,...extra});
  if(rerender) {render();notify('镜头已保存');}
  return true;
}
async function saveScript() {
  const form=$('#draft-form');
  if(!form.reportValidity()) return false;
  const value=formValues(form);
  await mutate('',{name:value.name,brief:value.brief,script:$('#script-text').value},'PATCH');
  return true;
}
async function makeDraft(split=false) {
  const form=$('#draft-form');
  if(!form.reportValidity()) return;
  const settings=formValues(form);
  const source=(split?$('#script-text').value:settings.brief).trim();
  if(!source) throw new Error(split?'请先粘贴剧本文本。':'请先填写剧情构想。');
  if(!settings.model) throw new Error('请选择本地编剧模型。');
  if(await saveScript()) await queue({kind:'draft',model:settings.model,count:settings.count,seconds:settings.seconds,
    brief:split?`请忠实拆分以下已有剧本，保留情节和角色设定。\n${source}`:source});
}
function showDialog(body) { dialog.innerHTML=body;dialog.showModal(); }
function newDialog() {
  showDialog(`<form id="new-form"><h2>新建短剧项目</h2>${field('项目名称',textInput('name','','required maxlength="100" autofocus placeholder="为这一集起个名字"'))}${field('画幅',`<select name="aspect">${options([['9:16','9:16 · 竖屏短剧'],['16:9','16:9 · 横屏短片']],'9:16')}</select>`)}<div class="actions">${button('取消','close-dialog','quiet')}<button class="button primary" type="submit">创建项目</button></div></form>`);
}
function assetDialog(id) {
  const asset=state.project.assets.find(a=>a.id===id)||{name:'',kind:'character',prompt:'',voice:'',image:''};
  showDialog(`<form id="asset-form"><h2>${id?'编辑素材':'添加参考素材'}</h2><input type="hidden" name="id" value="${esc(id||'')}"><input type="hidden" name="image" value="${esc(asset.image)}">
    <div class="dialog-media"><div class="ref-frame" id="asset-upload-preview">${asset.image?`<img src="${media(asset.image)}" alt="参考图">`:'待上传参考图'}</div><div>${upload('上传参考图','asset','image/png,image/jpeg,image/webp')}<p class="subtle" style="margin-top:8px">支持 PNG、JPG、WebP</p></div></div>
    <div class="field-row">${field('名称',textInput('name',asset.name,'required maxlength="100"'))}${field('类型',`<select name="kind">${options(Object.entries(kinds),asset.kind)}</select>`)}</div>
    ${field('参考图提示词',textarea('prompt',asset.prompt,4,'描述外形、服装、场景与光线'))}
    ${field('配音声线',`<select name="voice">${options([['','使用导出默认声线'],...Object.entries(state.status.voices)],asset.voice)}</select>`,'仅对同名角色的 AI 配音生效。')}
    <div class="actions">${id?button('移除','remove-asset','danger small',`data-id="${id}"`):''}${button('取消','close-dialog','quiet')}<button class="button primary" type="submit">保存素材</button></div></form>`);
}

async function dispatch(buttonEl) {
  const {action,id,dir,slot,page}=buttonEl.dataset;
  if(page) {go(page);return;}
  switch(action) {
    case 'projects': go('projects');break;
    case 'open-project': await openProject(id);break;
    case 'new': newDialog();break;
    case 'close-dialog': dialog.close();break;
    case 'sample': {
      const project=await api('/sample','POST',{});await loadProjects();await openProject(project.id);notify('示例已导入');break;
    }
    case 'status': await refreshStatus();render();break;
    case 'save-script': if(await saveScript()){await loadProjects();render();notify('剧本已保存');}break;
    case 'split-script': await makeDraft(true);break;
    case 'apply-draft': await mutate('/apply-draft',{});await loadProjects();go('shots');notify('草案已加入时间线');break;
    case 'asset': assetDialog(id);break;
    case 'remove-asset': if(confirm('移除这条素材记录？已用于镜头的图片仍可播放。')){await mutate('/assets',{id,remove:true});dialog.close();render();}break;
    case 'copy-asset': {
      const asset=state.project.assets.find(a=>a.id===id);await navigator.clipboard.writeText(asset.prompt);notify('提示词已复制');break;
    }
    case 'sketch-asset': await queue({kind:'image',asset_id:id});break;
    case 'open-shot': state.shot=id;go('shots');break;
    case 'pick-shot': if(leaveEdits()){state.shot=id;render();}break;
    case 'add-shot': if(leaveEdits()){await mutate('/shots',{action:'add'});state.shot=state.project.shots.at(-1).id;render();}break;
    case 'move-shot': if(await saveShot({},false)){await mutate('/shots',{action:dir,id:selectedShot().id});render();}break;
    case 'remove-shot': if(confirm('将该镜头从当前时间线移除？')){await mutate('/shots',{action:'remove',id:selectedShot().id});state.shot=null;render();}break;
    case 'clear-ref': await saveShot({[slot]:''});break;
    case 'clear-clip': if(confirm('清除当前片段并保留在历史片段中？')) await saveShot({clip:''});break;
    case 'generate-shot': if(await saveShot({},false)) await queue({kind:'video',shot_id:selectedShot().id});break;
    case 'sketch-shot': if(await saveShot({},false)) await queue({kind:'image',shot_id:selectedShot().id});break;
    case 'copy-frame-prompt': {
      const shot=formValues($('#shot-form'));
      const references=state.project.assets.filter(a=>a.prompt).slice(0,12).map(a=>`${kinds[a.kind]} ${a.name}：${a.prompt}`);
      const prompt=[`制作一张 ${state.project.aspect} 的短剧分镜首帧。`, `镜头：${shot.title}`, shot.visual || shot.prompt,
        references.length?'项目设定如下，只采用本镜需要的人物与场景。':'', ...references].filter(Boolean).join('\n');
      await navigator.clipboard.writeText(prompt);notify('首帧提示词已复制');break;
    }
    case 'batch': if(!state.changed||await saveShot({},false)) await queue({kind:'video'});break;
    case 'cancel-job': case 'retry': await api(`/jobs/${id}/${action==='retry'?'retry':'cancel'}`,'POST',{});await refreshJobs();render();break;
    case 'view-draft': await openProject(id,'script');break;
    case 'pick-result': state.result=id;render();break;
  }
}

async function runAction(element, task) {
  if(state.busy) return;
  state.busy=true;
  const wasDisabled=element?.disabled;
  if(element && 'disabled' in element) element.disabled=true;
  try { await task(); } catch(error) { notify(error.message||String(error),true); }
  finally { state.busy=false;if(element && 'disabled' in element) element.disabled=wasDisabled; }
}

document.addEventListener('click',event=>{
  const element=event.target.closest('button[data-action],button[data-page]');
  if(element&&!element.disabled) runAction(element,()=>dispatch(element));
});
document.addEventListener('submit',event=>{
  event.preventDefault();const form=event.target;
  runAction(event.submitter,async()=>{
    if(form.id==='new-form') {
      const p=await api('/projects','POST',formValues(form));dialog.close();await loadProjects();await openProject(p.id,'script');
    } else if(form.id==='asset-form') {
      await mutate('/assets',formValues(form));dialog.close();render();notify('素材已保存');
    } else if(form.id==='draft-form') await makeDraft();
    else if(form.id==='shot-form') await saveShot();
    else if(form.id==='export-form') await queue({kind:'export',...formValues(form),subtitles:form.elements.subtitles.checked});
  });
});
document.addEventListener('input',event=>{
  if(event.target.closest('#shot-form,#draft-form')||event.target.id==='script-text') {
    if(event.target.type==='file') return;
    state.changed=true;
    const indicator=$('#save-indicator');if(indicator) indicator.textContent='有未保存修改';
  }
});
document.addEventListener('change',event=>{
  const element=event.target;
  if(element.id==='project-select') { runAction(element,()=>element.value?openProject(element.value):go('projects'));return; }
  if(element.dataset.pick && element.value) { runAction(element,()=>saveShot({[element.dataset.pick]:element.value}));return; }
  if(element.hasAttribute('data-version')&&element.value) {runAction(element,()=>saveShot({clip:element.value}));return;}
  const slot=element.dataset.upload;
  if(!slot||!element.files?.[0]) return;
  runAction(element,async()=>{
    const file=element.files[0];const data=new FormData();data.set('file',file);
    notify('正在导入素材…');
    const uploaded=await api(projectPath('/upload'),'POST',data);
    if(slot==='asset') {
      $('#asset-form').elements.image.value=uploaded.file;
      $('#asset-upload-preview').innerHTML=`<img src="${media(uploaded.file)}" alt="已上传的参考图">`;
      notify('已导入图片，请保存素材');
    } else if(slot==='track') {
      await mutate('',{track:uploaded.file},'PATCH');render();notify('项目音轨已保存');
    } else await saveShot({[slot]:uploaded.file});
  });
});

async function poll() {
  if(polling||state.busy||document.hidden) return;
  polling=true;
  try {
    const previous=JSON.stringify(state.jobs);
    const wasActive=activeJobs().length>0;
    await refreshJobs();
    if(previous===JSON.stringify(state.jobs)) return;
    const active=activeJobs().length>0;
    if(wasActive&&!active&&state.project) {
      state.project=await api(projectPath());await loadProjects();await refreshStatus();
      if(!state.changed&&!dialog.open) render();
    } else if(state.page==='jobs'&&!dialog.open) render();
    else chrome();
  } catch(error) {
    $('#engine-status').textContent='等待工作台重新连接';
  } finally {polling=false;}
}

async function init() {
  try {
    await Promise.all([loadProjects(),refreshJobs()]);
    const remembered=localStorage.getItem('jingliu.project');
    const project=state.projects.find(p=>p.id===remembered)||state.projects[0];
    const route=location.hash.slice(1);
    if(project) await openProject(project.id,pages.some(([key])=>key===route)?route:'overview');
    else go(route==='jobs'?'jobs':'projects');
    performance.mark('jingliu:ready');
    // Service probes can time out while engines are stopped. Keep editing usable.
    refreshStatus().then(()=>{if(!state.changed&&!dialog.open)render();}).catch(()=>{});
    setInterval(poll,2500);
    setInterval(()=>{if(!document.hidden)refreshStatus().catch(()=>{});},20000);
  } catch(error) {content.innerHTML=empty('无法连接工作台',error.message);}
}

init();
