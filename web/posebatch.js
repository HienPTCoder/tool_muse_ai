// Tạo hàng loạt "Video hướng dẫn tạo dáng": chọn số video -> tool lên kế hoạch (mỗi video 1 người mẫu, 1 bối cảnh,
// 1 bộ pose khác nhau, sửa/đổi từng video được) -> bắt đầu: luồng nền ở server (mv/pose_batch.py) tự chạy từng bước
// cho mọi video, tự thử lại khi Muse lỗi, dựng xong thì hiện video ở đây. Mỗi video vẫn là 1 dự án "tạo dáng" bình thường.

let pbPlan = null;     // kế hoạch đang soạn: {items, opts}
let pbTimer = null;
const PB_SEXY = ['auto', 'Gợi cảm', 'Quyến rũ', 'Nóng bỏng', 'Vừa phải'];

function pbLoadDraft() { try { return JSON.parse(localStorageGet('pb-draft') || 'null'); } catch (e) { return null; } }
function pbSaveDraft() { localStorageSet('pb-draft', JSON.stringify(pbPlan)); }
function pbStop() { clearInterval(pbTimer); pbTimer = null; }

function pbShow() {
  pbPlan = pbPlan || pbLoadDraft();
  const o = pbPlan?.opts || {count: 5, gender: 'mix', sexy: 'auto', poses: 5, render: 'ai', live: true, notes: '', title: ''};
  $('#create-posebatch').innerHTML = `
    <button class="btn sm back-types">← Loại video</button>
    <h1 style="margin-top:10px">Tạo hàng loạt video tạo dáng</h1>
    <p class="sub">Chọn số video muốn tạo 1 lần. Mỗi video có 1 người mẫu, 1 bối cảnh và 1 bộ pose riêng, không trùng nhau và ưu tiên bối cảnh chưa dùng ở các lô trước. Tool tự chạy hết các bước và tự thử lại khi Muse lỗi.</p>
    <div class="card"><h2>1. Lên kế hoạch</h2>
      <div class="grid2">
        <div><label for="pb-count">Số video</label><input type="number" id="pb-count" min="1" max="30" value="${o.count}"></div>
        <div><label for="pb-title">Tên lô</label><input type="text" id="pb-title" value="${esc(o.title)}" placeholder="Mặc định: Lô N"></div>
        <div><label>Người mẫu</label><div class="seg" id="pb-gender">${[['mix', 'Trộn nam & nữ'], ['nu', 'Chỉ nữ'], ['nam', 'Chỉ nam']]
          .map(([v, l]) => `<button data-v="${v}" class="${o.gender === v ? 'on' : ''}">${l}</button>`).join('')}</div></div>
        <div><label for="pb-sexy">Mức gợi cảm</label><select id="pb-sexy">${PB_SEXY.map(v =>
          `<option value="${v}" ${o.sexy === v ? 'selected' : ''}>${v === 'auto' ? 'Ngẫu nhiên (Gợi cảm → Nóng bỏng)' : v}</option>`).join('')}</select></div>
        <div><label for="pb-poses">Số pose mỗi video</label><select id="pb-poses">${[3, 4, 5, 6, 7].map(n =>
          `<option ${o.poses === n ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
        <div><label for="pb-render">Kiểu dựng</label><select id="pb-render">
          <option value="ai" ${o.render === 'ai' ? 'selected' : ''}>Bấm Pose AI tạo pose + 3 kiểu overlay</option>
          <option value="classic" ${o.render === 'classic' ? 'selected' : ''}>Cổ điển (như video gốc)</option></select></div>
      </div>
      <label style="display:flex;gap:8px;align-items:center;margin-top:12px"><input type="checkbox" id="pb-live" ${o.live ? 'checked' : ''} style="width:auto">
        Muse tạo video chuyển động cho từng pose <span class="hint">(người mẫu chuyển dáng như thật; tắt thì dùng ảnh tĩnh, đỡ credit và nhanh hơn)</span></label>
      <label for="pb-notes" style="margin-top:12px">Yêu cầu thêm cho mọi người mẫu <span class="hint">— không bắt buộc</span></label>
      <input type="text" id="pb-notes" value="${esc(o.notes)}" placeholder="Ví dụ: tông màu trang phục pastel, đeo trang sức vàng">
      <div class="row" style="justify-content:space-between;margin-top:14px">
        <span class="hint" id="pb-cost"></span>
        <button class="btn primary" id="pb-make">${pbPlan ? 'Lên lại kế hoạch' : 'Lên kế hoạch'}</button></div>
    </div>
    <div id="pb-plan"></div>
    <div id="pb-batches"></div>`;
  $$('#create-posebatch .back-types').forEach(b => b.onclick = () => showCreate('types'));
  $$('#pb-gender button').forEach(b => b.onclick = () => { $$('#pb-gender button').forEach(x => x.classList.toggle('on', x === b)); pbCost(); });
  ['#pb-count', '#pb-poses', '#pb-live'].forEach(s => $(s).onchange = pbCost);
  $('#pb-make').onclick = pbMake;
  pbCost(); pbDrawPlan(); pbBatches();
  pbStop(); pbTimer = setInterval(pbBatches, 5000);
}

function pbOpts() {
  return {count: Math.max(1, Math.min(30, +$('#pb-count').value || 5)), gender: $('#pb-gender .on').dataset.v,
    sexy: $('#pb-sexy').value, poses: +$('#pb-poses').value, render: $('#pb-render').value, live: $('#pb-live').checked,
    notes: $('#pb-notes').value.trim(), title: $('#pb-title').value.trim()};
}

function pbCost() {
  const o = pbOpts(), n = pbPlan?.items?.length || o.count;
  // mỗi video: 2 phương án người mẫu + 1 bối cảnh + 1 danh sách pose + (pose + 1) ảnh + pose video chuyển động
  const per = 4 + o.poses + 1 + (o.live ? o.poses : 0);
  $('#pb-cost').textContent = `Ước tính ~${n * per} lượt Muse cho ${n} video (≈${per} lượt/video), thời gian ~${Math.ceil(n * per * 2.5 / 3 / 60 * 10) / 10} giờ (Muse chạy song song 3 việc).`;
}

async function pbMake() {
  const o = pbOpts();
  if (pbPlan?.items?.length && !confirm('Lên kế hoạch mới sẽ thay kế hoạch đang soạn. Tiếp tục?')) return;
  try {
    const r = await api('/api/pose_batch/plan', {json: o});
    pbPlan = {items: r.items, opts: o}; pbSaveDraft(); pbDrawPlan(); pbCost();
    $('#pb-make').textContent = 'Lên lại kế hoạch';
  } catch (e) { toast(e.message); }
}

function pbDrawPlan() {
  const box = $('#pb-plan');
  if (!pbPlan?.items?.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px">
      <h2 style="margin:0">2. Kiểm tra kế hoạch (${pbPlan.items.length} video)</h2>
      <span class="row"><button class="btn sm" id="pb-clear">Huỷ kế hoạch</button>
        <button class="btn primary" id="pb-go">Bắt đầu tạo ${pbPlan.items.length} video</button></span></div>
    <p class="hint">Sửa mô tả thoải mái. Bấm <b>Đổi</b> để đổi 1 video sang người mẫu và bối cảnh khác.</p>
    ${pbPlan.items.map((it, i) => `<div class="card" style="margin:10px 0;padding:12px 14px" data-i="${i}">
      <div class="row" style="justify-content:space-between;gap:8px">
        <b>${i + 1}. ${esc(it.title)}</b>
        <span class="row" style="gap:6px">
          ${[it.gender, it.region, it.age, it.body, it.hair, it.sexy].filter(Boolean).map(x => `<span class="badge">${esc(x)}</span>`).join('')}
          <button class="btn sm" data-reroll="${i}">Đổi</button><button class="btn sm danger" data-del="${i}">Bỏ</button></span></div>
      <div class="grid2" style="margin-top:8px">
        <div><label>Người mẫu & trang phục</label><textarea data-f="notes" rows="3">${esc(it.notes)}</textarea></div>
        <div><label>Bối cảnh: ${esc(it.location.name)}</label><textarea data-f="loc" rows="3">${esc(it.location.description)}</textarea></div>
      </div>
      <label style="margin-top:6px">Gợi ý pose</label><textarea data-f="pose_notes" rows="2">${esc(it.pose_notes)}</textarea>
    </div>`).join('')}</div>`;
  $$('#pb-plan [data-i] textarea').forEach(t => t.onchange = () => {
    const it = pbPlan.items[+t.closest('[data-i]').dataset.i];
    if (t.dataset.f === 'loc') it.location.description = t.value; else it[t.dataset.f] = t.value;
    pbSaveDraft();
  });
  $$('#pb-plan [data-reroll]').forEach(b => b.onclick = async () => {
    try {
      pbPlan.items[+b.dataset.reroll] = await api('/api/pose_batch/reroll', {json: {items: pbPlan.items, index: +b.dataset.reroll}});
      pbSaveDraft(); pbDrawPlan();
    } catch (e) { toast(e.message); }
  });
  $$('#pb-plan [data-del]').forEach(b => b.onclick = () => { pbPlan.items.splice(+b.dataset.del, 1); pbSaveDraft(); pbDrawPlan(); pbCost(); });
  $('#pb-clear').onclick = () => { pbPlan = null; pbSaveDraft(); pbDrawPlan(); $('#pb-make').textContent = 'Lên kế hoạch'; };
  $('#pb-go').onclick = async () => {
    const o = {...pbPlan.opts, ...pbOpts()};
    if (!confirm(`Bắt đầu tạo ${pbPlan.items.length} video? Việc này dùng credit Muse (${$('#pb-cost').textContent})`)) return;
    try {
      await api('/api/pose_batch', {json: {...o, items: pbPlan.items}});
      pbPlan = null; pbSaveDraft(); pbDrawPlan(); toast('Đã bắt đầu — tool tự chạy, có thể đóng trang'); pbBatches();
    } catch (e) { toast(e.message); }
  };
}

let pbSig = '';
async function pbBatches() {
  const list = await api('/api/pose_batch').catch(() => null);
  if (!list || !$('#pb-batches')) return;
  const sig = JSON.stringify(list);
  if (sig === pbSig) return;
  pbSig = sig;
  const color = st => st === 'done' ? 'var(--ok, #2a9d4b)' : st === 'error' ? 'var(--danger, #d33)' : 'inherit';
  $('#pb-batches').innerHTML = list.length ? `<h2 style="margin:18px 0 8px">Các lô đã tạo</h2>` + list.map(b => {
    const errs = b.items.filter(it => it.stage === 'error').length;
    return `<div class="card"><div class="row" style="justify-content:space-between">
        <span><b>${esc(b.title)}</b> <span class="hint">· ${fmtTime(b.created)} · ${b.items.length} video · ${b.render === 'ai' ? 'Pose AI + 3 overlay' : 'cổ điển'}${b.live ? '' : ' · ảnh tĩnh'}</span></span>
        <span class="row" style="gap:6px"><span class="badge">${b.done_count}/${b.items.length} xong${errs ? ` · ${errs} lỗi` : ''}</span>
          ${b.status === 'running' ? `<button class="btn sm" data-act="pause" data-b="${b.id}">Tạm dừng</button>` : ''}
          ${b.status === 'paused' ? `<button class="btn sm" data-act="resume" data-b="${b.id}">Tiếp tục</button>` : ''}
          ${errs ? `<button class="btn sm" data-act="retry" data-b="${b.id}">Chạy lại video lỗi</button>` : ''}
          <button class="btn sm danger" data-delb="${b.id}">Xoá khỏi danh sách</button></span></div>
      <div style="height:6px;background:var(--panel2);border-radius:3px;margin:10px 0"><div style="height:6px;border-radius:3px;background:var(--accent);width:${100 * b.done_count / b.items.length}%"></div></div>
      ${b.items.map((it, i) => `<div class="row" style="justify-content:space-between;gap:8px;padding:6px 0;border-top:1px solid var(--border)">
        <span style="flex:1;min-width:200px">${i + 1}. ${esc(it.title)} <span class="hint">· ${esc(it.gender)}, ${esc(it.region)}</span></span>
        <span style="color:${color(it.stage)}">${esc(it.stage_label)}${b.status === 'paused' && !['done', 'error'].includes(it.stage) ? ' (tạm dừng)' : ''}</span>
        <span class="hint" style="flex:1;min-width:160px">${esc(it.msg || '')}</span>
        <span class="row" style="gap:6px">${it.pid ? `<button class="btn sm" data-open="${it.pid}">Mở dự án</button>` : ''}
          ${it.video_url ? `<a class="btn sm" href="${it.video_url}" target="_blank">Xem video</a>` : ''}</span></div>`).join('')}
    </div>`;
  }).join('') : '';
  $$('#pb-batches [data-act]').forEach(x => x.onclick = async () => {
    try { await api(`/api/pose_batch/${x.dataset.b}/${x.dataset.act}`, {method: 'POST'}); pbSig = ''; pbBatches(); } catch (e) { toast(e.message); }
  });
  $$('#pb-batches [data-delb]').forEach(x => x.onclick = async () => {
    if (!confirm('Xoá lô khỏi danh sách? (Dự án và video đã tạo vẫn giữ nguyên)')) return;
    await api(`/api/pose_batch/${x.dataset.delb}`, {method: 'DELETE'}); pbSig = ''; pbBatches();
  });
  $$('#pb-batches [data-open]').forEach(x => x.onclick = () => mvOpen(+x.dataset.open));
}
