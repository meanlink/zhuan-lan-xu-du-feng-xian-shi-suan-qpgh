import {esc,date} from '../../utils/dom.js';
import {SlotName,AssignmentStatus,BasisName} from '../../constants/enums.js';

// 逐条判定表：核标员只看自己列；裁定人在分歧态看到双方列并仅对分歧行裁定
export function decisionTable(caseDetail, assignment){
 const samples=caseDetail.samples||[];
 const isAdj=assignment&&assignment.kind==='adjudication';
 const showBoth=isAdj; // 仅裁定人视角出现双方列，核标员只见自己列（双盲）
 const head=['<th>匿名读者</th>','<th>原始 renewed</th>'];
 if(showBoth){head.push('<th>核标 A</th>','<th>核标 B</th>','<th>分歧</th>');}
 head.push('<th>'+(isAdj?'裁定标签':'我的判定')+'</th>','<th>备注</th>');
 const rows=samples.map(s=>{
   const key=esc(s.reader_id);
   const cells=[`<td>${key}</td>`,`<td>${esc(s.renewed)}</td>`];
   if(showBoth){
     cells.push(`<td>${s.label_a??'—'}</td>`,`<td>${s.label_b??'—'}</td>`,
       `<td>${s.disagree?'<span class="flag">分歧</span>':'一致'}</td>`);
   }
   const myVal=isAdj?s.label_adj:(caseDetail.my_slot==='review_a'?s.label_a:(caseDetail.my_slot==='review_b'?s.label_b:undefined));
   const disabled=assignment&&assignment.status==='submitted'?'disabled':'';
   const rowDisabled=isAdj&&!s.disagree?'disabled':'';
   cells.push(`<td><label class="label-pick">
      <input type="radio" name="lbl-${key}" value="1" ${String(myVal)==='1'?'checked':''} ${disabled} ${rowDisabled}><span>1 未续读</span>
      <input type="radio" name="lbl-${key}" value="0" ${String(myVal)==='0'?'checked':''} ${disabled} ${rowDisabled}><span>0 续读</span>
    </label></td>`);
   cells.push(`<td><input class="note-input" data-note="${key}" value="${esc(isAdj?(s.note_adj||''):(caseDetail.my_slot==='review_a'?s.note_a:(s.note_b||'')))}" ${disabled} ${rowDisabled} placeholder="可选"></td>`);
   return `<tr data-sample="${key}" ${isAdj&&!s.disagree?'class="muted-row"':''}>${cells.join('')}</tr>`;
 }).join('');
 return `<div class="table-wrap review-table"><table><thead><tr>${head.join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function assignmentPanel(caseDetail, assignment, role){
 if(!assignment)return '<div class="empty">本案没有分派给你的任务。</div>';
 const a=assignment;
 const isAdmin=role==='admin';
 const seq=a.claimed_seq;
 let actions='';
 if(caseDetail.status==='sealed'){
   actions='<p class="warning">案件已封案，任务冻结，不能再交卷或交回。</p>';
 }else if(a.status==='pending'){
   actions=`<button class="primary" data-act="claim" data-id="${a.id}" data-seq="${seq}">领取任务 ↗</button>
            <p class="hint">领取后产生领取凭据；交回或重派会使旧凭据失效，迟交将被拒绝。</p>`;
 }else if(a.status==='submitted'){
   actions=`<p class="hint">已于 ${date(a.submitted_at)} 交卷，意见已保留。需要更正时请先交回任务。</p>
            <button data-act="return" data-id="${a.id}" ${caseDetail.status==='sealed'?'disabled':''}>交回任务（意见保留）</button>`;
 }else if(a.status==='returned'){
   actions=`<p class="warning">任务已交回，等待负责人重新分派；旧领取的交卷会被拒绝。</p>`;
 }
 const adminReassign=isAdmin&&a.kind==='review'&&a.status!=='submitted'?`<button data-act="reassign" data-id="${a.id}">负责人改派</button>`:'';
 return `<section class="panel assignment-panel">
   <div class="section-title"><h2>${esc(SlotName[a.slot]||a.slot)} · ${esc(AssignmentStatus[a.status]||a.status)}</h2><span>领取序号 ${seq}</span></div>
   <p class="case-meta">承办：${esc(a.assignee?a.assignee.name:'—')}${a.claimed_at?(' · 领取于 '+date(a.claimed_at)):''}</p>
   <div class="action-row">${actions}${adminReassign}</div>
 </section>`;
}

export function readinessPanel(readiness){
 const items=readiness.blockers.length
   ? readiness.blockers.map(b=>`<li>${esc(b)}</li>`).join('')
   : '<li>全部读者已定案，可封案生成训练批次。</li>';
 return `<section class="panel readiness-panel ${readiness.ready?'ready':''}">
   <div class="section-title"><h2>封案条件</h2><span>${readiness.ready?'可封案':'未就绪'}</span></div>
   <ul class="questions">${items}</ul>
   <p class="hint">核标缺交 ${readiness.missing_review_slots.length} 项 · 分歧 ${readiness.disagreement_count} 条 · 裁定状态 ${esc(AssignmentStatus[readiness.adjudication_status]||readiness.adjudication_status)}</p>
 </section>`;
}

export function basisBadge(basis){
 return '<span class="basis-badge b-'+esc(basis)+'">'+esc(BasisName[basis]||basis)+'</span>';
}
