const sidebar = document.getElementById("sidebar");
const toggleBtn = document.getElementById("toggle-btn");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");

  if (sidebar.classList.contains("collapsed")) {
    toggleBtn.textContent = "›››";
  } else {
    toggleBtn.textContent = "‹‹‹";
  }
});



/*백엔드 연결 함수 - 윤서영 추가*/

let originCoord = null;   // { lat, lon }
let destCoord   = null;   // { lat, lon }

/** 지도(map_main.html iframe) → 부모 창 메시지 수신*/
window.addEventListener('message', function(e) {
  if (!e.data) return;

  if (e.data.type === 'SET_ORIGIN') {
    originCoord = { lat: e.data.lat, lon: e.data.lon };
    document.getElementById('origin').value =
      `${e.data.lat.toFixed(5)}, ${e.data.lon.toFixed(5)}`;
    sessionStorage.setItem('originCoord', JSON.stringify(originCoord));  // ← 추가
  }

  if (e.data.type === 'SET_DEST') {
    destCoord = { lat: e.data.lat, lon: e.data.lon };
    document.getElementById('destination').value =
        `${e.data.lat.toFixed(5)}, ${e.data.lon.toFixed(5)}`;
    sessionStorage.setItem('destCoord', JSON.stringify(destCoord));  // ← 추가
  }
});

/** 체크박스 상태 → user_switches 딕셔너리 */
function getUserSwitches() {
  const keys = ['congestion', 'time', 'walk', 'fare', 'transfer', 'facility', 'seating'];
  const boxes = document.querySelectorAll('.option-list input[type="checkbox"]');
  const result = {};
  boxes.forEach((cb, i) => { result[keys[i]] = cb.checked; });
  return result;
}

/** HH:MM → 'N시MM분' 형식 변환 (find_optimal_departure용) */
function toKoreanTime(hhmm) {
  const [h, m] = hhmm.split(':');
  return `${parseInt(h)}시${m}분`;
}

/** 오전/오후 표시 */
function formatAmPm(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  const ampm = h < 12 ? '오전' : '오후';
  const hour = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${ampm} ${hour}:${String(m).padStart(2, '0')}`;
}

/** 로딩 오버레이 표시/숨기기 */
function setLoading(on) {
  let overlay = document.getElementById('loading-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'loading-overlay';
    overlay.innerHTML = `
      <div style="
        position:fixed; inset:0; background:rgba(0,0,0,0.5);
        display:flex; flex-direction:column; align-items:center; justify-content:center;
        z-index:9999; font-family:'Noto Sans KR',sans-serif;">
        <!-- 메인 문구 -->
        <div style="color:#fff; font-size:28px; font-weight:700; margin-bottom:16px;">
          경로 탐색 중...
        </div>
        <!-- 워터마크 서비스명 -->
        <div style="
          color:rgba(255, 255, 255, 0.37);
          font-size:96px;
          font-weight:900;
          letter-spacing:0.08em;
          user-select:none;
          position:absolute;
          bottom:35%;
          left:50%;
          transform:translateX(-50%);
          white-space:nowrap;">
          여유로
        </div>
      </div>`;
    document.body.appendChild(overlay);
  }
  overlay.style.display = on ? 'flex' : 'none';
}



/*검색 버튼 클릭 → 경로 검색*/
document.getElementById('search-btn').addEventListener('click', async () => {
  const origin      = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();
  const date        = document.getElementById('depart-date').value;
  const timeFrom    = document.getElementById('time-from').value;
  const timeTo      = document.getElementById('time-to').value;

  // ── 입력값 검증 ──────────────────────────────────────────────
  if (!origin || !destination) {
    alert('출발지와 도착지를 입력해주세요.'); return;
  }
  if (!date) {
    alert('날짜를 입력해주세요.'); return;
  }
  if (!timeFrom || !timeTo) {
    alert('출발 가능 시간을 입력해주세요.'); return;
  }
  if (timeFrom >= timeTo) {
    alert('종료 시간은 시작 시간보다 이후여야 합니다.'); return;
  }

  setLoading(true);

  try {
    // 1. 경로 검색
        const searchRes = await fetch('/api/search', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                origin_lat:    originCoord.lat,
                origin_lon:    originCoord.lon,
                dest_lat:      destCoord.lat,
                dest_lon:      destCoord.lon,
                depart_dt:     `${date}T${timeFrom}:00`,
                user_switches: getUserSwitches(),
            }),
        });

        if (!searchRes.ok) {
            const err = await searchRes.json();
            throw new Error(err.error || '경로 검색 실패');
        }

        const routes = await searchRes.json();

        // 2. 최적 출발 시각
        let optimalTime = timeFrom;
        try {
            const optRes = await fetch('/api/optimal-time', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    routes:      routes,
                    target_date: date,
                    start_time:  toKoreanTime(timeFrom),
                    end_time:    toKoreanTime(timeTo),
                    target:      'best',
                }),
            });
            if (optRes.ok) {
                const optData = await optRes.json();
                optimalTime = optData.optimal_time;
            }
        } catch (_) {}

    // ── 3. 결과 페이지로 데이터 전달 ───────────────────────────
    // sessionStorage에 저장 후 결과 페이지로 이동
    sessionStorage.setItem('routes',      JSON.stringify(routes));
    sessionStorage.setItem('optimalTime', optimalTime);
    sessionStorage.setItem('origin',      origin);
    sessionStorage.setItem('destination', destination);

    window.location.href = '/result';

  } catch (err) {
    alert(`오류: ${err.message}`);
    console.error(err);
  } finally {
    setLoading(false);
  }
});