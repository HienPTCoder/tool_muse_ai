// Phim ngắn Sticker Man: tạo kịch bản phim hoạt hình ngắn hài hước/kịch tính
// -> Thiết kế & KHOÁ nhân vật sticker man đồng bộ (ảnh tham chiếu gửi kèm mọi short)
// -> Lên bảng phân cảnh (hành động, góc máy, lời thoại, nhân vật tham gia)
// -> Tạo từng short hoạt hình bằng Muse -> Ghép phim hoàn chỉnh kèm nhạc nền & phụ đề thoại.

const STICKER_STYLES = [
  ['diecut', 'Sticker 2D viền trắng (Die-cut)', 'Nhân vật dạng sticker dán viền trắng sắc nét, đổ bóng nhẹ, hoạt hình hài hước sinh động.'],
  ['doodle', 'Stickman nét đen tối giản', 'Người que kinh điển nét mực đen trên nền giấy trắng sạch, đầu tròn biểu cảm phong phú dí dỏm.'],
  ['colorful', 'Sticker Douyin màu sắc (Cute Chibi)', 'Nhân vật chibi ngộ nghĩnh, màu pastel tươi tắn rực rỡ, biểu cảm meme hài hước Douyin/TikTok.'],
  ['comic', 'Manga Comic Sticker', 'Phong cách truyện tranh comic strip, biểu cảm kịch tính, nét vẽ tốc độ, góc quay điện ảnh.'],
  ['epic', 'Stickman Chiến đấu Võ thuật', 'Stickman đường nét sắc sảo, hiệu ứng chưởng lực ánh sáng neon glow, hành động kịch tính.'],
];

const STICKER_GENRES = [
  ['comedy', '🤣 Hài hước / Meme đời sống'],
  ['workplace', '💼 Drama công sở / Học đường'],
  ['action', '⚔️ Võ thuật / Hành động kịch tính'],
  ['mystery', '🕵️ Trinh thám / Plot twist bất ngờ'],
  ['life', '💡 Bài học cuộc sống / Kể chuyện triết lý'],
];

const DURATION_PRESETS = [
  [15, '15s', '3 cảnh · Teaser nhanh'],
  [30, '30s', '5 cảnh · Chuẩn Shorts/TikTok'],
  [45, '45s', '8 cảnh · Mini Story'],
  [60, '1 phút (60s)', '10–12 cảnh · Phim ngắn'],
  [90, '1.5 phút (90s)', '15–18 cảnh · Câu chuyện chi tiết'],
  [120, '2 phút (120s)', '20–24 cảnh · Kịch tính cao trào'],
  [150, '2.5 phút (150s)', '25–30 cảnh · Kịch bản dài'],
  [180, '3 phút (180s - Tối đa)', '30–36 cảnh · Phim ngắn đầy đủ'],
];

function fmtDurationLabel(sec) {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (!m) return `${s} giây`;
  if (!rem) return `${m} phút`;
  return `${m} phút ${rem}s`;
}

TASK_LABEL.stickerman_script = 'Viết kịch bản phim sticker';
TASK_LABEL.stickerman_plan = 'Lên bảng phân cảnh sticker';

KINDS.stickerman = {
  title: 'Phim ngắn Sticker Man',
  projectLabel: 'phim sticker',
  sub: 'Phim ngắn hoạt hình sticker man / doodle: tạo & khoá nhân vật sticker đồng bộ, chọn thời lượng tối đa 3 phút, Muse vẽ & tạo chuyển động các short rồi dựng thành phim kèm thoại & nhạc nền.',
  field: 'audio',
  optional: true,
  accept: 'audio/*,.mp3,.wav,.m4a',
  fileLabel: 'Nhạc nền / Voiceover <span class="hint">— không bắt buộc · mp3/wav/m4a</span>',
  info: p => `Phim ngắn Sticker Man · ${p.duration ? fmtDurationLabel(p.duration) : `${p.shorts?.length || 0} cảnh`} · ${esc(p.aspect)} · ${esc(p.style)}`,
  steps: ['Kịch bản & Ý tưởng', 'Đồng bộ nhân vật & Bối cảnh', 'Bảng phân cảnh', 'Tạo video & Duyệt', 'Xuất phim'],
  render: () => [smScript, smAssets, smPlan, smGenerate, smExport],
  done: n => n === 1 ? !!MV.script
    : n === 2 ? MV.assets?.length > 0 && MV.assets.some(a => a.kind === 'character' && a.locked)
    : n === 3 ? MV.shorts?.length > 0
    : n === 4 ? MV.shorts?.length && MV.shorts.every(s => s.status === 'done')
    : !!MV.exported_url,
};

// ==========================================
// BƯỚC 1: Ý TƯỞNG & KỊCH BẢN
// ==========================================
function smScript() {
  const spec = MV.model_spec || {};
  const curGenre = spec.genre || 'comedy';
  const curPreset = spec.style_preset || 'diecut';
  let targetDur = Math.max(10, Math.min(180, +(spec.target_duration || MV.duration || 30)));
  const maxSec = Math.max(4, Math.min(10, +(MV.max_short_sec || 6)));
  let estScenes = spec.scenes_count || Math.max(2, Math.min(36, Math.round(targetDur / Math.max(4, maxSec - 1))));

  $('#mv-body').innerHTML = `
    <div class="card">
      <h2>1. Cấu hình & Phong cách phim Sticker Man</h2>
      <div class="grid2" style="margin-bottom:14px">
        <div>
          <label>Thể loại câu chuyện</label>
          <div class="chips" id="sm-genre-chips">
            ${STICKER_GENRES.map(([k, lbl]) => `<button class="chip ${k === curGenre ? 'on' : ''}" data-val="${k}">${lbl}</button>`).join('')}
          </div>
        </div>
        <div>
          <label>Khung hình video</label>
          <div class="seg" id="sm-aspect-seg">
            <button class="${MV.aspect === '9:16' ? 'on' : ''}" data-aspect="9:16">9:16 (Dọc TikTok/Reels)</button>
            <button class="${MV.aspect === '16:9' ? 'on' : ''}" data-aspect="16:9">16:9 (Ngang YouTube)</button>
            <button class="${MV.aspect === '1:1' ? 'on' : ''}" data-aspect="1:1">1:1 (Vuông)</button>
          </div>
        </div>
      </div>

      <div style="margin-bottom:14px">
        <label>Phong cách hình ảnh Sticker Man</label>
        <div class="chips" id="sm-preset-chips" style="margin-bottom:8px">
          ${STICKER_STYLES.map(([k, lbl, desc]) => `<button class="chip ${k === curPreset ? 'on' : ''}" data-val="${k}" title="${esc(desc)}">${esc(lbl)}</button>`).join('')}
        </div>
        <div class="hint" id="sm-preset-desc" style="background:var(--panel2);padding:8px 12px;border-radius:8px">
          ${esc((STICKER_STYLES.find(x => x[0] === curPreset) || STICKER_STYLES[0])[2])}
        </div>
      </div>

      <div style="margin-bottom:14px;border-top:1px solid var(--border);padding-top:14px">
        <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:6px">
          <label style="margin:0">⏱️ Thời lượng phim (Tối đa 3 phút / 180 giây)</label>
          <b id="sm-dur-display" style="color:var(--accent);font-size:14px">
            ${fmtDurationLabel(targetDur)} (${targetDur}s) · Dự kiến ~${estScenes} cảnh
          </b>
        </div>
        <div class="chips" id="sm-dur-chips" style="margin-bottom:10px">
          ${DURATION_PRESETS.map(([sec, lbl, desc]) => `
            <button class="chip ${Math.abs(sec - targetDur) <= 2 ? 'on' : ''}" data-sec="${sec}" title="${esc(desc)}">${lbl}</button>
          `).join('')}
        </div>
        <div class="row" style="gap:12px;align-items:center;background:var(--panel2);padding:10px 14px;border-radius:10px">
          <input type="range" id="sm-dur-range" min="10" max="180" step="5" value="${targetDur}" style="flex:1;cursor:pointer">
          <div class="row" style="gap:6px">
            <input type="number" id="sm-dur-input" min="10" max="180" value="${targetDur}" style="width:72px;padding:6px;text-align:center;font-weight:600">
            <span class="hint">giây</span>
          </div>
        </div>
      </div>

      <div class="grid2">
        <div>
          <label for="sm-scenes">Số lượng phân cảnh ước tính</label>
          <select id="sm-scenes">
            ${[2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 20, 24, 28, 32, 36].map(n => `
              <option value="${n}" ${n === estScenes ? 'selected' : ''}>${n} cảnh (${(targetDur / n).toFixed(1)}s/cảnh)</option>
            `).join('')}
          </select>
        </div>
        <div>
          <label for="sm-max-sec">Độ dài tối đa mỗi short (giây)</label>
          <input type="number" id="sm-max-sec" min="4" max="10" value="${maxSec}">
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between;margin-bottom:8px">
        <h2 style="margin:0">2. Ý tưởng hoặc tình huống cụ thể</h2>
        <button class="btn primary" id="sm-gen-script" ${busy('stickerman_script') ? 'disabled' : ''}>
          ${busy('stickerman_script') ? 'Muse đang viết kịch bản…' : '🤖 Muse viết kịch bản phim sticker'}
        </button>
      </div>
      <p class="hint">Nhập gợi ý ngắn về chủ đề (ví dụ: "Stickman đi xin việc gặp sếp khó tính và cái kết bất ngờ", hoặc "Người que thi đấu võ đài"), hoặc để trống để Muse tự sáng tạo tình huống hài hước có cú twist.</p>
      <input type="text" id="sm-topic" placeholder="Ví dụ: Stickman trốn bạn gái đi chơi game bị bắt quả tang..." value="${esc(spec.topic || '')}" style="margin-bottom:14px">

      <label for="sm-script-text">Kịch bản chi tiết</label>
      <textarea id="sm-script-text" style="min-height:260px;font-family:inherit;font-size:13.5px" placeholder="Bấm 'Muse viết kịch bản phim sticker' hoặc tự nhập kịch bản của bạn tại đây...">${esc(MV.script || '')}</textarea>

      <div class="row" style="justify-content:flex-end;margin-top:14px;gap:8px">
        <button class="btn" id="sm-trans-script" title="Chuyển kịch bản sang tiếng Anh chuẩn để Muse hiểu tốt nhất">🌐 Dịch sang tiếng Anh</button>
        <button class="btn" id="sm-save-script">Lưu kịch bản</button>
        ${nextBtn(2, 'Tiếp: Đồng bộ nhân vật & Bối cảnh →')}
      </div>
    </div>`;

  function updateDurationUI(newSec) {
    targetDur = Math.max(10, Math.min(180, Math.round(newSec)));
    $('#sm-dur-range').value = targetDur;
    $('#sm-dur-input').value = targetDur;
    $$('#sm-dur-chips .chip').forEach(b => b.classList.toggle('on', Math.abs(+b.dataset.sec - targetDur) <= 2));

    const curMaxSec = Math.max(4, Math.min(10, +$('#sm-max-sec').value || 6));
    estScenes = Math.max(2, Math.min(36, Math.round(targetDur / Math.max(4, curMaxSec - 1))));
    $('#sm-scenes').value = estScenes;
    $('#sm-dur-display').textContent = `${fmtDurationLabel(targetDur)} (${targetDur}s) · Dự kiến ~${estScenes} cảnh`;
    saveSpec({target_duration: targetDur, scenes_count: estScenes});
    mvSave({duration: targetDur});
  }

  $$('#sm-dur-chips .chip').forEach(b => b.onclick = () => updateDurationUI(+b.dataset.sec));
  $('#sm-dur-range').oninput = e => updateDurationUI(+e.target.value);
  $('#sm-dur-input').onchange = e => updateDurationUI(+e.target.value || 30);

  // Bind chips & actions
  $$('#sm-genre-chips .chip').forEach(b => b.onclick = () => {
    $$('#sm-genre-chips .chip').forEach(x => x.classList.toggle('on', x === b));
    saveSpec({genre: b.dataset.val});
  });

  $$('#sm-preset-chips .chip').forEach(b => b.onclick = () => {
    $$('#sm-preset-chips .chip').forEach(x => x.classList.toggle('on', x === b));
    const item = STICKER_STYLES.find(x => x[0] === b.dataset.val) || STICKER_STYLES[0];
    $('#sm-preset-desc').textContent = item[2];
    saveSpec({style_preset: b.dataset.val});
    mvSave({style: item[1]});
  });

  $$('#sm-aspect-seg button').forEach(b => b.onclick = () => {
    $$('#sm-aspect-seg button').forEach(x => x.classList.toggle('on', x === b));
    mvSave({aspect: b.dataset.aspect});
  });

  $('#sm-scenes').onchange = e => {
    estScenes = +e.target.value;
    $('#sm-dur-display').textContent = `${fmtDurationLabel(targetDur)} (${targetDur}s) · Dự kiến ~${estScenes} cảnh`;
    saveSpec({scenes_count: estScenes});
  };

  $('#sm-max-sec').onchange = e => {
    const val = Math.max(4, Math.min(10, +e.target.value || 6));
    mvSave({max_short_sec: val});
    estScenes = Math.max(2, Math.min(36, Math.round(targetDur / Math.max(4, val - 1))));
    $('#sm-scenes').value = estScenes;
    $('#sm-dur-display').textContent = `${fmtDurationLabel(targetDur)} (${targetDur}s) · Dự kiến ~${estScenes} cảnh`;
    saveSpec({scenes_count: estScenes});
  };

  async function saveSpec(fields) {
    const cur = MV.model_spec || {};
    await mvSave({model_spec: {...cur, ...fields}});
  }

  $('#sm-save-script').onclick = async () => {
    await mvSave({script: $('#sm-script-text').value.trim()});
    toast('Đã lưu kịch bản');
  };

  if ($('#sm-trans-script')) {
    $('#sm-trans-script').onclick = async () => {
      const text = $('#sm-script-text').value.trim();
      if (!text) return toast('Chưa có kịch bản để dịch');
      await mvSave({script: text});
      toast('Đang chuyển kịch bản sang tiếng Anh…');
      try {
        const res = await api(`/api/mv/${MV.id}/translate_script`, {method: 'POST'});
        $('#sm-script-text').value = res.script;
        MV.script = res.script;
        toast('Đã chuyển kịch bản sang tiếng Anh thành công');
      } catch (e) { toast(e.message); }
    };
  }

  $('#sm-gen-script').onclick = async () => {
    const topic = $('#sm-topic').value.trim();
    const cur = MV.model_spec || {};
    const dur = Math.max(10, Math.min(180, +$('#sm-dur-input').value || 30));
    const scenes = +$('#sm-scenes').value || Math.round(dur / 5);
    await saveSpec({topic, target_duration: dur, scenes_count: scenes});
    await mvSave({duration: dur});
    if (MV.script && !confirm(`Viết kịch bản mới (${fmtDurationLabel(dur)}) sẽ thay thế kịch bản hiện tại. Tiếp tục?`)) return;
    runTask('stickerman_script', {
      topic,
      genre: cur.genre || 'comedy',
      style_preset: cur.style_preset || 'diecut',
      scenes_count: scenes,
      duration_sec: dur,
    });
  };

  bindNext();
}

// ==========================================
// BƯỚC 2: ĐỒNG BỘ NHÂN VẬT & BỐI CẢNH
// ==========================================
function smAssets() {
  const chars = MV.assets.filter(a => a.kind === 'character');
  const locs = MV.assets.filter(a => a.kind === 'location');

  $('#mv-body').innerHTML = `
    <div class="card" style="background:linear-gradient(135deg, rgba(37,99,235,0.08), rgba(124,58,237,0.08));border-color:rgba(37,99,235,0.25)">
      <div class="row" style="gap:10px;align-items:flex-start">
        <span style="font-size:24px">🔒</span>
        <div>
          <b style="font-size:14px;color:var(--accent)">Cơ chế Đồng Bộ Nhân Vật Sticker Man:</b>
          <div style="font-size:13px;color:var(--text);margin-top:2px;line-height:1.5">
            Khi một nhân vật được bấm <b>"Khoá" (🔒)</b>, ảnh chân dung sticker của nhân vật đó sẽ trở thành <b>ảnh tham chiếu mẫu</b> được đính kèm vào tất cả các phân cảnh mà nhân vật xuất hiện. Muse bắt buộc giữ nguyên 100% đường nét viền, màu áo, phụ kiện và biểu cảm của nhân vật từ đầu đến cuối phim.
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <h2 style="margin:0">Nhân vật Sticker Man (${chars.length})</h2>
          <span class="hint">Khóa nhân vật để làm mẫu tham chiếu đồng bộ</span>
        </div>
        <div class="row">
          <button class="btn primary" id="sm-extract-assets" ${busy('assets') ? 'disabled' : ''}>
            ${busy('assets') ? 'Muse đang đọc kịch bản…' : MV.assets.length ? '🤖 Muse trích xuất lại' : '🤖 Muse trích xuất từ kịch bản'}
          </button>
          ${drawAllBtn('character', chars)}
          <button class="btn" data-add="character">+ Thêm nhân vật</button>
        </div>
      </div>
      <div class="agrid" id="sm-chars-grid" style="margin-bottom:18px">
        ${chars.map(assetCard).join('') || '<div class="empty">Chưa có nhân vật nào. Bấm "Muse trích xuất từ kịch bản" hoặc tự thêm nhân vật.</div>'}
      </div>

      <div class="row" style="justify-content:space-between;align-items:center;margin-top:24px;margin-bottom:12px;border-top:1px solid var(--border);padding-top:16px">
        <div>
          <h2 style="margin:0">Bối cảnh (${locs.length})</h2>
          <span class="hint">Các không gian 2D tối giản làm nền cho sticker man</span>
        </div>
        <div class="row">
          ${drawAllBtn('location', locs)}
          <button class="btn" data-add="location">+ Thêm bối cảnh</button>
        </div>
      </div>
      <div class="agrid" id="sm-locs-grid">
        ${locs.map(assetCard).join('') || '<div class="empty">Chưa có bối cảnh nào. Bấm "Muse trích xuất từ kịch bản" hoặc tự thêm bối cảnh.</div>'}
      </div>
    </div>

    <div class="row" style="justify-content:space-between;margin-top:14px">
      <button class="btn" data-next="1">← Ý tưởng & Kịch bản</button>
      ${nextBtn(3, 'Tiếp: Lên bảng phân cảnh →')}
    </div>`;

  $('#sm-extract-assets').onclick = () => {
    if (!MV.script) return toast('Hãy có kịch bản ở bước 1 trước');
    if (MV.assets.length && !confirm('Trích xuất lại sẽ thay thế các mục chưa khoá. Tiếp tục?')) return;
    runTask('assets');
  };

  $$('#mv-body [data-drawall]').forEach(b => b.onclick = async () => {
    try { await api(`/api/mv/${MV.id}/draw_all`, {json: {kind: b.dataset.drawall}}); toast('Đã gửi Muse vẽ'); mvPoll(); }
    catch (e) { toast(e.message); }
  });

  $$('#mv-body [data-add]').forEach(b => b.onclick = () => addAsset(b.dataset.add));

  bindAssetCards();
  bindNext();
}

// ==========================================
// BƯỚC 3: BẢNG PHÂN CẢNH
// ==========================================
function smPlan() {
  const shorts = MV.shorts || [];
  const chars = MV.assets.filter(a => a.kind === 'character');
  const locs = MV.assets.filter(a => a.kind === 'location');
  const totalPlanSec = shorts.reduce((acc, s) => acc + (s.end - s.start), 0);

  $('#mv-body').innerHTML = `
    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <h2 style="margin:0">Bảng phân cảnh Sticker Man (${shorts.length} cảnh)</h2>
          <span class="hint">Mỗi cảnh tạo 1 short video — tự động gắn đúng ảnh nhân vật đã khoá</span>
        </div>
        <div class="row">
          <button class="btn primary" id="sm-gen-plan" ${busy('stickerman_plan') ? 'disabled' : ''}>
            ${busy('stickerman_plan') ? 'Muse đang lên phân cảnh…' : '🤖 Muse lên bảng phân cảnh'}
          </button>
          <button class="btn" id="sm-add-short">+ Thêm cảnh</button>
          <button class="btn" id="sm-save-plan">Lưu phân cảnh</button>
        </div>
      </div>

      <div class="row" style="justify-content:space-between;align-items:center;background:var(--panel2);padding:8px 12px;border-radius:8px;margin-bottom:12px;font-size:13px">
        <span>⏱️ Tổng thời lượng: <b style="color:var(--accent)">${fmtDurationLabel(totalPlanSec)}</b> (${totalPlanSec.toFixed(1)}s / Tối đa 3 phút · 180s)</span>
        <span class="hint">${totalPlanSec > 180 ? '<span style="color:var(--warn)">⚠️ Đã vượt quá 3 phút (180s)</span>' : 'Độ dài tối ưu'}</span>
      </div>

      <div style="overflow-x:auto">
        <table class="plan" style="min-width:750px">
          <thead>
            <tr>
              <th style="width:50px">#</th>
              <th style="width:110px">Thời gian</th>
              <th style="width:180px">Nhân vật trong cảnh</th>
              <th style="width:130px">Bối cảnh</th>
              <th>Mô tả hành động Sticker Man</th>
              <th style="width:180px">Thoại / Lời dẫn</th>
              <th style="width:70px;text-align:center">Nối cảnh</th>
              <th style="width:40px"></th>
            </tr>
          </thead>
          <tbody id="sm-plan-body">
            ${shorts.map((s, idx) => `
              <tr class="sm-short-row" data-id="${s.id || ''}">
                <td><b>${idx + 1}</b></td>
                <td>
                  <div class="row" style="gap:4px">
                    <input type="number" step="0.5" class="s-start" value="${s.start}" style="width:50px;padding:4px">
                    <span>-</span>
                    <input type="number" step="0.5" class="s-end" value="${s.end}" style="width:50px;padding:4px">
                  </div>
                </td>
                <td>
                  <div class="chips sm-char-chips" style="gap:4px">
                    ${chars.map(c => {
                      const on = (s.characters || []).some(x => x.toLowerCase() === c.name.toLowerCase());
                      return `<button type="button" class="chip sm ${on ? 'on' : ''}" data-name="${esc(c.name)}">${esc(c.name)}</button>`;
                    }).join('') || '<span class="hint">Chưa có nhân vật</span>'}
                  </div>
                </td>
                <td>
                  <select class="s-loc" style="padding:4px 6px">
                    <option value="">(Tự chọn)</option>
                    ${locs.map(l => `<option value="${esc(l.name)}" ${s.location === l.name ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}
                  </select>
                </td>
                <td>
                  <textarea class="s-desc" style="min-height:54px;font-family:inherit;padding:6px;width:100%">${esc(s.description || '')}</textarea>
                </td>
                <td>
                  <input type="text" class="s-lyric" value="${esc(s.lyric || '')}" placeholder="Thoại / phụ đề..." style="padding:4px 6px">
                </td>
                <td style="text-align:center">
                  <input type="checkbox" class="s-cont" ${s.cont ? 'checked' : ''} title="Nối tiếp tư thế từ cuối cảnh trước">
                </td>
                <td>
                  <button class="btn sm danger s-del" title="Xoá cảnh">✕</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      ${!shorts.length ? '<div class="empty" style="margin-top:14px">Chưa có phân cảnh nào. Bấm "Muse lên bảng phân cảnh" để tự động chia kịch bản thành từng cảnh.</div>' : ''}
    </div>

    <div class="row" style="justify-content:space-between;margin-top:14px">
      <button class="btn" data-next="2">← Nhân vật & Bối cảnh</button>
      <button class="btn primary" id="sm-plan-next">Lưu & Bắt đầu tạo short →</button>
    </div>`;

  // Bind character chip toggles in plan table
  $$('.sm-char-chips .chip').forEach(b => b.onclick = () => {
    b.classList.toggle('on');
  });

  $$('.s-del').forEach(b => b.onclick = () => {
    b.closest('.sm-short-row').remove();
  });

  $('#sm-add-short').onclick = () => {
    const rows = $$('.sm-short-row');
    const lastRow = rows[rows.length - 1];
    const lastEnd = lastRow ? +lastRow.querySelector('.s-end').value || 0 : 0;
    if (lastEnd >= 180) return toast('Phim đã đạt thời lượng tối đa 3 phút (180s)');
    let dur = MV.max_short_sec || 5;
    if (lastEnd + dur > 180) dur = Math.max(3, 180 - lastEnd);
    const idx = rows.length + 1;
    const tr = document.createElement('tr');
    tr.className = 'sm-short-row';
    tr.innerHTML = `
      <td><b>${idx}</b></td>
      <td>
        <div class="row" style="gap:4px">
          <input type="number" step="0.5" class="s-start" value="${lastEnd}" style="width:50px;padding:4px">
          <span>-</span>
          <input type="number" step="0.5" class="s-end" value="${lastEnd + dur}" style="width:50px;padding:4px">
        </div>
      </td>
      <td>
        <div class="chips sm-char-chips" style="gap:4px">
          ${chars.map(c => `<button type="button" class="chip sm on" data-name="${esc(c.name)}">${esc(c.name)}</button>`).join('')}
        </div>
      </td>
      <td>
        <select class="s-loc" style="padding:4px 6px">
          <option value="">(Tự chọn)</option>
          ${locs.map(l => `<option value="${esc(l.name)}">${esc(l.name)}</option>`).join('')}
        </select>
      </td>
      <td>
        <textarea class="s-desc" style="min-height:54px;font-family:inherit;padding:6px;width:100%" placeholder="Mô tả hành động của nhân vật..."></textarea>
      </td>
      <td>
        <input type="text" class="s-lyric" placeholder="Thoại..." style="padding:4px 6px">
      </td>
      <td style="text-align:center"><input type="checkbox" class="s-cont"></td>
      <td><button class="btn sm danger s-del">✕</button></td>`;
    tr.querySelector('.s-del').onclick = () => tr.remove();
    $$('.sm-char-chips .chip', tr).forEach(b => b.onclick = () => b.classList.toggle('on'));
    $('#sm-plan-body').appendChild(tr);
  };

  function collectPlan() {
    return $$('.sm-short-row').map((r, i) => {
      const selectedChars = $$('.sm-char-chips .chip.on', r).map(c => c.dataset.name);
      return {
        id: r.dataset.id ? +r.dataset.id : null,
        idx: i + 1,
        start: +r.querySelector('.s-start').value || 0,
        end: +r.querySelector('.s-end').value || 5,
        characters: selectedChars,
        location: r.querySelector('.s-loc').value,
        description: r.querySelector('.s-desc').value.trim(),
        lyric: r.querySelector('.s-lyric').value.trim(),
        cont: r.querySelector('.s-cont').checked,
        lipsync: 0,
      };
    });
  }

  async function savePlanToServer() {
    const plan = collectPlan();
    if (!plan.length) throw new Error('Cần có ít nhất 1 phân cảnh');
    try {
      await api(`/api/mv/${MV.id}/plan`, {method: 'PUT', json: {shorts: plan}});
    } catch {
      await api(`/api/mv/${MV.id}/shorts`, {method: 'PUT', json: plan});
    }
    MV = await api(`/api/mv/${MV.id}`);
  }

  $('#sm-save-plan').onclick = async () => {
    try {
      await savePlanToServer();
      toast('Đã lưu bảng phân cảnh');
      smPlan();
    } catch (e) { toast(e.message); }
  };

  $('#sm-plan-next').onclick = async () => {
    try {
      await savePlanToServer();
      try {
        const res = await api(`/api/mv/${MV.id}/generate`, {method: 'POST'});
        toast(`Đã lưu và đưa ${res.queued} short vào hàng đợi tạo video`);
      } catch (genErr) {
        toast('Đã lưu bảng phân cảnh');
      }
      goStep(4);
    } catch (e) { toast(e.message); }
  };

  $('#sm-gen-plan').onclick = () => {
    if (!MV.script) return toast('Hãy viết kịch bản ở bước 1 trước');
    if (shorts.some(s => s.video_path) && !confirm('Lên lại plan sẽ xoá các video short đã tạo. Tiếp tục?')) return;
    runTask('stickerman_plan');
  };

  bindNext();
}

// ==========================================
// BƯỚC 4: TẠO VIDEO & DUYỆT CẢNH
// ==========================================
function smGenerate() {
  const shorts = MV.shorts || [];
  const nDone = shorts.filter(s => s.status === 'done').length;
  const isGenerating = busy('shorts') || shorts.some(s => ['queued', 'running'].includes(s.status));

  $('#mv-body').innerHTML = `
    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:center">
        <div>
          <h2 style="margin:0">Tạo video các phân cảnh (${nDone}/${shorts.length} xong)</h2>
          <span class="hint">Muse tạo hoạt hình 2D sticker theo đúng nhân vật tham chiếu đã khoá</span>
        </div>
        <div class="row">
          <button class="btn primary" id="sm-start-gen" ${isGenerating ? 'disabled' : ''}>
            ${isGenerating ? 'Muse đang tạo short…' : nDone === shorts.length && nDone > 0 ? 'Tạo lại tất cả' : '🚀 Bắt đầu tạo tất cả các cảnh'}
          </button>
        </div>
      </div>
    </div>

    ${reviewPanel(shorts, MV.duration || shorts.reduce((acc, s) => acc + (s.end - s.start), 0), MV.audio_url)}

    <div class="row" style="justify-content:space-between;margin-top:14px">
      <button class="btn" data-next="3">← Bảng phân cảnh</button>
      ${nextBtn(5, 'Tiếp: Dựng & Xuất phim →')}
    </div>`;

  $('#sm-start-gen').onclick = async () => {
    try {
      await api(`/api/mv/${MV.id}/generate`, {method: 'POST'});
      toast('Đã bắt đầu tạo các cảnh');
      mvRender(true);
    } catch (e) { toast(e.message); }
  };

  bindReviewPanel(shorts, MV.duration || shorts.reduce((acc, s) => acc + (s.end - s.start), 0), 0, false);
  bindNext();
}

// ==========================================
// BƯỚC 5: DỰNG & XUẤT PHIM
// ==========================================
function smExport() {
  const shorts = MV.shorts || [];
  const doneShorts = shorts.filter(s => s.status === 'done' && s.video_path);
  const totalDuration = shorts.reduce((acc, s) => acc + (s.end - s.start), 0);

  $('#mv-body').innerHTML = `
    <div class="grid2">
      <div class="card">
        <h2>Cài đặt xuất phim Sticker Man</h2>
        <p class="hint">Ghép các phân cảnh thành 1 video hoàn chỉnh, thêm nhạc nền và phụ đề.</p>

        <div style="margin-bottom:14px">
          <label for="sm-music-file">File nhạc nền (BGM / Âm thanh)</label>
          <input type="file" id="sm-music-file" accept="audio/*,.mp3,.wav,.m4a">
          <span class="hint">${MV.audio_path ? 'Dự án đã có sẵn file âm thanh gốc.' : 'Không bắt buộc. Nếu không chọn nhạc, video sẽ giữ âm thanh gốc của các cảnh.'}</span>
        </div>

        <div style="margin-bottom:16px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="sm-show-subs" ${MV.show_lyrics ? 'checked' : ''} style="width:auto">
            <span>Hiển thị phụ đề lời thoại (chữ chạy dưới màn hình)</span>
          </label>
        </div>

        <div class="kv" style="margin-bottom:16px;background:var(--panel2);padding:10px;border-radius:8px">
          <div>Tổng số cảnh:</div><div><b>${doneShorts.length} / ${shorts.length} cảnh hoàn thành</b></div>
          <div>Thời lượng phim:</div><div><b>~${fmtDurationLabel(totalDuration)} (${totalDuration.toFixed(1)}s / Tối đa 3 phút)</b></div>
          <div>Khung hình:</div><div>${esc(MV.aspect)}</div>
        </div>

        <button class="btn primary" id="sm-do-export" style="width:100%;padding:10px" ${!doneShorts.length ? 'disabled' : ''}>
          🎬 Ghép & Xuất phim hoàn chỉnh
        </button>
      </div>

      <div class="card">
        <h2>Xem trước phim hoàn chỉnh</h2>
        ${MV.exported_url ? `
          <video src="${MV.exported_url}" controls playsinline style="width:100%;max-height:420px;border-radius:10px;background:#000;display:block"></video>
          <div class="row" style="justify-content:space-between;margin-top:14px">
            <span class="hint">Đã lưu vào Thư viện video</span>
            <a class="btn primary" href="${MV.exported_url}" download="phim_stickerman_${MV.id}.mp4">⬇ Tải về MP4</a>
          </div>
        ` : `
          <div class="empty" style="min-height:220px;display:grid;place-items:center">
            ${doneShorts.length ? 'Chưa xuất phim. Bấm "Ghép & Xuất phim hoàn chỉnh" ở bên trái.' : 'Cần hoàn thành ít nhất 1 cảnh ở bước 4 trước khi xuất.'}
          </div>
        `}
      </div>
    </div>

    <div class="row" style="justify-content:space-between;margin-top:14px">
      <button class="btn" data-next="4">← Tạo video & Duyệt</button>
    </div>`;

  $('#sm-show-subs').onchange = e => mvSave({show_lyrics: e.target.checked ? 1 : 0});

  $('#sm-do-export').onclick = async () => {
    const btn = $('#sm-do-export');
    btn.disabled = true;
    btn.textContent = 'Đang ghép video…';
    const fd = new FormData();
    const mf = $('#sm-music-file').files[0];
    if (mf) fd.append('music', mf);
    try {
      const res = await api(`/api/mv/${MV.id}/export`, {method: 'POST', body: fd});
      MV.exported_url = res.url;
      toast('Đã xuất phim thành công!');
      smExport();
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
      btn.textContent = '🎬 Ghép & Xuất phim hoàn chỉnh';
    }
  };

  bindNext();
}
