import re
import os
import tempfile
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Robot Log Analyser", page_icon="🤖", layout="wide")

st.markdown("""
<style>
.metric-card{background:#fff;border-radius:12px;padding:20px;border:1px solid #e8e8e4;text-align:center}
.metric-label{font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.metric-value{font-size:28px;font-weight:700;color:#1a1a18}
.metric-sub{font-size:12px;color:#aaa;margin-top:4px}
</style>
""", unsafe_allow_html=True)

st.title("🤖 Robot Log Analyser")
st.caption("Upload a robot log file to generate current draw report")

CD_RE    = re.compile(r'CD\s*:\s*([\d.]+)\s*A', re.IGNORECASE)
TS_RE    = re.compile(r'\[.\]\s+(\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})')
NAVIG_RE = re.compile(r'NAVIG.DONE', re.IGNORECASE)
TS_FMT   = "%d/%m/%y %H:%M:%S.%f"

def parse_timestamp(raw):
    try:
        return datetime.strptime(raw.strip(), TS_FMT)
    except:
        return None

def fmt_duration(seconds):
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return "{}h {}m {}s".format(h, m, sec)
    return "{}m {}s".format(m, sec)

def downsample(points, n=3000):
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n)]

uploaded = st.file_uploader("Drop your log file here", type=["txt", "log"], label_visibility="collapsed")

if uploaded:
    progress = st.progress(0, text="Starting...")
    status   = st.empty()

    cd_points   = []
    first_navig = None
    last_navig  = None
    total_lines = 0
    file_size   = uploaded.size
    bytes_read  = 0

    # Write to temp file and parse
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='wb') as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    with open(tmp_path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            bytes_read += len(line.encode('utf-8', errors='replace'))
            total_lines += 1

            if total_lines % 100000 == 0:
                pct = min(99, int(bytes_read / file_size * 100))
                progress.progress(pct, text="Parsing... {:,} lines".format(total_lines))

            ts_match = TS_RE.search(line)
            ts = parse_timestamp(ts_match.group(1)) if ts_match else None
            cd_match = CD_RE.search(line)
            if cd_match and ts:
                cd_points.append((ts, float(cd_match.group(1))))
            if NAVIG_RE.search(line) and ts:
                if first_navig is None:
                    first_navig = ts
                last_navig = ts

    progress.progress(100, text="Done!")
    progress.empty()
    status.empty()
    os.unlink(tmp_path)

    if not cd_points:
        st.error("No current draw (CD) data found in this log file.")
    else:
        values  = [v for _, v in cd_points]
        max_val = max(values)
        avg_val = sum(values) / len(values)
        max_ts  = cd_points[values.index(max_val)][0]

        runtime_str = "N/A"
        navig_range = "No NAVIG DONE markers found"
        if first_navig and last_navig:
            delta = (last_navig - first_navig).total_seconds()
            runtime_str = fmt_duration(delta)
            navig_range = "{} → {}".format(first_navig.strftime("%H:%M:%S"), last_navig.strftime("%H:%M:%S"))

        # Metrics
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Max Current", "{:.3f} A".format(max_val), "at {}".format(max_ts.strftime("%H:%M:%S")))
        with c2:
            st.metric("Avg Current", "{:.3f} A".format(avg_val), "{:,} readings".format(len(values)))
        with c3:
            st.metric("Run Time", runtime_str, navig_range)
        with c4:
            st.metric("Lines Scanned", "{:,}".format(total_lines), uploaded.name)

        # Chart
        sampled = downsample(cd_points, 3000)
        times   = [t.strftime("%H:%M:%S") for t, _ in sampled]
        data    = [v for _, v in sampled]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=times, y=data, mode='lines', name='Current (A)',
            line=dict(color='#1a1a18', width=1.5), fill='tozeroy',
            fillcolor='rgba(26,26,24,0.05)'))
        fig.add_trace(go.Scatter(x=times, y=[max_val]*len(times), mode='lines', name='Max ({:.3f} A)'.format(max_val),
            line=dict(color='#E24B4A', width=1.2, dash='dash')))
        fig.add_trace(go.Scatter(x=times, y=[avg_val]*len(times), mode='lines', name='Avg ({:.3f} A)'.format(avg_val),
            line=dict(color='#1D9E75', width=1.2, dash='dash')))

        fig.update_layout(
            title="Current draw over time",
            xaxis_title="Time", yaxis_title="Current (A)",
            plot_bgcolor='white', paper_bgcolor='white',
            hovermode='x unified', height=420,
            legend=dict(orientation='h', y=1.1),
            xaxis=dict(showgrid=True, gridcolor='#f0f0ec'),
            yaxis=dict(showgrid=True, gridcolor='#f0f0ec'),
            margin=dict(l=20, r=20, t=60, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Chart shows {:,} of {:,} points (downsampled). All stats use full dataset.".format(len(sampled), len(values)))
