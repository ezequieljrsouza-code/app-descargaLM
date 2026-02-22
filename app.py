import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Concluída",
    "Descarga finalizada",
]

# =========================
# Helpers
# =========================
def to_dt(series):
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def format_hms(dt_series):
    return dt_series.dt.strftime("%H:%M:%S").fillna("")

def df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")

@st.cache_data(show_spinner=False)
def process_csv(file_bytes):
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(BytesIO(file_bytes), sep=sep)
            if len(df.columns) > 1:
                break
        except:
            continue

    # Filtro fixo
    df = df[
        (df["Destino"].astype(str).str.strip() == "SPA1") &
        (to_dt(df["Destino ATA"]).dt.date == date.today()) &
        (df["Motorista"].astype(str).str.strip() != "RODOPENHA")
    ].copy()

    df["__ATA"] = to_dt(df["Destino ATA"])
    df["__ATD"] = to_dt(df["Destino ATD"])
    df["__PAC"] = pd.to_numeric(df["Pacotes"], errors="coerce").fillna(0).astype(int)

    grouped = (
        df.groupby("Veículo de carga 1")
          .agg(
              ATA=("__ATA", "min"),
              ATD=("__ATD", "max"),
              PACOTES=("__PAC", "sum"),
          )
          .reset_index()
          .rename(columns={"Veículo de carga 1": "PLACA"})
    )

    grouped["SORT"] = grouped["ATA"].fillna(grouped["ATD"])
    grouped = grouped.sort_values("SORT").reset_index(drop=True)

    grouped["ORDEM"] = [f"{i}ª" for i in range(1, len(grouped)+1)]
    grouped["YMS IN"] = format_hms(grouped["ATA"])
    grouped["YMS OUT"] = format_hms(grouped["ATD"])
    grouped["DOCA"] = ""
    grouped["STATUS"] = "Aguardando Doca"

    final = grouped[["ORDEM","DOCA","PLACA","YMS IN","YMS OUT","PACOTES","STATUS"]]

    return final


# =========================
# Upload
# =========================
uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])

if not uploaded:
    st.stop()

if "data" not in st.session_state:
    with st.spinner("Processando arquivo..."):
        st.session_state.data = process_csv(uploaded.getvalue())

st.info(f"Placas encontradas: {len(st.session_state.data)}")

# =========================
# Tabela leve (muito mais rápida)
# =========================
edited = st.data_editor(
    st.session_state.data,
    use_container_width=True,
    hide_index=True,
    column_config={
        "DOCA": st.column_config.TextColumn("DOCA"),
        "STATUS": st.column_config.SelectboxColumn("STATUS", options=DEFAULT_STATUS_OPTIONS)
    },
    key="editor"
)

st.session_state.data = edited

st.download_button(
    "⬇️ Baixar CSV atualizado",
    data=df_to_csv_bytes(edited),
    file_name="monitoramento_lh_atualizado.csv",
    mime="text/csv",
)
