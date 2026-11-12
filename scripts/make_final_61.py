"""Assemble the full narrated film: per-short (blur-fill vertical clips, Muse ambience low, narration), concat, music bed, loudnorm."""
import os, sys, sqlite3, subprocess, json
FF='/opt/homebrew/bin/ffmpeg'; FP='/opt/homebrew/bin/ffprobe'
ND, OUT, MUSIC = sys.argv[1], sys.argv[2], sys.argv[3]          # narration dir, output file, music wav
TMP = os.environ['TMP']; os.makedirs(TMP, exist_ok=True)
db = sqlite3.connect('data.db')
rows = db.execute("select idx,video_path,\"end\"-start from mv_shorts where project_id=61 order by idx").fetchall()
parts = []; srt = []; t = 0.0
def sh(*a): subprocess.run(a, check=True)
for idx, vp, dur in rows:
    w, h = map(int, subprocess.check_output([FP,'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','csv=p=0:s=x',vp]).decode().strip().split('x'))
    d = float(subprocess.check_output([FP,'-v','error','-show_entries','format=duration','-of','csv=p=0',vp]))
    nar = f"{ND}/n{idx:02d}.wav"; have = os.path.exists(nar)
    if h > w:   # vertical: blurred fill background + centred sharp copy
        vf = "[0:v]split[a][b];[a]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=24:3[bg];[b]scale=-2:720[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1,fps=24[v]"
    else:
        vf = "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v]"
    af = "[0:a]volume=0.30[a0]"; ins = ['-i', vp]
    if have:
        nd = float(subprocess.check_output([FP,'-v','error','-show_entries','format=duration','-of','csv=p=0',nar]))
        tempo = max(1.0, nd / (d - 0.9)); ins += ['-i', nar]               # speed up only if it would overrun the clip
        tf = f",atempo={min(tempo,1.35):.3f}" if tempo > 1.0 else ""
        af += f";[1:a]adelay=400|400{tf}[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0[a]"
    else: af += ";[a0]anull[a]"
    o = f"{TMP}/c{idx:02d}.mp4"
    sh(FF,'-y','-loglevel','error',*ins,'-filter_complex',vf+";"+af,'-map','[v]','-map','[a]','-t',f"{d:.3f}",
       '-c:v','libx264','-pix_fmt','yuv420p','-crf','19','-preset','medium','-c:a','aac','-ar','44100','-ac','2',o)
    parts.append(o)
    txt = db.execute("select lyric from mv_shorts where project_id=61 and idx=?", (idx,)).fetchone()[0]
    if txt.strip():
        f = lambda x: f"{int(x//3600):02d}:{int(x%3600//60):02d}:{int(x%60):02d},{int((x%1)*1000):03d}"
        srt.append(f"{len(srt)+1}\n{f(t+0.4)} --> {f(t+d-0.3)}\n{txt}\n")
    t += d
    print(idx, 'ok', flush=True)
open(f"{TMP}/list.txt",'w').write(''.join(f"file '{p}'\n" for p in parts))
sh(FF,'-y','-loglevel','error','-f','concat','-safe','0','-i',f"{TMP}/list.txt",'-c','copy',f"{TMP}/all.mp4")
sh(FF,'-y','-loglevel','error','-i',f"{TMP}/all.mp4",'-i',MUSIC,'-filter_complex',
   "[1:a]volume=0.55[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
   '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k',OUT)
open(OUT.rsplit('.',1)[0]+'.srt','w').write("\n".join(srt))
print('FINAL', OUT, round(t,1))
