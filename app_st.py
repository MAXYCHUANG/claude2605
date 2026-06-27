import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from scripts.cc_spot_intraday_monitor import SYMBOLS, _fetch_1m, _parse_bars, _analyze, get_latest_oc_metadata

st.set_page_config(page_title="3-Layer Spot Monitor", layout="wide", page_icon="📈")

st.title("📈 3-Layer Spot Monitor")
st.markdown("Integrates Real-time Spot momentum with Static Pre-market OC Metadata (Put Wall, Max Pain, G1, Call Wall).")

st.sidebar.header("Controls")
window_min = st.sidebar.selectbox("Analysis Window (minutes)", [5, 15, 30, 90, 150], index=2)
refresh = st.sidebar.button("🔄 Refresh Data")

@st.cache_data(ttl=60)
def load_data(symbol, window):
    raw = _fetch_1m(symbol)
    meta, bars = _parse_bars(raw)
    if not bars:
        return None, None, None
    analysis = _analyze(meta, bars, window, symbol)
    df = pd.DataFrame(bars)
    return analysis, df, bars

for sym in SYMBOLS:
    st.markdown("---")
    st.subheader(f"🔹 {sym}")
    try:
        # We clear cache manually if refresh button is pressed
        if refresh:
            load_data.clear()
            
        analysis, df, bars = load_data(sym, window_min)
        if not analysis:
            st.warning(f"No data available for {sym}")
            continue
            
        # ── 1. Top Metrics ──
        col1, col2, col3, col4, col5 = st.columns(5)
        
        c = analysis['price_w']
        pct = analysis['pct_prev']
        col1.metric("Current Price", f"${c:.2f}", f"{pct:+.2f}%")
        
        vwap = analysis['vwap_w']
        sig_vwap = analysis['sig_vwap']
        col2.metric("VWAP", f"${vwap:.2f}", f"{'High' if sig_vwap >= 0 else 'Low'}")
        
        mf = analysis['mf_net_m']
        mom = analysis['signals'][0][1]
        col3.metric("MF (Net)", f"{mf:+.0f}M", f"{mom}")
        
        col4.metric("Direction", analysis['direction'])
        col5.metric("Volume Pace", analysis['pace_label'].replace('⚡', '').replace('🔥', '').replace('✅', '').replace('📉', '').strip())
        
        # ── 2. Interactive Chart ──
        fig = go.Figure(data=[go.Candlestick(
            x=df['dt'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name=sym
        )])
        
        # VWAP Line
        fig.add_trace(go.Scatter(
            x=df['dt'], y=[vwap]*len(df), 
            mode='lines', 
            line=dict(color='yellow', width=1.5, dash='dash'), 
            name='VWAP (Window)'
        ))
        
        # OC Metadata Lines
        oc = analysis.get("oc", {})
        if oc:
            colors = {"Put Wall": "red", "Max Pain": "orange", "G1": "purple", "Call Wall": "green"}
            for key in ["Put Wall", "Max Pain", "G1", "Call Wall"]:
                if key in oc and oc[key] > 0:
                    fig.add_hline(
                        y=oc[key], 
                        line_dash="dash", 
                        line_color=colors[key], 
                        annotation_text=f"{key}: ${oc[key]}", 
                        annotation_position="top left",
                        annotation_font_color=colors[key]
                    )
                    
        # Style Chart
        fig.update_layout(
            height=450,
            margin=dict(l=0, r=0, t=30, b=0),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            yaxis_title="Price"
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error loading {sym}: {e}")
