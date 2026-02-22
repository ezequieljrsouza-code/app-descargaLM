import streamlit as st
import pandas as pd

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")
st.caption("Upload do CSV → consolida por PLACA → ordena por horário → usuário edita DOCA e STATUS → baixa CSV atualizado.")

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Descarga finalizada",
    "Cancelado",
]

def read_csv_smart(uploaded_file) -> pd.DataFrame:
    # tenta separadores comuns
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(uploaded_file, sep=sep)
            if df is not None and len(df.columns) > 1:
                return df
        except Exception:
            pass
    raise ValueError("Não consegui ler o CSV (separador/codificação).")

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    # procura por match exato ou case-insensitive
    cols = list(df.columns)
    lower_map = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower_map:
            return lower_map[key]
    return None

def to_dt(series: pd.Series) -> pd.Series:
    # tenta interpretar datas/horas de forma robusta
    # dayfirst=True costuma ajudar em pt-BR
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def build_monitor_df(raw: pd.DataFrame) -> pd.DataFrame:
    # mapeia colunas (ajuste aqui se o CSV usar outros nomes)
    col_placa = find_col(raw, ["Placa", "PLACA"])
    col_ata   = find_col(raw, ["Destino ATA", "DESTINO ATA"])
    col_atd   = find_col(raw, ["Destino ATD", "DESTINO ATD"])
    col_pac   = find_col(raw, ["Pacotes", "PACOTES", "Qtd Pacotes", "Quantidade de Pacotes"])

    missing = [name for name, col in [
        ("Placa", col_placa),
        ("Destino ATA", col_ata),
        ("Destino ATD", col_atd),
        ("Pacotes", col_pac),
    ] if col is None]

    if missing:
        raise ValueError(f"Não encontrei as colunas obrigatórias no CSV: {', '.join(missing)}")

    df = raw.copy()

    # normaliza campos usados
    df[col_placa] = df[col_placa].astype(str).str.strip().str.upper()
    df["__ATA"] = to_dt(df[col_ata])
    df["__ATD"] = to_dt(df[col_atd])

    # pacotes (se vier com texto/NaN)
    df["__PAC"] = pd.to_numeric(df[col_pac], errors="coerce").fillna(0).astype(int)

    # remove linhas sem placa válida
    df = df[df[col_placa].notna() & (df[col_placa] != "")]

    # consolida por PLACA:
    # - entrada: menor ATA (primeira entrada)
    # - saída: maior ATD (última saída)
    # - pacotes: soma
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

    # chave para ordenar: primeiro por entrada; se não tiver, usa saída
    grouped["__SORT"] = grouped["YMS_IN"].fillna(grouped["YMS_OUT"])

    # ordena
    grouped = grouped.sort_values(by="__SORT", ascending=True, na_position="last").reset_index(drop=True)

    # cria ORDEM (1º, 2º, 3º...)
    grouped.insert(0, "ORDEM", range(1, len(grouped) + 1))

    # DOCA e STATUS editáveis pelo usuário
    grouped.insert(1, "DOCA", "")
    grouped["STATUS"] = DEFAULT_STATUS_OPTIONS[0]

    # formata horas (mantém datetime internamente; o Streamlit mostra bem)
    # Se você preferir string HH:MM, descomente as duas linhas:
    # grouped["YMS_IN"] = grouped["YMS_IN"].dt.strftime("%H:%M")
    # grouped["YMS_OUT"] = grouped["YMS_OUT"].dt.strftime("%H:%M")

    # remove coluna de sort
    grouped = grouped.drop(columns=["__SORT"])

    return grouped

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])

if not uploaded:
    st.info("Envie um CSV para começar.")
    st.stop()

try:
    raw = read_csv_smart(uploaded)
except Exception as e:
    st.error(f"Erro lendo CSV: {e}")
    st.stop()

st.subheader("🔎 Prévia do CSV original")
st.dataframe(raw.head(20), use_container_width=True)

try:
    monitor = build_monitor_df(raw)
except Exception as e:
    st.error(f"Erro processando o CSV: {e}")
    st.stop()

st.subheader("🧾 Monitoramento consolidado (edite DOCA e STATUS)")

status_options = st.text_area(
    "Opções de status (uma por linha)",
    value="\n".join(DEFAULT_STATUS_OPTIONS),
    height=120
)
status_list = [s.strip() for s in status_options.splitlines() if s.strip()]

column_config = {
    "STATUS": st.column_config.SelectboxColumn("STATUS", options=status_list, required=False),
    "DOCA": st.column_config.TextColumn("DOCA"),
}

edited = st.data_editor(
    monitor,
    use_container_width=True,
    hide_index=True,
    column_config=column_config,
    num_rows="fixed",
)

st.download_button(
    "⬇️ Baixar CSV atualizado",
    data=df_to_csv_bytes(edited),
    file_name="monitoramento_lh_atualizado.csv",
    mime="text/csv",
)
