'use strict';

// An opt-in canvas game. No WebGL context, external assets, audio or network calls.
(() => {
  const room = document.querySelector('#wait-lounge');
  const canvas = room.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const play = room.querySelector('[data-wait-play]');
  const note = room.querySelector('[data-wait-note]');
  const scoreLabel = room.querySelector('[data-wait-score]');
  const taskLabel = room.querySelector('[data-wait-task]');
  const meter = room.querySelector('progress');
  let jobs = [], tracked = new Set(), running = false, finished = false;
  let frame = 0, previous = 0, distance = 0, best = 0, next = 1.1;
  let y = 0, velocity = 0, obstacles = [];
  try { best = Number(localStorage.getItem('jingliu.runner.best')) || 0; } catch (_) {}
  const active = job => ['queued', 'running'].includes(job.state);

  function paint() {
    ctx.clearRect(0, 0, 900, 300);
    const sky = ctx.createLinearGradient(0, 0, 900, 300);
    sky.addColorStop(0, '#14182f'); sky.addColorStop(1, '#26213b');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, 900, 300);
    for (let i = 0; i < 45; i++) {
      ctx.fillStyle = i % 3 ? '#62658f' : '#c4baff';
      const x = ((i * 127 + 39 - distance * (i % 3 + 1) * 5) % 920 + 920) % 920;
      ctx.fillRect(x, 22 + i * 37 % 165, i % 3 ? 2 : 3, i % 3 ? 2 : 3);
    }
    ctx.strokeStyle = '#70628f'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, 250); ctx.lineTo(900, 250); ctx.stroke();
    ctx.fillStyle = '#302d48';
    for (let i = 0; i < 12; i++) ctx.fillRect(((i * 89 - distance * 100) % 1000 + 1000) % 1000, 263, 24, 2);
    // A tiny studio robot; crisp vector-like drawing at every screen size.
    ctx.save(); ctx.translate(128, 250 - y);
    ctx.fillStyle = '#b9a5ff'; ctx.fillRect(-21, -51, 42, 34);
    ctx.fillStyle = '#e4dcff'; ctx.fillRect(-15, -16, 30, 12);
    ctx.fillStyle = '#14182f'; ctx.fillRect(-13, -42, 26, 17);
    ctx.fillStyle = '#90f2cf'; ctx.fillRect(-8, -37, 5, 5); ctx.fillRect(4, -37, 5, 5);
    ctx.fillStyle = '#b9a5ff'; ctx.fillRect(-2, -60, 4, 8);
    ctx.fillStyle = '#90f2cf'; ctx.fillRect(-4, -63, 8, 5);
    const step = running && !y ? Math.sin(distance * 22) * 3 : 0;
    ctx.fillRect(-17, -5 + step, 12, 5); ctx.fillRect(5, -5 - step, 12, 5);
    ctx.restore();
    for (const obstacle of obstacles) {
      ctx.fillStyle = '#f2c67f'; ctx.fillRect(obstacle.x, 210, 27, 40);
      ctx.fillStyle = '#443c4c'; ctx.fillRect(obstacle.x + 6, 217, 15, 3);
    }
  }

  function pause(message) {
    running = false; cancelAnimationFrame(frame); frame = 0;
    try { localStorage.setItem('jingliu.runner.best', String(best)); } catch (_) {}
    if (message) note.textContent = message;
    play.textContent = finished ? '任务已结束' : '开始 / 重新挑战';
    paint();
  }

  function tick(now) {
    if (!running || !room.open) return;
    frame = requestAnimationFrame(tick);
    if (now - previous < 1000 / 30) return;
    const dt = Math.min((now - previous) / 1000, 0.05); previous = now;
    distance += dt; next -= dt;
    velocity -= 1450 * dt; y = Math.max(0, y + velocity * dt);
    if (!y) velocity = 0;
    const speed = Math.min(390, 265 + distance * 2);
    if (next <= 0) { obstacles.push({x:925}); next = 1.25 + Math.random() * 0.7; }
    obstacles.forEach(o => { o.x -= speed * dt; });
    obstacles = obstacles.filter(o => o.x > -30);
    const score = Math.floor(distance * 10);
    if (score > best) {
      best = score;
    }
    scoreLabel.textContent = `${String(score).padStart(4,'0')} / 最佳 ${best}`;
    if (obstacles.some(o => o.x < 145 && o.x + 27 > 112 && y < 37)) {
      pause('碰到路障啦，再试一次？生成任务仍在继续。'); return;
    }
    paint();
  }

  function jump() {
    if (finished || document.hidden) return;
    if (!running) {
      y = 0; velocity = 0; distance = 0; next = 1.1; obstacles = [];
      running = true; previous = performance.now();
      play.textContent = '跳跃 ↑'; note.textContent = '空格、轻点画面或点击按钮，越过路障。';
      frame = requestAnimationFrame(tick);
    }
    if (!y) velocity = 590;
  }

  function updateJobs(value) {
    jobs = value;
    if (!room.open) return;
    jobs.filter(active).forEach(job => tracked.add(job.id));
    const pending = jobs.filter(job => tracked.has(job.id) && active(job));
    const current = pending.find(job => job.state === 'running') || pending[0];
    if (current) {
      taskLabel.textContent = `${current.label} · ${current.message || '排队中'}${pending.length > 1 ? ` · 还有 ${pending.length - 1} 项` : ''}`;
      if (Number(current.progress) > 0) meter.value = current.progress;
      else meter.removeAttribute('value');
    } else {
      const results = jobs.filter(job => tracked.has(job.id));
      finished = true; play.disabled = true;
      const failed = results.some(job => job.state === 'failed');
      const done = results.length === tracked.size && results.length > 0 && results.every(job => job.state === 'done');
      taskLabel.textContent = failed ? '有任务失败，请返回队列查看原因并重试。' : done ? '生成完成，可以返回队列查看结果了。' : '任务已结束，请返回队列查看状态。';
      meter.value = done ? 100 : 0;
      pause('等待结束，回到创作吧。');
    }
  }

  document.addEventListener('click', event => {
    if (!event.target.closest('[data-wait-open]')) return;
    tracked = new Set(jobs.filter(active).map(job => job.id));
    finished = false; play.disabled = false;
    room.showModal(); updateJobs(jobs);
    pause(finished ? '等待结束，回到创作吧。' : '一段轻巧的星光旅程。想玩的时候再开始。');
  });
  room.querySelector('[data-wait-close]').addEventListener('click', () => room.close());
  room.addEventListener('close', () => pause());
  room.addEventListener('keydown', event => {
    if (event.code === 'Space' && !event.target.closest('[data-wait-close]')) { event.preventDefault(); jump(); }
  });
  play.addEventListener('click', jump);
  canvas.addEventListener('pointerdown', jump);
  document.addEventListener('visibilitychange', () => { if (document.hidden && room.open) pause('已暂停。回来后点击按钮重新开始。'); });
  window.JingliuWait = {updateJobs};
  paint();
})();
