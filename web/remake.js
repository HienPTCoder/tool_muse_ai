// Làm lại MV từ video có sẵn: tải MV gốc -> Muse phân tích nhân vật/bối cảnh/đạo cụ + phân cảnh
// -> người dùng thay từng mục bằng ảnh của mình (Muse dựng bản thay thế) -> plan short theo MV gốc
// -> tạo short (khung gốc đã thay + đoạn gốc làm mẫu động tác) -> xuất kèm nhạc gốc.
// Dùng khung chung ở web/mv.js (MV, KINDS, runTask, busy, reviewPanel…).

const RM_KINDS = [['character', 'Nhân vật / ca sĩ / vũ công'], ['location', 'Bối cảnh'], ['prop', 'Đạo cụ']];

KINDS.remake = {
  title: 'Làm lại MV từ video có sẵn', projectLabel: 'MV làm lại',
  sub: 'Tải lên 1 MV nhảy/hát ngắn: Muse phân tích nhân vật, bối cảnh, đạo cụ và từng phân cảnh. Bạn thay ca sĩ, bối cảnh, đạo cụ bằng ảnh của mình — Muse làm lại MV giữ nguyên vũ đạo, góc máy, nhạc gốc.',
  field: 'video', accept: 'video/*,.mp4,.mov,.m4v,.webm',
  fileLabel: 'Video MV gốc <span class="hint">— mp4/mov, nên dưới 1 phút</span>',
  info: p => `Làm lại MV · ${tfmt(p.duration || 0)} · ${esc(p.aspect)}${p.audio_path ? '' : ' · ⚠ video không có tiếng'}`,
  steps: ['MV gốc', 'Thay thế', 'Plan short', 'Tạo & xuất'],
  render: () => [rmSource, rmSwap, rmPlan, rmReview],
  done: n => n === 1 ? !!MV.analysis && MV.shorts.length > 0
    : n === 2 ? MV.assets.some(a => a.mode === 'replace' && a.image_url)
    : n === 3 ? MV.shorts.some(s => s.status !== 'pending') : MV.shorts.length && MV.shorts.every(s => s.status === 'done'),
};

// ---------- bước 1: MV gốc ----------
function rmSource() {
  const L = MV.lyrics || [];
  $('#mv-body').innerHTML = `
    <div class="mdgrid">
      <div class="card"><h2>MV gốc</h2>
        <video id="ref-video" src="${MV.ref_video_url}" controls playsinline class="refvid"></video>
        ${MV.audio_url ? '' : '<div class="warnbox" style="margin-top:10px">Video này không có tiếng — MV xuất ra sẽ im lặng.</div>'}
        ${MV.audio_url ? `<div class="row" style="justify-content:space-between;margin-top:12px">
          <span class="hint" style="max-width:360px">Tuỳ chọn: chép lời trên máy để short hát nhép khớp đúng từng câu (${L.filter(l => l.text).length ? `đã có ${L.filter(l => l.text).length} câu` : 'chưa có'}). Nên làm trước khi phân tích.</span>
          <button class="btn" id="rm-lyrics" ${busy('lyrics') ? 'disabled' : ''}>${busy('lyrics') ? 'Đang chép lời…' : L.length ? 'Chép lại lời' : 'Chép lời + timeline'}</button></div>` : ''}
      </div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Muse phân tích MV</h2>
        <button class="btn primary" id="rm-analyze" ${busy('remake_analysis') ? 'disabled' : ''}>${busy('remake_analysis') ? 'Muse đang xem MV…' : MV.analysis ? 'Phân tích lại' : 'Muse phân tích MV'}</button></div>
        <p class="hint">Muse xem MV, liệt kê nhân vật, bối cảnh, đạo cụ (kèm ảnh cắt từ video) và chia MV thành các phân cảnh theo đúng điểm cắt cảnh — thành plan short ở bước 3.</p>
        <div class="grid2" style="margin-bottom:10px">
          <div><label for="rm-max">Độ dài tối đa mỗi short (giây)</label><input type="number" id="rm-max" min="3" max="10" value="${MV.max_short_sec}"></div>
          <div><label>Khung hình</label><input type="text" value="${esc(MV.aspect)} (theo video gốc)" disabled></div></div>
        <label for="analysis">Tóm tắt MV</label>
        <textarea id="analysis" style="min-height:220px;font-family:inherit;font-size:13.5px" placeholder="Chưa có phân tích">${esc(MV.analysis || '')}</textarea>
        <div class="hint" style="margin-top:6px">${MV.assets.length ? `${MV.assets.filter(a => a.kind === 'character').length} nhân vật · ${MV.assets.filter(a => a.kind === 'location').length} bối cảnh · ${MV.assets.filter(a => a.kind === 'prop').length} đạo cụ · ${MV.shorts.length} short` : ''}</div>
        <div class="row" style="justify-content:flex-end;margin-top:12px">${nextBtn(2)}</div>
      </div>
    </div>`;
  if ($('#rm-lyrics')) $('#rm-lyrics').onclick = () => { if (!L.length || confirm('Chép lại sẽ thay lời hiện tại. Tiếp tục?')) runTask('lyrics'); };
  $('#rm-max').onchange = e => mvSave({max_short_sec: Math.max(3, Math.min(10, +e.target.value || 6))});
  $('#rm-analyze').onclick = async () => {
    if (MV.shorts.some(s => s.video_path) && !confirm('Phân tích lại sẽ thay plan short (mất các short đã tạo) và các mục chưa khoá. Tiếp tục?')) return;
    await mvSave({max_short_sec: Math.max(3, Math.min(10, +$('#rm-max').value || 6))});
    runTask('remake_analysis');
  };
  $('#analysis').onchange = e => mvSave({analysis: e.target.value});
  bindNext();
}

// ---------- bước 2: thay thế ----------
function rmCard(a) {
  const rep = a.mode === 'replace', refs = a.ref_urls || [];
  const tall = a.kind === 'character' ? 'portrait' : a.kind;
  return `<div class="acard ${a.locked ? 'locked' : ''}" data-a="${a.id}">
    <div class="row" style="gap:0">
      <div class="aimg ${tall}" style="flex:1;${a.orig_url ? `background-image:url('${a.orig_url}')` : ''}" title="Trong MV gốc">${a.orig_url ? '' : '<span>Chưa có ảnh gốc</span>'}<span class="vtag">Gốc</span></div>
      ${rep ? `<div class="aimg ${tall}" style="flex:1;${a.image_url ? `background-image:url('${a.image_url}')` : ''}" title="Bản thay thế">${a.image_url ? '' : '<span>Chưa có bản thay</span>'}<span class="vtag">${a.locked ? '🔒 ' : ''}Thay</span></div>` : ''}
    </div>
    <div style="padding:10px">
      <input type="text" class="a-name" value="${esc(a.name)}" ${a.locked ? 'disabled' : ''}>
      <textarea class="a-desc" style="min-height:70px;font-family:inherit;margin-top:6px" ${a.locked ? 'disabled' : ''} placeholder="Mô tả / yêu cầu thêm (ví dụ: giữ trang phục như gốc, hoặc mặc áo trắng của tôi)">${esc(a.description || '')}</textarea>
      <div class="seg" style="margin-top:8px"><button data-mode="keep" class="${rep ? '' : 'on'}" ${a.locked ? 'disabled' : ''}>Giữ như gốc</button>
        <button data-mode="replace" class="${rep ? 'on' : ''}" ${a.locked ? 'disabled' : ''}>Thay bằng của tôi</button></div>
      ${rep ? `<div style="margin-top:8px"><div class="hint">Ảnh của bạn (${refs.length}/8)${a.kind === 'character' ? ' — ảnh ⭐ là <b>mặt chuẩn</b>, được gửi kèm ở MỌI bước: chọn ảnh cận mặt chính diện, rõ nét, thấy rõ kiểu tóc, không đeo kính râm/mũ. Thêm 2–4 ảnh nghiêng 2 bên + toàn thân.' : ''}</div>
        <div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px">${refs.map((u, i) => `<span style="position:relative">
          <span class="pthumb" style="background-image:url('${u}');${a.kind === 'character' && i === 0 ? 'outline:2px solid var(--warn)' : ''}"></span>
          ${a.kind === 'character' ? (i === 0 ? '<span class="hint" style="display:block;font-size:11px">⭐ mặt chuẩn</span>'
            : a.locked ? '' : `<button class="btn sm" data-mainref="${i}" title="Đặt làm ảnh mặt chuẩn" style="display:block;margin-top:2px;padding:0 4px;font-size:11px">⭐</button>`) : ''}
          ${a.locked ? '' : `<button class="btn sm" data-rmref="${i}" style="position:absolute;top:-6px;right:-6px;padding:0 5px">×</button>`}
          ${a.kind !== 'character' && !a.locked ? `<button class="btn sm" data-useref="${i}" title="Dùng thẳng ảnh này làm bản thay thế" style="display:block;margin-top:2px;padding:0 4px;font-size:11px">Dùng</button>` : ''}</span>`).join('')}
          ${a.locked ? '' : `<label class="btn sm" style="margin:0">+ Tải ảnh<input type="file" accept="image/*" multiple data-refs hidden></label>`}</div></div>` : ''}
      <div class="row" style="gap:6px;margin-top:8px;flex-wrap:wrap">
        ${a.locked ? '<button class="btn sm" data-unlock>Mở khoá</button>' : `
          ${rep && refs.length ? `<button class="btn sm primary" data-gen>${a.image_url ? 'Muse tạo lại' : 'Muse tạo bản thay thế'}</button>` : ''}
          ${rep && a.image_url ? '<button class="btn sm" data-fix>Sửa ảnh…</button><button class="btn sm" data-lock>🔒 Khoá</button>' : ''}
          <button class="btn sm" data-frame title="Lấy khung hình đang dừng ở video gốc phía trên làm ảnh gốc">Ảnh gốc từ video</button>
          <button class="btn sm danger" data-del>Xoá</button>`}
      </div>
      ${busyAsset(a.id) ? '<div class="hint" style="margin-top:6px">Muse đang tạo…</div>' : ''}
    </div></div>`;
}

function rmSwap() {
  const n = MV.assets.filter(a => a.mode === 'replace').length;
  $('#mv-body').innerHTML = `
    <div class="card">
      <p class="hint" style="margin:0">Chọn mục nào <b>thay bằng của tôi</b>, tải ảnh của bạn lên (người: nhiều góc chụp rõ mặt; bối cảnh/đạo cụ: ảnh chụp thật), rồi bấm <b>Muse tạo bản thay thế</b>. Ưng thì <b>Khoá</b>. Mục để "Giữ như gốc" sẽ giữ nguyên; short nào không có mục cần thay thì dùng luôn đoạn MV gốc (không tốn lượt Muse).</p>
      <div class="warnbox" style="margin:10px 0 0">Mặt và kiểu tóc được khoá theo ảnh thật của bạn ở mọi bước (ảnh nhân vật, khung đầu, video). AI vẫn không đảm bảo giống tuyệt đối 100% — ảnh mặt chuẩn càng rõ thì càng giống; short nào lệch mặt bấm "Tạo lại" kèm ghi chú "sửa mặt/tóc giống ảnh thật". Chỉ dùng ảnh của chính bạn hoặc người đã đồng ý.</div>
      <details style="margin-top:10px"><summary class="hint">MV gốc — tua tới khung hình rõ rồi bấm "Ảnh gốc từ video" trên thẻ để đổi ảnh gốc</summary>
        <video id="ref-video" src="${MV.ref_video_url}" controls playsinline class="refvid" style="max-height:340px;margin-top:8px"></video></details>
    </div>
    ${RM_KINDS.map(([k, label]) => {
      const items = MV.assets.filter(a => a.kind === k);
      return `<div class="row" style="justify-content:space-between;margin-top:18px"><h2 style="font-size:15px">${label} (${items.length})</h2>
        <button class="btn sm" data-add="${k}">+ Thêm</button></div>
        <div class="agrid">${items.map(rmCard).join('') || '<div class="hint">Không có</div>'}</div>`;
    }).join('')}
    <div class="row" style="justify-content:space-between;margin-top:20px">
      <span class="hint">${n ? `${n} mục sẽ được thay.` : 'Chưa chọn mục nào để thay.'}</span>
      <span class="row"><button class="btn" data-next="1">← MV gốc</button>${nextBtn(3)}</span></div>`;
  const reload = () => mvPoll().then(() => mvRender(true));
  for (const el of $$('#mv-body [data-a]')) {
    const id = el.dataset.a, q = s => el.querySelector(s), on = (sel, fn) => { const b = q(sel); if (b) b.onclick = fn; };
    const patch = f => api('/api/mv/assets/' + id, {method: 'PATCH', json: f}).catch(e => toast(e.message));
    q('.a-name').onchange = e => patch({name: e.target.value.trim()});
    q('.a-desc').onchange = e => patch({description: e.target.value});
    el.querySelectorAll('[data-mode]').forEach(b => b.onclick = async () => { await patch({mode: b.dataset.mode}); reload(); });
    on('[data-gen]', async () => { await patch({description: q('.a-desc').value}); genAsset(id); });
    on('[data-fix]', () => fixDialog('Sửa ảnh thay thế', 'Nhập các điểm cần sửa (Muse làm lại dựa trên ảnh hiện tại):', fb => genAsset(id, fb)));
    on('[data-lock]', async () => { await patch({locked: 1}); reload(); });
    on('[data-unlock]', async () => { await patch({locked: 0}); reload(); });
    on('[data-del]', async () => { if (confirm('Xoá mục này?')) { await api('/api/mv/assets/' + id, {method: 'DELETE'}); reload(); } });
    on('[data-frame]', async () => {
      const v = $('#ref-video');
      try { await api(`/api/mv/assets/${id}/frame`, {json: {t: v ? v.currentTime : 0}}); toast('Đã lấy ảnh gốc từ video'); } catch (e) { toast(e.message); }
      reload();
    });
    el.querySelectorAll('[data-rmref]').forEach(b => b.onclick = async () => { await api(`/api/mv/assets/${id}/refs/${b.dataset.rmref}`, {method: 'DELETE'}); reload(); });
    el.querySelectorAll('[data-mainref]').forEach(b => b.onclick = async () => { await api(`/api/mv/assets/${id}/refs/${b.dataset.mainref}/main`, {method: 'POST'}); reload(); });
    el.querySelectorAll('[data-useref]').forEach(b => b.onclick = async () => {
      try { await api(`/api/mv/assets/${id}/use_ref`, {json: {i: +b.dataset.useref}}); toast('Đã dùng ảnh này làm bản thay thế'); } catch (e) { toast(e.message); }
      reload();
    });
    const up = q('[data-refs]');
    if (up) up.onchange = async e => {
      const fd = new FormData(); for (const f of e.target.files) fd.append('files', f);
      try { await api(`/api/mv/assets/${id}/refs`, {method: 'POST', body: fd}); toast('Đã tải ảnh lên'); } catch (er) { toast(er.message); }
      reload();
    };
  }
  $$('#mv-body [data-add]').forEach(b => b.onclick = () => addAsset(b.dataset.add));
  bindNext();
}

// ---------- bước 3: plan short ----------
function rmPlan() {
  const S = MV.shorts, names = MV.assets.map(a => a.name);
  const swapped = new Set(MV.assets.filter(a => a.mode === 'replace' && a.image_url).map(a => a.name.toLowerCase()));
  const willSwap = s => [...(s.characters || []), s.location || ''].some(n => swapped.has(n.toLowerCase()));
  const pendingRep = MV.assets.filter(a => a.mode === 'replace' && !a.image_url);
  $('#mv-body').innerHTML = `
    <div class="card"><p class="hint" style="margin:0">Plan bám đúng phân cảnh của MV gốc. Short <b>Thay</b>: Muse vẽ lại khung gốc với nhân vật/bối cảnh/đạo cụ của bạn rồi làm video theo đúng động tác của đoạn gốc. Short <b>Gốc</b>: không có gì cần thay, dùng luôn đoạn MV gốc. "Nối cảnh" = quay tiếp từ khung cuối short trên.</p>
      ${pendingRep.length ? `<div class="warnbox" style="margin:10px 0 0">Chưa có bản thay thế cho: ${pendingRep.map(a => esc(a.name)).join(', ')} — các mục này sẽ giữ như gốc.</div>` : ''}</div>
    ${S.length ? `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px">
      <h2 style="margin:0">${S.length} short · ${S.filter(willSwap).length} short cần Muse tạo · ${S.filter(s => s.lipsync).length} short hát nhép</h2>
      <button class="btn sm" id="plan-save">Lưu plan</button></div>
      <table class="plan"><thead><tr><th>#</th><th style="width:110px">Thời gian</th><th>Nội dung (theo MV gốc)</th><th style="width:70px">Hát nhép</th><th style="width:70px">Nối cảnh</th><th style="width:60px"></th></tr></thead><tbody>
      ${S.map(s => `<tr data-s="${s.id}"><td>${s.idx}</td><td>${tfmt(s.start)}<br>→ ${tfmt(s.end)}<div class="hint">${(s.end - s.start).toFixed(1)}s</div>
          <button class="btn sm" data-seek="${s.start}" style="margin-top:4px">▶ gốc</button></td>
        <td>${s.lyric ? `<div class="hint" style="margin-bottom:4px">🎵 ${esc(s.lyric)}</div>` : ''}
          <textarea class="p-desc" style="min-height:60px;font-family:inherit">${esc(s.description || '')}</textarea>
          <div class="row" style="gap:6px;margin-top:6px">
            <input type="text" class="p-chars" value="${esc((s.characters || []).join(', '))}" placeholder="Nhân vật, đạo cụ (cách nhau dấu phẩy)" list="rm-names" style="flex:1">
            <input type="text" class="p-loc" value="${esc(s.location || '')}" placeholder="Bối cảnh" list="rm-names" style="flex:1"></div></td>
        <td><input type="checkbox" class="p-ls" ${s.lipsync ? 'checked' : ''}></td>
        <td><input type="checkbox" class="p-cont" ${s.cont ? 'checked' : ''} ${s.idx > 1 ? '' : 'disabled'}></td>
        <td><span class="badge ${willSwap(s) ? 'b-running' : 'b-queued'}">${willSwap(s) ? 'Thay' : 'Gốc'}</span></td></tr>`).join('')}</tbody></table>
      <datalist id="rm-names">${names.map(n => `<option value="${esc(n)}">`).join('')}</datalist>
      <details style="margin-top:12px"><summary class="hint">Xem MV gốc</summary>
        <video id="ref-video" src="${MV.ref_video_url}" controls playsinline class="refvid" style="max-height:340px;margin-top:8px"></video></details>
      <div class="row" style="justify-content:space-between;margin-top:14px"><button class="btn" data-next="2">← Thay thế</button>
        <button class="btn primary" id="plan-go">Lưu & bắt đầu tạo short</button></div></div>`
    : '<div class="card"><div class="empty">Chưa có plan — quay lại bước 1 và bấm "Muse phân tích MV".</div></div>'}`;
  const read = () => $$('#mv-body tr[data-s]').map(tr => ({id: +tr.dataset.s, description: tr.querySelector('.p-desc').value,
    lipsync: tr.querySelector('.p-ls').checked ? 1 : 0, cont: tr.querySelector('.p-cont').checked ? 1 : 0,
    characters: tr.querySelector('.p-chars').value.split(',').map(x => x.trim()).filter(Boolean), location: tr.querySelector('.p-loc').value.trim()}));
  const save = async () => { for (const s of read()) { const {id, ...f} = s; await api('/api/mv/shorts/' + id, {method: 'PATCH', json: f}); } };
  $$('#mv-body [data-seek]').forEach(b => b.onclick = () => {
    const v = $('#ref-video'); v.closest('details').open = true; v.currentTime = +b.dataset.seek; v.play();
  });
  if ($('#plan-save')) $('#plan-save').onclick = async () => { await save(); toast('Đã lưu plan'); mvPoll().then(() => mvRender(true)); };
  if ($('#plan-go')) $('#plan-go').onclick = async () => {
    await save();
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); }
    catch (e) { toast(e.message); }
    goStep(4);
  };
  bindNext();
}

// ---------- bước 4: tạo & xuất ----------
function rmReview() {
  const S = MV.shorts, done = S.filter(s => s.status === 'done').length;
  const left = S.filter(s => ['pending', 'failed'].includes(s.status)).length;
  const keep = pv ? [pv.clock.currentTime, !pv.clock.paused] : [0, false];
  stopPreview();
  $('#mv-body').innerHTML = `
    <div class="row" style="justify-content:space-between;margin-bottom:12px">
      <span><b>${done}/${S.length}</b> short đã có video${left ? ` · ${left} chưa tạo/lỗi` : ''}<span class="hint"> · tạo lần lượt theo thứ tự MV</span></span>
      <span class="row">${left ? `<button class="btn" id="rm-rest">Tạo ${left} short còn lại</button>` : ''}
        <button class="btn primary" id="rm-export" ${done ? '' : 'disabled'}>Xuất MV</button></span></div>
    ${MV.exported_url ? `<div class="warnbox" style="border-color:var(--ok)">Đã xuất: <a href="${MV.exported_url}" target="_blank">${esc(MV.exported_url.split('/').pop())}</a> (cũng có trong Thư viện)</div>` : ''}
    ${S.length ? reviewPanel(S, MV.duration, MV.audio_url) : '<div class="card"><div class="empty">Chưa có short.</div></div>'}
    ${thumbCard()}
    <div class="row" style="margin-top:14px"><button class="btn" data-next="3">← Plan short</button></div>`;
  if (S.length) bindReviewPanel(S, MV.duration, ...keep);
  bindThumbCard();
  if ($('#rm-rest')) $('#rm-rest').onclick = async () => {
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); mvPoll(); } catch (e) { toast(e.message); }
  };
  $('#rm-export').onclick = async () => {
    const b = $('#rm-export'); b.disabled = true; b.textContent = 'Đang xuất…';
    try {
      const r = await api(`/api/mv/${MV.id}/export`, {method: 'POST'});
      toast(r.missing ? `Đã xuất (${r.missing} short chưa có video được để màn đen)` : 'Đã xuất MV — có trong Thư viện');
      await mvPoll(); mvRender(true);
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Xuất MV'; }
  };
  bindNext();
}
