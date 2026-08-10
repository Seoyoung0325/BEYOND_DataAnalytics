import folium
from folium import DivIcon

# 서울역 부근을 중심 좌표로 사용
SEOUL_CENTER = [37.5547, 126.9707]

m = folium.Map(
    location=SEOUL_CENTER,
    zoom_start=15,
    tiles="CartoDB dark_matter",  #지도 모드
)

# 출발/도착 결합 마커
start_end_html = """
<div style="display:flex;flex-direction:column;align-items:center;">
  <div style="display:flex;overflow:hidden;border-radius:14px;
              box-shadow:0 2px 8px rgba(0,0,0,.35);">
    <div style="background:#e74c3c;color:#fff;padding:10px 20px;
                font-weight:800;font-size:16px;white-space:nowrap;">출발</div>
    <div style="background:#5cb85c;color:#fff;padding:10px 20px;
                font-weight:800;font-size:16px;white-space:nowrap;">도착</div>
  </div>
  <div style="width:26px;height:16px;margin-top:-1px;
              clip-path: polygon(0 0, 100% 0, 50% 100%);
              background: linear-gradient(to right, #e74c3c 50%, #5cb85c 50%);"></div>
</div>
"""

folium.Marker(
    location=SEOUL_CENTER,
    icon=DivIcon(html=start_end_html, icon_size=(170, 85), icon_anchor=(85, 85)),
).add_to(m)

# 결과를 map.html 파일로 저장
m.get_root().html.add_child(folium.Element("""
<style>
  html, body, #map {
    width: 100%; height: 100%;
    margin: 0; padding: 0;
    overflow: hidden;
    background-color: #2a4067;
  }
  .leaflet-container { background: #2a4067 !important; }
  .leaflet-tile {
    opacity: 0.5 !important;
    filter: sepia(100%) hue-rotate(180deg) saturate(300%) brightness(3.0) contrast(1.1) !important;
  }
  .leaflet-control-zoom, .leaflet-control-attribution { display: none !important; }
</style>
"""))

m.save("map.html")
print("map.html 생성 완료!")