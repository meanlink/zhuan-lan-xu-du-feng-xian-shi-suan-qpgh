import {CaseStatus} from '../../constants/enums.js';
import {esc,date} from '../../utils/dom.js';

const FILTERS=[['','全部案件'],['reviewing','待核标'],['adjudicating','待裁定'],['sealing','封案中'],['sealed','已完成']];

export function caseFilters(active){
 return '<div class="review-filters">'+FILTERS.map(([key,label])=>
   `<a href="#/review${key?('?status='+key):''}" class="filter-chip ${active===key?'active':''}">${esc(label)}</a>`
 ).join('')+'</div>';
}

export function statusPill(status){
 const map=CaseStatus;
 return '<span class="case-status s-'+esc(status)+'">'+esc(map[status]||status)+'</span>';
}

export function assignmentState(a){
 const map={pending:'待领取',submitted:'已交卷',returned:'已交回'};
 return '<span class="assign-state st-'+esc(a.status)+'">'+esc(map[a.status]||a.status)+'</span>';
}

export function caseRow(c){
 return `<article class="case-card" data-case-id="${c.id}">
  <div class="case-card-head">${statusPill(c.status)}<small>#${c.id} · ${date(c.created_at)}</small></div>
  <h3>${esc(c.name)}</h3>
  <p class="case-meta">固定样本 <strong>${c.sample_count}</strong> 条 · 分歧 <strong>${c.disagreement_count}</strong> 条${c.my_slot?(' · 我的角色 <strong>'+esc({review_a:'核标员 A',review_b:'核标员 B',adjudication:'裁定人'}[c.my_slot])+'</strong>'):''}</p>
  <div class="case-people">
    <span>核标 A：${esc(c.reviewer_a.name)}</span>
    <span>核标 B：${esc(c.reviewer_b.name)}</span>
    <span>裁定：${esc(c.adjudicator.name)}</span>
  </div>
  <a class="button small" href="#/review/${c.id}">打开案件 ↗</a>
 </article>`;
}
