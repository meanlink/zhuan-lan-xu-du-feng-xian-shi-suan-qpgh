import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const review={
 users:()=>api('/review/users'),
 cases:(status='')=>api('/review/cases'+(status?('?status='+status):'')),
 case:id=>api('/review/cases/'+id),
 readiness:id=>api('/review/cases/'+id+'/readiness'),
 createCase:data=>api('/review/cases',{method:'POST',body:JSON.stringify(data)}),
 seal:id=>api('/review/cases/'+id+'/seal',{method:'POST'}),
 claim:(id,expected_seq=0)=>api('/review/assignments/'+id+'/claim',{method:'POST',body:JSON.stringify({expected_seq})}),
 submit:(id,payload)=>api('/review/assignments/'+id+'/submit',{method:'POST',body:JSON.stringify(payload)}),
 return:(id,reason='')=>api('/review/assignments/'+id+'/return',{method:'POST',body:JSON.stringify({reason})}),
 reassign:(id,user_id,reason='')=>api('/review/assignments/'+id+'/reassign',{method:'POST',body:JSON.stringify({user_id,reason})}),
 batches:()=>api('/review/batches'),
 batch:id=>api('/review/batches/'+id),
};
