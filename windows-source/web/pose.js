// Video hướng dẫn tạo dáng (quảng cáo app tạo dáng kiểu POSTYLE): người mẫu & bối cảnh (dùng chung bước của
// "Người mẫu tạo dáng") -> danh sách pose (dòng 0 = dáng sai mở đầu) -> Muse vẽ ảnh từng pose -> dựng video trên máy:
// dáng sai + dấu X -> điện thoại mở app chọn pose, hiện khung viền -> ảnh đẹp ... -> màn kết logo app.
// Dùng khung chung ở web/mv.js và bước người mẫu/bối cảnh ở web/model.js.

KINDS.pose = {
  title: 'Video hướng dẫn tạo dáng', projectLabel: 'video tạo dáng',
  sub: 'Quảng cáo app tạo dáng: ảnh tạo dáng sai → điện thoại mở app gợi ý pose (khung viền, bấm chọn) → ảnh đẹp, lặp nhiều pose → logo app. Giữ nguyên giao diện app gốc, chỉ thay người mẫu và pose.',
  field: 'video', optional: true, accept: 'video/*,.mp4,.mov,.m4v,.webm',
  fileLabel: 'Video mẫu <span class="hint">— không bắt buộc</span>',
  info: p => `Video hướng dẫn tạo dáng · ${p.shorts.length ? `${p.shorts.length - 1} pose` : 'chưa có pose'} · 9:16`,
  steps: ['Video mẫu', 'Người mẫu & bối cảnh', 'Danh sách pose', 'Ảnh & xuất video'],
  render: () => [mdVideo, mdDesign, psList, psRender],
  done: n => n === 1 ? true
    : n === 2 ? !!(selAsset('sel_model')?.image_url && selAsset('sel_location')?.image_url)
    : n === 3 ? MV.shorts.length > 1 : n === 4 ? !!MV.exported_url && MV.shorts.every(s => s.thumb_url) : false,
};
TASK_LABEL.pose_list = 'Đề xuất pose'; TASK_LABEL.pose_images = 'Vẽ ảnh pose'; TASK_LABEL.pose_image = 'Vẽ lại 1 pose';
TASK_LABEL.pose_render = 'Dựng video (trên máy)'; TASK_LABEL.pose_videos = 'Muse tạo video chuyển động';

// ---------- bước 3: danh sách pose ----------
function psList() {
  const rows = MV.shorts.length ? MV.shorts : [];
  $('#mv-body').innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Danh sách pose (${Math.max(0, rows.length - 1)})</h2>
      <span class="row"><select id="ps-n" style="width:auto">${[3, 4, 5, 6, 7].map(n => `<option value="${n}" ${n === 5 ? 'selected' : ''}>${n} pose</option>`).join('')}</select>
        <button class="btn" id="ps-bank">Bốc từ thư viện (miễn phí)</button>
        <button class="btn primary" id="ps-muse" ${busy('pose_list') ? 'disabled' : ''}>${busy('pose_list') ? 'Muse đang nghĩ…' : 'Muse đề xuất pose'}</button></span></div>
      <p class="hint">Dòng đầu là <b>dáng sai</b> mở video (có dấu X). Các dòng sau là pose app gợi ý — mỗi pose ra 1 ảnh đẹp. Sửa mô tả thoải mái; pose nào đổi mô tả sẽ được vẽ lại.</p>
      <div id="ps-rows">${rows.map((s, i) => `<div class="row ps-row" data-id="${s.id}" style="gap:8px;align-items:flex-start;margin-bottom:8px">
        <b style="width:28px;padding-top:8px">${i === 0 ? '✕' : i}</b>
        <input type="text" class="ps-name" value="${esc(s.lyric || '')}" style="width:180px" ${i === 0 ? 'readonly' : ''}>
        <textarea class="ps-desc" style="flex:1;min-height:54px;font-family:inherit">${esc(s.description || '')}</textarea>
        ${i === 0 ? '<span style="width:34px"></span>' : '<button class="btn sm danger ps-del" title="Xoá pose">✕</button>'}</div>`).join('') || '<div class="hint">Chưa có pose — bấm "Muse đề xuất pose" hoặc "Bốc từ thư viện".</div>'}</div>
      ${rows.length ? '<div class="row" style="justify-content:space-between;margin-top:8px"><button class="btn sm" id="ps-add">+ Thêm pose</button><button class="btn" id="ps-save">Lưu thay đổi</button></div>' : ''}
    </div>
    <div class="row" style="justify-content:space-between"><button class="btn" data-next="2">← Người mẫu & bối cảnh</button>
      <button class="btn primary" id="ps-next">Lưu & vẽ ảnh →</button></div>`;
  const collect = () => $$('#ps-rows .ps-row').map(r => ({id: +r.dataset.id || null, name: r.querySelector('.ps-name').value.trim(),
    description: r.querySelector('.ps-desc').value.trim()})).filter(x => x.description);
  const save = async () => { try { MV = await api(`/api/mv/${MV.id}/poses`, {method: 'PUT', json: {poses: collect()}}); } catch (e) { toast(e.message); } };
  const ready = () => selAsset('sel_model')?.image_url && selAsset('sel_location')?.image_url;
  $('#ps-muse').onclick = () => {
    if (!ready()) return toast('Chọn người mẫu và bối cảnh (đã có ảnh) ở bước 2 trước');
    if (!rows.length || confirm('Thay danh sách pose hiện tại?')) runTask('pose_list', {count: +$('#ps-n').value});
  };
  $('#ps-bank').onclick = () => { if (!rows.length || confirm('Thay danh sách pose hiện tại?')) runTask('pose_list', {count: +$('#ps-n').value, source: 'bank'}); };
  $$('#ps-rows .ps-del').forEach(b => b.onclick = () => { b.closest('.ps-row').remove(); });
  if ($('#ps-add')) $('#ps-add').onclick = () => {
    $('#ps-rows').insertAdjacentHTML('beforeend', `<div class="row ps-row" style="gap:8px;align-items:flex-start;margin-bottom:8px"><b style="width:28px;padding-top:8px">+</b>
      <input type="text" class="ps-name" placeholder="Tên pose" style="width:180px"><textarea class="ps-desc" style="flex:1;min-height:54px;font-family:inherit" placeholder="Tay, chân, thân, hướng đầu, ánh mắt, biểu cảm…"></textarea>
      <button class="btn sm danger ps-del">✕</button></div>`);
    $$('#ps-rows .ps-del').forEach(b => b.onclick = () => b.closest('.ps-row').remove());
  };
  if ($('#ps-save')) $('#ps-save').onclick = async () => { await save(); toast('Đã lưu'); mvRender(true); };
  $('#ps-next').onclick = async () => {
    if (!rows.length) return toast('Chưa có pose');
    await save(); goStep(4);
  };
  bindNext();
}

// ---------- bước 4: ảnh pose & xuất video ----------
const busyPose = id => MV.tasks.some(t => t.kind === 'pose_image' && ['running', 'queued'].includes(t.status) && t.args?.short_id === id);
function psRender() {
  const rows = MV.shorts, missing = rows.filter(s => !s.thumb_url).length;
  const drawing = busy('pose_images'), rendering = busy('pose_render'), filming = busy('pose_videos');
  const noLive = rows.slice(1).filter(s => s.thumb_url && !s.video_url).length;
  $('#mv-body').innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Ảnh pose</h2>
      <span class="row">${missing ? `<button class="btn primary" id="ps-draw" ${drawing ? 'disabled' : ''}>${drawing ? 'Muse đang vẽ…' : `Muse vẽ ${missing} ảnh còn thiếu`}</button>` : ''}
        ${rows.length && !missing ? `<button class="btn" id="ps-redraw" ${drawing ? 'disabled' : ''}>Vẽ lại tất cả</button>` : ''}
        ${rows.length > 1 && !missing ? `<button class="btn ${noLive ? 'primary' : ''}" id="ps-film" ${filming ? 'disabled' : ''}>${filming ? 'Muse đang tạo video…' : noLive ? `Muse tạo ${noLive} video chuyển động` : 'Tạo lại tất cả video'}</button>` : ''}</span></div>
      <p class="hint">Ảnh đầu là dáng sai (mở video, có dấu X). Mỗi pose có <b>video chuyển động</b> (Muse): trên màn hình điện thoại người mẫu từ dáng đứng đơ chuyển vào pose, khớp khung viền rồi được bấm chụp. Không có video thì màn hình điện thoại dùng ảnh tĩnh.</p>
      <div class="agrid">${rows.map((s, i) => `<div class="acard">
        <div class="aimg" style="aspect-ratio:9/16;${s.thumb_url ? `background-image:url('${s.thumb_url}?v=${encodeURIComponent(s.thumb_path || '')}')` : ''}">${s.thumb_url ? '' : `<span class="hint">${s.status === 'running' || busyPose(s.id) ? 'Muse đang vẽ…' : s.status === 'error' ? 'Lỗi' : 'Chưa có ảnh'}</span>`}</div>
        <div style="padding:8px"><b>${i === 0 ? '✕ Dáng sai' : `${i}. ${esc(s.lyric || '')}`}</b>
          ${s.error ? `<div class="hint" style="color:var(--err)">${esc(s.error)}</div>` : ''}
          <div class="row" style="gap:6px;margin-top:6px"><button class="btn sm" data-fix="${s.id}" ${busyPose(s.id) || drawing ? 'disabled' : ''}>Sửa & vẽ lại</button>
          ${s.thumb_url ? `<a class="btn sm" href="${s.thumb_url}" target="_blank">Xem</a>` : ''}
          ${i && s.thumb_url ? `<button class="btn sm" data-film="${s.id}" ${filming ? 'disabled' : ''}>${s.video_url ? 'Tạo lại video' : 'Tạo video'}</button>` : ''}</div>
          ${i && s.video_url ? `<video src="${s.video_url}?v=${s.version}" controls muted loop playsinline style="width:100%;margin-top:6px;border-radius:8px"></video>` : ''}</div></div>`).join('')}</div>
    </div>
    <div class="card"><h2>Xuất video</h2>
      <div class="row" style="gap:12px;align-items:center;margin-bottom:12px">
        <span style="flex:1"><b>Nhạc nền</b> <span class="hint">— ${MV.audio_url ? 'đã có, tự cắt vừa video và giảm dần cuối video' : 'chưa có (video sẽ im lặng). Nên dùng nhạc bắt tai, nhịp nhanh, có bản quyền.'}</span>
          ${MV.audio_url ? `<audio src="${MV.audio_url}" controls style="display:block;margin-top:6px;width:100%"></audio>` : ''}</span>
        <label class="btn sm" style="margin:0">${MV.audio_url ? 'Đổi nhạc' : 'Tải nhạc lên'}<input type="file" accept="audio/*,video/*" id="ps-music" hidden></label>
        ${MV.audio_url ? '<button class="btn sm danger" id="ps-music-del">Bỏ</button>' : ''}</div>
      <div class="row" style="justify-content:space-between">
        <span class="hint">Dựng trên máy (không tốn credit): mở đầu 1,7s · mỗi pose ~4,3s · màn kết logo 4,6s.</span>
        <select id="ps-style" title="Kiểu dựng"><option value="ai">Pose AI tạo pose + 3 kiểu overlay</option><option value="classic">Cổ điển (như video gốc)</option></select>
        <button class="btn primary" id="ps-render" ${rendering || missing ? 'disabled' : ''}>${rendering ? 'Đang dựng…' : MV.exported_url ? 'Dựng lại video' : 'Dựng video'}</button></div>
      ${MV.exported_url ? `<video src="${MV.exported_url}?v=${encodeURIComponent(MV.exported_path)}" controls playsinline style="display:block;max-height:640px;margin:14px auto 0;border-radius:12px"></video>
        <div class="row" style="justify-content:center;margin-top:8px"><a class="btn sm" href="${MV.exported_url}" download>Tải video</a></div>` : ''}
    </div>
    <div class="row"><button class="btn" data-next="3">← Danh sách pose</button></div>`;
  if ($('#ps-draw')) $('#ps-draw').onclick = () => runTask('pose_images');
  if ($('#ps-film')) $('#ps-film').onclick = () => {
    if (noLive || confirm('Tạo lại video chuyển động cho tất cả pose? (tốn credit Muse)')) runTask('pose_videos', noLive ? {} : {redo: true});
  };
  $$('#mv-body [data-film]').forEach(b => b.onclick = () => fixDialog('Tạo lại video chuyển động', 'Cần sửa gì trong video này?', v => runTask('pose_videos', {short_id: +b.dataset.film, feedback: v})));
  if ($('#ps-redraw')) $('#ps-redraw').onclick = () => { if (confirm('Vẽ lại toàn bộ ảnh pose? (tốn credit Muse)')) runTask('pose_images', {redo: true}); };
  $$('#mv-body [data-fix]').forEach(b => b.onclick = () => fixDialog('Sửa & vẽ lại ảnh', 'Cần sửa gì?', async v => {
    try { await api(`/api/mv/shorts/${b.dataset.fix}/pose_regen`, {json: {feedback: v}}); toast('Đã gửi Muse vẽ lại'); mvPoll(); } catch (e) { toast(e.message); }
  }));
  $('#ps-music').onchange = async e => {
    const fd = new FormData(); fd.append('file', e.target.files[0]);
    try { MV = await api(`/api/mv/${MV.id}/music`, {method: 'POST', body: fd}); toast('Đã tải nhạc'); mvRender(true); } catch (er) { toast(er.message); }
  };
  if ($('#ps-music-del')) $('#ps-music-del').onclick = async () => { MV = await api(`/api/mv/${MV.id}/music`, {method: 'DELETE'}); mvRender(true); };
  try { $('#ps-style').value = localStorage.getItem('psStyle') || 'ai'; } catch (e) {}
  $('#ps-style').onchange = e => { try { localStorage.setItem('psStyle', e.target.value); } catch (er) {} };
  $('#ps-render').onclick = () => runTask('pose_render', {music: MV.audio_path || '', style: $('#ps-style').value});
  bindNext();
}
