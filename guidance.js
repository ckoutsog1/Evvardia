const guidanceForm = document.getElementById('guidance-form');
guidanceForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = guidanceForm.querySelector('button');
  const topic = document.getElementById('guidance-topic');
  const status = document.getElementById('guidance-status');
  const result = document.getElementById('guidance-result');
  button.disabled = topic.disabled = true;
  result.hidden = true;
  status.textContent = 'Αναζήτηση κατευθύνσεων…';
  try {
    const response = await fetch('/guidance', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-Study-Participant':studyParticipant},
      body:JSON.stringify({topic:topic.value})
    });
    if (!response.ok) throw new Error();
    const card = await response.json();
    document.getElementById('guidance-today').textContent = card.today;
    document.getElementById('guidance-next').textContent = card.next_days;
    result.hidden = false;
    status.textContent = 'Οι κατευθύνσεις είναι διαθέσιμες.';
  } catch {
    status.textContent = 'Οι κατευθύνσεις δεν είναι διαθέσιμες. Μπορείς να δεις τις επιλογές ανθρώπινης υποστήριξης.';
  } finally {
    button.disabled = topic.disabled = false;
  }
});
