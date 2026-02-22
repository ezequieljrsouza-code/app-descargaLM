import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")
st.caption("Faça upload do CSV, edite o STATUS e baixe o CSV atualizado.")

# Opções padrão de status (você pode ajustar depois)
DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Descarga finalizada",
    "Cancelado",
]

uploaded = st.file_uploader("📤 Envie o arquivo CSV", type=["csv"])

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

if uploaded:
    # Tenta ler com separadores comuns
    df = None
    read_errors = []
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(uploaded, sep=sep)
            if df is not None and len(df.columns) > 1:
                break
        except Exception as e:
            read_errors.append((sep, str(e)))

    if df is None:
        st.error("Não consegui ler o CSV. Verifique o separador e a codificação.")
        st.stop()

    st.subheader("⚙️ Configurações")

    cols = list(df.columns)

    # Se não existir coluna STATUS, deixa o usuário criar
    has_status = "STATUS" in cols
    c1, c2, c3 = st.columns([2, 2, 3])

    with c1:
        status_col = st.selectbox(
            "Coluna de status",
            options=(["STATUS"] if has_status else []) + cols + (["(criar STATUS)"] if not has_status else []),
            index=0 if has_status else 0,
        )

    with c2:
        status_options_text = st.text_area(
            "Opções de status (uma por linha)",
            value="\n".join(DEFAULT_STATUS_OPTIONS),
            height=140,
        )
        status_options = [s.strip() for s in status_options_text.splitlines() if s.strip()]

    with c3:
        st.info(
            "✅ Dica: se seu CSV não tiver STATUS, escolha “(criar STATUS)”.\n\n"
            "Depois edite a tabela abaixo pelo dropdown e baixe o CSV atualizado."
        )

    if status_col == "(criar STATUS)":
        df["STATUS"] = status_options[0] if status_options else ""
        status_col = "STATUS"

    # Colunas “bonitas” no topo, se existirem (tenta achar similar)
    preferred_order = ["ORDEM", "DOCA", "PLACA", "YMS IN", "YMS OUT", "PACOTES", "STATUS"]
    # Mantém o que existe + resto
    ordered_cols = [c for c in preferred_order if c in df.columns] + [c for c in df.columns if c not in preferred_order]
    df = df[ordered_cols]

    st.subheader("📝 Tabela (edite o STATUS aqui)")

    # Config do dropdown para STATUS
    column_config = {}
    if status_col in df.columns:
        column_config[status_col] = st.column_config.SelectboxColumn(
            status_col,
            options=status_options,
            required=False,
        )

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        num_rows="dynamic",
        key="editor",
    )

    st.divider()
    st.subheader("⬇️ Exportar")

    st.download_button(
        "Baixar CSV atualizado",
        data=to_csv_bytes(edited),
        file_name="monitoramento_lh_atualizado.csv",
        mime="text/csv",
    )

    st.caption("Observação: este app não salva alterações automaticamente em um banco. Ele gera o CSV atualizado para download.")
else:
    st.warning("Envie um CSV para começar.")
