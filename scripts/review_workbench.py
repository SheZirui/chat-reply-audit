"""Build an offline review form. No server, external resources, or API calls."""
import base64
import json
from pathlib import Path

from audit_core import ensure_new_output, review_template, validate_reviews


def select_cases(packet, event_ids=None):
    if event_ids is None:
        return packet
    if not event_ids or len(set(event_ids)) != len(event_ids):
        raise ValueError('候选编号必须非空且不能重复')
    known = {c['event']['event_id'] for c in packet['cases']}
    if not set(event_ids) <= known:
        raise ValueError('所选编号不是本次统计中的长间隔候选')
    return {**packet, 'scope': 'Explicitly selected timestamp-screened candidates only.',
            'cases': [c for c in packet['cases'] if c['event']['event_id'] in event_ids]}


def write_workbench(out, packet, reviews=None):
    annotations = review_template(packet) if reviews is None else reviews
    validated, source = validate_reviews(packet, annotations, allow_partial=True)
    payload = {'packet': packet, 'annotations': {'analysis_id': packet['analysis_id'],
               'review_source': source, 'reviews': validated}}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    page = PAGE.replace('__PAYLOAD__', encoded)
    dest = ensure_new_output(out)
    (dest/'index.html').write_text(page, encoding='utf-8', newline='\n')


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>本地上下文复核工作台</title><style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;max-width:1050px;margin:30px auto;padding:0 18px;background:#f4f7f7;color:#183b40;line-height:1.6}
article,header{background:white;border-radius:14px;padding:22px;margin:18px 0}h1{font-size:26px}h2{font-size:20px}button,select,input,textarea{font:inherit}button{background:#196a60;color:white;border:0;padding:10px 16px;border-radius:7px;cursor:pointer}
textarea{box-sizing:border-box;width:100%;min-height:85px}select{max-width:100%;padding:6px}label{display:block;margin:10px 0}blockquote{margin:8px 0;padding:10px 14px;border-left:3px solid #81b7a8;background:#f0f6f4;white-space:pre-wrap;overflow-wrap:anywhere}small,.note{color:#567277}.notice{background:#fff3ce;padding:12px;border-radius:7px}.evidence{display:inline;margin-right:10px}nav{display:flex;gap:12px;flex-wrap:wrap;align-items:center}a{color:#126252}
</style></head><body><header><h1>本地上下文复核工作台</h1>
<p>此文件内嵌所选聊天正文。页面不调用网络或模型；请在你信任的本机浏览器中打开，不要分享此 HTML。</p>
<p class="notice">勾选证据、选择分类、填写理由，再下载结果 JSON。页面不自动保存，也不写回原文件；关闭或刷新前先下载。最终请运行 apply-review 校验并生成报告。</p>
<p id="source"></p><nav><button id="save" type="button">下载 reviews.json</button><span id="progress"></span></nav>
<p class="note">原始模型建议会保留 model_suggestion 来源，编辑表单不会自动变成人工确认。下载可能进入浏览器的“下载”目录，也需要私密保存。</p></header><main id="cases"></main>
<script>
"use strict";
const data=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob('__PAYLOAD__'),c=>c.charCodeAt(0))));
const packet=data.packet, annotations=data.annotations;
const statuses={unreviewed:'尚未审阅',retained:'保留：校准后仍超过阈值',restart:'新话题：校准后未超过阈值',closed:'旧事项已收尾',agreed_deferral:'明确约定延后',uncertain:'证据不足'};
const contexts={insufficient:'证据不足',explained:'原文明确说明原因',possible_context:'只有可能的线索',no_explanation_visible:'当前片段未见解释',not_applicable:'不适用'};
function element(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.appendChild(e);return e;}
function select(label,options,value,parent,onchange){const l=element('label',label+' ',parent),s=element('select',undefined,l);for(const [key,text]of Object.entries(options)){const o=element('option',text,s);o.value=key;}s.value=value??'';s.addEventListener('change',()=>{onchange(s.value);progress();});return s;}
function field(label,value,parent,oninput){const l=element('label',label,parent),a=element('textarea',undefined,l);a.value=value||'';a.addEventListener('input',()=>oninput(a.value));return a;}
function progress(){document.getElementById('progress').textContent=`已填写分类 ${annotations.reviews.filter(r=>r.status!=='unreviewed').length} / ${packet.cases.length}；不等于已通过校验`;}
document.getElementById('source').textContent=`来源：${annotations.review_source}；筛选阈值：严格超过 ${packet.candidate_minutes} 分钟。`;
const byId=new Map(annotations.reviews.map(r=>[r.event_id,r]));
for(const c of packet.cases){const e=c.event,r=byId.get(e.event_id),a=element('article',undefined,document.getElementById('cases'));element('h2',`${e.event_id} · 等 ${e.reply_sender} 回复`,a);element('p',`原首条间隔 ${(e.first_seconds/3600).toFixed(2)} 小时；下一方发言 ${e.reply_time}`,a);
 select('判断分类',statuses,r.status,a,v=>r.status=v);
 const starts={'':'此分类不设置起点'};for(const m of c.context.waiting)starts[m.ref]=`${m.ref} · ${m.time} · ${m.sender}`;
 select('校准起点（仅 retained / restart 使用）',starts,r.revised_start_ref||'',a,v=>r.revised_start_ref=v||null);
 select('解释状态',contexts,r.context_status,a,v=>r.context_status=v);
 field('判断理由：哪些原文支持分类？',r.reason,a,v=>r.reason=v);
 field('背景说明：为何延后？事实和推测分开写。',r.context_assessment,a,v=>r.context_assessment=v);
 const details=element('details',undefined,a);details.open=true;element('summary','展开/收起原文，勾选实际证据',details);
 for(const [name,messages]of Object.entries(c.context)){element('h3',({before:'前文',waiting:'本段连续发言',after:'后文（首条为下一方首次发言）'})[name]||name,details);
 for(const m of messages){const box=element('blockquote',undefined,details),l=element('label',undefined,box),input=element('input',undefined,l);input.type='checkbox';input.checked=r.basis_refs.includes(m.ref);input.addEventListener('change',()=>{r.basis_refs=input.checked?[...new Set([...r.basis_refs,m.ref])]:r.basis_refs.filter(x=>x!==m.ref);});element('span',` 作为证据 ${m.ref} · ${m.time} · ${m.sender}`,l);element('div',m.text,box);if(m.truncated)element('strong','[已截断：扩大上下文后再定性，或保留不确定]',box);}}
}
document.getElementById('save').addEventListener('click',()=>{const reviews=annotations.reviews.map(r=>({event_id:r.event_id,status:r.status,revised_start_ref:r.revised_start_ref,basis_refs:r.basis_refs,reason:r.reason,context_assessment:r.context_assessment,context_status:r.context_status}));const blob=new Blob([JSON.stringify({...annotations,reviews},null,2)+'\n'],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=element('a');a.href=url;a.download='reviews.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});progress();
</script></body></html>'''
