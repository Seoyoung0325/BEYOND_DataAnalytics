"""데이터 전처리 및 분석 파이프라인 모듈"""

"""## 0. 라이브러리 설치 및 임포트"""

import matplotlib.pyplot as plt
plt.rc('font', family='Malgun Gothic')  #로컬버전 한글폰트 설정

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# TMAP API키 불러오기
from dotenv import load_dotenv
import os

load_dotenv()
TMAP_API_KEY = os.getenv('TMAP_API_KEY_ysy')




"""## 1. 데이터 로드"""

## 1~8호선 지하철 혼잡도 데이터 로드
CSV_PATH  = 'data/서울교통공사_지하철혼잡도정보_20250930.csv'
XLSX_PATH = 'data/2025년 9호선 역별 시간별 혼잡도 자료.xlsx'

FILE_PATH = 'data/서울교통공사_편의시설_현황_20250320.csv'
df_facil = pd.read_csv(FILE_PATH, encoding='cp949')
#1. 필요한 컬럼만 추출
facility_df = df_facil[['역명', '호선', '휠체어리프트여부', '엘리베이터여부', '환전키오스크여부']].copy()
# Y/N → 1/0 변환
for col in ['휠체어리프트여부', '엘리베이터여부', '환전키오스크여부']:
    facility_df[col] = (facility_df[col] == 'Y').astype(int)




"""## 2. Wide → Long 변환"""

# ---------- 1~8호선 (CSV) ----------
df_raw = pd.read_csv(CSV_PATH, encoding='cp949')

time_cols = [c for c in df_raw.columns if '시' in c]
df_1to8 = df_raw.melt(
    id_vars=['요일구분', '호선', '역번호', '출발역', '상하구분'],
    value_vars=time_cols,
    var_name='시간대',
    value_name='혼잡도'
)
df_1to8['급행여부'] = 0   # 1~8호선은 급행 없음

# ---------- 9호선 (xlsx, 시트별 상하선×급행/일반×평일/휴일) ----------
xl = pd.ExcelFile(XLSX_PATH)
records = []
for sheet in xl.sheet_names:
    direction  = '상선' if sheet.startswith('상선') else '하선'
    is_express = 1 if '급행' in sheet else 0
    day_types   = ['평일'] if '평일' in sheet else ['토요일', '일요일']  #윤서영 수정 - '휴일' 데이터를 토일로 각각 복사해 넣기

    # header=1: 1행(row0)은 병합된 날짜 안내문이라 skip, 실제 시간대 헤더는 2번째 행
    sdf = pd.read_excel(XLSX_PATH, sheet_name=sheet, header=1)
    sdf = sdf.rename(columns={sdf.columns[0]: '출발역'})
    time_cols_9 = sdf.columns[1:]

    for day_type in day_types:   # 휴일이면 두 번 반복
        long_sdf = sdf.melt(id_vars='출발역', value_vars=time_cols_9, var_name='시간대', value_name='혼잡도')
        long_sdf['호선']     = '9호선'
        long_sdf['상하구분'] = direction
        long_sdf['요일구분'] = day_type
        long_sdf['급행여부'] = is_express
        long_sdf['역번호']   = np.nan   # 9호선은 공식 역번호 데이터가 없음 → 아래 피처 엔지니어링에서 대체
        records.append(long_sdf)

df_9 = pd.concat(records, ignore_index=True)

# 9호선 시간대 라벨('05:30~05:59')을 1~8호선 스타일('5시30분')로 통일
def to_csv_style_time(raw):
    start = str(raw).split('~')[0]
    h, m = start.split(':')
    h_fmt = '00' if int(h) == 0 else str(int(h))
    return f"{h_fmt}시{m}분"

df_9['시간대'] = df_9['시간대'].apply(to_csv_style_time)

# 통합
COLS = ['요일구분', '호선', '역번호', '출발역', '상하구분', '시간대', '혼잡도', '급행여부']
df = pd.concat([df_1to8[COLS], df_9[COLS]], ignore_index=True)

print(f'통합 완료: {df.shape[0]:,}행 (1~8호선 {len(df_1to8):,} + 9호선 {len(df_9):,})')
df['호선'].value_counts()



"""## 3. 피처 엔지니어링"""

# 시간대 문자열 -> 분 단위 정수 변환
def parse_time_to_minutes(t):
    t = t.strip()
    if '시30분' in t:
        h = int(t.replace('시30분', ''))
        m = 30
    else:
        h = int(t.replace('시00분', ''))
        m = 0
    total = h * 60 + m
    if total < 330:  # 자정~새벽 보정
        total += 1440
    return total

df['time_minutes'] = df['시간대'].apply(parse_time_to_minutes)

# 요일 피처
df['is_weekday']  = (df['요일구분'] == '평일').astype(int)
df['is_saturday'] = (df['요일구분'] == '토요일').astype(int)
df.loc[(df['호선'] == '9호선') & (df['요일구분'] == '휴일'), 'is_saturday'] = 1

# 출퇴근 시간대 플래그
df['is_rush_am'] = ((df['time_minutes'] >= 420)  & (df['time_minutes'] <= 540)).astype(int)   # 7~9시
df['is_rush_pm'] = ((df['time_minutes'] >= 1020) & (df['time_minutes'] <= 1140)).astype(int)  # 17~19시

# 역번호 대체: 9호선은 공식 역번호가 없으므로 (호선 + 출발역) 조합으로 새 인코딩을 만들어
# 1~8호선까지 전체 노선에 통일 적용 (환승역이라도 호선이 다르면 다른 코드로 구분됨)
df['station_key']    = df['호선'] + '_' + df['출발역']
print(f'역(호선 조합) 수: {df["station_key"].nunique()}개')

df[['출발역','호선','상하구분','요일구분','시간대','time_minutes',
    'is_weekday','is_rush_am','is_rush_pm','급행여부', '혼잡도']].head(5)




"""## 4. 데이터 품질 확인"""

# 혼잡도 0, 결측 대비 isna()도 함께 체크 -> 학습에서 제외
zero_or_na = (df['혼잡도'] == 0) | (df['혼잡도'].isna())
print(f"혼잡도 0/결측 행: {zero_or_na.sum():,}개 ({zero_or_na.mean()*100:.1f}%) -> 제거 예정")


# 분포 시각화 (코랩 확인버전)
def plot_data_quality():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    df[df['혼잡도'] > 0]['혼잡도'].hist(bins=50, ax=axes[0], color='steelblue', edgecolor='white')
    axes[0].set_title('혼잡도 분포 (0 제외)')
    axes[0].set_xlabel('혼잡도 (%)')

    df[df['혼잡도'] > 0].groupby('time_minutes')['혼잡도'].mean().plot(ax=axes[1], color='tomato')
    axes[1].set_title('시간대별 평균 혼잡도')
    axes[1].set_xlabel('시각 (분)')
    axes[1].set_ylabel('평균 혼잡도 (%)')
    plt.tight_layout()
    plt.show()




"""## 5. Lookup 테이블 생성"""

df_model = df[~zero_or_na].copy()
print(f'유효 데이터: {len(df_model):,}행')

# (station_key, 상하구분, 요일구분, time_minutes) → 혼잡도 평균
lookup_table = (
    df_model
    .groupby(['station_key', '상하구분', '요일구분', 'time_minutes'])['혼잡도']
    .mean()
    .round(1)
    .to_dict()
)
print(f'lookup 테이블 항목 수: {len(lookup_table):,}개')




"""##6. 혼잡도 조회 함수 (lookup 테이블 기반)"""

# 단일 역·시각의 혼잡도를 lookup 테이블에서 조회하는 함수
def lookup_congestion(station_name, line, direction, depart_hour, depart_minute, day_type, is_express=0):
    """
    Parameters
    ----------
    station_name  : str  예) '서울역'
    line          : str  예) '1호선'
    direction     : str  예) '상선' / '하선' / '내선' / '외선'
    depart_hour   : int  예) 8
    depart_minute : int  예) 30
    day_type      : str  '평일' / '토요일' / '일요일'
    is_express    : int  0=일반, 1=급행 (9호선 전용)

    Returns
    -------
    float : 혼잡도 (%), None = 데이터 없음
    """
    # 30분 슬롯으로 반올림
    raw_min = depart_hour * 60 + depart_minute
    slot    = round(raw_min / 30) * 30
    if slot < 330:
        slot += 1440  # 자정~새벽 보정

    station_key = f'{line}_{station_name}'

    # 급행 우선 조회 → 없으면 일반으로 fallback
    # (9호선 급행역은 급행/일반 둘 다 데이터 있을 수 있음)
    result = lookup_table.get((station_key, direction, day_type, slot))

    if result is None:
        # fallback 1: 같은 호선 전체 평균
        fallback = df_model[
            (df_model['호선'] == line) &
            (df_model['요일구분'] == day_type) &
            (df_model['time_minutes'] == slot)
        ]['혼잡도'].mean()
        if not np.isnan(fallback):
            return round(fallback, 1)
        return None

    return result



# TMAP에서 파싱한 지하철 구간 리스트 전체의 혼잡도를 조회하고, 구간별 결과와 총점을 반환하는 함수
def score_route(subway_legs, depart_hour, depart_minute, day_type):
    """
    Parameters
    ----------
    subway_legs : list of dict
        각 원소: {'station_name': str, 'line': str, 'direction': str, 'elapsed_min': int}
    day_type    : str  '평일' / '토요일' / '일요일'

    Returns
    -------
    total_score : float  구간 혼잡도 합산
    details     : list   각 구간의 조회 결과
    """
    details  = []
    base_min = depart_hour * 60 + depart_minute

    for leg in subway_legs:
        board_min  = base_min + leg['elapsed_min']
        board_h    = (board_min % 1440) // 60
        board_m    = board_min % 60

        congestion = lookup_congestion(
            station_name  = leg['station_name'],
            line          = leg['line'],
            direction     = leg['direction'],
            depart_hour   = board_h,
            depart_minute = board_m,
            day_type      = day_type,
            is_express    = leg.get('is_express', 0),
        )
        details.append({
            **leg,
            'board_time': f'{board_h:02d}:{board_m:02d}',
            'congestion': congestion,
        })

    valid = [d['congestion'] for d in details if d['congestion'] is not None]
    return round(sum(valid), 1), details




"""##7. TMAP 대중교통 API 연동"""

# 1) TMAP API 호출
def call_tmap_transit(origin_lat, origin_lon, dest_lat, dest_lon, depart_dt: datetime):
    """
    Parameters
    ----------
    origin_lat / origin_lon : 출발지 위경도
    dest_lat   / dest_lon   : 도착지 위경도
    depart_dt               : 출발 일시 (datetime 객체)

    Returns
    -------
    dict : TMAP 응답 JSON  (실패 시 None)
    """
    url = 'https://apis.openapi.sk.com/transit/routes'
    headers = {
        'Content-Type': 'application/json',
        'appKey': TMAP_API_KEY,
    }
    body = {
        'startX':        str(origin_lon),
        'startY':        str(origin_lat),
        'endX':          str(dest_lon),
        'endY':          str(dest_lat),
        'reqCoordType':  'WGS84GEO',
        'resCoordType':  'WGS84GEO',
        'searchDttm':    depart_dt.strftime('%Y%m%d%H%M'),  # '202507081830'
        'count':         3,   # 후보 경로 최대 5개
    }
    resp = requests.post(url, headers=headers, json=body, timeout=10)

    if resp.status_code != 200:
        print(f'TMAP 호출 실패: {resp.status_code}  {resp.text[:200]}')
        return None

    return resp.json()

# 2) 응답 파싱 — 경로 요약 정보 추출  (소요시간 / 도보거리 / 요금 / 환승횟수)
def parse_route_summary(itinerary):
    return {
        'total_sec':      itinerary.get('totalTime', 0),         # 총 소요시간 (초)
        'walk_sec':       itinerary.get('totalWalkTime', 0),     # 도보 시간 (초)
        'walk_distance':  itinerary.get('totalWalkDistance', 0), # 도보 거리 (m)
        'transfer_count': itinerary.get('transferCount', 0),     # 환승 횟수
        'fare':           itinerary.get('fare', {})
                                   .get('regular', {})
                                   .get('totalFare', 0),         # 요금 (원)
    }

# 3) 응답 파싱 — 지하철 구간 추출
def parse_subway_legs(itinerary, depart_dt: datetime):
    """
    Returns
    -------
    list of dict :
        station_name  - 역 이름
        line          - 호선 (예: '2호선')
        direction     - 방향 (상선/하선/내선/외선)
        elapsed_min   - 출발 시각 기준 이 역 탑승까지 경과 분
        is_weekday    - 평일 여부
    """
    results  = []
    elapsed  = 0   # 출발부터 경과 시간 (초)

    # 호선명 정규화: TMAP '수도권 2호선' → '2호선'
    def normalize_line(raw):
        match = re.search(r'(\d+)호선', raw)
        if match:
            return f'{match.group(1)}호선'
        return raw

    # 방향 매핑: TMAP 방면 정보 → 상선/하선/내선/외선
    # 2호선은 내선/외선, 나머지는 상선/하선
    def infer_direction(line, station_list):
        if '2호선' in line:
            # 역번호 오름차순이면 외선, 내림차순이면 내선 (간이 판단)
            codes = [s.get('stationCode', '0') for s in station_list]
            return '외선' if codes == sorted(codes) else '내선'
        else:
            codes = [s.get('stationCode', '0') for s in station_list]
            return '상선' if codes == sorted(codes) else '하선'

    for leg in itinerary.get('legs', []):
        mode = leg.get('mode', '')

        if mode != 'SUBWAY':
            elapsed += leg.get('sectionTime', 0)  # 도보 등 시간 누적
            continue

        line      = normalize_line(leg.get('route', ''))
        stop_list = leg.get('passStopList', {})
        stations  = stop_list.get('stationList') or stop_list.get('stations', [])
        direction = infer_direction(line, stations)

        for station in stations:
            results.append({
                'station_name': station.get('stationName', ''),
                'line':         line,
                'direction':    direction,
                'elapsed_min':  elapsed // 60,
                'is_express':   leg.get('is_express', 0),
            })
            # 역간 이동시간 누적 (TMAP이 역별 시간을 주지 않으면 평균 2분 가정)
            elapsed += station.get('travelTime', 120)

    return results




"""##8. 쾌적도 계산"""

# 이동편의시설 지수 계산

# 희귀도 기반 가중치 설정  (전체 역 중 보유 비율이 낮을수록 = 있을 때 더 큰 혜택)
total = len(facility_df)
w_lift    = 1 - (facility_df['휠체어리프트여부'].sum() / total)  # ≈ 0.986
w_elev    = 1 - (facility_df['엘리베이터여부'].sum()   / total)  # ≈ 0.021
w_kiosk   = 1 - (facility_df['환전키오스크여부'].sum() / total)  # ≈ 0.910

print(f'휠체어리프트 가중치: {w_lift:.3f}')
print(f'엘리베이터    가중치: {w_elev:.3f}')
print(f'환전키오스크  가중치: {w_kiosk:.3f}')

# 시설 점수 계산 (0~1, 높을수록 잘 갖춰짐)
facility_df['raw_score'] = (
    w_lift  * facility_df['휠체어리프트여부'] +
    w_elev  * facility_df['엘리베이터여부']   +
    w_kiosk * facility_df['환전키오스크여부']
)

# 0~1 정규화
max_score = w_lift + w_elev + w_kiosk
facility_df['facility_score'] = facility_df['raw_score'] / max_score

# 호선명 통일
facility_df['호선'] = facility_df['호선'].str.lstrip('0').str.replace('호선', '호선')

# 역이름 → S이동편의시설 딕셔너리로 변환
facility_map = facility_df.set_index('역명')['facility_score'].to_dict()

#착석가능지수 계산 함수
def get_seating_score(congestion):
    # ① 예외 처리: 예측값이 없으면(None) 똑같이 None 반환하여 에러 방지
    if congestion is None:
        return None

    # ② 전원 착석 구간: 혼잡도 33.8% 이하 ➔ 무조건 1
    if congestion <= 33.8:
        return 1.0

    # ③ 착석 비율 계산: 혼잡도가 높을수록 점수가 비례해서 감소
    return round(33.8 / congestion,3)

# 4) 전체 파이프라인: TMAP 호출 → 파싱 → 쾌적도 점수화
def calculate_comfort_score(api_data, user_switches):
    """
    Parameters
    ----------
    api_data : dict
        totalTime        - 총 소요시간 (초)
        totalWalkTime    - 도보 소요시간 (초)
        totalFare        - 총 요금 (원)
        transferCount    - 환승 횟수
        facilityScore    - 이동편의시설 점수 (0~1, 높을수록 좋음)
        congestionCarValue - 평균 혼잡도 (%) lookup 테이블 조회

    user_switches : dict
        각 지표 사용 여부 (True/False)
        키: time, walk, fare, transfer, facility, congestion, seating

    Returns
    -------
    float : 쾌적도 점수 (0~100, 높을수록 쾌적)
    """
    base_scores = []

    if user_switches.get('time'):
        # 초 단위를 분 단위로 변환 후 점수화
        s_time = max(0.0, 1.0 - (api_data.get('totalTime', 0) / 60) / 120)
        base_scores.append(s_time)

    if user_switches.get('walk'):
        s_walk = max(0.0, 1.0 - (api_data.get('totalWalkTime', 0) / 60) / 30)
        base_scores.append(s_walk)

    if user_switches.get('fare'):
        s_fare = max(0.0, 1.0 - api_data.get('totalFare', 0) / 5000)
        base_scores.append(s_fare)

    if user_switches.get('transfer'):
        s_transfer = max(0.0, 1.0 - api_data.get('transferCount', 0) / 3)
        base_scores.append(s_transfer)

    if user_switches.get('facility'):
        s_facility = api_data.get('facilityScore', 0.5)
        base_scores.append(s_facility)

    base_avg = sum(base_scores) / len(base_scores) if base_scores else 1.0

    multiplier = 1.0
    if user_switches.get('congestion'):
        congestion_val = api_data.get('congestionCarValue', 100)
        multiplier *= max(0.5, 1.0 - (congestion_val / 300))

    if user_switches.get('seating'):
        seat_score = api_data.get('seatingScore')
        if seat_score is not None:
            multiplier *= seat_score

    final_score = base_avg * multiplier * 100
    return round(final_score, 1)

# TMAP 경로 후보 전체에 쾌적도 점수를 계산해 점수 낮은 순(쾌적한 순)으로 정렬해 반환하는 함수
def get_route_with_comfort(origin_lat, origin_lon, dest_lat, dest_lon, depart_dt,
                           user_switches=None,   # 사용자 토글 상태
                           facility_map=None,    # 역이름 → facilityScore 딕셔너리
):
    # 기본값: 모든 지표 활성화
    if user_switches is None:
        user_switches = {
            'time':       True,
            'walk':       True,
            'fare':       True,
            'transfer':   True,
            'facility':   True,
            'congestion': True,
            'seating':    True,
        }

    if facility_map is None:
        facility_map = {}

    # TMAP 호출
    raw = call_tmap_transit(origin_lat, origin_lon, dest_lat, dest_lon, depart_dt)
    if raw is None:
        return []

    itineraries = raw.get('metaData', {}) \
                     .get('plan', {}) \
                     .get('itineraries', [])
    print(f'후보 경로 수: {len(itineraries)}개')

    results = []

    for idx, itin in enumerate(itineraries):

        # 요약 지표 추출 (TMAP 직접 필드)
        summary = parse_route_summary(itin)

        # 지하철 구간 혼잡도 조회 (lookup 테이블)
        day_type    = ('평일' if depart_dt.weekday() < 5
                        else '토요일' if depart_dt.weekday() == 5
                        else '일요일')
        subway_legs = parse_subway_legs(itin, depart_dt)
        cong_total, cong_detail = score_route(
            subway_legs,
            depart_dt.hour, depart_dt.minute,
            day_type,
        )

        has_subway = any(leg['mode'] == 'SUBWAY' for leg in itin['legs'])
        avg_cong   = cong_total / len(cong_detail) if (cong_detail and has_subway) else None

        # 이동편의시설 점수: 경로 상 역 평균
        facility_scores = [
            facility_map.get(seg['station_name'])
            for seg in cong_detail
            if facility_map.get(seg['station_name']) is not None
        ]
        facility_score = (
            sum(facility_scores) / len(facility_scores)
            if facility_scores else 0.5   # 데이터 없으면 중간값
        )

        #구간별 모델 예측 혼잡도로 착석가능지수 계산 후 평균
        seat_scores = [
            get_seating_score(seg['congestion'])
            for seg in cong_detail
            if seg['congestion'] is not None
        ]
        avg_seat_score = (
            sum(seat_scores) / len(seat_scores)
            if seat_scores else None
        )

        # calculate_comfort_score() 입력 데이터 구성
        api_data = {
            'totalTime':         summary['total_sec'],
            'totalWalkTime':     summary['walk_sec'],
            'totalFare':         summary['fare'],
            'transferCount':     summary['transfer_count'],
            'facilityScore':     facility_score,
            'congestionCarValue': avg_cong if avg_cong is not None else 0,
            'seatingScore':      avg_seat_score,

        }

        # 쾌적도 점수 계산 (0~100, 높을수록 쾌적)
        comfort_score = calculate_comfort_score(api_data, user_switches)

        results.append({
            'route_idx':      idx + 1,
            'comfort_score':  comfort_score,
            'avg_congestion': round(avg_cong, 1) if avg_cong is not None else None,
            **summary,
            'facility_score': round(facility_score, 3),
            'cong_detail':    cong_detail,
        })

    # 쾌적도 높은 순 정렬 (점수가 클수록 쾌적)
    results.sort(key=lambda x: x['comfort_score'], reverse=True)
    return results




def find_optimal_departure(routes, target_date, start_time, end_time,
    target='best',   # 'worst'=쾌적도 최하위 | 'best'=최상위 | int=route_idx 직접 지정
):
    """
    사용자가 설정한 출발 가능 시간 범위 내에서
    혼잡도가 가장 낮은 출발 시간을 추천

    Parameters
    ----------
    routes      : get_route_with_comfort() 반환값 (리스트)
    target_date : datetime  — 출발 날짜 (평일/주말 판단용)
    start_time  : str       — '8시30분' 형식
    end_time    : str       — '9시00분' 형식
    target      : str|int   — 분석 대상 경로 선택 기준

    Returns
    -------
    dict
        optimal_time    : 추천 출발 시간 ('HH:MM')
        min_congestion  : 해당 시간의 구간 혼잡도 합산
        all_results     : 후보 시간대 전체 결과 (DataFrame)
        optimal_details : 추천 시간의 구간별 상세 혼잡도
    """

    START_MINUTES = 330   # 05:30
    END_MINUTES   = 1470  # 00:30

    # ── 시간 파싱 & 검증 ──────────────────────────────────────────
    start_minutes = parse_time_to_minutes(start_time)
    end_minutes   = parse_time_to_minutes(end_time)

    if not (START_MINUTES <= start_minutes <= END_MINUTES):
        raise ValueError("출발 가능 시작 시간은 05:30~00:30 사이여야 합니다.")
    if not (START_MINUTES <= end_minutes <= END_MINUTES):
        raise ValueError("출발 가능 종료 시간은 05:30~00:30 사이여야 합니다.")
    if start_minutes > end_minutes:
        raise ValueError("종료 시간은 시작 시간보다 이후여야 합니다.")

    # ── 대상 경로 선택 ────────────────────────────────────────────
    # get_route_with_comfort()는 쾌적도 높은 순(내림차순) 정렬
    if target == 'worst':
        candidates = list(reversed(routes))   # 쾌적도 낮은 순
    elif target == 'best':
        candidates = list(routes)
    elif isinstance(target, int):
        candidates = [r for r in routes if r['route_idx'] == target] + list(reversed(routes))
    else:
        candidates = list(reversed(routes))

    # ── 지하철 구간이 실제로 존재하는 경로 선택 ──────────────────
    # 매핑 성공(congestion is not None)한 구간만 추출
    # → 매핑 실패 구간을 재포함하면 score_route()가 전부 None → 합산 0
    chosen    = None
    valid_legs = []

    for route in candidates:
        legs = [
            {
                'station_name': seg['station_name'],
                'line'        : seg['line'],
                'direction'   : seg['direction'],
                'elapsed_min' : seg['elapsed_min'],
            }
            for seg in route['cong_detail']
            if seg.get('congestion') is not None   # 매핑 성공 구간만
        ]
        if legs:          # 지하철 구간이 1개 이상 있는 경로
            chosen     = route
            valid_legs = legs
            break

    # 버스 전용 경로(지하철 없음)는 건너뜀
    if chosen is None:
        raise ValueError("선택 가능한 경로 중 지하철 구간이 없습니다. (버스 전용 경로만 존재)")

    print(f"▶ 분석 대상: 경로 {chosen['route_idx']}  "
          f"(쾌적도 {chosen['comfort_score']}점 | "
          f"평균혼잡도 {chosen['avg_congestion']}% | "
          f"유효 구간 {len(valid_legs)}개)")

    # ── 슬롯별 혼잡도 재예측 ─────────────────────────────────────
    day_type = ('평일' if target_date.weekday() < 5
            else '토요일' if target_date.weekday() == 5
            else '일요일')
    results    = []

    for total_minutes in range(start_minutes, end_minutes + 1, 30):

        display_min   = total_minutes if total_minutes < 1440 else total_minutes - 1440
        depart_hour   = display_min // 60
        depart_minute = display_min % 60

        total_congestion, details = score_route(
            subway_legs  = valid_legs,
            depart_hour  = depart_hour,
            depart_minute= depart_minute,
            day_type      = day_type,
        )

        results.append({
            "departure_time"   : f"{depart_hour:02d}:{depart_minute:02d}",
            "total_congestion" : total_congestion,
            "details"          : details,
        })

    # ── 최적 시각 탐색 ───────────────────────────────────────────
    optimal = min(results, key=lambda x: x["total_congestion"])

    all_results = pd.DataFrame({
        "출발시간" : [r["departure_time"]    for r in results],
        "총혼잡도" : [r["total_congestion"]  for r in results],
    })

    print(f"\n추천 출발시간 : {optimal['departure_time']}  "
          f"(총 혼잡도 {optimal['total_congestion']})")
    print("\n전체 후보 결과:")
    print(all_results.to_string(index=False))

    return {
        "optimal_time"    : optimal["departure_time"],
        "min_congestion"  : optimal["total_congestion"],
        "all_results"     : all_results,
        "optimal_details" : optimal["details"],
    }




"""##9. 실시간 혼잡 역/호선 통계 분석, 실시간 혼잡 역/호선 경고"""

# 혼잡도 판정 기준)
#   1. percentile : 지금 시간대에 운행 중인 전체 역 대비 상대적 혼잡도 순위
#   2. z-score    : 그 역의 '평소(해당 요일구분 전체 시간대) 평균·표준편차' 대비
#                   지금이 얼마나 이례적으로 혼잡한지 (표준편차 단위)
#   3. 호선 랭킹  : 현재 슬롯 기준 호선별 평균 혼잡도 순위
def analyze_current_congestion(df_model, now=None,
                               top_percentile=90.0,  # 상위 몇 % 이상을 '혼잡'으로 볼지
                               z_threshold=1.5,      # 평소 대비 표준편차 몇 배 이상을 '이례적'으로 볼지
                               min_absolute_congestion=70.0):  # 혼잡도 최소 기준선
    """
    Parameters
    ----------
    df_model        : DataFrame  전처리된 혼잡도 데이터
                       ('요일구분','호선','출발역','상하구분','time_minutes','혼잡도' 포함)
    now             : datetime, optional  테스트용 시각 지정 (기본값=컴퓨터 현재 시각)
    top_percentile  : float  전체 역 중 상위 몇 %(percentile) 이상이면 혼잡으로 판정
    z_threshold     : float  역 자체 평균 대비 z-score가 몇 이상이면 '이례적 혼잡'으로 판정
    min_absolute_congestion : float  절대 기준선(%). 데이터셋 정의상 34%가 '전원 착석 가능' 지점이므로,
                              이보다 높여서 '입석이 생기기 시작하는' 수준(기본 50%) 미만은
                              상대적으로 아무리 순위가 높아도 혼잡으로 보지 않음
                              (예: 심야처럼 전체적으로 한산한 시간대에 상대 1위가 뽑히는 문제 방지)

    Returns
    -------
    congested    : DataFrame  절대 혼잡도 + 1또는2 조건을 만족하는 역 (호선,출발역,상하구분,혼잡도,percentile,z_score,사유)
    line_ranking : DataFrame  현재 슬롯 기준 호선별 평균 혼잡도 랭킹
    day_type     : str
    slot         : int
    """
    KST = ZoneInfo("Asia/Seoul")

    if now is None:
        now = datetime.now(KST)

    weekday_num = now.weekday()
    if weekday_num == 5:
        day_type = '토요일'
    elif weekday_num == 6:
        day_type = '일요일'
    else:
        day_type = '평일'

    raw_min = now.hour * 60 + now.minute
    slot = round(raw_min / 30) * 30
    if slot < 330:
        slot += 1440
    slot = min(slot, 1470)

    if day_type not in df_model['요일구분'].unique():
        print(f'⚠️ 데이터에 "{day_type}" 구분이 없어 "평일" 기준으로 분석합니다.')
        day_type = '평일'

    #1. 현재 슬롯 스냅샷 (운행 없는 혼잡도=0 행 제외)
    snapshot = df_model[
        (df_model['요일구분'] == day_type) &
        (df_model['time_minutes'] == slot) &
        (df_model['혼잡도'] > 0)
    ].copy()

    if snapshot.empty:
        empty = pd.DataFrame(columns=['호선','출발역','상하구분','혼잡도','percentile','z_score','사유'])
        return empty, pd.DataFrame(columns=['호선','평균혼잡도']), day_type, slot

    # 전체 역 대비 상대 순위 (0~100, 높을수록 혼잡)
    snapshot['percentile'] = snapshot['혼잡도'].rank(pct=True) * 100

    #2. 역별 '평소' 평균·표준편차 (같은 요일구분, 전체 시간대, 운행중인 데이터 기준) ──
    station_stats = (
        df_model[(df_model['요일구분'] == day_type) & (df_model['혼잡도'] > 0)]
        .groupby(['호선', '출발역', '상하구분'])['혼잡도']
        .agg(평소평균='mean', 평소표준편차='std')
        .reset_index()
    )

    snapshot = snapshot.merge(station_stats, on=['호선', '출발역', '상하구분'], how='left')
    # 표준편차가 0/NaN인 경우 z-score 계산 불가 → NaN 처리
    snapshot['z_score'] = (
        (snapshot['혼잡도'] - snapshot['평소평균']) / snapshot['평소표준편차'].replace(0, np.nan)
    )

    #혼잡 판정: 절대기준선 충족 AND (percentile 상위 top_percentile% 이상 '또는' z-score >= z_threshold)
    is_high_percentile = snapshot['percentile'] >= top_percentile
    is_anomaly         = snapshot['z_score'] >= z_threshold
    is_above_floor     = snapshot['혼잡도'] >= min_absolute_congestion

    def make_reason(row):
        reasons = []
        if row['percentile'] >= top_percentile:
            reasons.append(f"상위 {100-row['percentile']:.0f}%")
        if pd.notna(row['z_score']) and row['z_score'] >= z_threshold:
            reasons.append(f"평소보다 표준편차 {row['z_score']:.1f}σ 높음")
        return ' · '.join(reasons)

    congested = snapshot[(is_high_percentile | is_anomaly) & is_above_floor].copy()
    congested['사유'] = congested.apply(make_reason, axis=1)
    congested = (
        congested[['호선', '출발역', '상하구분', '혼잡도', 'percentile', 'z_score', '사유']]
        .sort_values('혼잡도', ascending=False)
        .reset_index(drop=True)
    )

    #3. 호선별 평균 혼잡도 랭킹 (현재 슬롯 기준)
    line_ranking = (
        snapshot.groupby('호선')['혼잡도']
        .mean()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={'혼잡도': '평균혼잡도'})
    )
    line_ranking['평균혼잡도'] = line_ranking['평균혼잡도'].round(1)

    return congested, line_ranking, day_type, slot


# 콘솔 출력용 헬퍼: 분석 결과를 표 형태로 보기 좋게 출력
def print_current_congestion_analysis(df_model, now=None, top_percentile=90.0, z_threshold=1.5, min_absolute_congestion=70.0):
    congested, line_ranking, day_type, slot = analyze_current_congestion(
        df_model, now, top_percentile, z_threshold, min_absolute_congestion
    )

    disp_min = slot if slot < 1440 else slot - 1440
    h, m = disp_min // 60, disp_min % 60

    print(f"\n현재 시각 기준 ({day_type} {h:02d}:{m:02d} 슬롯) 데이터 분석 결과")
    print(f"   판정 기준: 혼잡도 {min_absolute_congestion:.0f}% 이상 AND(상위 {100-top_percentile:.0f}% 이내 OR 평소 대비 표준편차 {z_threshold}σ 이상)\n")

    print("호선별 평균 혼잡도 랭킹")
    for _, row in line_ranking.iterrows():
        print(f"   {row['호선']:<5} 평균 {row['평균혼잡도']:>5.1f}%")

    print("\n현재 통계적으로 혼잡한 역/호선")
    if congested.empty:
        print("특별히 혼잡한 역이 없습니다.")
    else:
        for _, row in congested.iterrows():
            bar = '🔴' if row['혼잡도'] >= 100 else '🟠'
            z_disp = f"{row['z_score']:.1f}σ" if pd.notna(row['z_score']) else 'N/A'
            print(f"   {bar} {row['호선']:<5} {row['출발역']:<8} ({row['상하구분']})  "
                  f"혼잡도 {row['혼잡도']:>5.1f}%  |  상위 {100-row['percentile']:.0f}%  |  "
                  f"z-score {z_disp}  |  {row['사유']}")

    return congested



#추천 경로(routes 중 하나)의 구간(cong_detail)이 현재 혼잡 역/호선 목록과 겹치는지 확인하고 경고 문구를 반환하는 함수
def check_route_congestion_warning(route, congested_df, check_direction=True):
    """
    Parameters
    ----------
    route           : get_route_with_comfort() 결과 중 하나의 route dict ('cong_detail' 포함)
    congested_df    : analyze_current_congestion()가 반환한 DataFrame (호선,출발역,상하구분,혼잡도 포함)
    check_direction : bool  True면 (호선,역,상하구분)까지 정확히 일치할 때만 경고,
                      False면 (호선,역)만 일치해도 경고 (기본값, 더 안전한 쪽으로 넓게 체크)

    Returns
    -------
    str or None : 경고 문구 1줄 (겹치는 구간이 없으면 None)
    """
    if congested_df is None or congested_df.empty:
        return None

    if check_direction:
        congested_set = set(
            zip(congested_df['호선'], congested_df['출발역'], congested_df['상하구분'])
        )
        overlapped = [
            seg for seg in route['cong_detail']
            if (seg['line'], seg['station_name'], seg['direction']) in congested_set
        ]
    else:
        congested_set = set(zip(congested_df['호선'], congested_df['출발역']))
        overlapped = [
            seg for seg in route['cong_detail']
            if (seg['line'], seg['station_name']) in congested_set
        ]

    if not overlapped:
        return None

    names = ', '.join(f"{seg['line']} {seg['station_name']}" for seg in overlapped)
    return f"주의: 이 경로는 현재 혼잡한 구간({names})을 지나갑니다!"