/* Synthetic-only candidate. Answers are acknowledged only after a server commit. */
'use strict';
const pendingResponses = new Map();
let responseBusy = false;
let persistenceReady = false;
async function persistResponse(path, data) {
  if (!persistenceReady) throw new Error('Η ανάκτηση δεν ολοκληρώθηκε. Ανανέωσε τη σελίδα.');
  if (responseBusy) throw new Error('Περίμενε να ολοκληρωθεί η αποστολή.');
  const old = pendingResponses.get(path);
  if (old && JSON.stringify(old.data) !== JSON.stringify(data))
    throw new Error('Υπάρχει εκκρεμής υποβολή. Πάτησε πρώτα «Επανάληψη εκκρεμών».');
  const pending = old || {data, body:{record_id:crypto.randomUUID(), ...data}};
  pendingResponses.set(path,pending);
  responseBusy = true;
  try {
    const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',
      'X-Study-Participant':studyParticipant},body:JSON.stringify(pending.body)});
    if (!response.ok) throw new Error('Δεν επιβεβαιώθηκε αποθήκευση ('+response.status+'). Κράτησε ανοικτή τη σελίδα και δοκίμασε ξανά.');
    const receipt=await response.json();
    pendingResponses.delete(path);
    return receipt;
  } finally { responseBusy=false; }
}
window.persistCheckin = async function(day,values) {
  return persistResponse('/api/checkins',{assessment_date:day,values});
};
window.addEventListener('beforeunload',event=>{
  if(pendingResponses.size){event.preventDefault();event.returnValue='';}
});
const persistencePanel=document.createElement('section');persistencePanel.className='card';
persistencePanel.innerHTML='<h2>Μόνιμη καταγραφή — συνθετική δοκιμή</h2><p>Οι επιβεβαιωμένες απαντήσεις αποθηκεύονται στην τοπική ερευνητική βάση. Δεν είναι εγκατάσταση πραγματικής μελέτης.</p><button type="button" id="response-retry">Επανάληψη εκκρεμών</button><p id="response-status" role="status">Ανάκτηση καταγραφών…</p><h2>BAT-23</h2><p>Πρωτότυπο με την ελληνική μορφή της επίδειξης. Η τελική έγκριση της χορήγησης εκκρεμεί. Μπορείς να παραλείψεις ερωτήσεις· ελλιπείς κλίμακες δεν βαθμολογούνται.</p><form id="persistent-bat"><label>Επίσκεψη <select id="persistent-visit"><option>T0</option><option>T4</option><option>T8</option></select></label><label>Πραγματική ημερομηνία <input id="persistent-bat-date" type="date" required></label><div id="persistent-bat-items"></div><button type="submit">Αποθήκευση BAT-23</button><p id="persistent-bat-status" role="status"></p></form>';
document.querySelector('main').append(persistencePanel);
const responseStatus=document.getElementById('response-status');
const batForm=document.getElementById('persistent-bat');
const visit=document.getElementById('persistent-visit');
const batDate=document.getElementById('persistent-bat-date');
const batStatus=document.getElementById('persistent-bat-status');
let savedBat=[];
EvvardiaBAT.items.forEach((text,index)=>{
  const label=document.createElement('label');label.style.display='block';label.style.margin='12px 0';
  label.append(document.createTextNode((index+1)+'. '+text+' '));
  const select=document.createElement('select');select.name='bat-'+index;
  ['', '1 · Ποτέ','2 · Σπάνια','3 · Μερικές φορές','4 · Συχνά','5 · Πάντα'].forEach((text,i)=>{
    const option=document.createElement('option');option.value=i?String(i):'';option.textContent=text||'Χωρίς απάντηση';select.append(option);
  });label.append(select);document.getElementById('persistent-bat-items').append(label);
});
function loadBat() {
  const record=savedBat.find(r=>r.visit===visit.value);
  batDate.value=record?.assessment_date || new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Athens'}).format(new Date());
  for(let i=0;i<23;i++)batForm.elements['bat-'+i].value=record?.values[i]??'';
  batStatus.textContent=record?'Ανακτήθηκε αποθηκευμένη αναθεώρηση '+record.revision+'.':'';
}
visit.addEventListener('change',()=>{
  if(pendingResponses.has('/api/bat')) {visit.value=pendingResponses.get('/api/bat').data.visit;batStatus.textContent='Ολοκλήρωσε την εκκρεμή υποβολή πριν αλλάξεις επίσκεψη.';return;}
  loadBat();
});
async function reloadResponses() {
  const r=await fetch('/api/records');if(!r.ok)throw new Error('Αποτυχία ανάκτησης ('+r.status+').');
  const data=await r.json();entries.clear();
  for(const r of data.records.filter(r=>r.kind==='checkin'))entries.set(r.assessment_date,r.values);
  savedBat=data.records.filter(r=>r.kind==='bat23');render();
  document.getElementById('date').dispatchEvent(new Event('change'));loadBat();
}
batForm.addEventListener('submit',async event=>{
  event.preventDefault();batStatus.textContent='Αποστολή…';
  try {
    const values=Array.from({length:23},(_,i)=>batForm.elements['bat-'+i].value).map(v=>v===''?null:Number(v));
    const receipt=await persistResponse('/api/bat',{assessment_date:batDate.value,values,visit:visit.value});
    const scores=EvvardiaBAT.score(values);
    savedBat=savedBat.filter(r=>r.visit!==visit.value).concat([{visit:visit.value,assessment_date:batDate.value,values,revision:receipt.revision}]);
    batStatus.textContent='Αποθηκεύτηκε. Αναθεώρηση '+receipt.revision+'. Συνολικό σκορ: '+(scores.total===null?'μη διαθέσιμο (ελλείψεις)':scores.total.toFixed(2))+'. Δεν αποτελεί διάγνωση.';
  } catch(error){batStatus.textContent=error.message;}
});
document.getElementById('response-retry').addEventListener('click',async()=>{
  try {
    for(const [path,pending] of [...pendingResponses]) {
      await persistResponse(path,pending.data);
      if(path==='/api/checkins')recordStudyEvent('checkin',{day:pending.data.assessment_date});
    }
    await reloadResponses();responseStatus.textContent='Οι εκκρεμείς απαντήσεις αποθηκεύτηκαν και ανακτήθηκαν.';
  } catch(error){responseStatus.textContent=error.message;}
});
for(const button of [document.querySelector('#checkin button[type=submit]'),batForm.querySelector('button')])button.disabled=true;
reloadResponses().then(()=>{
  persistenceReady=true;responseStatus.textContent='Ανάκτηση ολοκληρώθηκε. Χρησιμοποίησε μόνο συνθετικά δεδομένα.';
  for(const button of [document.querySelector('#checkin button[type=submit]'),batForm.querySelector('button')])button.disabled=false;
}).catch(error=>{responseStatus.textContent=error.message+' Η υποβολή παραμένει κλειστή. Ανανέωσε τη σελίδα.';});
