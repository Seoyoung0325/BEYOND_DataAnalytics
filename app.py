"""Flask 서버 실행 코드"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime
import requests as req
import os

#data_pipeline.py에서 필요한 것들 import
from data_pipeline import (
    # 데이터
    df_model,
    lookup_table,
    facility_map,
    # 함수
    get_route_with_comfort,
    find_optimal_departure,
    analyze_current_congestion,
    check_route_congestion_warning,
    parse_time_to_minutes,
    call_tmap_transit,
    TMAP_API_KEY,
)


LINE_COLORS = {
    '1호선': '#0052A4', '2호선': '#00A84D', '3호선': '#EF7C1C',
    '4호선': '#00A5DE', '5호선': '#996CAC', '6호선': '#CD7C2F',
    '7호선': '#747F00', '8호선': '#E6186C', '9호선': '#BDB092',
    '수인분당선': '#F5A200', '신분당선': '#D4003B', '경의중앙선': '#77C4A3',
}

def normalize_line(raw):
    """'수도권2호선' → '2호선'"""
    import re as _re
    match = _re.search(r'(\d+)호선', raw)
    return f'{match.group(1)}호선' if match else raw

app = Flask(__name__)



# ================================================================
# 페이지 라우팅

@app.route('/')
def index():
    """시작 화면"""
    return render_template('index_main.html')


@app.route('/result')
def result():
    """결과 화면"""
    return render_template('index.html')



# ================================================================
## API 엔드포인트

@app.route('/api/geocode')
def geocode():
    """역명 → 위경도 변환 (TMAP POI 검색)"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': '검색어가 없습니다.'}), 400

    try:
        res = req.get(
            'https://apis.openapi.sk.com/tmap/pois',
            params={
                'version':       1,
                'searchKeyword': query,
                'count':         1,
                'searchType':    'all',
            },
            headers={'appKey': TMAP_API_KEY},
            timeout=5,
        )
        print(res.json)
        poi = res.json()['searchPoiInfo']['pois']['poi'][0]
        return jsonify({
            'lat':  float(poi['frontLat']),
            'lon':  float(poi['frontLon']),
            'name': poi.get('name', query),
        })
    except Exception as e:
        return jsonify({'error': f'좌표 변환 실패: {str(e)}'}), 500


@app.route('/api/search', methods=['POST'])
def search():
    """경로 검색 → 쾌적도 계산"""
    data = request.get_json()

    try:
        origin_lat    = float(data['origin_lat'])
        origin_lon    = float(data['origin_lon'])
        dest_lat      = float(data['dest_lat'])
        dest_lon      = float(data['dest_lon'])
        depart_dt     = datetime.fromisoformat(data['depart_dt'])
        user_switches = data.get('user_switches', {
            'time': True, 'walk': True, 'fare': True,
            'transfer': True, 'facility': True,
            'congestion': True, 'seating': True,
        })
    except (KeyError, ValueError) as e:
        return jsonify({'error': f'잘못된 요청 형식: {str(e)}'}), 400

    routes = get_route_with_comfort(
        origin_lat, origin_lon,
        dest_lat,   dest_lon,
        depart_dt,
        user_switches=user_switches,
        facility_map=facility_map,
    )

    if not routes:
        return jsonify({'error': '경로를 찾을 수 없습니다.'}), 404

    # TMAP 원본 응답에서 경로 좌표 추출
    try:
        raw_tmap    = call_tmap_transit(origin_lat, origin_lon, dest_lat, dest_lon, depart_dt)
        itineraries = raw_tmap.get('metaData', {}).get('plan', {}).get('itineraries', [])
    
        def parse_linestring(ls):
            """'lon,lat lon,lat ...' → [[lat,lon], ...] 변환"""
            path = []
            for pt in ls.strip().split(' '):
                parts = pt.split(',')
                if len(parts) == 2:
                    try:
                        lon2, lat2 = float(parts[0]), float(parts[1])
                        if lat2 and lon2:
                            path.append([lat2, lon2])
                    except ValueError:
                        pass
            return path
    
        for i, r in enumerate(routes):
            if i >= len(itineraries):
                r['map_segments'] = []
                continue

            legs_coords = []
            for leg in itineraries[i].get('legs', []):
                mode = leg.get('mode', '')

                if mode == 'WALK':
                    # 도보: steps linestring 이어붙이기
                    path = []
                    for step in leg.get('steps', []):
                        ls = step.get('linestring', '')
                        if ls:
                            path.extend(parse_linestring(ls))
                    if not path:
                        s, e = leg.get('start', {}), leg.get('end', {})
                        try:
                            path = [[float(s['lat']), float(s['lon'])],
                                    [float(e['lat']), float(e['lon'])]]
                        except (KeyError, ValueError, TypeError):
                            path = []
                    if len(path) >= 2:
                        legs_coords.append({'color': '#aaaaaa', 'path': path, 'dash': True})

                elif mode == 'BUS':
                    # 버스: passShape.linestring 우선
                    ls = leg.get('passShape', {}).get('linestring', '')
                    path = parse_linestring(ls) if ls else []
                    if not path:
                        for s in leg.get('passStopList', {}).get('stationList', []):
                            try:
                                path.append([float(s['lat']), float(s['lon'])])
                            except (KeyError, ValueError, TypeError):
                                pass
                    if len(path) >= 2:
                        color = '#' + leg.get('routeColor', 'FF8C00')
                        legs_coords.append({'color': color, 'path': path, 'dash': False})

                elif mode == 'SUBWAY':
                    # 지하철: passShape.linestring 우선
                    ls = leg.get('passShape', {}).get('linestring', '')
                    path = parse_linestring(ls) if ls else []
                    if not path:
                        stops = (leg.get('passStopList', {}).get('stations')
                                 or leg.get('passStopList', {}).get('stationList', []))
                        for s in stops:
                            try:
                                path.append([float(s['lat']), float(s['lon'])])
                            except (KeyError, ValueError, TypeError):
                                pass
                    line  = normalize_line(leg.get('route', ''))
                    color = LINE_COLORS.get(line, '#888888')
                    if len(path) >= 2:
                        legs_coords.append({'color': color, 'path': path, 'dash': False})

            r['map_segments'] = legs_coords
    
    except Exception as e:
        print(f'map_segments 추출 실패: {e}')
        for r in routes:
            r.setdefault('map_segments', [])

    # cong_detail 안의 datetime 등 직렬화 불가 타입 처리
    for r in routes:
        for seg in r.get('cong_detail', []):
            seg.pop('elapsed_min', None)

    return jsonify(routes)


@app.route('/api/optimal-time', methods=['POST'])
def optimal_time():
    """최적 출발 시각 추천"""
    data = request.get_json()

    try:
        routes      = data['routes']
        target_date = datetime.fromisoformat(data['target_date'])
        start_time  = data['start_time']   # '8시30분' 형식
        end_time    = data['end_time']
        target      = data.get('target', 'best')
    except KeyError as e:
        return jsonify({'error': f'필수 파라미터 누락: {str(e)}'}), 400

    try:
        result = find_optimal_departure(
            routes      = routes,
            target_date = target_date,
            start_time  = start_time,
            end_time    = end_time,
            target      = target,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'optimal_time':   result['optimal_time'],
        'min_congestion': result['min_congestion'],
        'all_results':    result['all_results'].to_dict(orient='records'),
    })


@app.route('/api/warning')
def warning():
    """현재 시각 기준 혼잡 역/호선 경고"""
    congested, line_ranking, day_type, slot = analyze_current_congestion(df_model)

    # NaN → None 변환 (JSON 직렬화)
    congested_records = (
        congested
        .where(congested.notna(), other=None)
        .to_dict(orient='records')
    )

    disp_min = slot if slot < 1440 else slot - 1440
    h, m = disp_min // 60, disp_min % 60

    return jsonify({
        'congested':    congested_records,
        'line_ranking': line_ranking.to_dict(orient='records'),
        'day_type':     day_type,
        'current_time': f'{h:02d}:{m:02d}',
    })


@app.route('/api/route-warning', methods=['POST'])
def route_warning():
    """추천 경로에 혼잡 구간 포함 여부 체크"""
    data = request.get_json()
    route = data.get('route')

    congested, _, _, _ = analyze_current_congestion(df_model)
    warning_msg = check_route_congestion_warning(route, congested)

    return jsonify({'warning': warning_msg})



# ================================================================
# 실행
if __name__ == '__main__':
    app.run(debug=True, port=5000)