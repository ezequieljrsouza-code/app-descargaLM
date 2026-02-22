import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from typing import Optional, List
from datetime import date

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")
st.caption(
    "Upload do CSV → filtro do dia (Destino=SPA1, data(Destino ATA)=hoje, Motorista!=RODOPENHA) → "
    "consolida por PLACA → edita DOCA/STATUS → baixa CSV e PNG (WhatsApp)."
)

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Concluída",
    "Descarga finalizada",
    "Cancelado",
]

# ----------------- Utils -----------------
def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    lower_map = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower_map:
            return lower_map[key]
    return None

def to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def fmt_hms(dt_series: pd.Series) -> pd.Series:
    s = dt_series.dt.strftime("%H:%M:%S")
    return s.fillna("")

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

# ----------------- Cache: parse -----------------
@st.cache_data(show_spinner=False)
def parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(BytesIO(file_bytes), sep=sep)
            if df is not None and len(df.columns) > 1:
                return df
        except Exception:
            pass
    raise ValueError("Não consegui ler o CSV (verifique separador/codificação).")

# ----------------- Filtering & grouping -----------------
def apply_daily_filter(raw: pd.DataFrame, x_value: str, day_value: date, e_exclude: str) -> pd.DataFrame:
    # Colunas fixas conforme você informou
    col_x = "Destino"
    col_y = "Destino ATA"
    col_e = "Motorista"

    # Valida existência
    missing = [c for c in [col_x, col_y, col_e] if c not in raw.columns]
    if missing:
        raise ValueError(f"CSV não tem as colunas necessárias para o filtro: {', '.join(missing)}")

    x_ok = raw[col_x].astype(str).str.strip().eq(str(x_value).strip())
    y_dt = to_dt(raw[col_y])
    y_ok = y_dt.dt.date.eq(day_value)
    e_ok = raw[col_e].astype(str).str.strip().ne(str(e_exclude).strip())

    return raw[x_ok & y_ok & e_ok].copy()

def build_monitor_df(filtered: pd.DataFrame) -> pd.DataFrame:
    # Colunas fixas
    col_placa = "Veículo de carga 1"
    col_ata = "Destino ATA"
    col_atd = "Destino ATD"
    col_pac = "Pacotes"

    missing = [c for c in [col_placa, col_ata, col_atd, col_pac] if c not in filtered.columns]
    if missing:
        raise ValueError(f"CSV filtrado não tem as colunas necessárias: {', '.join(missing)}")

    df = filtered.copy()
    df[col_placa] = df[col_placa].astype(str).str.strip().str.upper()
    df["__ATA"] = to_dt(df[col_ata])
    df["__ATD"] = to_dt(df[col_atd])
    df["__PAC"] = pd.to_numeric(df[col_pac], errors="coerce").fillna(0).astype(int)

    df = df[df[col_placa].notna() & (df[col_placa] != "")]

    grouped = (
        df.groupby(col_placa, dropna=False)
          .agg(
              ATA=("__ATA", "min"),
              ATD=("__ATD", "max"),
              PACOTES=("__PAC", "sum"),
          )
          .reset_index()
          .rename(columns={col_placa: "PLACA"})
    )

    grouped["__SORT"] = grouped["ATA"].fillna(grouped["ATD"])
    grouped = grouped.sort_values(by="__SORT", ascending=True, na_position="last").reset_index(drop=True)

    grouped.insert(0, "ORDEM", [f"{i}ª" for i in range(1, len(grouped) + 1)])
    grouped.insert(1, "DOCA", "")
    grouped["STATUS"] = "Aguardando Doca"

    grouped["YMS IN"] = fmt_hms(grouped["ATA"])
    grouped["YMS OUT"] = fmt_hms(grouped["ATD"])

    grouped = grouped.drop(columns=["ATA", "ATD", "__SORT"])
    grouped = grouped[["ORDEM", "DOCA", "PLACA", "YMS IN", "YMS OUT", "PACOTES", "STATUS"]]
    return grouped

# ----------------- PNG rendering (on demand) -----------------
@st.cache_resource
def get_fonts():
    def load_font(size: int):
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    return {
        "title": load_font(30),
        "header": load_font(16),
        "cell": load_font(16),
        "bold": load_font(18),
    }

def status_style(status: str):
    s = (status or "").strip().lower()
    if "descarga inici" in s:
        return {"fill": (255, 235, 59), "text": (0, 0, 0)}          # amarelo
    if "conclu" in s:
        return {"fill": (22, 120, 74), "text": (255, 255, 255)}    # verde
    if "aguardando" in s:
        return {"fill": (70, 70, 70), "text": (255, 255, 255)}     # cinza escuro
    if "não chegou" in s or "nao chegou" in s:
        return {"fill": (255, 165, 0), "text": (255, 255, 255)}    # laranja
    return {"fill": (200, 200, 200), "text": (0, 0, 0)}            # cinza claro

def render_monitor_png(df: pd.DataFrame, max_rows: int = 25) -> bytes:
    df = df.head(max_rows).copy()

    orange = (255, 140, 0)
    white = (255, 255, 255)
    black = (0, 0, 0)

    title_h = 70
    header_h = 40
    row_h = 44

    cols = ["ORDEM", "DOCA", "PLACA", "YMS IN", "YMS OUT", "PACOTES", "STATUS"]
    col_w = {
        "ORDEM": 90,
        "DOCA": 90,
        "PLACA": 180,
        "YMS IN": 120,
        "YMS OUT": 120,
        "PACOTES": 130,
        "STATUS": 250,
    }

    width = sum(col_w[c] for c in cols)
    height = title_h + header_h + row_h * max(1, len(df)) + 20

    img = Image.new("RGB", (width, height), white)
    draw = ImageDraw.Draw(img)

    fonts = get_fonts()
    font_title = fonts["title"]
    font_header = fonts["header"]
    font_cell = fonts["cell"]
    font_bold = fonts["bold"]

    # Title
    draw.rectangle([0, 0, width, title_h], fill=orange)
    title = "MONITORAMENTO LH"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (title_h - th) / 2), title, fill=white, font=font_title)

    # Header
    y0 = title_h
    draw.rectangle([0, y0, width, y0 + header_h], fill=orange)

    x = 0
    for c in cols:
        draw.line([x, y0, x, y0 + header_h], fill=white, width=2)
        bbox = draw.textbbox((0, 0), c, font=font_header)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x + (col_w[c] - lw) / 2, y0 + (header_h - lh) / 2), c, fill=white, font=font_header)
        x += col_w[c]

    # Rows
    y = y0 + header_h
    for i in range(len(df)):
        row = df.iloc[i]
        draw.rectangle([0, y, width, y + row_h], fill=white)

        x = 0
        for c in cols:
            val = "" if pd.isna(row[c]) else str(row[c])
            draw.line([x, y, x, y + row_h], fill=(230, 230, 230), width=2)

            if c == "STATUS":
                sty = status_style(val)
                pill_pad = 8
                pill_h = 30
                pill_w = col_w[c] - 2 * pill_pad
                pill_x0 = x + pill_pad
                pill_y0 = y + (row_h - pill_h) // 2
                pill_x1 = pill_x0 + pill_w
                pill_y1 = pill_y0 + pill_h

                try:
                    draw.rounded_rectangle([pill_x0, pill_y0, pill_x1, pill_y1], radius=14, fill=sty["fill"])
                except Exception:
                    draw.rectangle([pill_x0, pill_y0, pill_x1, pill_y1], fill=sty["fill"])

                bbox = draw.textbbox((0, 0), val, font=font_bold)
                lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(
                    (pill_x0 + (pill_w - lw) / 2, pill_y0 + (pill_h - lh) / 2 - 1),
                    val,
                    fill=sty["text"],
                    font=font_bold,
                )
                arrow = "▾"
                bbox = draw.textbbox((0, 0), arrow, font=font_bold)
                aw, ah = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(
                    (pill_x1 - aw - 10, pill_y0 + (pill_h - ah) / 2 - 1),
                    arrow,
                    fill=sty["text"],
                    font=font_bold,
                )
            else:
                font_use = font_bold if c in ["ORDEM", "DOCA"] else font_cell
                bbox = draw.textbbox((0, 0), val, font=font_use)
                lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((x + (col_w[c] - lw) / 2, y + (row_h - lh) / 2), val, fill=black, font=font_use)

            x += col_w[c]

        draw.line([0, y + row_h, width, y + row_h], fill=(240, 240, 240), width=2)
        y += row_h

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

# ----------------- UI -----------------
uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])
if not uploaded:
    st.info("Envie um CSV para começar.")
    st.stop()

file_bytes = uploaded.getvalue()

try:
    raw = parse_csv_bytes(file_bytes)
except Exception as e:
    st.error(f"Erro lendo CSV: {e}")
    st.stop()

# Filtro do dia (editáveis)
st.subheader("🧰 Filtro do dia")
c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    x_value = st.text_input('Destino (X) =', value="SPA1")
with c2:
    day_value = st.date_input("Data (HOJE) baseada em Destino ATA", value=date.today())
with c3:
    e_exclude = st.text_input('Motorista (E) <>', value="RODOPENHA")

with st.expander("🔎 Prévia do CSV (5 linhas)", expanded=False):
    st.dataframe(raw.head(5), use_container_width=True)

try:
    filtered = apply_daily_filter(raw, x_value=x_value, day_value=day_value, e_exclude=e_exclude)
except Exception as e:
    st.error(f"Erro no filtro: {e}")
    st.stop()

st.info(f"Linhas após filtro: **{len(filtered)}** (antes: {len(raw)})")

try:
    monitor = build_monitor_df(filtered)
except Exception as e:
    st.error(f"Erro consolidando dados: {e}")
    st.stop()

st.subheader("✍️ Edite DOCA e STATUS")
status_options_text = st.text_area(
    "Opções de STATUS (uma por linha)",
    value="\n".join(DEFAULT_STATUS_OPTIONS),
    height=110
)
status_list = [s.strip() for s in status_options_text.splitlines() if s.strip()]

column_config = {
    "DOCA": st.column_config.TextColumn("DOCA", help="Digite a doca manualmente"),
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

st.divider()

st.download_button(
    "⬇️ Baixar CSV atualizado",
    data=df_to_csv_bytes(edited),
    file_name="monitoramento_lh_atualizado.csv",
    mime="text/csv",
)

st.subheader("🖼️ Imagem para WhatsApp")
max_rows = st.slider("Quantidade de linhas na imagem", min_value=5, max_value=40, value=25, step=1)

if st.button("Gerar imagem PNG"):
    with st.spinner("Gerando imagem..."):
        png_bytes = render_monitor_png(edited, max_rows=max_rows)
    st.image(png_bytes, caption="Imagem gerada (pronta para baixar e enviar no WhatsApp)", use_container_width=True)
    st.download_button(
        "Baixar imagem PNG",
        data=png_bytes,
        file_name="monitoramento_lh.png",
        mime="image/png",
    )
else:
    st.caption("Clique em **Gerar imagem PNG** (isso evita lentidão a cada edição).")
