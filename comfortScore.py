import requests
import json
#착석가능성 계산함수
def get_seating_score(congestion):
    # ① 예외 처리: 예측값이 없으면(None) 똑같이 None 반환하여 에러 방지
    if congestion is None:
        return None

    # ② 전원 착석 구간: 혼잡도 33.8% 이하 ➔ 무조건 1
    if congestion <= 33.8:
        return 1.0

    # ③ 착석 비율 계산: 혼잡도가 높을수록 점수가 비례해서 감소
    return round(33.8 / congestion,3)

# ==========================================
# 1. 쾌적도 계산 로직 함수 (기존 코드)
# ==========================================
def calculate_comfort_score(api_data, user_switches):
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
     # main의 dataAnalytics 의 함수 사용
    if user_switches.get('seating'):
        c_val = predict_congestion('congestionCarValue')
        seat_score = get_seating_score(c_val)
        if seat_score is not None:
            multiplier *= seat_score

    final_score = base_avg * multiplier * 100
    return round(final_score, 1)
    


# ==========================================
# 2. SK TMAP 대중교통 API 연동 함수 
# ==========================================
def get_sk_transit_data(app_key):
    url = "https://apis.openapi.sk.com/transit/routes"
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "appKey": app_key
    }
    # 예시 좌표: 출발지(서울역 Y:37.5546, X:126.9706) -> 도착지(강남역 Y:37.4979, X:127.0276)
    payload = {
        "startX": "126.9706",
        "startY": "37.5546",
        "endX": "127.0276",
        "endY": "37.4979",
        "lang": 0,
        "format": "json",
        "count": 1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            res_json = response.json()
            itinerary = res_json['metaData']['plan']['itineraries'][0]
            
            extracted_data = {
                "totalTime": itinerary.get("totalTime"),
                "totalWalkTime": itinerary.get("totalWalkTime"),
                "totalFare": itinerary['fare']['regular'].get("totalFare"),
                "transferCount": itinerary.get("transferCount"),
                "facilityScore": 0.7,
                "congestionCarValue": 135,#학습된 혼잡도 모델로 판단한 혼잡도 넣을 것
            }
            return extracted_data
        else:
      
            print(f"SK API 요청 실패 (오류 코드): {response.status_code}")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"네트워크 통신 에러: {e}")
        return None

# ==========================================
# 3. 실제 메인 실행 영역
# ==========================================
if __name__ == "__main__":
    API_KEY = "bAAYljxPKgakoZWpbHOJQ9BA8OMlFwXA77bGh7LS" 
    
    print("1. SK TMAP 대중교통 API 호출 중...")
    api_result = get_sk_transit_data(API_KEY)
    
    if api_result:
        print("\n2. [SK API]로부터 받아온 실제 경로 데이터:")
        print(f"   - 총 소요 시간: {round(api_result['totalTime']/60)}분")
        print(f"   - 총 도보 시간: {round(api_result['totalWalkTime']/60)}분")
        print(f"   - 요금: {api_result['totalFare']}원")
        print(f"   - 환승 횟수: {api_result['transferCount']}회")
        print(f"   - 가상 혼잡도: {api_result['congestionCarValue']}%")
        print("-" * 50)
        
        # 3. 유저가 가상으로 웹/앱 UI에서 스위치를 켰다 껐다 하는 상황 설정
        user_switches = {
            'time': True, 
            'walk': True, 
            'fare': True, 
            'transfer': True, 
            'facility': False, 
            'congestion': True, 
            'seating': True
        }
        
        # 4. 최종 쾌적도 점수 계산
        comfort_score = calculate_comfort_score(api_result, user_switches)
        
        print("3. [최종 결과] 사용자 맞춤형 쾌적도 점수:")
        print(f"   ➔ 현재 이 경로의 쾌적도 점수는 【 {comfort_score}점 】 입니다!")