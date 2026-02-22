import streamlit as st
import pandas as pd

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")
st.caption(
    "Upload do CSV → consolida por PLACA → ordena por horário → usuário edita DOCA e STATUS → baixa CSV atualizado."
)

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Descarga finalizada",
    "Cancelado",
]

def read_csv_smart(uploaded_file) -> pd.DataFrame:
    # Tenta separadores comuns (muito CSV pt-BR usa ';')
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(uploaded_file, sep=sep)
            if df is not None and len(df.columns) > 1:
                return df
        except Exception:
            pass
    raise ValueError("Não consegui ler o CSV (separador/codificação).")

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    # Procura match exato e case-insensitive
    cols = list(df.columns)
    lower_map = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower_map:
            return lower_map[key]
    return None

def to_dt(series: pd.Series) -> pd.Series:
    # Interpreta datas/horas de forma robusta (pt-BR)
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def build_monitor_df(raw: pd.DataFrame) -> pd.DataFrame:
    # Colunas do CSV
    col_placa = find_col(raw, ["Veículo de carga 1", "VEÍCULO DE CARGA 1"])
    col_ata   = find_col(raw, ["Destino ATA", "DESTINO ATA"])
    col_atd   = find_col(raw, ["Destino ATD", "DESTINO ATD"])
    col_pac   = find_col(raw, ["Pacotes", "PACOTES", "Qtd Pacotes", "Quantidade de Pacotes"])

    missing = [name for name, col in [
        ("Veículo de carga 1", col_placa),
        ("Destino ATA", col_ata),
        ("Destino ATD", col_atd),
        ("Pacotes", col_pac),
    ] if col is None]

    if missing:
        raise ValueError(f"Não encontrei as colunas obrigatórias no CSV: {', '.join(missing)}")

    df = raw.copy()

    # Normaliza placa
    df[col_placa] = df[col_placa].astype(str).str.strip().str.upper()

    # Converte datas/horas
    df["__ATA"] = to_dt(df[col_ata])
    df["__ATD"] = to_dt(df[col_atd])

    # Pacotes numérico
    df["__PAC"] = pd.to_numeric(df[col_pac], errors="coerce").fillna(0).astype(int)

    # Remove linhas sem placa válida
    df = df[df[col_placa].notna() & (df[col_placa] != "")]

    # Consolida por PLACA:
    # - YMS_IN: menor ATA por placa
    # - YMS_OUT: maior ATD por placa
    # - PACOTES: soma por placa
    grouped = (
        df.groupby(col_placa, dropna=False)
          .agg(
              YMS_IN=("__ATA", "min"),
              YMS_OUT=("__ATD", "max"),
              PACOTES=("__PAC", "sum"),
          )
          .reset_index()
          .rename(columns={col_placa: "PLACA"})
    )

    # Ordena por YMS_IN (se vazio, usa YMS_OUT)
    grouped["__SORT"] = grouped["YMS_IN"].fillna(grouped["YMS_OUT"])
    grouped = grouped.sort_values(by="__SORT", ascending=True, na_position="last").reset_index(drop=True)

    # Cria ORDEM 1..N
    grouped.insert(0, "ORDEM", range(1, len(grouped) + 1))

    # Colunas editáveis pelo usuário
    grouped.insert(1, "DOCA", "")
    grouped["STATUS"] = DEFAULT_STATUS_OPTIONS[0]

    # (Opcional) Se quiser mostrar só HH:MM, descomente:
    # grouped["YMS_IN"] = grouped["YMS_IN"].dt.strftime("%H:%M")
    # grouped["YMS_OUT"] = grouped["YMS_OUT"].dt.strftime("%H:%M")

    grouped = grouped.drop(columns=["__SORT"])
    return grouped

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])

if not uploaded:
    st.info("Envie um CSV para começar.")
    st.stop()

# Lê o CSV
try:
    raw = read_csv_smart(uploaded)
except Exception as e:
    st.error(f"Erro lendo CSV: {e}")
    st.stop()

with st.expander("🔎 Ver prévia do CSV original (primeiras 20 linhas)"):
    st.dataframe(raw.head(20), use_container_width=True)

# Processa e consolida
try:
    monitor = build_monitor_df(raw)
except Exception as e:
    st.error(f"Erro processando o CSV: {e}")
    st.stop()

st.subheader("🧾 Monitoramento consolidado (edite DOCA e STATUS)")

status_options_text = st.text_area(
    "Opções de STATUS (uma por linha)",
    value="\n".join(DEFAULT_STATUS_OPTIONS),
    height=120
)
status_list = [s.strip() for s in status_options_text.splitlines() if s.strip()]

column_config = {
    "DOCA": st.column_config.TextColumn("DOCA"),
    "STATUS": st.column_config.SelectboxColumn("STATUS", options=status_list, required=False),
}

edited = st.data_editor(
    monitor,
    use_container_width=True,
    hide_index=True,
    column_config=column_config,
    num_rows="fixed",
    key="editor",
)

st.download_button(
    "⬇️ Baixar CSV atualizado",
    data=df_to_csv_bytes(edited),
    file_name="monitoramento_lh_atualizado.csv",
    mime="text/csv",
)
