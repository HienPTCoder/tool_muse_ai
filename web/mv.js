// Khung chung cho các loại video nhiều short (danh sách dự án, các bước, thanh tác vụ Muse, thẻ nhân vật/bối cảnh,
// danh sách short + xem trước) và các bước của MV âm nhạc:
// nhạc -> lời + timeline -> kịch bản -> nhân vật/bối cảnh khoá -> plan short -> tạo & duyệt short -> xuất.
// Loại "người mẫu tạo dáng" ở web/model.js. Dùng chung $, $$, esc, api, toast từ index.html.

const MV_STEPS = ['Nhạc & lời', 'Kịch bản', 'Nhân vật & bối cảnh', 'Plan short', 'Duyệt & xuất'];
const TASK_LABEL = {lyrics: 'Chép lời + timeline (trên máy)', lyrics_fix: 'Muse sửa lời', script: 'Viết kịch bản', assets: 'Phân tích nhân vật & bối cảnh',
  asset_image: 'Vẽ ảnh nhân vật/bối cảnh', plan: 'Lên plan short', shorts: 'Tạo short', video_analysis: 'Phân tích video mẫu',
  thumbnail: 'Tạo thumbnail', song_analysis: 'Phân tích bài hát', asset_images: 'Vẽ tất cả nhân vật/bối cảnh', model_design: 'Thiết kế người mẫu', locations: 'Đề xuất bối cảnh', model_scripts: 'Viết kịch bản', remake_analysis: 'Phân tích MV gốc', stickerman_plan: 'Lên plan short'};
const TASK_STATUS = {queued: 'Đang chờ', running: 'Đang chạy', done: 'Xong', failed: 'Lỗi', cancelled: 'Đã huỷ'};
const SHORT_STATUS = {pending: 'Chưa tạo', queued: 'Đang chờ', running: 'Muse đang tạo', done: 'Xong', failed: 'Lỗi'};
let MV = null;          // dự án đang mở
let thumbPrompt = '';  // yêu cầu thumbnail đang gõ (giữ lại khi màn hình vẽ lại)
let mvSig = '';         // chữ ký dữ liệu để biết khi nào cần vẽ lại
let mvTimer = null;
let curKind = 'mv';     // loại video đang xem ở màn danh sách

// Mỗi loại video: tên, mô tả, file đầu vào, các bước (hàm vẽ từng bước) và điều kiện "xong" của từng bước
const KINDS = {
  mv: {title: 'MV âm nhạc', projectLabel: 'MV',
    sub: 'Từ 1 file nhạc: Muse chép lời, viết kịch bản hoạt hình 2D, khoá nhân vật & bối cảnh, tạo từng short rồi ghép thành MV.',
    field: 'audio', accept: 'audio/*,.mp3,.wav,.m4a', fileLabel: 'File nhạc <span class="hint">— mp3, wav, m4a…</span>',
    info: p => `MV âm nhạc · ${tfmt(p.duration || 0)} · ${esc(p.style)} · ${esc(p.aspect)}`,
    steps: MV_STEPS, render: () => [stepLyrics, stepScript, stepAssets, stepPlan, stepReview],
    done: n => n === 1 ? MV.lyrics?.length > 0 : n === 2 ? !!MV.script : n === 3 ? MV.assets.length && MV.assets.every(a => a.locked)
      : n === 4 ? MV.shorts.length > 0 : MV.shorts.length && MV.shorts.every(s => s.status === 'done')},
  scriptvideo: {title: 'Tạo video theo kịch bản', projectLabel: 'video theo kịch bản',
    sub: 'Dán kịch bản, thiết kế nhân vật người que, chia phân cảnh và tạo short tuần tự với ảnh tham chiếu nhân vật và khung cuối short trước.',
    field: '', accept: '', fileLabel: '', optional: true,
    projectPlaceholder: 'Ví dụ: Hành trình của người que áo đỏ',
    createHint: 'Tạo dự án trước, sau đó dán kịch bản và chọn phong cách hoạt hình ở bước đầu tiên.',
    info: p => `Video theo kịch bản · ${tfmt(p.duration || 0)} · ${esc(p.style)} · ${esc(p.aspect)}`,
    steps: ['Kịch bản', 'Thiết kế nhân vật', 'Plan short', 'Tạo & xem video'],
    render: () => [stepScriptVideo, stepAssets, stepPlan, stepReview],
    done: n => n === 1 ? !!MV.script : n === 2 ? MV.assets?.some(a => a.kind === 'character' && a.locked)
      : n === 3 ? MV.shorts?.length > 0 : MV.shorts?.length && MV.shorts.every(s => s.status === 'done')},
};

const tfmt = s => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
const tparse = v => { const m = String(v).trim().match(/^(\d+):(\d+(?:\.\d+)?)$/); return m ? +m[1] * 60 + +m[2] : +v; };

// ---------- chọn loại video ----------
function showCreate(view) {
  // View lạ (vd 'stickerman' — loại chưa có khối #create-* riêng) sẽ ẩn SẠCH mọi khối và để lại
  // màn hình trắng, lại còn được lưu vào localStorage nên mọi lần tải sau đều trắng. Quay về 'types'.
  if (!document.getElementById('create-' + view)) view = 'types';
  for (const v of ['types', 'prompt', 'mv', 'posebatch', 'shortpromo']) $('#create-' + v).classList.toggle('hidden', v !== view);
  if (view !== 'mv') { clearInterval(mvTimer); MV = null; stopPreview(); localStorageSet('mv-open', ''); }
  if (view === 'posebatch') pbShow(); else pbStop();
  if (view === 'shortpromo' && typeof loadShortPromoSequences === 'function') loadShortPromoSequences();
  window.scrollTo({top: 0, behavior: 'instant'});
  localStorageSet('create-view', view);
}
$$('[data-create]').forEach(c => c.onclick = () => {
  if (KINDS[c.dataset.create]) { showCreate('mv'); mvList(c.dataset.create); } else showCreate(c.dataset.create);
});
$$('.back-types').forEach(b => b.onclick = () => showCreate('types'));

// ---------- danh sách dự án ----------
async function mvList(kind) {
  curKind = kind || curKind;
  const K = KINDS[curKind];
  clearInterval(mvTimer); MV = null; stopPreview();
  localStorageSet('mv-open', ''); localStorageSet('mv-kind', curKind);
  const list = (await api('/api/mv').catch(() => [])).filter(p => (p.kind || 'mv') === curKind);
  $('#create-mv').innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><button class="btn sm back-types">← Loại video</button><h1 style="margin-top:10px">${K.title}</h1>
      <p class="sub">${K.sub}</p></div>
    </div>
    <div class="card"><h2>Tạo dự án mới</h2>
      <div class="grid2">
        ${K.field ? `<div><label for="mv-file">${K.fileLabel}</label><input type="file" id="mv-file" accept="${K.accept}"></div>` : ''}
        <div><label for="mv-title">Tên dự án</label><input type="text" id="mv-title" placeholder="${K.projectPlaceholder || (K.optional ? 'Mặc định theo tên file / ngày giờ' : 'Mặc định theo tên file')}"></div>
      </div>
      ${K.createHint ? `<p class="hint">${K.createHint}</p>` : ''}
      <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn primary" id="mv-create">Tạo dự án</button></div>
    </div>
    <div class="card"><h2>Dự án của bạn</h2>
      ${list.length ? `<table><thead><tr><th>#</th><th>Tên</th><th>Thời lượng</th><th>Bước</th><th>Short</th><th></th></tr></thead><tbody>
        ${list.map(p => `<tr class="click" data-open="${p.id}"><td>${p.id}</td><td>${esc(p.title)}</td><td>${p.duration ? tfmt(p.duration) : ''}</td>
          <td>${p.step}. ${K.steps[p.step - 1]}</td><td>${p.n_shorts ? `${p.n_done}/${p.n_shorts}` : ''}</td>
          <td><button class="btn sm danger" data-del="${p.id}">Xoá</button></td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">Chưa có dự án nào</div>'}
    </div>`;
  $$('#create-mv .back-types').forEach(b => b.onclick = () => showCreate('types'));
  if ($('#mv-file')) $('#mv-file').onchange = e => { const f = e.target.files[0]; if (f && !$('#mv-title').value) $('#mv-title').value = f.name.replace(/\.[^.]+$/, ''); };
  $('#mv-create').onclick = async () => {
    const f = $('#mv-file')?.files[0];
    if (!f && !K.optional) return toast('Chọn file trước');
    const fd = new FormData(); if (f) fd.append(K.field, f); fd.append('kind', curKind);
    fd.append('title', $('#mv-title').value || (f ? f.name.replace(/\.[^.]+$/, '') : ''));
    const b = $('#mv-create'); b.disabled = true; b.textContent = 'Đang tải lên…';
    try { const r = await api('/api/mv', {method: 'POST', body: fd}); mvOpen(r.id); }
    catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Tạo dự án'; }
  };
  $$('[data-open]').forEach(tr => tr.onclick = e => { if (!e.target.dataset.del) mvOpen(+tr.dataset.open); });
  $$('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('Xoá dự án này cùng toàn bộ ảnh và short?')) return;
    try { await api('/api/mv/' + b.dataset.del, {method: 'DELETE'}); mvList(); } catch (e) { toast(e.message); }
  });
}

// ---------- mở dự án ----------
async function mvOpen(id) {
  localStorageSet('mv-open', id);
  showCreate('mv');
  MV = await api('/api/mv/' + id);
  curKind = MV.kind || 'mv';
  mvSig = ''; mvRender(true);
  window.scrollTo({top: 0, behavior: 'instant'});
  clearInterval(mvTimer);
  mvTimer = setInterval(mvPoll, 3000);
}
async function mvPoll() {
  if (!MV || $('#create-mv').classList.contains('hidden')) return;
  try { MV = await api('/api/mv/' + MV.id); } catch (e) { return; }
  mvRender(false);
}
async function mvSave(fields) {
  try { MV = await api('/api/mv/' + MV.id, {method: 'PATCH', json: fields}); }
  catch (e) { toast(e.message); }
}
function goStep(n) { mvSave({step: n}).then(() => { mvSig = ''; mvRender(true); }); }

function signature() {
  return JSON.stringify([MV.step, MV.tasks.map(t => [t.id, t.status, t.log.length]),
    MV.assets.map(a => [a.id, a.image_path, a.locked, a.name]), MV.shorts.map(s => [s.id, s.status, s.version]),
    !!MV.lyrics?.length, !!MV.script, MV.exported_path, !!MV.analysis, MV.scripts.map(x => [x.id, x.title]), (MV.thumbs || []).length, MV.mv_mode, JSON.stringify(MV.song || {})]);
}

function mvRender(force) {
  const sig = signature();
  const editing = document.activeElement?.closest?.('#mv-body') && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  renderTasks();
  if (!force && (sig === mvSig || editing)) return;
  mvSig = sig;
  const box = $('#create-mv');
  if (!$('#mv-head') || force) {
    box.innerHTML = `
      <div class="row" style="justify-content:space-between;align-items:flex-start" id="mv-head">
        <div>
          <div class="row" style="gap:8px;margin-bottom:8px">
            <button class="btn sm" id="mv-back">← Dự án ${KINDS[MV.kind].projectLabel}</button>
            <button class="btn sm back-types">← Chọn loại video khác</button>
          </div>
          <h1 style="margin-top:6px">${esc(MV.title)}</h1>
          <p class="sub">${KINDS[MV.kind].info(MV)}</p>
        </div>
      </div>
      <div class="steps" id="mv-steps"></div>
      <div id="mv-tasks"></div>
      <div id="mv-body"></div>`;
    $('#mv-back').onclick = () => mvList(MV.kind);
    $$('#create-mv .back-types').forEach(b => b.onclick = () => showCreate('types'));
  }
  $('#mv-steps').innerHTML = KINDS[MV.kind].steps.map((s, i) =>
    `<button class="step ${MV.step === i + 1 ? 'on' : ''} ${stepDone(i + 1) ? 'done' : ''}" data-step="${i + 1}"><b>${i + 1}</b>${s}</button>`).join('');
  $$('#mv-steps [data-step]').forEach(b => b.onclick = () => goStep(+b.dataset.step));
  renderTasks();
  const keepScroll = window.scrollY;
  KINDS[MV.kind].render()[MV.step - 1]();
  if (!force) window.scrollTo(0, keepScroll);
}
const stepDone = n => KINDS[MV.kind].done(n);

function stepScriptVideo() {
  const spec = MV.model_spec || {};
  const styles = [
    ['stick2d', '2D người que tối giản', '2D stick figure animation: round solid black head, simple black line limbs, clearly readable clothing and signature accessories.'],
    ['toon2d', '2D cartoon màu', 'Polished 2D cartoon animation with clean outlines, expressive poses and a consistent color palette.'],
    ['toon3d', '3D cartoon', 'Polished stylized 3D cartoon animation, expressive shapes, soft cinematic lighting and consistent materials.'],
    ['clay3d', '3D đất nặn', 'Stylized 3D clay animation with tactile clay surfaces, expressive poses and consistent handmade materials.'],
  ];
  const preset = spec.style_preset || 'stick2d';
  $('#mv-body').innerHTML = `
    <div class="card"><h2>Kịch bản bạn cung cấp</h2>
      <label for="sv-script">Dán kịch bản</label>
      <textarea id="sv-script" style="min-height:300px;font-family:inherit;font-size:14px" placeholder="Dán kịch bản tại đây. Có thể ghi rõ nhân vật, bối cảnh, hành động và lời thoại từng phân cảnh.">${esc(MV.script || '')}</textarea>
      <div class="hint" style="margin-top:6px">Muse sẽ phân tích kịch bản để nhận diện nhân vật, trang phục, phụ kiện, bối cảnh và diễn biến từng cảnh.</div>
      <div class="grid2" style="margin-top:14px">
        <div><label for="sv-style">Phong cách / chất lượng hoạt hình</label><select id="sv-style">${styles.map(([k, label]) => `<option value="${k}" ${k === preset ? 'selected' : ''}>${label}</option>`).join('')}</select><div class="hint" id="sv-style-hint" style="margin-top:5px"></div></div>
        <div><label for="sv-aspect">Tỷ lệ khung hình</label><select id="sv-aspect">${['9:16', '16:9', '1:1'].map(x => `<option ${x === MV.aspect ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
        <div><label for="sv-duration">Thời lượng dự kiến (giây)</label><input id="sv-duration" type="number" min="10" max="900" value="${Math.max(10, Math.min(900, +(MV.duration || 30)))}"><div class="hint">10–180 giây; Muse sẽ chia thành các short theo diễn biến kịch bản.</div></div>
        <div><label for="sv-max">Tối đa mỗi short (giây)</label><input id="sv-max" type="number" min="3" max="10" value="${MV.max_short_sec || 10}"></div>
        <div><label for="sv-cm">Cách gửi short lên Muse</label><select id="sv-cm"><option value="batch" ${MV.chat_mode !== 'chain' ? 'selected' : ''}>1 prompt – 1 chat: Muse tự tạo lần lượt các short (mỗi short ≤ 10s), short sau lấy khung cuối short trước, đúng nhân vật &amp; bối cảnh tham chiếu (khuyên dùng)</option><option value="chain" ${MV.chat_mode === 'chain' ? 'selected' : ''}>Từng short 1 chat riêng, nối bằng khung cuối thật của short trước (chậm hơn)</option></select></div>
      </div>
      <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn primary" id="sv-next">Lưu kịch bản & tiếp tục thiết kế nhân vật</button></div>
    </div>`;
  const styleHint = () => { $('#sv-style-hint').textContent = styles.find(x => x[0] === $('#sv-style').value)?.[2] || ''; };
  styleHint(); $('#sv-style').onchange = styleHint;
  $('#sv-next').onclick = async () => {
    const script = $('#sv-script').value.trim();
    if (!script) return toast('Dán kịch bản trước khi tiếp tục');
    const selected = styles.find(x => x[0] === $('#sv-style').value);
    await mvSave({script, style: selected?.[2] || '2D stick figure animation', aspect: $('#sv-aspect').value,
      duration: Math.max(10, Math.min(900, +$('#sv-duration').value || 30)),
      max_short_sec: Math.max(3, Math.min(10, +$('#sv-max').value || 6)),
      chat_mode: $('#sv-cm').value || 'batch', model_spec: {...spec, style_preset: $('#sv-style').value}});
    goStep(2);
  };
}

// thanh tác vụ Muse đang chạy / vừa xong
function renderTasks() {
  const el = $('#mv-tasks');
  if (!el) return;
  const t = MV.tasks.find(t => ['running', 'queued'].includes(t.status)) || MV.tasks[0];
  if (!t || (t.status === 'done' && Date.now() / 1000 - (t.finished || 0) > 30)) { el.innerHTML = ''; return; }
  const lines = t.log.trim().split('\n');
  const html = `<div class="card taskbar">
    <div class="row" style="justify-content:space-between">
      <span><span class="dot ${t.status === 'running' ? 'run' : t.status === 'failed' ? 'err' : t.status === 'done' ? 'ok' : ''}"></span>
        <b>${TASK_LABEL[t.kind] || t.kind}</b> · ${TASK_STATUS[t.status]}${t.status === 'queued' && MV.worker_task && MV.worker_task !== t.id ? ' (chờ việc khác xong)' : ''}</span>
      ${['running', 'queued'].includes(t.status) ? `<button class="btn sm danger" data-cancel-task="${t.id}">Huỷ</button>` : ''}
    </div>
    ${t.error ? `<div class="warnbox" style="margin:10px 0 0">${esc(t.error)}</div>` : ''}
    ${t.log ? `<div class="hint" style="margin-top:6px;white-space:pre-wrap">${esc(lines.slice(-3).join('\n'))}</div>` : ''}
  </div>`;
  if (el._html !== html) {
    el.innerHTML = el._html = html;
    const c = el.querySelector('[data-cancel-task]');
    if (c) c.onclick = async () => { await api(`/api/mv/tasks/${c.dataset.cancelTask}/cancel`, {method: 'POST'}); toast('Đang huỷ…'); };
  }
}
const busy = kind => MV.tasks.some(t => t.kind === kind && ['running', 'queued'].includes(t.status));
async function runTask(kind, body) {
  try { await api(`/api/mv/${MV.id}/task/${kind}`, {json: body || {}}); toast('Đã gửi việc cho Muse'); mvPoll(); }
  catch (e) { toast(e.message); }
}
function nextBtn(n, label) { return `<button class="btn" data-next="${n}">${label || 'Tiếp →'}</button>`; }
function bindNext() { $$('#mv-body [data-next]').forEach(b => b.onclick = () => goStep(+b.dataset.next)); }

// ---------- bước 1: nhạc & lời ----------
function stepLyrics() {
  const L = MV.lyrics || [];
  $('#mv-body').innerHTML = `
    <div class="card"><h2>File nhạc</h2>
      <audio controls src="${MV.audio_url}" style="width:100%"></audio>
      <div class="row" style="justify-content:space-between;margin-top:12px">
        <span class="hint" style="max-width:560px">Tool nghe file nhạc ngay trên máy (Whisper) để lấy lời + mốc thời gian chính xác từng câu (~1 phút), sau đó có thể nhờ Muse sửa chữ nghe nhầm và gắn tên đoạn (verse/chorus…). Bạn sửa tay được ở bảng dưới.</span>
        <span class="row">
          <button class="btn ${L.length ? '' : 'primary'}" id="do-lyrics" ${busy('lyrics') ? 'disabled' : ''}>${busy('lyrics') ? 'Đang chép lời…' : L.length ? 'Chép lại lời' : 'Chép lời + timeline'}</button>
          ${L.length ? `<button class="btn primary" id="do-fix" ${busy('lyrics_fix') ? 'disabled' : ''}>${busy('lyrics_fix') ? 'Muse đang sửa…' : 'Nhờ Muse sửa lời'}</button>` : ''}
        </span>
      </div>
    </div>
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Lời bài hát (${L.length} dòng)</h2>
      <span class="row"><button class="btn sm" id="ly-add">+ Thêm dòng</button><button class="btn sm" id="ly-save">Lưu lời</button></span></div>
      ${L.length ? `<table class="ly"><thead><tr><th style="width:90px">Bắt đầu</th><th style="width:90px">Kết thúc</th><th>Lời</th><th style="width:100px">Đoạn</th><th></th></tr></thead>
      <tbody>${L.map((l, i) => `<tr data-i="${i}"><td><input type="text" class="ly-s" value="${tfmt(l.start)}"></td><td><input type="text" class="ly-e" value="${tfmt(l.end)}"></td>
        <td><input type="text" class="ly-t" value="${esc(l.text)}" placeholder="(nhạc không lời)"></td><td><input type="text" class="ly-sec" value="${esc(l.section)}"></td>
        <td><button class="btn sm" data-play="${l.start}">▶</button> <button class="btn sm danger" data-rm="${i}">×</button></td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">Chưa có lời. Bấm "Muse chép lời + timeline", hoặc "+ Thêm dòng" để tự nhập.</div>'}
      <div class="row" style="justify-content:flex-end;margin-top:14px">${nextBtn(2)}</div>
    </div>`;
  $('#do-lyrics').onclick = () => { if (!L.length || confirm('Chép lại sẽ thay toàn bộ lời hiện tại. Tiếp tục?')) runTask('lyrics'); };
  if ($('#do-fix')) $('#do-fix').onclick = () => runTask('lyrics_fix');
  const read = () => $$('#mv-body tr[data-i]').map(tr => ({start: tparse(tr.querySelector('.ly-s').value), end: tparse(tr.querySelector('.ly-e').value),
    text: tr.querySelector('.ly-t').value.trim(), section: tr.querySelector('.ly-sec').value.trim()}));
  $('#ly-save').onclick = async () => { await mvSave({lyrics: read().sort((a, b) => a.start - b.start)}); toast('Đã lưu lời'); mvRender(true); };
  $('#ly-add').onclick = async () => { const r = read(); const last = r[r.length - 1]; r.push({start: last?.end || 0, end: (last?.end || 0) + 4, text: '', section: ''}); await mvSave({lyrics: r}); mvRender(true); };
  $$('#mv-body [data-rm]').forEach(b => b.onclick = async () => { const r = read(); r.splice(+b.dataset.rm, 1); await mvSave({lyrics: r}); mvRender(true); });
  $$('#mv-body [data-play]').forEach(b => b.onclick = () => { const a = $('#mv-body audio'); a.currentTime = +b.dataset.play; a.play(); });
  bindNext();
}

// ---------- bước 2: kịch bản ----------
// loại MV: chỉ kể chuyện / có ca sĩ + vài đoạn lip sync / lip sync cả bài
const MV_MODES = {story: ['Chỉ kể chuyện', 'Không có ca sĩ, không ai hát nhép — MV là 1 câu chuyện minh hoạ bài hát.'],
  singer: ['Câu chuyện + ca sĩ', 'Có nhân vật ca sĩ hát nhép ở vài phân đoạn (theo mức lip sync), xen kẽ câu chuyện.'],
  full: ['Ca sĩ lip sync cả bài', 'Ca sĩ hát nhép tất cả câu hát, câu chuyện diễn ra quanh ca sĩ.']};
const SONG_FIELDS = [['singer_gender', 'Giọng hát', 'nam / nữ / song ca nam nữ / nhóm'], ['voice_age', 'Độ tuổi giọng', 'thiếu niên / thanh niên / trung niên…'],
  ['language', 'Ngôn ngữ bài hát', 'tiếng Anh'], ['theme', 'Chủ đề', ''], ['mood', 'Cảm xúc', ''], ['story_core', 'Câu chuyện trong lời', ''],
  ['performer', 'Người trình bày phù hợp', 'giới tính, tuổi, ngoại hình, phong cách']];

function songCard() {
  const S = MV.song || {}, has = SONG_FIELDS.some(([k]) => S[k] && k !== 'language');
  return `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Phân tích bài hát</h2>
      <button class="btn ${has ? '' : 'primary'}" id="do-song" ${busy('song_analysis') ? 'disabled' : ''}>${busy('song_analysis') ? 'Muse đang phân tích…' : has ? 'Muse phân tích lại' : 'Muse phân tích bài hát'}</button></div>
    <div class="hint" style="margin-bottom:10px">Ngôn ngữ do máy nghe nhạc nhận ra. Giọng nam/nữ và độ tuổi: Muse không nghe được file nhạc nên suy luận từ tên bài + lời (hoặc theo ca sĩ gốc nếu biết bài) — hãy sửa lại nếu sai. Kịch bản, nhân vật và chữ trong video đều bám theo phần này.</div>
    <div class="grid2">${SONG_FIELDS.map(([k, label, ph]) => `<div ${['story_core', 'performer'].includes(k) ? 'style="grid-column:1/-1"' : ''}><label>${label}</label>
      ${['story_core', 'performer'].includes(k) ? `<textarea class="song-f" data-k="${k}" style="min-height:56px;font-family:inherit" placeholder="${ph}">${esc(S[k] || '')}</textarea>`
        : `<input type="text" class="song-f" data-k="${k}" value="${esc(S[k] || '')}" placeholder="${ph}">`}</div>`).join('')}</div>
    ${S.reason ? `<div class="hint" style="margin-top:8px">Căn cứ: ${esc(S.reason)}</div>` : ''}</div>`;
}

function stepScript() {
  const pct = MV.lipsync_pct, mode = MV_MODES[MV.mv_mode] ? MV.mv_mode : 'singer';
  $('#mv-body').innerHTML = `${songCard()}
    <div class="card"><h2>Thiết lập trước khi viết kịch bản</h2>
      <label>Loại MV</label>
      <div class="row" style="gap:8px;margin-bottom:12px">${Object.entries(MV_MODES).map(([k, [t, d]]) =>
        `<label class="btn ${k === mode ? 'primary' : ''}" title="${esc(d)}" style="margin:0"><input type="radio" name="mvmode" value="${k}" ${k === mode ? 'checked' : ''} hidden>${t}</label>`).join('')}</div>
      <div class="hint" style="margin-bottom:12px">${esc(MV_MODES[mode][1])}</div>
      <div ${mode === 'singer' ? '' : 'hidden'}>
      <label for="ls">Mức lip sync: <span id="ls-v">${pct}%</span> <span class="hint">— số cảnh ca sĩ hát nhép khớp lời</span></label>
      <input type="range" id="ls" min="10" max="90" step="10" value="${Math.min(90, Math.max(10, pct))}" style="width:100%">
      <div class="hint" id="ls-hint" style="margin:4px 0 14px"></div></div>
      <div class="grid2">
        <div><label for="st">Phong cách 2D <span class="hint">— mọi ảnh và short luôn là hoạt hình 2D cùng 1 nét vẽ</span></label><input type="text" id="st" value="${esc(MV.style)}" placeholder="ví dụ: hoạt hình 2D kiểu anime, nét mảnh, màu pastel"></div>
        <div><label for="asp">Khung hình</label><select id="asp">${['16:9', '9:16', '1:1'].map(a => `<option ${a === MV.aspect ? 'selected' : ''}>${a}</option>`).join('')}</select></div>
        <div><label for="mx">Độ dài tối đa mỗi short (giây)</label><input type="number" id="mx" min="3" max="10" value="${MV.max_short_sec}"></div>
        <div><label for="mv-cm">Cách gửi short lên Muse</label><select id="mv-cm"><option value="batch" ${MV.chat_mode !== 'chain' ? 'selected' : ''}>1 prompt – 1 chat: Muse tự tạo lần lượt các short (mỗi short ≤ 10s), short sau lấy khung cuối short trước, đúng nhân vật &amp; bối cảnh tham chiếu (khuyên dùng)</option><option value="chain" ${MV.chat_mode === 'chain' ? 'selected' : ''}>Từng short 1 chat riêng, nối bằng khung cuối thật của short trước (chậm hơn)</option></select><div class="hint">Cả hai cách đều nối khung hình cuối short trước sang short sau và khoá theo ảnh nhân vật/bối cảnh.</div></div>
      </div>
    </div>
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Kịch bản MV</h2>
      <button class="btn primary" id="do-script" ${busy('script') ? 'disabled' : ''}>${busy('script') ? 'Muse đang viết…' : MV.script ? 'Nhờ Muse viết lại' : 'Nhờ Muse viết kịch bản'}</button></div>
      <textarea id="script" style="min-height:360px;font-family:inherit;font-size:14px" placeholder="Tự nhập kịch bản, hoặc bấm &quot;Nhờ Muse viết kịch bản&quot;. Muse sẽ xây dựng câu chuyện có mâu thuẫn, chuyển biến nhân vật, mô-típ hình ảnh và kết thúc có dư âm.">${esc(MV.script || '')}</textarea>
      <div class="row" style="justify-content:space-between;margin-top:14px"><span class="hint">Kịch bản tự lưu khi bạn rời khỏi ô nhập.</span>
        <span class="row"><button class="btn" data-next="1">← Lời</button>${nextBtn(3)}</span></div>
    </div>`;
  const hint = v => v >= 100 ? 'Tất cả cảnh có lời đều hát nhép khớp khẩu hình.' : v <= 0 ? 'Không hát nhép — chỉ minh hoạ bằng hình ảnh.'
    : `Khoảng ${v}% số cảnh có lời là cảnh hát nhép (ưu tiên điệp khúc), còn lại minh hoạ.`;
  $('#ls-hint').textContent = hint(+$('#ls').value);
  $('#ls').oninput = e => { $('#ls-v').textContent = e.target.value + '%'; $('#ls-hint').textContent = hint(+e.target.value); };
  $$('#mv-body [name=mvmode]').forEach(r => r.onchange = async () => { await mvSave({mv_mode: r.value}); mvRender(true); });
  $('#do-song').onclick = () => runTask('song_analysis');
  $$('#mv-body .song-f').forEach(el => el.onchange = () =>
    mvSave({song: {...(MV.song || {}), [el.dataset.k]: el.value.trim()}}));
  $('#ls').onchange = e => mvSave({lipsync_pct: +e.target.value});
  $('#st').onchange = e => mvSave({style: e.target.value.trim() || 'hoạt hình 2D'});
  $('#asp').onchange = e => mvSave({aspect: e.target.value});
  $('#mv-cm').onchange = e => mvSave({chat_mode: e.target.value});
  $('#mx').onchange = e => mvSave({max_short_sec: Math.max(3, Math.min(10, +e.target.value || 8))});
  $('#script').onchange = e => mvSave({script: e.target.value});
  $('#do-script').onclick = async () => {
    if (MV.script && !confirm('Muse sẽ viết kịch bản mới thay cho kịch bản hiện tại. Tiếp tục?')) return;
    if (!MV.song?.singer_gender && !confirm('Chưa phân tích bài hát — kịch bản sẽ không bám theo giọng hát/chủ đề. Vẫn viết?')) return;
    await mvSave({lipsync_pct: mode === 'singer' ? +$('#ls').value : pct, style: $('#st').value.trim() || 'hoạt hình 2D'});
    runTask('script');
  };
  bindNext();
}

// ---------- bước 3: nhân vật & bối cảnh ----------
// thẻ nhân vật/bối cảnh: ảnh, tên, mô tả, Muse vẽ / sửa ảnh / import / khoá
function assetCard(a) {
  const fromVideo = MV.kind === 'model' && a.kind === 'character' && MV.ref_video_url;
  return `<div class="acard ${a.locked ? 'locked' : ''}" data-a="${a.id}">
      <div class="aimg ${a.kind} ${['model', 'pose'].includes(MV.kind) && a.kind === 'character' ? 'portrait' : ''}" style="${a.image_url ? `background-image:url('${a.image_url}')` : ''}">${a.image_url ? '' : '<span>Chưa có ảnh</span>'}
        ${a.locked ? '<span class="vtag">🔒 Đã khoá</span>' : ''}</div>
      <div style="padding:10px">
        <input type="text" class="a-name" value="${esc(a.name)}" ${a.locked ? 'disabled' : ''}>
        <textarea class="a-desc" style="min-height:90px;font-family:inherit;margin-top:6px" ${a.locked ? 'disabled' : ''}>${esc(a.description || '')}</textarea>
        <div class="row" style="gap:6px;margin-top:8px">
          ${a.locked ? `<button class="btn sm" data-unlock>Mở khoá</button>` : `
            <button class="btn sm" data-gen>${a.image_url ? 'Muse vẽ lại' : 'Muse vẽ'}</button>
            ${a.image_url ? '<button class="btn sm" data-fix>Sửa ảnh…</button>' : ''}
            <label class="btn sm" style="margin:0">Import ảnh<input type="file" accept="image/*" data-import hidden></label>
            ${fromVideo ? '<button class="btn sm" data-frame title="Lấy khung hình đang dừng ở video mẫu phía trên">Lấy từ video</button>' : ''}
            ${a.image_url ? '<button class="btn sm primary" data-lock>🔒 Khoá</button>' : ''}
            <button class="btn sm danger" data-del>Xoá</button>`}
        </div>
        ${busyAsset(a.id) ? '<div class="hint" style="margin-top:6px">Muse đang vẽ…</div>' : ''}
      </div></div>`;
}
function bindAssetCards() {
  for (const el of $$('#mv-body [data-a]')) {
    const id = el.dataset.a, q = s => el.querySelector(s);
    const patch = f => api('/api/mv/assets/' + id, {method: 'PATCH', json: f}).catch(e => toast(e.message));
    const reload = () => mvPoll().then(() => mvRender(true));
    q('.a-name').onchange = e => patch({name: e.target.value.trim()});
    q('.a-desc').onchange = e => patch({description: e.target.value});
    const on = (sel, fn) => { const b = q(sel); if (b) b.onclick = fn; };
    on('[data-gen]', async () => { await patch({description: q('.a-desc').value}); genAsset(id); });
    on('[data-fix]', () => fixDialog('Sửa ảnh', 'Nhập các điểm cần sửa trên ảnh (Muse vẽ lại dựa trên ảnh hiện tại):', fb => genAsset(id, fb)));
    on('[data-lock]', async () => { await patch({locked: 1}); reload(); });
    on('[data-unlock]', async () => { await patch({locked: 0}); reload(); });
    on('[data-del]', async () => { if (confirm('Xoá mục này?')) { await api('/api/mv/assets/' + id, {method: 'DELETE'}); reload(); } });
    on('[data-frame]', async () => {
      const v = $('#ref-video');
      try { await api(`/api/mv/assets/${id}/frame`, {json: {t: v ? v.currentTime : 0}}); toast('Đã lấy khung hình từ video mẫu'); } catch (e) { toast(e.message); }
      reload();
    });
    const imp = q('[data-import]');
    if (imp) imp.onchange = async e => {
      const fd = new FormData(); fd.append('file', e.target.files[0]);
      try { await api(`/api/mv/assets/${id}/image`, {method: 'POST', body: fd}); toast('Đã import ảnh'); } catch (er) { toast(er.message); }
      reload();
    };
  }
}
async function addAsset(kind) {
  const name = prompt(kind === 'character' ? 'Tên nhân vật' : kind === 'prop' ? 'Tên đạo cụ' : 'Tên bối cảnh');
  if (!name) return;
  await api(`/api/mv/${MV.id}/assets`, {json: {kind, name}}).catch(e => toast(e.message));
  mvPoll().then(() => mvRender(true));
}

// nút "Muse vẽ tất cả" cho nhân vật / bối cảnh chưa khoá
function drawAllBtn(kind, items) {
  const n = items.filter(a => !a.locked).length, run = MV.tasks.some(t => t.kind === 'asset_images' && t.args?.kind === kind && ['running', 'queued'].includes(t.status));
  if (!items.length) return '';
  return `<button class="btn sm primary" data-drawall="${kind}" ${run || !n ? 'disabled' : ''} title="${n ? `Vẽ ${n} mục chưa khoá, 3 ảnh cùng lúc` : 'Tất cả đã khoá'}">
    ${run ? 'Muse đang vẽ…' : `🎨 Muse vẽ tất cả ${kind === 'character' ? 'nhân vật' : 'bối cảnh'}${n ? ` (${n})` : ''}`}</button>`;
}
function stepAssets() {
  const card = assetCard;
  const chars = MV.assets.filter(a => a.kind === 'character'), locs = MV.assets.filter(a => a.kind === 'location');
  const unlocked = MV.assets.filter(a => !a.locked).length;
  $('#mv-body').innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between">
      <span class="hint" style="max-width:640px">Muse đọc kịch bản và liệt kê nhân vật/bối cảnh chính. Sheet nhân vật có nhiều góc nhìn và biểu cảm của cùng một thiết kế để Muse tham chiếu đúng khi đổi góc máy hoặc cảm xúc. Mỗi mục: tự thiết kế rồi <b>Import ảnh</b>, hoặc để <b>Muse vẽ</b>. Ưng ảnh nào thì <b>Khoá</b> — ảnh khoá được gửi kèm mọi short. Với video theo kịch bản, thiết kế nhân vật chính giữ đầu tròn đen, dáng người que, trang phục và phụ kiện nhận diện.</span>
      <button class="btn primary" id="do-assets" ${busy('assets') ? 'disabled' : ''}>${busy('assets') ? 'Muse đang phân tích…' : MV.assets.length ? 'Muse phân tích lại' : 'Muse phân tích nhân vật & bối cảnh'}</button></div>
      <div class="row" style="gap:8px;margin-top:12px"><label for="mv-region" style="margin:0">Phong cách nhân vật & bối cảnh</label>
        <select id="mv-region" style="width:auto">
          <option value="" ${!MV.region ? 'selected' : ''}>Tự do (theo kịch bản)</option>
          <option value="eu" ${MV.region === 'eu' ? 'selected' : ''}>Châu Âu</option>
          <option value="asia" ${MV.region === 'asia' ? 'selected' : ''}>Châu Á</option></select>
        <span class="hint">Áp dụng khi Muse phân tích và vẽ. Đổi phong cách thì bấm "Muse phân tích lại" để mô tả theo phong cách mới.</span></div></div>
    <div class="row" style="justify-content:space-between"><h2 style="font-size:15px">Nhân vật (${chars.length})</h2>
      <span class="row" style="gap:6px">${drawAllBtn('character', chars)}<button class="btn sm" data-add="character">+ Thêm nhân vật</button></span></div>
    <div class="agrid">${chars.map(card).join('') || '<div class="hint">Chưa có nhân vật</div>'}</div>
    <div class="row" style="justify-content:space-between;margin-top:22px"><h2 style="font-size:15px">Bối cảnh (${locs.length})</h2>
      <span class="row" style="gap:6px">${drawAllBtn('location', locs)}<button class="btn sm" data-add="location">+ Thêm bối cảnh</button></span></div>
    <div class="agrid">${locs.map(card).join('') || '<div class="hint">Chưa có bối cảnh</div>'}</div>
    <div class="row" style="justify-content:space-between;margin-top:20px">
      <span class="hint">${MV.assets.length ? (unlocked ? `Còn ${unlocked} mục chưa khoá.` : 'Đã khoá tất cả.') : ''}</span>
      <span class="row"><button class="btn" data-next="2">← Kịch bản</button>${nextBtn(4)}</span></div>`;
  $('#do-assets').onclick = () => runTask('assets');
  $('#mv-region').onchange = e => mvSave({region: e.target.value || null});
  $$('#mv-body [data-drawall]').forEach(b => b.onclick = async () => {
    try { await api(`/api/mv/${MV.id}/draw_all`, {json: {kind: b.dataset.drawall}}); toast('Đã gửi Muse vẽ'); mvPoll(); }
    catch (e) { toast(e.message); }
  });
  $$('#mv-body [data-add]').forEach(b => b.onclick = () => addAsset(b.dataset.add));
  bindAssetCards();
  bindNext();
}
const busyAsset = id => MV.tasks.some(t => t.kind === 'asset_image' && ['running', 'queued'].includes(t.status) && t.args?.asset_id === +id);
async function genAsset(id, feedback) {
  try { await api(`/api/mv/assets/${id}/generate`, {json: {feedback: feedback || ''}}); toast('Đã gửi Muse vẽ'); mvPoll(); }
  catch (e) { toast(e.message); }
}

// hộp thoại nhập điểm cần sửa
function fixDialog(title, label, onOk, extra = '') {
  $('#modal-box').innerHTML = `<h2 style="margin:0 0 12px">${esc(title)}</h2>${extra}
    <label for="fix-text">${esc(label)}</label><textarea id="fix-text" style="min-height:120px;font-family:inherit" placeholder="Ví dụ: nhân vật đang quay lưng, cần quay mặt về camera; tóc phải màu đen…"></textarea>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" id="fix-cancel">Huỷ</button><button class="btn primary" id="fix-ok">Gửi Muse làm lại</button></div>`;
  $('#modal').classList.add('open');
  $('#fix-text').focus();
  $('#fix-cancel').onclick = closeModal;
  $('#fix-ok').onclick = () => { const v = $('#fix-text').value.trim(); if (!v) return toast('Nhập điểm cần sửa'); onOk(v); closeModal(); };
}

// ---------- bước 4: plan short ----------
function stepPlan() {
  const linked = MV.kind === 'mv' || MV.kind === 'scriptvideo';
  const planTask = MV.kind === 'scriptvideo' ? 'stickerman_plan' : 'plan';
  const S4 = MV.shorts, names = MV.assets.map(a => a.name);
  const sung = S4.filter(s => s.lyric?.trim()).length, ls = S4.filter(s => s.lipsync).length;
  const unlocked = MV.assets.filter(a => !a.locked).length;
  $('#mv-body').innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between">
      <span class="hint" style="max-width:640px">${MV.kind === 'scriptvideo' ? `Muse chia kịch bản thành các short ≤ ${MV.max_short_sec}s, giữ đúng thứ tự diễn biến và nhân vật đã khoá. Tạo tuần tự; mỗi short sau gửi kèm ảnh nhân vật chính và khung cuối short trước làm tham chiếu.` : `Muse chia bài hát thành các short ≤ ${MV.max_short_sec}s theo lời + kịch bản, gắn nhân vật/bối cảnh đã khoá và đánh dấu short lip sync (${MV.mv_mode === 'story' ? 'MV kể chuyện: không lip sync' : MV.mv_mode === 'full' ? 'ca sĩ lip sync cả bài' : MV.lipsync_pct + '%'}). MV luôn tạo tuần tự: mỗi short sau dùng khung cuối short trước làm ảnh tham chiếu, giữ đúng trạng thái câu chuyện, nhân vật, góc máy và cảm xúc. Từng short phải chờ short trước hoàn tất.`}</span>
      <button class="btn primary" id="do-plan" ${busy(planTask) ? 'disabled' : ''}>${busy(planTask) ? 'Muse đang lên plan…' : S4.length ? 'Muse lên plan lại' : 'Muse lên plan short'}</button></div>
      ${unlocked ? `<div class="warnbox" style="margin:12px 0 0">Còn ${unlocked} nhân vật/bối cảnh chưa khoá — short chỉ dùng ảnh đã khoá để giữ đồng nhất.</div>` : ''}
    </div>
    ${S4.length ? `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px">
      <h2 style="margin:0">${S4.length} short · ${ls}/${sung} short có lời lip sync</h2><button class="btn sm" id="plan-save">Lưu plan</button></div>
      <table class="plan"><thead><tr><th>#</th><th style="width:110px">Thời gian</th><th>Nội dung</th><th style="width:90px">Lip sync</th><th style="width:80px" title="Short này quay tiếp phân cảnh của short ngay trên: cùng góc máy, bối cảnh, hành động liền mạch">Nối cảnh</th></tr></thead><tbody>
      ${S4.map(s => `<tr data-s="${s.id}"><td>${s.idx}</td><td>${tfmt(s.start)}<br>→ ${tfmt(s.end)}<div class="hint">${(s.end - s.start).toFixed(1)}s</div></td>
        <td><div class="hint" style="margin-bottom:4px">🎵 ${esc(s.lyric || '(nhạc không lời)')}</div>
          <textarea class="p-desc" style="min-height:64px;font-family:inherit">${esc(s.description || '')}</textarea>
          <div class="row" style="gap:6px;margin-top:6px">
            <input type="text" class="p-chars" value="${esc((s.characters || []).join(', '))}" placeholder="Nhân vật (cách nhau dấu phẩy)" list="mv-names" style="flex:1">
            <input type="text" class="p-loc" value="${esc(s.location || '')}" placeholder="Bối cảnh" list="mv-names" style="flex:1"></div></td>
        <td><input type="checkbox" class="p-ls" ${s.lipsync ? 'checked' : ''} ${s.lyric?.trim() ? '' : 'disabled'}></td>
        <td>${linked ? `<input type="checkbox" class="p-cont" ${s.idx > 1 ? 'checked' : ''} disabled title="Short sau luôn nối từ khung cuối short trước">` : `<input type="checkbox" class="p-cont" ${s.cont ? 'checked' : ''} ${s.idx > 1 ? '' : 'disabled'}>`}</td></tr>`).join('')}</tbody></table>
      <datalist id="mv-names">${names.map(n => `<option value="${esc(n)}">`).join('')}</datalist>
      <div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-next="${MV.kind === 'scriptvideo' ? 2 : 3}">← Nhân vật</button>
        <button class="btn primary" id="plan-go">Lưu & bắt đầu tạo short</button></div></div>`
    : '<div class="card"><div class="empty">Chưa có plan.</div></div>'}`;
  $('#do-plan').onclick = () => {
    if (MV.kind === 'scriptvideo' && !MV.assets.some(a => a.kind === 'character' && a.locked && a.image_url))
      return toast('Hãy tạo hoặc import ảnh nhân vật chính rồi khoá ảnh trước khi lên plan');
    if (S4.some(s => s.video_path) && !confirm('Lên plan lại sẽ xoá các short đã tạo. Tiếp tục?')) return;
    runTask(planTask);
  };
  const read = () => $$('#mv-body tr[data-s]').map(tr => {
    const sid = +tr.dataset.s;
    const s = S4.find(x => x.id === sid) || {id: sid};
    return {...s, id: sid, description: tr.querySelector('.p-desc')?.value || '', lipsync: tr.querySelector('.p-ls')?.checked || false, cont: tr.querySelector('.p-cont')?.checked || false,
      characters: (tr.querySelector('.p-chars')?.value || '').split(',').map(x => x.trim()).filter(Boolean), location: tr.querySelector('.p-loc')?.value?.trim() || ''};
  }).filter(s => s.id);
  const save = async () => {
    for (const s of read()) await api('/api/mv/shorts/' + s.id, {method: 'PATCH', json: {description: s.description, lipsync: s.lipsync ? 1 : 0, cont: s.cont ? 1 : 0, characters: s.characters, location: s.location}});
  };
  if ($('#plan-save')) $('#plan-save').onclick = async () => { await save(); toast('Đã lưu plan'); mvPoll().then(() => mvRender(true)); };
  if ($('#plan-go')) $('#plan-go').onclick = async () => {
    await save();
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); }
    catch (e) { toast(e.message); }
    goStep(MV.kind === 'scriptvideo' ? 4 : 5);
  };
  bindNext();
}

// ---------- bước 5: duyệt & xuất ----------
function stepReview() {
  const S5 = MV.shorts, done = S5.filter(s => s.status === 'done').length;
  const TOT = Math.max(MV.duration || 0, ...S5.map(s => s.end || 0));  // tổng theo các short thật, không tin số cũ của dự án
  const isTaskRunning = MV.tasks.some(t => t.kind === 'shorts' && ['queued', 'running'].includes(t.status));
  const left = S5.filter(s => s.status !== 'done').length;
  const html = `
    <div class="row" style="justify-content:space-between;margin-bottom:12px">
      <span><b>${done}/${S5.length}</b> short đã có video${left ? ` · ${left} chưa tạo/lỗi` : ''}
        <span class="hint"> · ${(MV.kind === 'mv' || MV.kind === 'scriptvideo') && MV.chat_mode !== 'chain' ? '1 prompt – 1 chat: Muse tạo lần lượt, nối khung cuối, khoá nhân vật/bối cảnh' : MV.kind === 'mv' || MV.kind === 'scriptvideo' ? 'tạo tuần tự, dùng ảnh nhân vật chính và khung cuối short trước' : MV.chat_mode === 'single' ? '1 chat cho cả MV' : MV.chat_mode === 'chain' ? 'liền mạch, tạo lần lượt' : 'mỗi short 1 chat, 3 short cùng lúc'}
        ${MV.chat_mode === 'single' && MV.chat_session ? ` · <a href="https://muse.ai/thread/${encodeURIComponent(MV.chat_session)}" target="_blank">mở chat MV trên Muse</a>` : ''}</span></span>
      <span class="row">
        ${isTaskRunning ? '<span class="badge b-running">Muse đang tạo short…</span>' : left ? `<button class="btn primary" id="gen-rest">Tạo ${left} short còn lại</button>` : ''}
        <button class="btn ${done ? 'primary' : ''}" id="mv-export" ${done ? '' : 'disabled'}>${MV.kind === 'scriptvideo' ? 'Xuất video' : 'Xuất MV'}</button></span>
    </div>
    ${MV.lyrics?.some(l => l.text?.trim()) ? `<label class="row" style="gap:8px;margin-bottom:12px;cursor:pointer">
      <input type="checkbox" id="mv-showly" ${MV.show_lyrics ? 'checked' : ''}> Hiện lời bài hát dưới video, hiệu ứng chạy từng chữ theo lời hát (karaoke)
      <span class="hint">— áp dụng khi xem trước và khi xuất MV</span></label>` : ''}
    ${MV.exported_url ? `<div class="warnbox" style="border-color:var(--ok)">Đã xuất: <a href="${MV.exported_url}" target="_blank">${esc(MV.exported_url.split('/').pop())}</a> (cũng có trong Thư viện)</div>` : ''}
    ${reviewPanel(S5, TOT, MV.audio_url)}
    ${thumbCard()}
    <div class="row" style="margin-top:14px"><button class="btn" data-next="${MV.kind === 'scriptvideo' ? 3 : 4}">← Plan short</button></div>`;
  const keep = pv ? [pv.clock.currentTime, !pv.clock.paused] : [0, false];
  stopPreview();
  $('#mv-body').innerHTML = html;
  bindReviewPanel(S5, TOT, ...keep);
  if ($('#mv-showly')) $('#mv-showly').onchange = e => mvSave({show_lyrics: e.target.checked ? 1 : 0});
  bindThumbCard();
  if ($('#gen-rest')) $('#gen-rest').onclick = async () => {
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); mvPoll(); } catch (e) { toast(e.message); }
  };
  $('#mv-export').onclick = async () => {
    const b = $('#mv-export'); b.disabled = true; b.textContent = 'Đang xuất…';
    try {
      const r = await api(`/api/mv/${MV.id}/export`, {method: 'POST'});
      toast(r.missing ? `Đã xuất MV (${r.missing} short chưa có video được để màn đen)` : 'Đã xuất MV — có trong Thư viện');
      await mvPoll(); mvRender(true);
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Xuất MV'; }
  };
  bindNext();
}

// thumbnail: nhập yêu cầu, hoặc để trống cho Muse tự thiết kế sao cho thu hút người xem
function thumbCard() {
  const th = MV.thumbs || [];
  return `<div class="card" style="margin-top:14px"><h2 style="margin:0 0 8px">Thumbnail</h2>
    <textarea id="th-prompt" style="min-height:70px;font-family:inherit" placeholder="Mô tả thumbnail bạn muốn (bố cục, nhân vật, cảm xúc, chữ trên ảnh…). Để trống: Muse tự thiết kế thumbnail thu hút người xem bấm vào.">${esc(thumbPrompt)}</textarea>
    <div class="row" style="justify-content:space-between;margin-top:8px">
      <span class="hint">Muse dùng ảnh nhân vật đã khoá + 1 khung hình trong MV để giữ đúng mặt và phong cách; mỗi lần tạo 2 phương án.</span>
      <button class="btn primary" id="th-go" ${busy('thumbnail') ? 'disabled' : ''}>${busy('thumbnail') ? 'Muse đang tạo thumbnail…' : 'Muse tạo thumbnail'}</button></div>
    ${th.length ? `<div class="thgrid">${th.map(u => `<a href="${u}" target="_blank" download title="Mở / tải ảnh"><img src="${u}" loading="lazy"></a>`).join('')}</div>` : ''}
  </div>`;
}
function bindThumbCard() {
  if (!$('#th-go')) return;
  $('#th-prompt').oninput = e => { thumbPrompt = e.target.value; };
  $('#th-go').onclick = () => runTask('thumbnail', {prompt: $('#th-prompt').value.trim()});
}

// danh sách short (trái) + xem trước liên tục như đã ghép (phải); audioUrl = nhạc làm nền, không có thì chạy đồng hồ ảo
function reviewPanel(shorts, total, audioUrl) {
  const isTaskRunning = MV?.tasks?.some(t => t.kind === 'shorts' && ['queued', 'running'].includes(t.status));
  return `<div class="review">
      <div class="slist" id="slist">${shorts.map(s => `
        <div class="sitem" data-s="${s.id}">
          <div class="sthumb" style="${s.thumb_url ? `background-image:url('${s.thumb_url}?v=${s.version}')` : ''}">${s.lipsync ? '<span class="vtag">lip sync</span>' : ''}${s.cont ? '<span class="vtag" style="top:auto;bottom:3px" title="Nối tiếp phân cảnh của short trước">↪ nối</span>' : ''}</div>
          <div class="grow">
            <div class="row" style="justify-content:space-between;gap:6px"><b>#${s.idx} · ${tfmt(s.start)}–${tfmt(s.end)}</b>
              <span class="badge b-${s.status === 'pending' ? 'queued' : s.status}">${SHORT_STATUS[s.status]}</span></div>
            <div class="hint ellip2">${esc(s.lyric || s.description || '')}</div>
            ${s.error ? `<div class="hint" style="color:var(--err)">${esc(s.error.slice(0, 140))}</div>` : ''}
            <div class="row" style="gap:6px;margin-top:4px">
              <button class="btn sm" data-seek="${s.start}">▶ Xem</button>
              ${isTaskRunning && ['queued', 'running'].includes(s.status) ? '' : `<button class="btn sm" data-regen="${s.id}">${s.status === 'done' ? 'Tạo lại…' : s.status === 'failed' ? 'Thử lại…' : 'Tạo…'}</button>`}
            </div>
          </div>
        </div>`).join('')}</div>
      <div class="pv">
        <div class="pvstage" id="pvstage" style="aspect-ratio:${MV.aspect.replace(':', '/')}">
          <video id="pv-a" ${audioUrl ? 'muted' : ''} playsinline preload="auto"></video><video id="pv-b" ${audioUrl ? 'muted' : ''} playsinline preload="auto"></video>
          <div class="pvempty" id="pv-empty"></div>
          <div class="pvlyric" id="pv-ly"></div>
        </div>
        <div class="pvbar" id="pvbar">${shorts.map(s => `<div class="seg ${s.status}" style="flex:${s.end - s.start}" data-seek="${s.start}" title="#${s.idx}"></div>`).join('')}<i id="pv-head"></i></div>
        <div class="row" style="justify-content:space-between;margin-top:8px">
          <span class="row"><button class="btn sm" id="pv-play">▶ Phát</button><span class="hint" id="pv-time">0:00.0 / ${tfmt(total)}</span></span>
          <span class="hint" id="pv-now"></span></div>
        ${audioUrl ? `<audio id="pv-audio" src="${audioUrl}" preload="auto"></audio>` : ''}
        <p class="hint">Xem trước như đã ghép: ${audioUrl ? 'nhạc gốc chạy liên tục, ' : ''}các short nối tiếp theo mốc thời gian.</p>
      </div>
    </div>`;
}
function bindReviewPanel(shorts, total, t0, playing) {
  startPreview(t0, playing, shorts, total);
  $$('#mv-body [data-regen]').forEach(b => b.onclick = () => {
    const s = shorts.find(x => x.id === +b.dataset.regen);
    const nxt = shorts.find(x => x.idx === s.idx + 1 && (x.script_id ?? null) === (s.script_id ?? null));
    fixDialog(`Tạo lại short #${s.idx}`, 'Điểm cần sửa (để trống ô này nếu chỉ muốn tạo lại):', fb => regen(s, fb),
      `<label for="rg-desc">Mô tả short</label><textarea id="rg-desc" style="min-height:80px;font-family:inherit;margin-bottom:12px">${esc(s.description || '')}</textarea>
       ${s.lyric?.trim() ? `<label style="display:flex;gap:8px;align-items:center;margin-bottom:12px"><input type="checkbox" id="rg-ls" ${s.lipsync ? 'checked' : ''}> Lip sync đoạn này</label>` : ''}
       ${versionsBox(s)}
       ${nxt?.cont ? `<label style="display:flex;gap:8px;align-items:center;margin-bottom:12px"><input type="checkbox" id="rg-next" checked> Tạo lại luôn các short nối cảnh phía sau (để vẫn liền mạch với bản mới)</label>` : ''}`);
    // cho phép gửi khi không nhập điểm sửa
    $('#fix-ok').onclick = () => { regen(s, $('#fix-text').value.trim()); closeModal(); };
    $$('#modal-box [data-use]').forEach(u => u.onclick = async () => {
      try {
        await api(`/api/mv/shorts/${s.id}/use`, {json: {v: +u.dataset.use}});
        toast(`Short #${s.idx} đã dùng lại bản ${u.dataset.use}` + (nxt?.cont ? ' — short nối cảnh phía sau có thể cần tạo lại cho khớp' : ''));
        closeModal(); mvPoll().then(() => mvRender(true));
      } catch (e) { toast(e.message); }
    });
  });
}
// các bản đã tạo của 1 short: xem lại và chọn dùng lại bản cũ nếu bản mới không ưng
function versionsBox(s) {
  const vs = s.versions || [];
  if (vs.length < 2) return '';
  return `<label>Các bản đã tạo (${vs.length}) — bấm "Dùng bản này" để quay lại bản cũ, không cần tạo lại</label>
    <div class="vers">${vs.map(v => `<div class="ver ${v.current ? 'cur' : ''}">
      <video src="${v.video_url}" poster="${v.thumb_url || ''}" controls playsinline preload="none"></video>
      <div class="row" style="justify-content:space-between;gap:6px"><b>Bản ${v.v}</b>
        ${v.current ? '<span class="badge b-done">đang dùng</span>' : `<button class="btn sm" data-use="${v.v}">Dùng bản này</button>`}</div></div>`).join('')}</div>`;
}
async function regen(s, feedback) {
  const body = {feedback, description: $('#rg-desc')?.value ?? s.description};
  if ($('#rg-ls')) body.lipsync = $('#rg-ls').checked ? 1 : 0;
  if ($('#rg-next')?.checked) body.with_next = true;
  try { await api(`/api/mv/shorts/${s.id}/regen`, {json: body}); toast(`Đã gửi Muse tạo lại short #${s.idx}`); mvPoll(); }
  catch (e) { toast(e.message); }
}

// ---------- trình xem trước: nhạc gốc (hoặc đồng hồ ảo) làm mốc thời gian, 2 video luân phiên để chuyển short không bị giật ----------
class VirtualClock {  // giống <audio> ở những gì trình xem trước cần, dùng khi không có nhạc
  constructor(total) { this.total = total; this._t = 0; this._start = null; }
  get paused() { return this._start === null; }
  get currentTime() {
    if (this._start === null) return this._t;
    const t = this._t + (performance.now() - this._start) / 1000;
    if (t >= this.total) { this._t = this.total; this._start = null; }
    return Math.min(t, this.total);
  }
  set currentTime(v) { this._t = Math.max(0, Math.min(v, this.total)); if (this._start !== null) this._start = performance.now(); }
  play() { if (this._t >= this.total) this._t = 0; if (this._start === null) this._start = performance.now(); return Promise.resolve(); }
  pause() { this._t = this.currentTime; this._start = null; }
}
let pv = null;
function stopPreview() {
  if (!pv) return;
  cancelAnimationFrame(pv.raf);
  pv.clock.pause();
  pv.vids.forEach(v => v.pause());
  pv = null;
}
// lời karaoke trên khung xem trước — cùng cách chia mốc từng chữ như post/lyrics_overlay.py khi xuất MV
function lyricAt(t) {
  const box = $('#pv-ly');
  if (!box) return;
  const L = MV?.kind === 'mv' && MV.show_lyrics ? (MV.lyrics || []).filter(l => l.text?.trim()) : [];
  const i = L.findIndex((l, k) => t >= l.start - 0.25 && t < Math.min(l.end + 0.35, (L[k + 1]?.start ?? 1e9) - 0.25));
  const key = i < 0 ? '' : i + ':' + L[i].text;
  if (box.dataset.k !== key) {
    box.dataset.k = key;
    box.innerHTML = i < 0 ? '' : L[i].text.split(/\s+/).filter(Boolean).map(w => `<span>${esc(w)}</span>`).join(' ');
  }
  if (i < 0) return;
  const l = L[i], ws = l.text.split(/\s+/).filter(Boolean), wt = ws.map(w => w.length + 2), sum = wt.reduce((a, b) => a + b, 0);
  const span = Math.max(0.3, l.end - l.start) * 0.92;
  let st = l.start, act = -1;
  ws.forEach((w, k) => { if (t >= st) act = k; st += span * wt[k] / sum; });
  [...box.children].forEach((el, k) => el.className = k < act ? 'sung' : k === act ? 'act' : '');
}
function startPreview(t0, autoplay, shorts, total) {
  const stage = $('#pvstage');
  if (!stage) return;
  const clock = $('#pv-audio') || new VirtualClock(total);
  pv = {clock, stage, vids: [$('#pv-a'), $('#pv-b')], front: 0, cur: null, raf: 0};
  const at = t => shorts.find(s => t >= s.start && t < s.end) || shorts[shorts.length - 1];
  const src = s => s?.video_url ? `${s.video_url}?v=${s.version}` : '';
  const load = (v, s) => { const u = src(s); if (u && !v.src.endsWith(u)) { v.src = u; v.load(); } };
  const show = s => {
    const [a, b] = [pv.vids[pv.front], pv.vids[1 - pv.front]];
    if (!src(s)) { a.style.opacity = b.style.opacity = 0; $('#pv-empty').textContent = s ? `Short #${s.idx} chưa có video` : ''; return; }
    $('#pv-empty').textContent = '';
    let v = a;
    if (!a.src.endsWith(src(s))) { if (b.src.endsWith(src(s))) { pv.front = 1 - pv.front; v = b; } else load(a, s); }
    v.style.opacity = 1; pv.vids[1 - pv.front].style.opacity = 0;
    // nạp sẵn short kế tiếp vào video đang ẩn
    const next = shorts[shorts.indexOf(s) + 1];
    if (next) load(pv.vids[1 - pv.front], next);
  };
  const tick = () => {
    if (!pv) return;
    if (!stage.isConnected) { stopPreview(); return; }  // đã rời màn xem
    const hasMusic = !!$('#pv-audio');
    // Không có nhạc riêng: tiếng gốc của short chính là âm thanh của phim. Video đang phát làm đồng hồ chủ để tiếng liền mạch,
    // không bị giật/ngắt do cứ nhảy lại thời điểm theo đồng hồ ảo.
    if (!hasMusic && !clock.paused) {
      const mv = pv.vids[pv.front], ms = pv.cur;
      // chỉ khi đồng hồ vẫn đang nằm trong short hiện tại; nếu người dùng vừa bấm nhảy sang short khác thì không kéo đồng hồ về video cũ
      const inCur = ms && clock.currentTime >= ms.start - 0.3 && clock.currentTime < ms.end + 0.3;
      if (inCur && src(ms) && !mv.paused && !mv.seeking && mv.readyState >= 2 && mv.currentTime > 0.05 && mv.currentTime < (ms.end - ms.start) + 0.1) {
        const vt = ms.start + mv.currentTime;
        if (Math.abs(vt - clock.currentTime) > 0.04) clock.currentTime = vt;
      }
    }
    const t = clock.currentTime, s = at(t);
    if (s !== pv.cur) { pv.cur = s; show(s); $$('#slist .sitem').forEach(el => el.classList.toggle('on', +el.dataset.s === s?.id)); }
    const v = pv.vids[pv.front];
    if (!hasMusic) {  // chỉ video đang hiện được phát tiếng; video nạp sẵn phải im và dừng để không chồng tiếng
      const hid = pv.vids[1 - pv.front];
      if (!hid.paused) hid.pause();
      hid.muted = true;
      v.muted = false; v.volume = 1;
    }
    if (s && src(s)) {
      const want = t - s.start;
      if (v.readyState >= 1 && want < (v.duration || 99) && Math.abs(v.currentTime - want) > 0.25) v.currentTime = want;
      if (clock.paused !== v.paused) clock.paused ? v.pause() : v.play().catch(() => {});
    }
    lyricAt(t);
    $('#pv-time').textContent = `${tfmt(t)} / ${tfmt(total)}`;
    $('#pv-now').textContent = s ? `#${s.idx} ${s.lyric ? '🎵 ' + s.lyric : ''}` : '';
    $('#pv-head').style.left = (100 * t / total) + '%';
    $('#pv-play').textContent = clock.paused ? '▶ Phát' : '❚❚ Dừng';
    pv.raf = requestAnimationFrame(tick);
  };
  const seek = t => { clock.currentTime = t; if (clock.paused) clock.play(); };
  $('#pv-play').onclick = () => clock.paused ? clock.play() : clock.pause();
  $$('#mv-body [data-seek]').forEach(el => el.onclick = () => seek(+el.dataset.seek));
  $('#pvbar').onclick = e => { if (e.target.id === 'pvbar' || e.target.id === 'pv-head') { const r = $('#pvbar').getBoundingClientRect(); seek(total * (e.clientX - r.left) / r.width); } };
  clock.currentTime = t0 || 0;
  if (autoplay) clock.play().catch(() => {});
  tick();
}

// khôi phục màn hình đang mở khi tải lại trang (chờ model.js đăng ký loại của nó)
document.addEventListener('DOMContentLoaded', () => {
  const v = localStorageGet('create-view') || 'types', id = +localStorageGet('mv-open');
  curKind = KINDS[localStorageGet('mv-kind')] ? localStorageGet('mv-kind') : 'mv';
  if (v === 'mv') { if (id) mvOpen(id).catch(() => mvList()); else { showCreate('mv'); mvList(); } }
  else showCreate(v);
});
