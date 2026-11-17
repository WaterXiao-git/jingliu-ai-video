'use strict';

(() => {
  const view = document.querySelector('#onboarding');
  const key = 'jingliu.guide.v1';
  const steps = [
    {
      title: '打开一个项目',
      body: '用练习项目可直接体验。自己的短剧可从新建项目开始。',
      ready: () => Boolean(state.project),
      page: 'projects', focus: '[data-action="new"]',
    },
    {
      title: '准备第一镜',
      body: '在分镜制作中选首帧，然后写下人物做什么、镜头怎么动。先选「试拍」，建议试 1–2 秒并保存。想用本地模型自动拆镜，可以从「剧本与拆镜」选 Ollama 模型。',
      ready: () => Boolean(selectedShot()?.first && (selectedShot()?.visual || selectedShot()?.prompt)),
      page: 'shots', focus: '#shot-form [name="prompt"]',
    },
    {
      title: '生成并播放',
      body: '点击「生成这个镜头」，在队列里查看进度。生成后回到分镜播放。显存不足时，改用试拍档或缩短镜头，再到队列重试。',
      ready: () => Boolean(selectedShot()?.clip),
      page: 'shots', focus: '[data-action="generate-shot"]',
    },
    {
      title: '导出一条视频',
      body: '在「成片与导出」选择字幕和声音来源。第一次可选静音或保留镜头原声。使用 AI 配音时，台词将交给 Edge TTS 联网合成。',
      ready: () => Boolean(state.project?.exports.length),
      page: 'exports', focus: '#export-form button[type="submit"]',
    },
    {
      title: '保存 MP4',
      body: '播放预览，确认时长和字幕后点击「下载 MP4」。可以随时从右上角重开引导。',
      ready: () => Boolean(state.project?.exports.length),
      page: 'exports', focus: '.result-video',
    },
  ];
  let current = 0;
  let open = localStorage.getItem(key) !== 'done';

  function guideButton(label, action, classes = 'quiet small', enabled = true) {
    return '<button type="button" class="button ' + classes + '" data-guide="' + action + '"' +
      (enabled ? '' : ' disabled') + '>' + label + '</button>';
  }

  function render() {
    document.querySelectorAll('.guide-focus').forEach(el => el.classList.remove('guide-focus'));
    view.hidden = !open;
    if (!open) return;
    const step = steps[current];
    const ready = step.ready();
    view.innerHTML = '<div class="panel-head"><h2>新手引导</h2>' + guideButton('关闭', 'close') +
      '</div><div class="panel-body"><div class="guide-count">' + (current + 1) + ' / ' + steps.length +
      (ready ? ' · 已完成' : '') + '</div><h3>' + step.title + '</h3><p>' + step.body +
      '</p><div class="actions">' +
      (current === 0 && !state.project ? guideButton('导入练习项目', 'sample', 'primary small') : '') +
      (state.page === step.page ? '' : guideButton('打开对应页面', 'page')) +
      guideButton(current === steps.length - 1 ? '完成引导' : '下一步', 'next', 'primary small', ready) +
      (ready ? '' : guideButton('跳过此步', 'skip')) +
      (current > 0 ? guideButton('上一步', 'prev') : '') + '</div></div>';
    if (!ready && state.page === step.page) document.querySelector(step.focus)?.classList.add('guide-focus');
  }

  function close() {
    open = false;
    localStorage.setItem(key, 'done');
    render();
  }

  function move(delta) {
    if (current + delta >= steps.length) {
      close();
      return;
    }
    current = Math.max(0, current + delta);
    if (state.project || steps[current].page === 'projects') go(steps[current].page);
    render();
  }

  async function action(element) {
    switch (element.dataset.guide) {
      case 'open': current = 0; open = true; render(); return;
      case 'close': close(); return;
      case 'page': go(steps[current].page); return;
      case 'next': case 'skip': move(1); return;
      case 'prev': move(-1); return;
      case 'sample': {
        const project = await api('/sample', 'POST', {});
        await loadProjects();
        current = 1;
        await openProject(project.id, 'shots');
        return;
      }
    }
  }

  function download(value, name) {
    const url = URL.createObjectURL(value);
    const link = Object.assign(document.createElement('a'), { href: url, download: name });
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function waitMedia(element, event) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => finish(false), 9000);
      const success = () => finish(true);
      const failure = () => finish(false);
      function finish(ok) {
        clearTimeout(timer);
        element.removeEventListener(event, success);
        element.removeEventListener('error', failure);
        if (ok) resolve();
        else reject(new Error('浏览器无法读取作品预览。'));
      }
      element.addEventListener(event, success, { once: true });
      element.addEventListener('error', failure, { once: true });
    });
  }

  async function thumbnail(clip, first, projectId) {
    let source, width, height, type;
    if (clip) {
      const video = document.createElement('video');
      video.muted = true;
      video.preload = 'auto';
      const loaded = waitMedia(video, 'loadeddata');
      video.src = media(clip, projectId);
      try {
        await loaded;
        if (video.duration > 0.4) {
          const seek = waitMedia(video, 'seeked');
          video.currentTime = Math.min(0.7, video.duration / 2);
          await seek;
        }
        source = video; width = video.videoWidth; height = video.videoHeight; type = 'video_frame';
      } catch (error) {
        video.removeAttribute('src');
        video.load();
        if (!first) throw error;
      }
    }
    if (!source && first) {
      const img = new Image();
      img.src = media(first, projectId);
      await img.decode();
      source = img; width = img.naturalWidth; height = img.naturalHeight; type = 'reference_frame';
    }
    if (!source) return null;
    const ratio = Math.min(1, 640 / Math.max(width, height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * ratio));
    canvas.height = Math.max(1, Math.round(height * ratio));
    canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    if (source.tagName === 'VIDEO') {
      source.removeAttribute('src');
      source.load();
    }
    const image = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.83));
    if (!image) throw new Error('缩略图编码失败。');
    return { image, type };
  }

  let share;
  function showShare() {
    const project = state.project;
    if (!project?.shots.length) return notify('请先添加镜头。', true);
    share = { project, payload: null, thumb: null };
    const chosen = selectedShot()?.id;
    const community = state.status.community;
    const link = /^https:\/\/github\.com\/[\w-]+\/[\w.-]+\/discussions$/.test(community || '')
      ? '<a href="' + esc(community) + '" target="_blank" rel="noopener noreferrer" class="button quiet small">打开作品社区</a>' : '';
    showDialog('<h2>导出作品分享卡</h2><p class="notice">在本机预览和保存。你可在确认内容与公开权限后，自行把分享卡发到社区。</p>' +
      field('标题', textInput('share-title', project.name, 'maxlength="120"')) +
      field('镜头', '<select name="share-shot">' + options(project.shots.map(s => [s.id, s.title]), chosen) + '</select>') +
      field('公开作品链接（可选）', textInput('share-url', '', 'type="url" placeholder="https://…" maxlength="1500"')) +
      '<label class="checkbox"><input name="share-prompt" type="checkbox">将所选镜头提示词加入分享卡</label>' +
      '<div id="sharing-preview"></div><div class="actions"><button type="button" class="button quiet" data-share="close">关闭</button>' + link +
      '<button type="button" class="button primary" data-share="preview">预览将要导出的内容</button></div>');
  }

  async function preview() {
    const project = share.project;
    const shot = project.shots.find(s => s.id === dialog.querySelector('[name="share-shot"]').value);
    const titleValue = dialog.querySelector('[name="share-title"]').value.trim();
    if (!titleValue) throw new Error('请填写分享标题。');
    let url = dialog.querySelector('[name="share-url"]').value.trim();
    if (url) {
      const parsed = new URL(url);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password ||
          !parsed.hostname.includes('.') || parsed.hostname.endsWith('.local')) {
        throw new Error('请输入可以公开访问的 HTTPS 作品链接。');
      }
      url = parsed.href;
    }
    const includePrompt = dialog.querySelector('[name="share-prompt"]').checked;
    const thumb = await thumbnail(shot.clip || project.exports.at(-1)?.file, shot.first, project.id);
    const payload = { schema: 'jingliu.share.v1', title: titleValue, shot: shot.title, aspect: project.aspect };
    if (url) payload.public_url = url;
    if (includePrompt) payload.prompt = shot.prompt || shot.visual;
    if (thumb) payload.thumbnail = { file: 'jingliu-thumbnail.jpg', source: thumb.type };
    share.payload = payload;
    share.thumb = thumb?.image;
    const output = dialog.querySelector('#sharing-preview');
    const previous = output.querySelector('img')?.src;
    if (previous) URL.revokeObjectURL(previous);
    output.innerHTML = '<div class="share-preview">' +
      (thumb ? '<img alt="将要导出的缩略图" src="' + URL.createObjectURL(thumb.image) + '">' : '') +
      '<pre>' + esc(JSON.stringify(payload, null, 2)) + '</pre></div><div class="actions">' +
      '<button type="button" class="button primary" data-share="download">确认下载分享卡</button>' +
      (thumb ? '<button type="button" class="button quiet" data-share="image">下载缩略图</button>' : '') + '</div>';
  }

  document.addEventListener('click', event => {
    const guide = event.target.closest('button[data-guide]');
    if (guide) return runAction(guide, () => action(guide));
    const button = event.target.closest('button[data-share]');
    if (!button) return;
    runAction(button, async () => {
      if (button.dataset.share === 'open') showShare();
      if (button.dataset.share === 'close') dialog.close();
      if (button.dataset.share === 'preview') await preview();
      if (button.dataset.share === 'download' && share?.payload) {
        download(new Blob([JSON.stringify(share.payload, null, 2)], { type: 'application/json' }), 'jingliu-share.json');
      }
      if (button.dataset.share === 'image' && share?.thumb) download(share.thumb, 'jingliu-thumbnail.jpg');
    });
  });
  dialog.addEventListener('input', event => {
    if (!event.target.name?.startsWith('share-')) return;
    const output = dialog.querySelector('#sharing-preview');
    if (output) {
      const previous = output.querySelector('img')?.src;
      if (previous) URL.revokeObjectURL(previous);
      output.replaceChildren();
    }
    if (share) share.payload = share.thumb = null;
  });
  dialog.addEventListener('close', () => {
    const previous = dialog.querySelector('#sharing-preview img')?.src;
    if (previous) URL.revokeObjectURL(previous);
    share = null;
  });
  window.JingliuGuide = { render };
  render();
})();
