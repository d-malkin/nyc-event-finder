(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('data').textContent);
  const events = data.events;
  const byId = id => document.getElementById(id);
  const initial = () => ({query:'', free:false, hidePast:true, pool:'all', categories:new Set()});
  let state = initial();
  function today() {
    if (data.demo) return data.demoDate;
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'
    }).formatToParts(new Date());
    const part = type => parts.find(p => p.type === type).value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
  // A mixed free/paid range is not classified as an entirely free event.
  const isFree = event => /^(free|\$0(?:\.00)?)$/i.test(event.admission.trim());
  const dateLabel = value => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-US', {
    weekday:'long', month:'long', day:'numeric', year:'numeric', timeZone:'America/New_York'
  });
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function button(parent, text, onClick) {
    const node = el('button', '', text);
    node.type = 'button';
    node.setAttribute('aria-pressed', 'false');
    node.onclick = onClick;
    parent.appendChild(node);
    return node;
  }
  const poolButtons = new Map();
  for (const [value, label] of [['all','All events'], ['shortlist','Shortlist'], ['candidate','Candidates']]) {
    poolButtons.set(value, button(byId('pools'), label, () => {state.pool = value; render();}));
  }
  const categoryButtons = new Map();
  for (const category of [...new Set(events.map(e => e.category).filter(Boolean))].sort()) {
    categoryButtons.set(category, button(byId('cats'), category, () => {
      state.categories.has(category) ? state.categories.delete(category) : state.categories.add(category);
      render();
    }));
  }
  byId('q').oninput = event => {state.query = event.target.value.trim().toLowerCase(); render();};
  byId('f-free').onclick = () => {state.free = !state.free; render();};
  byId('f-past').onclick = () => {state.hidePast = !state.hidePast; render();};
  byId('reset').onclick = () => {state = initial(); byId('q').value = ''; render();};
  byId('demo').hidden = !data.demo;

  function card(event, currentDate) {
    const node = el('article', `entry${event.pool === 'shortlist' ? ' short' : ''}${event.date < currentDate ? ' past' : ''}`);
    const top = el('div', 'etop');
    top.appendChild(el('h3', 'ename', event.name));
    top.appendChild(el('span', 'etime', event.time || 'Time to be confirmed'));
    node.appendChild(top);
    node.appendChild(el('p', 'meta', [event.organizer, event.venue].filter(Boolean).join(' · ')));
    if (event.description) node.appendChild(el('p', 'description', event.description));
    const labels = el('div', 'labels');
    labels.appendChild(el('span', 'label', event.pool === 'shortlist' ? 'Shortlist' : 'Candidate'));
    if (event.category) labels.appendChild(el('span', 'label', event.category));
    const unknown = !event.admission || /^unknown/i.test(event.admission);
    labels.appendChild(el('span', `label${isFree(event) ? ' free' : unknown ? ' unknown' : ''}`, unknown ? 'Admission unknown' : event.admission));
    if (event.registration) labels.appendChild(el('span', 'label', event.registration));
    node.appendChild(labels);
    if (event.pool === 'shortlist') {
      const sameDate = events.filter(other => other !== event && other.pool === 'shortlist' && other.date === event.date);
      if (sameDate.length) node.appendChild(el('p', 'clash', `Also shortlisted that day: ${sameDate.map(other => other.name).join('; ')}. Check the start times.`));
    }
    // Never turn an imported value into HTML or an executable link.
    if (event.url && /^https?:\/\//i.test(event.url)) {
      const link = el('a', 'out', 'View organizer’s event page ↗');
      link.href = event.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      node.appendChild(link);
    }
    const provenance = [event.verified, event.source ? `Source: ${event.source}` : ''].filter(Boolean).join(' · ');
    if (provenance) node.appendChild(el('p', 'provenance', provenance));
    return node;
  }
  function render() {
    const currentDate = today();
    byId('f-free').setAttribute('aria-pressed', String(state.free));
    byId('f-past').setAttribute('aria-pressed', String(state.hidePast));
    for (const [key, node] of poolButtons) node.setAttribute('aria-pressed', String(state.pool === key));
    for (const [key, node] of categoryButtons) node.setAttribute('aria-pressed', String(state.categories.has(key)));
    const rows = events.filter(event => {
      if (state.pool !== 'all' && event.pool !== state.pool) return false;
      if (state.free && !isFree(event)) return false;
      if (state.hidePast && event.date < currentDate) return false;
      if (state.categories.size && !state.categories.has(event.category)) return false;
      return !state.query || [event.name,event.organizer,event.venue,event.description].join(' ').toLowerCase().includes(state.query);
    });
    byId('count').textContent = `${rows.length} ${rows.length === 1 ? 'event' : 'events'} shown${data.demo ? ' · fictional sample data' : ''}`;
    byId('list').replaceChildren();
    byId('none').hidden = rows.length > 0;
    let group, lastDate;
    for (const event of rows) {
      if (event.date !== lastDate) {
        lastDate = event.date;
        group = el('section', 'daygroup');
        const heading = el('h2', 'day', dateLabel(event.date));
        if (event.date < currentDate) heading.appendChild(el('span', 'past-label', 'Past'));
        group.appendChild(heading);
        byId('list').appendChild(group);
      }
      group.appendChild(card(event, currentDate));
    }
    byId('tally').replaceChildren();
    for (const [label, count] of [
      ['events',events.length], ['shortlisted',events.filter(e => e.pool === 'shortlist').length],
      ['upcoming',events.filter(e => e.date >= currentDate).length], ['free',events.filter(isFree).length]
    ]) {
      const item = el('span');
      item.appendChild(el('b','',String(count)));
      item.appendChild(document.createTextNode(` ${label}`));
      byId('tally').appendChild(item);
    }
  }
  render();
  // Refresh date-sensitive filters after a background tab crosses midnight.
  document.addEventListener('visibilitychange', () => {if (!document.hidden) render();});
  setInterval(render, 60000);
})();
