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
# Funções auxiliares
# =========================
def to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def format_hms(dt_series: pd.Series) -> pd.Series:
    return dt_series.dt.strftime("%H:%M:%S").fillna("")

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

@st.cache_data(show_spinner=False)
def parse_csv(file_bytes: bytes) -> pd.DataFrame:
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(BytesIO(file_bytes), sep=sep)
            if len(df.columns) > 1:
                return df
        except Exception:
            pass
    raise ValueError("Não consegui ler o CSV.")

# =========================
# Upload CSV
# =========================
uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])

if not uploaded:
    st.stop()

raw = parse_csv(uploaded.getvalue())

# =========================
# Filtro automático
# =========================
col_x = "Destino"
col_y = "Destino ATA"
col_e = "Motorista"

missing = [c for c in [col_x, col_y, col_e] if c not in raw.columns]
if missing:
    st.error(f"CSV não possui as colunas necessárias: {', '.join(missing)}")
    st.stop()

x_value = "SPA1"
today_date = date.today()
e_exclude = "RODOPENHA"

filtered = raw[
    (raw[col_x].astype(str).str.strip() == x_value) &
    (to_dt(raw[col_y]).dt.date == today_date) &
    (raw[col_e].astype(str).str.strip() != e_exclude)
].copy()

st.info(f"Registros após filtro: {len(filtered)}")

if filtered.empty:
    st.warning("Nenhum registro encontrado para hoje com os critérios definidos.")
    st.stop()

# =========================
# Consolidação por placa
# =========================
required_cols = ["Veículo de carga 1", "Destino ATA", "Destino ATD", "Pacotes"]
missing = [c for c in required_cols if c not in filtered.columns]

if missing:
    st.error(f"CSV não possui colunas necessárias: {', '.join(missing)}")
    st.stop()

df = filtered.copy()
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

# Ordenação
grouped["SORT"] = grouped["ATA"].fillna(grouped["ATD"])
grouped = grouped.sort_values("SORT").reset_index(drop=True)

grouped["ORDEM"] = [f"{i}ª" for i in range(1, len(grouped) + 1)]
grouped["YMS IN"] = format_hms(grouped["ATA"])
grouped["YMS OUT"] = format_hms(grouped["ATD"])

grouped = grouped[["ORDEM", "PLACA", "YMS IN", "YMS OUT", "PACOTES"]]

# =========================
# Interface manual (Input + Selectbox por placa)
# =========================
st.subheader("✍️ Atualização Manual")

final_rows = []

for i, row in grouped.iterrows():
    col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 2, 2, 2, 2, 2, 2])

    with col1:
        st.markdown(f"**{row['ORDEM']}**")

    with col2:
        st.markdown(f"**{row['PLACA']}**")

    with col3:
        st.markdown(row["YMS IN"])

    with col4:
        st.markdown(row["YMS OUT"])

    with col5:
        st.markdown(str(row["PACOTES"]))

    with col6:
        doca = st.text_input("Doca", key=f"doca_{i}")

    with col7:
        status = st.selectbox("Status", DEFAULT_STATUS_OPTIONS, key=f"status_{i}")

    final_rows.append({
        "ORDEM": row["ORDEM"],
        "DOCA": doca,
        "PLACA": row["PLACA"],
        "YMS IN": row["YMS IN"],
        "YMS OUT": row["YMS OUT"],
        "PACOTES": row["PACOTES"],
        "STATUS": status,
    })

final_df = pd.DataFrame(final_rows)

st.divider()

st.download_button(
    "⬇️ Baixar CSV atualizado",
    data=df_to_csv_bytes(final_df),
    file_name="monitoramento_lh_atualizado.csv",
    mime="text/csv",
)
