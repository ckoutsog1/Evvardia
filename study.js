const studyParticipant = document.querySelector('meta[name="study-participant"]').content;
const pendingStudyEvents = [];
let sendingStudyEvents = false;
const studyStatus = document.getElementById('study-status');
const studyRetry = document.getElementById('study-retry');

function recordStudyEvent(type, details = {}) {
  pendingStudyEvents.push({id:crypto.randomUUID(), type, ...details});
  sendStudyEvents();
}

async function sendStudyEvents() {
  if (sendingStudyEvents) return;
  sendingStudyEvents = true;
  studyRetry.hidden = true;
  try {
    while (pendingStudyEvents.length) {
      studyStatus.textContent = 'Αποστολή συμβάντων…';
      const response = await fetch('/event', {
        method:'POST', headers:{'Content-Type':'application/json','X-Study-Participant':studyParticipant},
        body:JSON.stringify(pendingStudyEvents[0])
      });
      if (!response.ok) throw new Error(String(response.status));
      pendingStudyEvents.shift();
    }
    studyStatus.textContent = 'Τα συμβάντα καταγράφηκαν.';
  } catch (error) {
    studyStatus.textContent = ['401','403'].includes(error.message)
      ? 'Η πρόσβαση έληξε. Η αποστολή εκκρεμεί. Κράτησε ανοικτή τη σελίδα και συνδέσου ξανά με τον ίδιο κωδικό σε άλλη καρτέλα.'
      : 'Η αποστολή εκκρεμεί. Κράτησε ανοικτή τη σελίδα και πάτησε «Επανάληψη αποστολής».';
    studyRetry.hidden = false;
  } finally {
    sendingStudyEvents = false;
  }
}

studyRetry.addEventListener('click', sendStudyEvents);
window.addEventListener('online', () => {
  if (pendingStudyEvents.length) sendStudyEvents();
});
window.addEventListener('beforeunload', event => {
  if (!pendingStudyEvents.length) return;
  event.preventDefault();
  event.returnValue = '';
});
document.getElementById('study-logout').addEventListener('click', async () => {
  if (pendingStudyEvents.length) {
    studyStatus.textContent = 'Ολοκλήρωσε την αποστολή πριν αποσυνδεθείς.';
    return;
  }
  try {
    const response = await fetch('/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if (response.ok) location.reload();
  } catch {
    studyStatus.textContent = 'Η αποσύνδεση δεν ολοκληρώθηκε. Δοκίμασε ξανά.';
  }
});
