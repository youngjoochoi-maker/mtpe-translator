"""
web.py
------
브라우저에서 쓰는 웹 UI(단일 HTML 페이지).

같은 FastAPI 서버가 이 페이지(사람용)와 API(n8n용)를 함께 제공한다.
페이지의 자바스크립트는 서버의 /split, /count, /platform/episodes 를
그대로 호출한다(인증 헤더 X-API-Key 포함).

HTML 을 파이썬 문자열로 내장하여 PyInstaller 로 얼려도 경로 문제가 없다.
"""

# 중괄호가 많은 CSS/JS 를 포함하므로 f-string/format 을 쓰지 않는다.
INDEX_HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>소설 분권</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         margin: 0; background: #f4f5f7; color: #1f2328; }
  @media (prefers-color-scheme: dark) { body { background:#1a1b1e; color:#e6e6e6; } .card{background:#26272b !important;} input,select,textarea{background:#1a1b1e;color:#e6e6e6;border-color:#444 !important;} th{background:#2f3136 !important;} }
  header { background:#2d6cdf; color:#fff; padding:14px 20px; font-size:18px; font-weight:600; }
  .wrap { max-width: 1000px; margin: 0 auto; padding: 16px; }
  .card { background:#fff; border:1px solid #e1e4e8; border-radius:10px; padding:16px; margin-bottom:16px; }
  .card h2 { margin:0 0 12px; font-size:15px; }
  label { font-size:13px; }
  input[type=text], input[type=number], select { padding:7px 9px; border:1px solid #ccc; border-radius:6px; font-size:14px; }
  input[type=text]{ width:100%; }
  button { background:#2d6cdf; color:#fff; border:0; border-radius:6px; padding:9px 16px; font-size:14px; cursor:pointer; }
  button:disabled { background:#9db8e8; opacity:.6; cursor:default; }
  button.sec { background:#5a6b85; }
  .row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:8px 0; }
  #drop { border:2px dashed #b7c3d6; border-radius:10px; padding:26px; text-align:center; color:#667; cursor:pointer; }
  #drop.hover { border-color:#2d6cdf; background:rgba(45,108,223,.06); }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { border:1px solid #e1e4e8; padding:6px 8px; text-align:right; }
  th { background:#f0f2f5; }
  td.l, th.l { text-align:left; }
  .muted { color:#7a828c; font-size:12px; }
  .ok { color:#1a7f37; font-weight:600; }
  .bad { color:#cf222e; font-weight:600; }
  .hide { display:none; }
  .grp { display:none; }
  .grp.on { display:block; }
  #status { font-size:13px; color:#555; margin-left:10px; }
</style>
</head>
<body>
<header>소설 분권 <span style="font-weight:400;font-size:13px;opacity:.85">(웹 버전 · 같은 서버가 n8n API도 제공)</span></header>
<div class="wrap">

  <!-- 설정: 토큰 -->
  <div class="card">
    <h2>서버 연결</h2>
    <div class="row">
      <label>API 토큰</label>
      <input type="text" id="token" placeholder="서버 실행 시 콘솔에 표시된 토큰" style="max-width:420px">
      <button class="sec" onclick="saveToken()">저장</button>
      <span id="tokmsg" class="muted"></span>
    </div>
    <div class="muted">토큰은 이 브라우저에만 저장됩니다. n8n 은 같은 토큰을 X-API-Key 헤더로 사용합니다.</div>
  </div>

  <!-- 1. 파일 -->
  <div class="card">
    <h2>① 파일 선택</h2>
    <div id="drop">여기로 파일을 끌어놓거나 클릭해서 선택하세요 (docx, txt)</div>
    <input type="file" id="file" class="hide" accept=".docx,.txt">
    <div class="row"><span id="fileinfo" class="muted">선택된 파일 없음</span>
      <button class="sec" onclick="doCount()">전체 글자수 보기</button>
      <span id="countinfo" class="muted"></span></div>
  </div>

  <!-- 2. 분권 방식 -->
  <div class="card">
    <h2>② 분권 방식</h2>
    <div class="row">
      <label><input type="radio" name="mode" value="separator" checked onchange="modeChg()"> 구분자 기준</label>
      <label><input type="radio" name="mode" value="char_count" onchange="modeChg()"> 글자수 기준</label>
      <label><input type="radio" name="mode" value="word_count" onchange="modeChg()"> 단어수 기준</label>
    </div>
    <div class="grp on" id="g_sep">
      <div class="row"><label>구분자</label><input type="text" id="sep" placeholder="예) ###, Chapter, ==="></div>
      <div class="row"><label>구분자 위치</label>
        <label><input type="radio" name="seppos" value="start" checked> 앞 (구분자로 시작하는 줄부터 새 화)</label>
        <label><input type="radio" name="seppos" value="end"> 뒤 (구분자로 끝나는 줄이 화의 마지막)</label>
      </div>
      <div class="row">
        <label><input type="checkbox" id="inc" checked> 구분자를 결과에 포함</label>
        <label><input type="checkbox" id="rem"> 구분자 문자열 제거 (###제목→제목, 문장.###→문장.)</label>
      </div>
    </div>
    <div class="grp" id="g_cnt">
      <div class="row"><label id="cntlabel">기준 글자수</label>
        <input type="number" id="limit" value="5000" min="1" step="1000" style="width:120px">
        <label><input type="checkbox" id="nospace"> 공백 제외 글자수 기준</label></div>
    </div>
    <div class="row">
      <label>번호 위치</label>
      <select id="numpos"><option value="suffix">파일명 뒤 (소설_0001)</option><option value="prefix">파일명 앞 (0001_소설)</option></select>
    </div>
    <div class="row"><button id="runbtn" onclick="doSplit()">분권 실행</button><span id="status"></span></div>
  </div>

  <!-- 3. 결과 -->
  <div class="card" id="resultCard" style="display:none">
    <h2>③ 결과 <button class="sec" style="float:right" onclick="downloadZip()">분권 파일 zip 저장</button>
      <button class="sec" style="float:right;margin-right:8px" onclick="downloadCsv()">결과 CSV 저장</button></h2>
    <div id="total" class="muted" style="margin-bottom:8px"></div>
    <div style="overflow:auto"><table id="rtbl"><thead><tr>
      <th>번호</th><th class="l">파일명</th><th class="l">제목</th><th>공백포함</th><th>공백제외</th><th>단어수</th><th>줄수</th>
    </tr></thead><tbody></tbody></table></div>
  </div>

  <!-- 4. 플랫폼 대조 -->
  <div class="card">
    <h2>④ 플랫폼 회차 대조 (네이버 시리즈)</h2>
    <div class="row"><input type="text" id="purl" placeholder="네이버 시리즈 작품 URL">
      <button onclick="doPlatform()">가져와서 대조</button>
      <button class="sec" onclick="downloadPlatformCsv()">회차목록 CSV 저장</button></div>
    <div id="psummary" class="muted"></div>
    <div style="overflow:auto"><table id="ptbl" class="hide"><thead><tr>
      <th>번호</th><th class="l">우리 분권 제목</th><th class="l">플랫폼 회차</th><th>일치</th>
    </tr></thead><tbody></tbody></table></div>
  </div>

</div>
<script>
let curFile=null, lastSplit=null, lastPlatform=null;

function tok(){ return document.getElementById('token').value.trim(); }
function saveToken(){ localStorage.setItem('splitter_token', tok()); document.getElementById('tokmsg').textContent='저장됨'; setTimeout(()=>document.getElementById('tokmsg').textContent='',1500); }
function hdr(){ return tok()? {'X-API-Key':tok()} : {}; }

window.onload=()=>{ const t=localStorage.getItem('splitter_token'); if(t) document.getElementById('token').value=t; };

// 파일 선택 / 드롭
const drop=document.getElementById('drop'), fileEl=document.getElementById('file');
drop.onclick=()=>fileEl.click();
fileEl.onchange=e=>setFile(e.target.files[0]);
drop.ondragover=e=>{e.preventDefault();drop.classList.add('hover');};
drop.ondragleave=()=>drop.classList.remove('hover');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('hover');setFile(e.dataTransfer.files[0]);};
function setFile(f){ if(!f)return; curFile=f; document.getElementById('fileinfo').textContent='선택: '+f.name; document.getElementById('countinfo').textContent=''; }

function modeChg(){ const m=document.querySelector('input[name=mode]:checked').value;
  document.getElementById('g_sep').classList.toggle('on', m==='separator');
  document.getElementById('g_cnt').classList.toggle('on', m!=='separator');
  document.getElementById('cntlabel').textContent = m==='word_count'?'기준 단어수':'기준 글자수';
}

async function doCount(){ if(!curFile){alert('먼저 파일을 선택하세요');return;}
  const fd=new FormData(); fd.append('file',curFile);
  const r=await fetch('/count',{method:'POST',headers:hdr(),body:fd});
  if(!r.ok){alert('오류: '+(await r.text()));return;}
  const d=await r.json(); const c=d.counts;
  document.getElementById('countinfo').textContent=`공백포함 ${c.chars_with_spaces.toLocaleString()}자 · 공백제외 ${c.chars_without_spaces.toLocaleString()}자 · 단어 ${c.words.toLocaleString()} · 줄 ${c.lines.toLocaleString()}`;
}

async function doSplit(){ if(!curFile){alert('먼저 파일을 선택하세요');return;}
  const m=document.querySelector('input[name=mode]:checked').value;
  const fd=new FormData(); fd.append('file',curFile); fd.append('mode',m);
  fd.append('separator',document.getElementById('sep').value);
  fd.append('separator_position',document.querySelector('input[name=seppos]:checked').value);
  fd.append('include_separator',document.getElementById('inc').checked);
  fd.append('remove_separator',document.getElementById('rem').checked);
  fd.append('count_limit',document.getElementById('limit').value);
  fd.append('char_count_with_spaces', !document.getElementById('nospace').checked);
  fd.append('number_position',document.getElementById('numpos').value);
  const btn=document.getElementById('runbtn'), st=document.getElementById('status');
  btn.disabled=true; st.textContent='처리 중...';
  try{
    const r=await fetch('/split',{method:'POST',headers:hdr(),body:fd});
    if(!r.ok){ st.textContent=''; alert('오류: '+(await r.text())); return; }
    lastSplit=await r.json(); renderResult(lastSplit); st.textContent='완료';
  }catch(e){ st.textContent=''; alert('요청 실패: '+e); }
  finally{ btn.disabled=false; }
}

function renderResult(d){
  document.getElementById('resultCard').style.display='block';
  const t=d.total;
  document.getElementById('total').textContent=`분권 ${d.output_count}개 · 공백포함 ${t.chars_with_spaces.toLocaleString()}자 · 공백제외 ${t.chars_without_spaces.toLocaleString()}자 · 단어 ${t.words.toLocaleString()} · 줄 ${t.lines.toLocaleString()}`;
  const tb=document.querySelector('#rtbl tbody'); tb.innerHTML='';
  d.chunks.forEach(c=>{ const cn=c.counts;
    tb.insertAdjacentHTML('beforeend', `<tr><td>${c.index}</td><td class="l">${esc(c.filename)}</td><td class="l">${esc(c.title||'')}</td><td>${cn.chars_with_spaces.toLocaleString()}</td><td>${cn.chars_without_spaces.toLocaleString()}</td><td>${cn.words.toLocaleString()}</td><td>${cn.lines.toLocaleString()}</td></tr>`);
  });
}
function esc(s){ return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function b64toBlob(b64,type){ const bin=atob(b64); const a=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i); return new Blob([a],{type}); }
function saveBlob(blob,name){ const u=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=u; a.download=name; a.click(); URL.revokeObjectURL(u); }

function downloadZip(){ if(!lastSplit||!lastSplit.zip_base64){alert('먼저 분권을 실행하세요');return;}
  saveBlob(b64toBlob(lastSplit.zip_base64,'application/zip'), lastSplit.zip_filename||'분권결과.zip'); }

function downloadCsv(){ if(!lastSplit){alert('먼저 분권을 실행하세요');return;}
  let csv='번호,파일명,제목,공백포함,공백제외,단어수,줄수\n';
  lastSplit.chunks.forEach(c=>{ const cn=c.counts; csv+=`${c.index},"${c.filename}","${(c.title||'').replace(/"/g,'""')}",${cn.chars_with_spaces},${cn.chars_without_spaces},${cn.words},${cn.lines}\n`; });
  saveBlob(new Blob(['﻿'+csv],{type:'text/csv'}), '분권결과.csv'); }

async function doPlatform(){ const url=document.getElementById('purl').value.trim(); if(!url){alert('URL을 입력하세요');return;}
  const fd=new FormData(); fd.append('url',url);
  document.getElementById('psummary').textContent='가져오는 중...';
  const r=await fetch('/platform/episodes',{method:'POST',headers:hdr(),body:fd});
  if(!r.ok){ document.getElementById('psummary').textContent=''; alert('오류: '+(await r.text())); return; }
  lastPlatform=await r.json(); renderPlatform(lastPlatform);
}
function renderPlatform(p){
  const ourTitles = lastSplit ? lastSplit.chunks.filter(c=>!c.skipped).map(c=>c.title) : [];
  const match = ourTitles.length===p.total_count;
  document.getElementById('psummary').innerHTML=`작품: <b>${esc(p.work_title||'(제목 미확인)')}</b> · 플랫폼 ${p.total_count}회차 vs 우리 분권 ${ourTitles.length}개 → 회차 수 <span class="${match?'ok':'bad'}">${match?'일치':'불일치'}</span>`;
  const n=Math.max(ourTitles.length, p.episodes.length);
  const tb=document.querySelector('#ptbl tbody'); tb.innerHTML='';
  const norm=s=>(s||'').replace(/\s+/g,'');
  for(let i=0;i<n;i++){ const o=ourTitles[i]||'', pl=p.episodes[i]?p.episodes[i].title:'';
    let mk='△'; if(!o&&pl)mk='우리 측 없음'; else if(o&&!pl)mk='플랫폼 측 없음';
    else { const a=norm(o),b=norm(pl); mk=(a&&b&&(a===b||a.includes(b)||b.includes(a)))?'O':'△'; }
    tb.insertAdjacentHTML('beforeend', `<tr><td>${i+1}</td><td class="l">${esc(o)}</td><td class="l">${esc(pl)}</td><td>${mk}</td></tr>`);
  }
  document.getElementById('ptbl').classList.remove('hide');
}
function downloadPlatformCsv(){ if(!lastPlatform){alert('먼저 회차 목록을 가져오세요');return;}
  let csv='번호,회차제목\n'; lastPlatform.episodes.forEach(e=>{ csv+=`${e.no},"${(e.title||'').replace(/"/g,'""')}"\n`; });
  saveBlob(new Blob(['﻿'+csv],{type:'text/csv'}), (lastPlatform.work_title||'회차목록')+'_회차목록.csv'); }
</script>
</body>
</html>
"""
