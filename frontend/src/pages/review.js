import {review,datasets} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {caseFilters,caseRow,statusPill,assignmentState} from '../components/review/case-list.js';
import {decisionTable,assignmentPanel,readinessPanel,basisBadge} from '../components/review/assignment.js';
import {SlotName} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

function currentFilter(){
 return new URLSearchParams(location.hash.split('?')[1]||'').get('status')||'';
}
function caseIdFromHash(){
 const seg=location.hash.replace(/^#\//,'').split('/')[1]||'';
 return seg.split('?')[0]||undefined;
}

// ---------- 列表页 ----------
export async function reviewPage(id){
 if(id)return caseWorkspace(id);
 const filter=currentFilter();
 // 仅 admin/analyst 可设案（can_write）；reviewer 只能处理分派任务，不请求人员清单
 const canCreate=['admin','analyst'].includes(session.user.role);
 const [cases,dsList,users]=await Promise.all([
   review.cases(filter),
   datasets.list(),
   canCreate?review.users():Promise.resolve([]),
 ]);
 const createForm=canCreate?`
 <section class="panel">
   <div class="section-title"><h2>设立双盲核标案</h2><span>固定样本 · 指定两核标员与裁定人</span></div>
   <form id="case-form">
     <label>核标案名称<input name="name" required minlength="2" placeholder="例如：续读标签双盲核标 · 11月第2批"></label>
     <label>固定样本来源<select name="dataset_id" required>${dsList.map(d=>`<option value="${d.id}">${esc(d.name)} · ${d.rows} 条</option>`).join('')}</select></label>
     <label>固定样本上限<input type="number" name="sample_limit" value="40" min="1" max="500"></label>
     <div class="parameter-grid">
       <label>核标员 A<select name="reviewer_a_id" required>${userOptions(users)}</select></label>
       <label>核标员 B<select name="reviewer_b_id" required>${userOptions(users)}</select></label>
       <label>第三人裁定<select name="adjudicator_id" required>${userOptions(users)}</select></label>
     </div>
     <p class="hint">填报人（${esc(session.user.name)}）不能担任本案任何核标或裁定角色；两名核标员互不可见对方意见。</p>
     <button type="submit" class="primary">设立核标案 ↗</button>
   </form>
 </section>`:'';
 return heading('05 / BLIND REVIEW','双盲核标与训练批次','固定样本由两名核标员独立判定、互不可见；分歧交第三人裁定；全部定案后封案生成训练批次，缺裁定不开放试算。')
 + caseFilters(currentFilter())
 + `<div class="review-layout">
     <section class="panel"><div class="section-title"><h2>核标案</h2><span>${cases.length} 件</span></div>
       <div class="case-grid">${cases.length?cases.map(caseRow).join(''):'<div class="empty">当前筛选下暂无案件。</div>'}</div>
     </section>${createForm}
   </div>`;
}

function userOptions(users){
 return users.filter(u=>u.role!=='viewer').map(u=>`<option value="${u.id}">${esc(u.name)}（${esc(u.role)}）</option>`).join('');
}

// ---------- 案件工作区 ----------
async function caseWorkspace(id){
 const c=await review.case(id);
 const readiness=await review.readiness(id);
 const myAssignment=c.assignments.find(a=>a.mine)||null;
 const isAdmin=session.user.role==='admin';
 const assignmentList=c.assignments.map(a=>`
   <article class="assign-row ${a.mine?'mine':''}">
     <div><strong>${esc(SlotName[a.slot]||a.slot)}</strong><span>${esc(a.assignee?a.assignee.name:'—')}</span></div>
     ${assignmentState(a)}
     <small>序号 ${a.claimed_seq}${a.submitted_at?(' · 交卷 '+date(a.submitted_at)):''}</small>
   </article>`).join('');
 const table=myAssignment?decisionTable(c,myAssignment):
   `<div class="empty">你未被分派本案任务。${isAdmin?'可在下方查看进度并执行封案。':'双盲规则下仅展示与你相关的判定列。'}</div>`;
 const noAdjWork=myAssignment&&myAssignment.kind==='adjudication'&&c.disagreement_count===0;
 const submitBar=myAssignment&&myAssignment.status==='pending'&&c.status!=='sealed'&&!noAdjWork?`
   <div class="submit-bar">
     <button class="primary" data-act="submit" data-id="${myAssignment.id}" data-seq="${myAssignment.claimed_seq}">交卷（不可见对席意见）↗</button>
     <span class="hint">交卷前请确认逐条判定完整；交卷后意见保留，更正须先交回。</span>
   </div>`:'';
 const sealSection=isAdmin?`
   <section class="panel">
     ${readinessPanel(readiness)}
     <div class="action-row">
       <button class="primary" data-act="seal" data-id="${c.id}" ${readiness.ready?'':'disabled'}>封案并生成训练批次 ↗</button>
       <a class="button" href="#/review/batches">查看训练批次与采用依据</a>
     </div>
   </section>`:`
   <section class="panel">${readinessPanel(readiness)}</section>`;
 return heading('05 / BLIND REVIEW',c.name,'双盲独立判定，分歧由第三人裁定；封案后定案不可改。',
   `<a class="button" href="#/review">返回列表 ↖</a>`)
 + `<section class="panel case-summary">
     <div class="section-title">${statusPill(c.status)}<h2 style="margin:0">案件进度</h2><span>样本 ${c.sample_count} · 分歧 ${c.disagreement_count}</span></div>
     <div class="case-people"><span>填报：${esc(c.created_by.name)}</span><span>核标 A：${esc(c.reviewer_a.name)}</span><span>核标 B：${esc(c.reviewer_b.name)}</span><span>裁定：${esc(c.adjudicator.name)}</span></div>
     <div class="assign-list">${assignmentList}</div>
   </section>
   ${assignmentPanel(c,myAssignment,session.user.role)}
   <section class="panel"><div class="section-title"><h2>${myAssignment?(myAssignment.kind==='adjudication'?'分歧样本裁定':'逐条判定'):'案件样本（双盲视角）'}</h2><span>${c.sample_count} 条固定样本</span></div>${table}${submitBar}</section>
   ${sealSection}`;
}

// ---------- 训练批次（采用依据）----------
export async function reviewBatches(){
 const list=await review.batches();
 if(!list.length)return heading('05 / BATCHES','训练批次','封案后在此生成；缺裁定的案件不会开放试算，也不会产生批次。')+'<div class="empty">尚无已封案批次。</div>';
 const first=await review.batch(list[0].id);
 const cards=list.map(b=>`<button class="batch-item ${b.id===first.id?'active':''}" data-batch="${b.id}"><strong>${esc(b.name)}</strong><span>${b.record_count} 条 · ${date(b.created_at)}</span><small>SHA256 ${esc(b.checksum.slice(0,20))}…</small></button>`).join('');
 const rows=first.records.map(r=>`<tr><td>${esc(r.sample_key)}</td><td>${esc(r.final_label)}</td><td>${basisBadge(r.basis)}</td><td>意见 #${r.source_opinion_id}</td></tr>`).join('');
 return heading('05 / BATCHES','训练批次与采用依据','每条定案记录标明最终标签来源：核标一致采用核标意见，分歧采用第三人裁定。',
   `<a class="button" href="#/review">返回核标案 ↖</a>`)
 + `<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>批次</h2><span>${list.length} 个</span></div><div class="batch-list">${cards}</div>
   <div class="action-row"><a class="button" href="/api/review/batches/${first.id}/download?format=csv" onclick="return authLink(this)">下载 CSV</a><a class="button" href="/api/review/batches/${first.id}/download?format=json" onclick="return authLink(this)">下载 JSON</a></div></section>
   <section class="panel"><div class="section-title"><h2 id="batch-name">${esc(first.name)}</h2><span>${first.records.length} 条定案</span></div>
   <div class="table-wrap"><table><thead><tr><th>匿名读者</th><th>最终标签</th><th>采用依据</th><th>来源意见</th></tr></thead><tbody id="batch-rows">${rows}</tbody></table></div></section></div>`;
}

// 带 JWT 的文件下载
window.authLink=function(anchor){
 const token=session.token;fetch(anchor.href,{headers:{Authorization:'Bearer '+token}}).then(r=>r.blob()).then(blob=>{
   const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=anchor.href.split('/').pop().split('?')[0];a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);});
 return false;
};

// ---------- 事件绑定 ----------
export function bindReview(refresh){
 const cid=caseIdFromHash();
 const form=document.querySelector('#case-form');
 if(form)submit(form,async f=>{
   const payload={name:f.get('name'),dataset_id:Number(f.get('dataset_id')),sample_limit:Number(f.get('sample_limit')),
     reviewer_a_id:Number(f.get('reviewer_a_id')),reviewer_b_id:Number(f.get('reviewer_b_id')),adjudicator_id:Number(f.get('adjudicator_id'))};
   const c=await review.createCase(payload);notify('核标案已设立，任务已分派');location.hash='#/review/'+c.id;
 });
 document.querySelectorAll('[data-act]').forEach(btn=>{
   btn.onclick=async()=>{
     const act=btn.dataset.act,aid=btn.dataset.id;
     try{
       if(act==='claim'){await review.claim(aid,Number(btn.dataset.seq||0));notify('已领取，可开始逐条判定');}
       else if(act==='submit'){
         const decisions=collectDecisions();
         await review.submit(aid,{expected_seq:Number(btn.dataset.seq),decisions});
         notify('交卷成功，意见已保留');
       }
       else if(act==='return'){const reason=prompt('交回原因（可选）：','')??'';await review.return(aid,reason);notify('任务已交回，已交意见保留');}
       else if(act==='reassign'){const users=await review.users();const list=users.filter(u=>u.role!=='viewer').map(u=>`${u.id}: ${u.name}（${u.role}）`).join('\n');const pick=prompt('改派给哪位核标员？输入用户 ID：\n'+list);if(!pick)return;const reason=prompt('改派原因（可选）：','')??'';await review.reassign(aid,Number(pick),reason);notify('已改派并重置为待领取');}
       else if(act==='seal'){await review.seal(aid);notify('封案完成，训练批次已生成');location.hash='#/review/batches';return;}
       await refresh();
     }catch(e){notify(e.message,true);}
   };
 });
 document.querySelectorAll('[data-batch]').forEach(btn=>{
   btn.onclick=async()=>{try{const b=await review.batch(btn.dataset.batch);renderBatch(b);}catch(e){notify(e.message,true);}};
 });
}

function renderBatch(b){
 document.querySelector('#batch-name').textContent=b.name;
 document.querySelector('#batch-rows').innerHTML=b.records.map(r=>`<tr><td>${esc(r.sample_key)}</td><td>${esc(r.final_label)}</td><td>${basisBadge(r.basis)}</td><td>意见 #${r.source_opinion_id}</td></tr>`).join('');
 document.querySelectorAll('.batch-item').forEach(x=>x.classList.toggle('active',x.dataset.batch==String(b.id)));
}

function collectDecisions(){
 const decisions={};
 document.querySelectorAll('tr[data-sample]').forEach(tr=>{
   const key=tr.dataset.sample;
   const checked=tr.querySelector('input[type=radio]:checked');
   const note=tr.querySelector('.note-input')?.value||'';
   if(checked)decisions[key]={label:Number(checked.value),note};
 });
 return decisions;
}
