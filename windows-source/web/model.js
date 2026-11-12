// Người mẫu tạo dáng: video mẫu -> Muse phân tích -> thiết kế người mẫu (hoặc dùng người trong video) + bối cảnh khoá
// -> vài kịch bản timeline -> tạo short theo kịch bản -> xem & tạo lại short lỗi -> xuất.
// Dùng khung chung ở web/mv.js (MV, KINDS, runTask, busy, assetCard, reviewPanel…).

const MODEL_STYLES = ['Đi biển', 'Cà phê', 'Du lịch', 'Đường phố', 'Công sở', 'Dạ tiệc', 'Thể thao', 'Studio thời trang', 'Vintage',
  'Mua sắm', 'Picnic công viên', 'Rooftop thành phố', 'Hồ bơi / resort', 'Mùa đông tuyết', 'Lễ hội / Tết'];
// các nhóm lựa chọn thêm khi thiết kế người mẫu (chọn 1 hoặc vài, bỏ trống = để Muse tự chọn)
const DESIGN_OPTS = [
  ['aesthetic', 'Gu thời trang', ['Hàn Quốc', 'Douyin / Trung Quốc', 'Nhật Bản', 'Âu Mỹ', 'Old money', 'Y2K', 'Clean girl', 'Streetwear', 'Boho', 'Tối giản', 'Nàng thơ', 'Sporty']],
  ['hair', 'Kiểu tóc', ['Dài uốn sóng', 'Dài thẳng', 'Ngang vai', 'Bob ngắn', 'Đuôi ngựa', 'Búi cao', 'Tết tóc', 'Mái thưa']],
  ['makeup', 'Makeup', ['Trong veo tự nhiên', 'Hàn Quốc má hồng', 'Douyin sắc nét', 'Âu Mỹ đậm', 'Môi đỏ cổ điển']],
  ['body', 'Dáng người', ['Mảnh mai', 'Cao chân dài', 'Đầy đặn quyến rũ', 'Săn chắc thể thao']],
];
const SEXY_LEVELS = ['Kín đáo', 'Vừa phải', 'Gợi cảm', 'Quyến rũ', 'Nóng bỏng'];
const POSE_STYLES = ['Sang chảnh', 'Quyến rũ', 'Dễ thương', 'Gợi cảm nhẹ', 'Cool / cá tính', 'Thanh lịch', 'Năng động', 'Candid tự nhiên', 'Editorial tạp chí'];
const chipVals = sel => $$(sel + ' .chip.on').map(b => b.textContent);
const REGIONS = ['Châu Á', 'Châu Âu', 'Mỹ La-tinh', 'Châu Phi', 'Trung Đông'];
let mdScript = null;  // kịch bản đang xem ở bước 5

KINDS.model = {
  title: 'Người mẫu tạo dáng', projectLabel: 'người mẫu',
  sub: 'Từ 1 video người mẫu mẫu: Muse phân tích, thiết kế người mẫu & bối cảnh khoá, viết vài kịch bản timeline, tạo từng short rồi xem & sửa.',
  field: 'video', optional: true, accept: 'video/*,.mp4,.mov,.m4v,.webm',
  fileLabel: 'Video mẫu <span class="hint">— không bắt buộc · mp4/mov, nên dưới 2 phút</span>',
  info: p => `Người mẫu tạo dáng · ${p.ref_video_path ? `video mẫu ${tfmt(p.duration || 0)}` : 'không có video mẫu'} · ${esc(p.aspect)}`,
  steps: ['Video mẫu', 'Người mẫu & bối cảnh', 'Kịch bản', 'Tạo short', 'Xem & sửa'],
  render: () => [mdVideo, mdDesign, mdScripts, mdGenerate, mdReview],
  done: n => n === 1 ? !MV.ref_video_url || !!MV.analysis
    : n === 2 ? !!(selAsset('sel_model') && selAsset('sel_location'))
    : n === 3 ? MV.scripts.length > 0 : n === 4 ? MV.shorts.some(s => s.status === 'done')
    : MV.shorts.length && MV.shorts.every(s => s.status === 'done'),
};

const assetById = id => MV.assets.find(a => a.id === id);
const selAsset = f => assetById(MV[f]);  // người mẫu / bối cảnh đang chọn để viết kịch bản
// thẻ người mẫu/bối cảnh kèm ô chọn "dùng cho kịch bản" (chỉ chọn 1 mỗi loại)
const pickCard = (a, f) => `<div class="pickcard ${MV[f] === a.id ? 'on' : ''}">
  <label class="pickbar"><input type="radio" name="${f}" value="${a.id}" ${MV[f] === a.id ? 'checked' : ''}> ${MV[f] === a.id ? 'Đã chọn cho kịch bản' : 'Chọn cho kịch bản'}</label>${assetCard(a)}</div>`;
const scriptShorts = id => MV.shorts.filter(s => s.script_id === id);
const scriptLen = id => Math.max(0, ...scriptShorts(id).map(s => s.end));

// ---------- bước 1: video mẫu ----------
function mdVideo() {
  if (!MV.ref_video_url) {  // dự án không có video mẫu: chỉ cần (tuỳ chọn) mô tả phong cách
    $('#mv-body').innerHTML = `
      <div class="card"><h2>Không có video mẫu</h2>
        <p class="hint">Dự án này không dùng video tham chiếu — bỏ qua bước này được. Nếu muốn, ghi vài dòng về phong cách mong muốn (kiểu tạo dáng, nhịp, cảm giác video) để Muse dựa vào khi thiết kế người mẫu, bối cảnh và kịch bản.</p>
        <textarea id="analysis" style="min-height:200px;font-family:inherit;font-size:13.5px" placeholder="Ví dụ: lookbook thời trang đường phố Hàn Quốc, người mẫu tạo dáng tự tin, ánh sáng ban ngày dịu…">${esc(MV.analysis || '')}</textarea>
        <div class="row" style="justify-content:flex-end;margin-top:12px">${nextBtn(2, 'Bỏ qua / Tiếp →')}</div>
      </div>`;
    $('#analysis').onchange = e => mvSave({analysis: e.target.value});
    return bindNext();
  }
  $('#mv-body').innerHTML = `
    <div class="mdgrid">
      <div class="card"><h2>Video mẫu</h2>
        <video id="ref-video" src="${MV.ref_video_url}" controls playsinline class="refvid"></video></div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Muse phân tích video</h2>
        <button class="btn primary" id="do-analysis" ${busy('video_analysis') ? 'disabled' : ''}>${busy('video_analysis') ? 'Muse đang xem video…' : MV.analysis ? 'Phân tích lại' : 'Muse phân tích video'}</button></div>
        <p class="hint">Muse xem video và ghi lại người mẫu, trang phục, bối cảnh, ánh sáng, timeline tư thế & góc máy, nhịp dựng. Bạn sửa được nội dung dưới đây — các bước sau dựa vào nó.</p>
        <textarea id="analysis" style="min-height:420px;font-family:inherit;font-size:13.5px" placeholder="Chưa có phân tích">${esc(MV.analysis || '')}</textarea>
        <div class="row" style="justify-content:flex-end;margin-top:12px">${nextBtn(2)}</div>
      </div>
    </div>`;
  $('#do-analysis').onclick = () => { if (!MV.analysis || confirm('Phân tích lại sẽ thay nội dung hiện tại. Tiếp tục?')) runTask('video_analysis'); };
  $('#analysis').onchange = e => mvSave({analysis: e.target.value});
  bindNext();
}

// ---------- bước 2: người mẫu & bối cảnh ----------
function mdDesign() {
  const sp = MV.model_spec || {};
  const hasVideo = !!MV.ref_video_url;
  const src = hasVideo ? sp.source || 'video' : 'new';
  const chars = MV.assets.filter(a => a.kind === 'character'), locs = MV.assets.filter(a => a.kind === 'location');
  const styles = (sp.style || '').split(',').map(x => x.trim()).filter(Boolean);
  const sm = selAsset('sel_model'), sl = selAsset('sel_location');
  $('#mv-body').innerHTML = `
    <div class="card"><h2>Người mẫu (${chars.length})</h2>
      <div class="seg ${hasVideo ? '' : 'hidden'}" id="md-src" style="margin-bottom:14px">
        <button data-src="video" class="${src === 'video' ? 'on' : ''}">Dùng người mẫu trong video</button>
        <button data-src="new" class="${src === 'new' ? 'on' : ''}">Thiết kế người mẫu mới</button></div>
      <div class="grid2 ${src === 'video' ? 'hidden' : ''}" id="md-new" style="margin-bottom:14px">
        <div><label>Giới tính</label><div class="seg" id="md-gender">${['Nữ', 'Nam'].map(g => `<button data-v="${g}" class="${(sp.gender || 'Nữ') === g ? 'on' : ''}">${g}</button>`).join('')}</div></div>
        <div><label for="md-region">Khu vực / nét người</label><select id="md-region">${REGIONS.map(r => `<option ${sp.region === r ? 'selected' : ''}>${r}</option>`).join('')}</select></div>
        <div><label for="md-age">Độ tuổi</label><input type="text" id="md-age" value="${esc(sp.age || '20–25')}"></div>
      </div>
      <label>Chủ đề / bối cảnh <span class="hint">— chọn 1 hoặc vài, dùng cho cả người mẫu, bối cảnh và kịch bản</span></label>
      <div class="chips" id="md-styles">${MODEL_STYLES.map(x => `<button class="chip ${styles.includes(x) ? 'on' : ''}">${x}</button>`).join('')}</div>
      <input type="text" id="md-style-more" placeholder="Chủ đề khác (tuỳ chọn)" value="${esc(styles.filter(x => !MODEL_STYLES.includes(x)).join(', '))}" style="margin:8px 0 14px">
      <div class="${src === 'video' ? 'hidden' : ''}">
      ${DESIGN_OPTS.map(([k, label, opts]) => { const on = (sp[k] || '').split(',').map(x => x.trim());
        return `<label>${label}</label><div class="chips" id="md-${k}" style="margin-bottom:12px">${opts.map(x => `<button class="chip ${on.includes(x) ? 'on' : ''}">${x}</button>`).join('')}</div>`; }).join('')}
      <label>Mức gợi cảm của trang phục</label>
      <div class="seg" id="md-sexy" style="margin-bottom:14px">${SEXY_LEVELS.map(x => `<button data-v="${x}" class="${(sp.sexy || 'Vừa phải') === x ? 'on' : ''}">${x}</button>`).join('')}</div>
      <div class="row" style="gap:12px;align-items:center;margin-bottom:14px;padding:10px;border:1px dashed var(--border);border-radius:10px">
        ${MV.beauty_url ? `<span class="pthumb" style="width:64px;height:84px;background-image:url('${MV.beauty_url}')"></span>` : ''}
        <span style="flex:1"><b>Ảnh chuẩn gương mặt / vẻ đẹp</b> <span class="hint">— tuỳ chọn. Nên dùng ảnh chính diện, rõ mặt, đủ sáng.</span>
          <label class="row" style="gap:6px;margin:6px 0 0;font-weight:normal"><input type="checkbox" id="md-facecopy" ${sp.face_copy === false ? '' : 'checked'}> Giữ nét mặt giống 100% ảnh này <span class="hint">(chỉ đổi trang phục, tóc, makeup — chỉ dùng ảnh của chính bạn hoặc người mẫu đã đồng ý)</span></label>
          <span class="hint">Bỏ tick = chỉ lấy gu, thần thái, tỷ lệ làm chuẩn, gương mặt mới.</span></span>
        <label class="btn sm" style="margin:0">${MV.beauty_url ? 'Đổi ảnh' : 'Tải ảnh lên'}<input type="file" accept="image/*" id="md-beauty" hidden></label>
        ${MV.beauty_url ? '<button class="btn sm danger" id="md-beauty-del">Bỏ</button>' : ''}
      </div></div>
      <div class="grid2">
        <div><label for="md-outfit">Trang phục</label><input type="text" id="md-outfit" value="${esc(sp.outfit || '')}" placeholder="${src === 'video' ? 'Để trống = giữ như trong video' : 'Ví dụ: váy maxi hoa nhí, mũ cói'}"></div>
        <div><label for="md-notes">Ghi chú thêm</label><input type="text" id="md-notes" value="${esc(sp.notes || '')}" placeholder="Ví dụ: tóc buộc cao, đeo kính râm"></div>
      </div>
      <div class="row" style="justify-content:space-between;margin-top:14px">
        <span class="hint">${src === 'video' ? 'Muse viết mô tả rồi vẽ ảnh người mẫu theo khung hình trong video mẫu.' : 'Muse thiết kế như stylist tạp chí (món điểm nhấn, phối chất liệu, phụ kiện, tóc, makeup) và vẽ cùng lúc nhiều phương án khác hẳn nhau để bạn chọn.'} Người mẫu cũ vẫn giữ trong danh sách.</span>
        <span class="row" style="gap:6px">${src === 'video' ? '' : `<select id="md-variants" style="width:auto">${[1, 2, 3, 4].map(n => `<option value="${n}" ${n === 3 ? 'selected' : ''}>${n} phương án</option>`).join('')}</select>`}
        <button class="btn primary" id="do-model" ${busy('model_design') ? 'disabled' : ''}>${busy('model_design') ? 'Muse đang thiết kế…' : chars.length ? 'Muse thiết kế thêm' : 'Muse thiết kế người mẫu'}</button></span></div>
      ${src === 'video' ? `<details style="margin-top:12px"><summary class="hint">Video mẫu — tua tới khung hình đẹp rồi bấm "Lấy từ video" trên thẻ người mẫu để dùng thẳng khung hình đó</summary>
        <video id="ref-video" src="${MV.ref_video_url}" controls playsinline class="refvid" style="max-height:360px;margin-top:8px"></video></details>` : ''}
      <div class="agrid" style="margin-top:14px">${chars.map(a => pickCard(a, 'sel_model')).join('') || `<div class="hint">Chưa có người mẫu.${src === 'video' ? ' Hoặc bấm "+ Thêm người mẫu" rồi "Lấy từ video".' : ''}</div>`}</div>
      <button class="btn sm" data-add="character" style="margin-top:10px">+ Thêm người mẫu</button>
    </div>
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Bối cảnh (${locs.length})</h2>
      <span class="row"><select id="md-nloc" style="width:auto">${[2, 3, 4, 5].map(n => `<option value="${n}" ${n === 3 ? 'selected' : ''}>${n} bối cảnh</option>`).join('')}</select>
        <button class="btn" id="do-locs" ${busy('locations') ? 'disabled' : ''}>${busy('locations') ? 'Muse đang đề xuất…' : locs.length ? 'Muse đề xuất thêm' : 'Muse đề xuất bối cảnh'}</button>
        ${locs.some(a => !a.image_url && !a.locked) ? '<button class="btn" id="draw-locs">Muse vẽ tất cả</button>' : ''}
        <button class="btn sm" data-add="location">+ Thêm bối cảnh</button></span></div>
      <div class="agrid">${locs.map(a => pickCard(a, 'sel_location')).join('') || '<div class="hint">Chưa có bối cảnh — Muse đề xuất theo style đã chọn và video mẫu.</div>'}</div>
    </div>
    <div class="row" style="justify-content:space-between">
      <span class="hint">Đã chọn: <b>${sm ? esc(sm.name) : '— chưa chọn người mẫu'}</b> · <b>${sl ? esc(sl.name) : '— chưa chọn bối cảnh'}</b></span>
      <span class="row"><button class="btn" data-next="1">← Video mẫu</button><button class="btn primary" id="md-to-scripts">${MV.kind === 'pose' ? 'Chọn pose với lựa chọn này →' : 'Viết kịch bản với lựa chọn này →'}</button></span></div>`;

  const spec = () => ({
    ...(MV.model_spec || {}),
    ...Object.fromEntries(DESIGN_OPTS.map(([k]) => [k, chipVals('#md-' + k).join(', ')])),
    sexy: $('#md-sexy .on')?.dataset.v || '',
    face_copy: $('#md-facecopy') ? $('#md-facecopy').checked : (MV.model_spec || {}).face_copy,
    source: $('#md-src .on').dataset.src, gender: $('#md-gender .on')?.dataset.v || '', region: $('#md-region').value,
    age: $('#md-age').value.trim(), outfit: $('#md-outfit').value.trim(), notes: $('#md-notes').value.trim(),
    style: [...$$('#md-styles .chip.on').map(b => b.textContent), ...$('#md-style-more').value.split(',').map(x => x.trim()).filter(Boolean)].join(', '),
  });
  const saveSpec = () => mvSave({model_spec: spec()});
  $$('#md-src button').forEach(b => b.onclick = async () => { $$('#md-src button').forEach(x => x.classList.toggle('on', x === b)); await saveSpec(); mvRender(true); });
  $$('#md-gender button').forEach(b => b.onclick = () => { $$('#md-gender button').forEach(x => x.classList.toggle('on', x === b)); saveSpec(); });
  $$('#md-styles .chip').forEach(b => b.onclick = () => { b.classList.toggle('on'); saveSpec(); });
  DESIGN_OPTS.forEach(([k]) => $$(`#md-${k} .chip`).forEach(b => b.onclick = () => { b.classList.toggle('on'); saveSpec(); }));
  $$('#md-sexy button').forEach(b => b.onclick = () => { $$('#md-sexy button').forEach(x => x.classList.toggle('on', x === b)); saveSpec(); });
  $('#md-beauty').onchange = async e => {
    const fd = new FormData(); fd.append('file', e.target.files[0]);
    try { MV = await api(`/api/mv/${MV.id}/beauty_ref`, {method: 'POST', body: fd}); toast('Đã tải ảnh chuẩn vẻ đẹp'); mvRender(true); } catch (er) { toast(er.message); }
  };
  if ($('#md-beauty-del')) $('#md-beauty-del').onclick = async () => { MV = await api(`/api/mv/${MV.id}/beauty_ref`, {method: 'DELETE'}); mvRender(true); };
  if ($('#md-facecopy')) $('#md-facecopy').onchange = saveSpec;
  ['#md-region', '#md-age', '#md-outfit', '#md-notes', '#md-style-more'].forEach(sel => $(sel).onchange = saveSpec);
  $('#do-model').onclick = async () => {
    await saveSpec(); runTask('model_design', {...spec(), variants: +($('#md-variants')?.value || 1)});
  };
  $('#do-locs').onclick = async () => { await saveSpec(); runTask('locations', {count: +$('#md-nloc').value}); };
  if ($('#draw-locs')) $('#draw-locs').onclick = async () => {
    for (const a of locs.filter(a => !a.image_url && !a.locked)) await api(`/api/mv/assets/${a.id}/generate`, {json: {}}).catch(e => toast(e.message));
    toast('Đã gửi Muse vẽ các bối cảnh'); mvPoll();
  };
  $$('#mv-body [data-add]').forEach(b => b.onclick = () => addAsset(b.dataset.add));
  $$('#mv-body .pickbar input').forEach(r => r.onchange = async () => { await mvSave({[r.name]: +r.value}); mvRender(true); });
  $('#md-to-scripts').onclick = () => {
    if (!sm || !sl) return toast('Tích chọn 1 người mẫu và 1 bối cảnh trước');
    if (!sm.image_url || !sl.image_url) return toast('Người mẫu/bối cảnh đã chọn chưa có ảnh — bấm Muse vẽ hoặc Import ảnh');
    goStep(3);
  };
  bindAssetCards();
  bindNext();
}

// ---------- bước 3: kịch bản ----------
function mdScripts() {
  const sm = selAsset('sel_model'), sl = selAsset('sel_location'), ready = !!(sm && sl);
  const thumb = a => a ? `<span class="row" style="gap:8px"><span class="pthumb" style="${a.image_url ? `background-image:url('${a.image_url}')` : ''}"></span><b>${esc(a.name)}</b></span>` : '<span class="hint">chưa chọn</span>';
  const defLen = Math.max(5, Math.round(Math.min(MV.duration || 15, 30)));
  $('#mv-body').innerHTML = `
    <div class="card"><h2>Viết kịch bản timeline</h2>
      <div class="row" style="gap:24px;margin-bottom:14px;align-items:center">
        <span><span class="hint">Người mẫu</span><br>${thumb(sm)}</span><span><span class="hint">Bối cảnh</span><br>${thumb(sl)}</span>
        <button class="btn sm" data-next="2">Đổi người mẫu / bối cảnh</button></div>
      ${ready ? '' : '<div class="warnbox">Quay lại bước 2 và tích chọn 1 người mẫu + 1 bối cảnh.</div>'}
      <div class="grid2">
        <div><label for="sc-len">Độ dài kịch bản (giây)</label><input type="number" id="sc-len" min="5" max="120" value="${defLen}"></div>
        <div><label for="sc-max">Độ dài tối đa mỗi short (giây)</label><input type="number" id="sc-max" min="3" max="10" value="${MV.max_short_sec}"></div>
        <div><label for="sc-asp">Khung hình</label><select id="sc-asp">${['9:16', '16:9', '1:1'].map(a => `<option ${a === MV.aspect ? 'selected' : ''}>${a}</option>`).join('')}</select></div>
        <div><label for="sc-cm">Cách gửi short lên Muse</label><select id="sc-cm">
          <option value="chain" ${MV.chat_mode === 'chain' ? 'selected' : ''}>Liền mạch — short sau quay tiếp từ khung cuối short trước (khuyên dùng, chạy lần lượt)</option>
          <option value="new" ${MV.chat_mode === 'new' ? 'selected' : ''}>Mỗi short 1 chat mới — nhanh, 3 short cùng lúc, cảnh không nối nhau</option>
          <option value="single" ${MV.chat_mode === 'single' ? 'selected' : ''}>1 chat cho cả dự án — gọn, chạy lần lượt</option>
          <option value="batch" ${MV.chat_mode === 'batch' ? 'selected' : ''}>1 prompt – 1 chat: Muse tự tạo lần lượt các short (≤10s), nối khung cuối, khoá nhân vật/bối cảnh</option></select></div>
        <div><label for="sc-pose">Kiểu tạo dáng</label><select id="sc-pose">
          <option value="photo" ${['still', 'move', 'ootd'].includes((MV.model_spec || {}).pose) ? '' : 'selected'}>Chụp ảnh nhiều pose — mỗi cảnh 2 pose có phong cách, cắt cảnh đổi góc (khuyên dùng)</option>
          <option value="ootd" ${(MV.model_spec || {}).pose === 'ootd' ? 'selected' : ''}>Đi dạo OOTD — đi về phía máy, xoay người, khoe phụ kiện, có cắt cảnh (kiểu Douyin)</option>
          <option value="still" ${(MV.model_spec || {}).pose === 'still' ? 'selected' : ''}>Đứng yên 1 chỗ, đổi pose chụp ảnh</option>
          <option value="move" ${(MV.model_spec || {}).pose === 'move' ? 'selected' : ''}>Có đi lại, xoay người (1 cú máy liền)</option></select></div>
        <div style="grid-column:1/-1" id="sc-pstyle-box" class="${['still', 'move', 'ootd'].includes((MV.model_spec || {}).pose) ? 'hidden' : ''}">
          <label>Phong cách pose <span class="hint">— chọn 1 hoặc vài; mỗi lần viết kịch bản tool bốc ngẫu nhiên các pose khác nhau trong phong cách đã chọn (bỏ trống = trộn tất cả)</span></label>
          <div class="chips" id="sc-pstyle">${POSE_STYLES.map(x => `<button class="chip ${((MV.model_spec || {}).pose_styles || []).includes(x) ? 'on' : ''}">${x}</button>`).join('')}</div></div>
        <div><label for="sc-notes">Ý tưởng / ghi chú cho Muse</label><input type="text" id="sc-notes" placeholder="Ví dụ: tông ánh sáng hoàng hôn, nhiều pose ngồi"></div>
      </div>
      <div class="row" style="justify-content:space-between;margin-top:14px">
        <span class="hint">Mỗi lần Muse viết 1 kịch bản cho người mẫu + bối cảnh đang chọn. Bấm "Tạo thêm kịch bản" để có thêm (ý tưởng khác, không xoá kịch bản cũ).</span>
        <button class="btn primary" id="do-scripts" ${busy('model_scripts') || !ready ? 'disabled' : ''}>${busy('model_scripts') ? 'Muse đang viết…' : MV.scripts.length ? '+ Tạo thêm kịch bản' : 'Muse viết kịch bản'}</button></div>
    </div>
    ${MV.scripts.map((sc, i) => `
    <div class="card" data-sc="${sc.id}">
      <div class="row" style="justify-content:space-between;margin-bottom:6px">
        <input type="text" class="sc-title" value="${esc(sc.title)}" style="font-weight:600;max-width:420px">
        <span class="row"><span class="hint">${scriptShorts(sc.id).length} short · ${tfmt(scriptLen(sc.id))}</span>
          <button class="btn sm danger" data-del-sc="${sc.id}">Xoá kịch bản</button></span></div>
      ${sc.model_id ? `<p class="hint" style="margin:0 0 4px">Người mẫu: <b>${esc(assetById(sc.model_id)?.name || '(đã xoá)')}</b> · Bối cảnh: <b>${esc(assetById(sc.location_id)?.name || '(đã xoá)')}</b></p>` : ''}
      ${sc.concept ? `<p class="hint" style="margin:0 0 10px">${esc(sc.concept)}</p>` : ''}
      <table class="plan"><thead><tr><th>#</th><th style="width:110px">Thời gian</th><th>Tạo dáng / góc máy</th></tr></thead><tbody>
      ${scriptShorts(sc.id).map(s => `<tr data-s="${s.id}"><td>${s.idx}</td><td>${tfmt(s.start)}<br>→ ${tfmt(s.end)}<div class="hint">${(s.end - s.start).toFixed(1)}s</div></td>
        <td><textarea class="p-desc" style="min-height:60px;font-family:inherit">${esc(s.description || '')}</textarea></td></tr>`).join('')}
      </tbody></table>
    </div>`).join('') || '<div class="card"><div class="empty">Chưa có kịch bản.</div></div>'}
    <div class="row" style="justify-content:space-between"><button class="btn" data-next="2">← Người mẫu & bối cảnh</button>${nextBtn(4)}</div>`;
  $$('#sc-pstyle .chip').forEach(b => b.onclick = () => b.classList.toggle('on'));
  $('#sc-pose').onchange = e => $('#sc-pstyle-box').classList.toggle('hidden', e.target.value !== 'photo');
  $('#sc-max').onchange = e => mvSave({max_short_sec: Math.max(3, Math.min(10, +e.target.value || 6))});
  $('#sc-asp').onchange = e => mvSave({aspect: e.target.value});
  $('#sc-cm').onchange = e => mvSave({chat_mode: e.target.value});
  $('#do-scripts').onclick = async () => {
    await mvSave({max_short_sec: Math.max(3, Math.min(10, +$('#sc-max').value || 6)), aspect: $('#sc-asp').value});
    runTask('model_scripts', {count: 1, duration: Math.max(5, +$('#sc-len').value || defLen), notes: $('#sc-notes').value.trim(), pose: $('#sc-pose').value, pose_styles: chipVals('#sc-pstyle')});
  };
  $$('#mv-body .sc-title').forEach(i => i.onchange = e =>
    api('/api/mv/scripts/' + e.target.closest('[data-sc]').dataset.sc, {method: 'PATCH', json: {title: e.target.value.trim()}}));
  $$('#mv-body tr[data-s]').forEach(tr => {
    const patch = f => api('/api/mv/shorts/' + tr.dataset.s, {method: 'PATCH', json: f}).catch(e => toast(e.message));
    tr.querySelector('.p-desc').onchange = e => patch({description: e.target.value});
  });
  $$('#mv-body [data-del-sc]').forEach(b => b.onclick = async () => {
    if (!confirm('Xoá kịch bản này cùng các short của nó?')) return;
    await api('/api/mv/scripts/' + b.dataset.delSc, {method: 'DELETE'}); mvPoll().then(() => mvRender(true));
  });
  bindNext();
}

// ---------- bước 4: tạo short ----------
function mdGenerate() {
  $('#mv-body').innerHTML = `
    <p class="hint">${MV.chat_mode === 'chain' ? 'Liền mạch: tạo lần lượt, mỗi short gửi kèm khung hình cuối của short trước để Muse quay tiếp. Nếu tạo lại 1 short ở giữa, nên tạo lại cả các short sau nó.' : MV.chat_mode === 'single' ? 'Gửi lần lượt vào 1 chat Muse của dự án.' : 'Muse tạo 3 short cùng lúc, mỗi short 1 chat.'} Mỗi short là 1 lượt tạo video trên Muse. Video tải về được tự chỉnh màu kiểu footage máy quay thật.</p>
    ${MV.scripts.map(sc => {
      const S = scriptShorts(sc.id), done = S.filter(s => s.status === 'done').length;
      const left = S.filter(s => ['pending', 'failed'].includes(s.status)).length;
      return `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:12px">
        <span><b>${esc(sc.title)}</b> <span class="hint">· ${done}/${S.length} short xong · ${tfmt(scriptLen(sc.id))}</span></span>
        <span class="row">${left ? `<button class="btn primary" data-gen-sc="${sc.id}">Tạo ${left} short${S.some(s => s.status === 'failed') ? ' (gồm short lỗi)' : ''}</button>` : ''}
          ${done ? `<button class="btn" data-view-sc="${sc.id}">Xem & sửa →</button>` : ''}</span></div>
        <div class="gshorts">${S.map(s => `<div class="gshort" title="${esc(s.description)}">
          <div class="sthumb" style="aspect-ratio:${MV.aspect.replace(':', '/')};width:100%;${s.thumb_url ? `background-image:url('${s.thumb_url}?v=${s.version}')` : ''}"></div>
          <div class="row" style="justify-content:space-between;gap:4px;margin-top:4px"><span class="hint">#${s.idx} · ${(s.end - s.start).toFixed(1)}s</span>
            <span class="badge b-${s.status === 'pending' ? 'queued' : s.status}">${SHORT_STATUS[s.status]}</span></div></div>`).join('')}</div>
      </div>`;
    }).join('') || '<div class="card"><div class="empty">Chưa có kịch bản — quay lại bước 3.</div></div>'}
    <div class="row" style="justify-content:space-between"><button class="btn" data-next="3">← Kịch bản</button>${nextBtn(5)}</div>`;
  $$('#mv-body [data-gen-sc]').forEach(b => b.onclick = async () => {
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {script_id: +b.dataset.genSc}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); mvPoll(); }
    catch (e) { toast(e.message); }
  });
  $$('#mv-body [data-view-sc]').forEach(b => b.onclick = () => { mdScript = +b.dataset.viewSc; goStep(5); });
  bindNext();
}

// ---------- bước 5: xem & sửa ----------
function mdReview() {
  if (!MV.scripts.some(sc => sc.id === mdScript)) mdScript = MV.scripts[0]?.id ?? null;
  const S = scriptShorts(mdScript), total = scriptLen(mdScript);
  const done = S.filter(s => s.status === 'done').length;
  const left = S.filter(s => ['pending', 'failed'].includes(s.status)).length;
  const keep = pv ? [pv.clock.currentTime, !pv.clock.paused] : [0, false];
  stopPreview();
  $('#mv-body').innerHTML = MV.scripts.length ? `
    <div class="row" style="justify-content:space-between;margin-bottom:12px">
      <div class="seg" id="md-pick">${MV.scripts.map(sc => `<button data-sc="${sc.id}" class="${sc.id === mdScript ? 'on' : ''}">${esc(sc.title)}</button>`).join('')}</div>
      <span class="row"><span class="hint">${done}/${S.length} short xong</span>
        ${left ? `<button class="btn" id="md-rest">Tạo ${left} short còn lại</button>` : ''}</span>
    </div>
    ${S.length ? reviewPanel(S, total, null) : '<div class="card"><div class="empty">Kịch bản này chưa có short.</div></div>'}
    <div class="card" style="margin-top:16px"><h2>Xuất video kịch bản này</h2>
      <div class="row">
        <div style="flex:1;min-width:240px"><label for="md-music">Nhạc nền <span class="hint">— tuỳ chọn, không chọn thì video không có tiếng</span></label>
          <input type="file" id="md-music" accept="audio/*,.mp3,.wav,.m4a"></div>
        <button class="btn primary" id="md-export" ${done ? '' : 'disabled'}>Xuất video</button></div>
      ${MV.exported_url ? `<p class="hint" style="margin:10px 0 0">Lần xuất gần nhất: <a href="${MV.exported_url}" target="_blank">${esc(MV.exported_url.split('/').pop())}</a> (cũng có trong Thư viện)</p>` : ''}
    </div>
    <div class="row" style="margin-top:14px"><button class="btn" data-next="4">← Tạo short</button></div>`
    : '<div class="card"><div class="empty">Chưa có kịch bản.</div></div>';
  if (S.length) bindReviewPanel(S, total, ...keep);
  $$('#md-pick button').forEach(b => b.onclick = () => { mdScript = +b.dataset.sc; stopPreview(); mvRender(true); });
  if ($('#md-rest')) $('#md-rest').onclick = async () => {
    try { const r = await api(`/api/mv/${MV.id}/generate`, {json: {script_id: mdScript}}); toast(`Đã đưa ${r.queued} short vào hàng chờ`); mvPoll(); }
    catch (e) { toast(e.message); }
  };
  if ($('#md-export')) $('#md-export').onclick = async () => {
    const b = $('#md-export'); b.disabled = true; b.textContent = 'Đang xuất…';
    const fd = new FormData(); fd.append('script_id', mdScript);
    if ($('#md-music').files[0]) fd.append('music', $('#md-music').files[0]);
    try {
      const r = await api(`/api/mv/${MV.id}/export`, {method: 'POST', body: fd});
      toast(r.missing ? `Đã xuất (${r.missing} short chưa có video được để màn đen)` : 'Đã xuất — có trong Thư viện');
      await mvPoll(); mvRender(true);
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Xuất video'; }
  };
  bindNext();
}
