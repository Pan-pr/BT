import streamlit as st
import networkx as nx
import folium
from streamlit_folium import st_folium

# (station definitions, fares, graph build ... same as before)

# -----------------------------
# Service Info (Operating hours, frequencies)
# -----------------------------

SERVICE_INFO = {
    "BTS": {
        "open": "05:30",
        "close": "24:00",
        "freq_min": 3,
        "freq_max": 8,
    },
    "MRT": {
        "open": "06:00",
        "close": "24:00",
        "freq_min": 4,
        "freq_max": 10,
    },
    "ARL": {
        "open": "05:30",
        "close": "24:00",
        "freq_min": 10,
        "freq_max": 15,
    },
}

# -----------------------------
# Pathfinding
# -----------------------------

class Planner:
    def __init__(self, graph):
        self.G = graph

    def shortest_time(self, src_key, dst_key):
        return nx.shortest_path(self.G, src_key, dst_key, weight=lambda u, v, d: d["time_s"])

    def shortest_fare(self, src_key, dst_key):
        path = self.shortest_time(src_key, dst_key)
        legs = self.path_to_legs(path)
        total_fare = 0
        for leg in legs:
            if leg["type"] == "ride":
                nstops = len(leg["stops"]) - 1
                fare_fn = FARE_FN.get(leg["operator"], lambda n: 0)
                total_fare += fare_fn(nstops)
        return path, total_fare

    def minimal_transfers(self, src_key, dst_key):
        def weight(u, v, d):
            if d["kind"] == "transfer":
                return 10000
            return 1
        return nx.shortest_path(self.G, src_key, dst_key, weight=weight)

    def path_to_legs(self, path):
        legs = []
        if len(path) < 2:
            return legs
        cur_leg = None
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            d = self.G.get_edge_data(u, v)
            if isinstance(d, dict) and 0 in d:
                d = d[0]
            if d["kind"] == "transfer":
                if cur_leg:
                    legs.append(cur_leg)
                    cur_leg = None
                legs.append({"type": "transfer", "from": u, "to": v, "time_s": d["time_s"]})
            else:
                if not cur_leg:
                    cur_leg = {"type":"ride","operator":d["operator"],"line":d["line"],"stops":[u,v],"time_s":d["time_s"],"dist_km":d["dist_km"]}
                else:
                    if cur_leg["operator"]==d["operator"] and cur_leg["line"]==d["line"]:
                        cur_leg["stops"].append(v)
                        cur_leg["time_s"]+=d["time_s"]
                        cur_leg["dist_km"]+=d["dist_km"]
                    else:
                        legs.append(cur_leg)
                        cur_leg={"type":"ride","operator":d["operator"],"line":d["line"],"stops":[u,v],"time_s":d["time_s"],"dist_km":d["dist_km"]}
        if cur_leg:
            legs.append(cur_leg)
        return legs

    def plan(self, src_name, dst_name, optimize="time"):
        srcs = station_lookup().get(src_name)
        dsts = station_lookup().get(dst_name)
        if not srcs or not dsts:
            return None
        src_key = srcs[0].key()
        dst_key = dsts[0].key()

        if optimize == "fare":
            path, est_fare = self.shortest_fare(src_key, dst_key)
        elif optimize == "transfers":
            path = self.minimal_transfers(src_key, dst_key)
            legs = self.path_to_legs(path)
            est_fare = 0
            for leg in legs:
                if leg["type"] == "ride":
                    nstops = len(leg["stops"])-1
                    est_fare += FARE_FN.get(leg["operator"], lambda n:0)(nstops)
        else:
            path = self.shortest_time(src_key, dst_key)
            legs = self.path_to_legs(path)
            est_fare = 0
            for leg in legs:
                if leg["type"]=="ride":
                    nstops=len(leg["stops"])-1
                    est_fare+=FARE_FN.get(leg["operator"],lambda n:0)(nstops)

        total_time=0
        for i in range(len(path)-1):
            d=self.G.get_edge_data(path[i], path[i+1])
            if isinstance(d, dict) and 0 in d:
                d=d[0]
            total_time+=d["time_s"]
        legs=self.path_to_legs(path)

        for leg in legs:
            if leg["type"] == "ride":
                op = leg["operator"]
                svc = SERVICE_INFO.get(op, None)
                if svc:
                    leg["service"] = svc

        return {"path":path,"legs":legs,"fare":int(round(est_fare)),"time_s":int(round(total_time))}

PLANNER=Planner(G)

# -----------------------------
# Streamlit UI
# -----------------------------

st.title("🚇 Bangkok Transit Planner")

src = st.text_input("ต้นทาง")
dst = st.text_input("ปลายทาง")
optimize = st.selectbox("เกณฑ์การวางแผน", ["time", "fare", "transfers"])

if st.button("วางแผน"):
    plan = PLANNER.plan(src, dst, optimize=optimize)
    if plan:
        st.subheader("สรุป")
        st.write(f"เวลา: {plan['time_s']//60} นาที | ค่าโดยสารประมาณ: {plan['fare']} บาท")

        st.subheader("รายละเอียดการเดินทาง")
        for leg in plan["legs"]:
            if leg["type"]=="ride":
                st.markdown(f"**{leg['operator']} {leg['line']}** ผ่าน {len(leg['stops'])-1} สถานี ({leg['time_s']//60} นาที)")
                if "service" in leg:
                    svc = leg["service"]
                    st.caption(f"เวลาเปิด: {svc['open']} - ปิด: {svc['close']} | ความถี่: {svc['freq_min']}-{svc['freq_max']} นาที")
            else:
                st.markdown(f"🔄 เปลี่ยนสายที่ {leg['from']} → {leg['to']} ({leg['time_s']//60} นาที)")

        st.subheader("แผนที่")
        m = folium.Map(location=[13.7563, 100.5018], zoom_start=11)
        # draw path
        for node in plan["path"]:
            # assume station_lookup() has lat/lon
            stn = station_by_key(node)
            folium.Marker([stn.lat, stn.lon], popup=stn.name).add_to(m)
        st_folium(m, width=700, height=500)
    else:
        st.error("ไม่พบเส้นทาง")
