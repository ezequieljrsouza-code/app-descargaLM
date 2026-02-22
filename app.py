import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
from typing import Optional, List
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Monitoramento LH", layout="wide")

st.title("📦 Monitoramento LH")
st.caption(
    "CSV (filtro SPA1/HOJE/!=RODOPENHA) ou Imagem (OCR opcional) → consolida por PLACA → "
    "edita DOCA/STATUS → baixa CSV e PNG (WhatsApp)."
)

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Concluída",
    "Descarga finalizada",
    "Cancelado",
]

# =========================
# Utils
# =========================
def to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def fmt_hms_from_dt(dt_series: pd.Series) -> pd.Series:
    s = dt_series.dt.strftime("%H:%M:%S")
    return s.fillna("")

def fmt_hms_from_text(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.where(~s.str.match(r"^\d{2}:\d{2}$"), s + ":00")
    return s

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

def build_monitor_from_base(df_base: pd.DataFrame) -> pd.DataFrame:
    out = df_base.copy()

    def parse_time_str(x: str):
        try:
            if not x:
                return None
            parts = x.split(":")
            if len(parts) == 2:
                h, m = int(parts[0]), int(parts[1])
                s = 0
            else:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 3600 + m * 60 + s
        except Exception:
            return None

    sort_vals = []
    for _, r in out.iterrows():
        a = parse_time_str(str(r.get("YMS IN", "")).strip())
        b = parse_time_str(str(r.get("YMS OUT", "")).strip())
        sort_vals.append(a if a is not None else (b if b is not None else 10**12))

    out["__SORT"] = sort_vals
    out = out.sort_values("__SORT", ascending=True).reset_index(drop=True)
    out.drop(columns=["__SORT"], inplace=True)

    out.insert(0, "ORDEM", [f"{i}ª" for i in range(1, len(out) + 1)])
    out.insert(1, "DOCA", "")
    out["STATUS"] = "Aguardando Doca"
    out = out[["ORDEM", "DOCA", "PLACA", "YMS IN", "YMS OUT", "PACOTES", "STATUS"]]
    return out


# =========================
# CSV mode (com filtro fixo)
# =========================
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

def apply_daily_filter_csv(raw: pd.DataFrame, x_value: str, day_value: date, e_exclude: str) -> pd.DataFrame:
    # Fixos conforme você informou
    col_x = "Destino"
    col_y = "Destino ATA"
    col_e = "Motorista"

    missing = [c for c in [col_x, col_y, col_e] if c not in raw.columns]
    if missing:
        raise ValueError(f"CSV não tem colunas para o filtro: {', '.join(missing)}")

    x_ok = raw[col_x].astype(str).str.strip().eq(str(x_value).strip())
    y_dt = to_dt(raw[col_y])
    y_ok = y_dt.dt.date.eq(day_value)
    e_ok = raw[col_e].astype(str).str.strip().ne(str(e_exclude).strip())

    return raw[x_ok & y_ok & e_ok].copy()

def build_base_from_csv(filtered: pd.DataFrame) -> pd.DataFrame:
    col_placa = "Veículo de carga 1"
    col_ata = "Destino ATA"
    col_atd = "Destino ATD"
    col_pac = "Pacotes"

    missing = [c for c in [col_placa, col_ata, col_atd, col_pac] if c not in filtered.columns]
    if missing:
        raise ValueError(f"CSV filtrado não tem colunas necessárias: {', '.join(missing)}")

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

    base = pd.DataFrame({
        "PLACA": grouped["PLACA"].astype(str).str.strip().str.upper(),
        "PACOTES": grouped["PACOTES"].astype(int),
        "YMS IN": fmt_hms_from_dt(grouped["ATA"]),
        "YMS OUT": fmt_hms_from_dt(grouped["ATD"]),
    })
    return base


# =========================
# IMAGE mode (OCR opcional; não derruba o app)
# =========================
def ocr_available() -> bool:
    try:
        import pytesseract  # noqa
        return True
    except Exception:
        return False

def ocr_extract_table_stub(image: Image.Image) -> pd.DataFrame:
    """
    Stub: só roda se pytesseract estiver disponível.
    Se você hospedar em HuggingFace Docker com tesseract instalado,
    você pode trocar esse stub pela versão OCR completa.
    """
    import pytesseract  # type: ignore
    # Se chegou aqui, pytesseract está importável, mas ainda pode faltar o binário "tesseract".
    # Vamos testar uma chamada simples.
    try:
        _ = pytesseract.image_to_string(image)
    except Exception as e:
        raise RuntimeError(
            "OCR não está pronto neste servidor (provavelmente falta o binário do Tesseract). "
            "Use Hugging Face Spaces (Docker) para habilitar."
        ) from e

    # Como fallback mínimo, retorna vazio e orienta.
    raise RuntimeError(
        "OCR importou, mas este app está com stub. "
        "Se você quiser, eu te mando a versão OCR completa para Hugging Face (Docker) e ela preenche PLACA/PACOTES/CHEGADA."
    )


# =========================
# PNG rendering (WhatsApp) — sob demanda
# =========================
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

    return {"title": load_font(30), "header": load_font(16), "cell": load_font(16), "bold": load_font(18)}

def status_style(status: str):
    s = (status or "").strip().lower()
    if "descarga inici" in s:
        return {"fill": (255, 235, 59), "text": (0, 0, 0)}
    if "conclu" in s:
        return {"fill": (22, 120, 74), "text": (255, 255, 255)}
    if "aguardando" in s:
        return {"fill": (70, 70, 70), "text": (255, 255, 255)}
    if "não chegou" in s or "nao chegou" in s:
        return {"fill": (255, 165, 0), "text": (255, 255, 255)}
    return {"fill": (200, 200, 200), "text": (0, 0, 0)}

def render_monitor_png(df: pd.DataFrame, max_rows: int = 25) -> bytes:
    df = df.head(max_rows).copy()

    orange = (255, 140, 0)
    white = (255, 255, 255)
    black = (0, 0, 0)

    title_h = 70
    header_h = 40
    row_h = 44

    cols = ["ORDEM", "DOCA", "PLACA", "YMS IN", "YMS OUT", "PACOTES", "STATUS"]
    col_w = {"ORDEM": 90, "DOCA": 90, "PLACA": 180, "YMS IN": 120, "YMS OUT": 120, "PACOTES": 130, "STATUS": 250}

    width = sum(col_w[c] for c in cols)
    height = title_h + header_h + row_h * max(1, len(df)) + 20

    img = Image.new("RGB", (width, height), white)
    draw = ImageDraw.Draw(img)

    fonts = get_fonts()
    font_title, font_header, font_cell, font_bold = fonts["title"], fonts["header"], fonts["cell"], fonts["bold"]

    draw.rectangle([0, 0, width, title_h], fill=orange)
    title = "MONITORAMENTO LH"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (title_h - th) / 2), title, fill=white, font=font_title)

    y0 = title_h
    draw.rectangle([0, y0, width, y0 + header_h], fill=orange)

    x = 0
    for c in cols:
        draw.line([x, y0, x, y0 + header_h], fill=white, width=2)
        bbox = draw.textbbox((0, 0), c, font=font_header)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x + (col_w[c] - lw) / 2, y0 + (header_h - lh) / 2), c, fill=white, font=font_header)
        x += col_w[c]

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
                pill_pad, pill_h = 8, 30
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
                draw.text((pill_x0 + (pill_w - lw) / 2, pill_y0 + (pill_h - lh) / 2 - 1), val, fill=sty["text"], font=font_bold)

                arrow = "▾"
                bbox = draw.textbbox((0, 0), arrow, font=font_bold)
                aw, ah = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((pill_x1 - aw - 10, pill_y0 + (pill_h - ah) / 2 - 1), arrow, fill=sty["text"], font=font_bold)
            else:
                font_use = font_bold if c in ["ORDEM", "DOCA"] else font_cell
                bbox = draw.textbbox((0, 0), val, font=font_use)
                lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((x + (col_w[c] - lw) / 2, y + (row_h - lh) / 2), val, fill=black, font=font_use)

            x += col_w[c]

        y += row_h

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# =========================
# UI
# =========================
mode = st.radio("Escolha a fonte dos dados:", ["📄 CSV (com filtro do dia)", "🖼️ Imagem (OCR)"], horizontal=True)

base_df: Optional[pd.DataFrame] = None

if mode.startswith("📄"):
    uploaded = st.file_uploader("📤 Envie o CSV", type=["csv"])
    if not uploaded:
        st.stop()

    raw = parse_csv_bytes(uploaded.getvalue())

    st.subheader("🧰 Filtro do dia (igual Excel FILTER)")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        x_value = st.text_input('Destino (X) =', value="SPA1")
    with c2:
        day_value = st.date_input("Data (HOJE) baseada em Destino ATA", value=date.today())
    with c3:
        e_exclude = st.text_input('Motorista (E) <>', value="RODOPENHA")

    filtered = apply_daily_filter_csv(raw, x_value=x_value, day_value=day_value, e_exclude=e_exclude)
    st.info(f"Linhas após filtro: **{len(filtered)}**")

    base_df = build_base_from_csv(filtered)

else:
    uploaded_img = st.file_uploader("📤 Envie a IMAGEM (print)", type=["png", "jpg", "jpeg", "webp"])
    if not uploaded_img:
        st.stop()

    image = Image.open(uploaded_img)
    st.image(image, caption="Imagem enviada", use_container_width=True)

    if not ocr_available():
        st.error(
            "OCR não está disponível neste servidor (Streamlit Cloud geralmente não tem Tesseract). "
            "Para OCR grátis, use Hugging Face Spaces (Docker)."
        )
        st.stop()

    if st.button("Extrair dados da imagem (OCR)"):
        try:
            base_df = ocr_extract_table_stub(image)
        except Exception as e:
            st.error(str(e))
            st.stop()

if base_df is None or base_df.empty:
    st.stop()

monitor = build_monitor_from_base(base_df)

st.subheader("✍️ Edite DOCA e STATUS")
status_options_text = st.text_area("Opções de STATUS (uma por linha)", value="\n".join(DEFAULT_STATUS_OPTIONS), height=110)
status_list = [s.strip() for s in status_options_text.splitlines() if s.strip()]

edited = st.data_editor(
    monitor,
    use_container_width=True,
    hide_index=True,
    column_config={
        "DOCA": st.column_config.TextColumn("DOCA"),
        "STATUS": st.column_config.SelectboxColumn("STATUS", options=status_list, required=False),
    },
    num_rows="fixed",
    key="editor",
)

st.download_button("⬇️ Baixar CSV atualizado", data=df_to_csv_bytes(edited), file_name="monitoramento_lh_atualizado.csv", mime="text/csv")

st.subheader("🖼️ Imagem para WhatsApp (sob demanda)")
max_rows = st.slider("Quantidade de linhas na imagem", min_value=5, max_value=40, value=25, step=1)

if st.button("Gerar imagem PNG"):
    png_bytes = render_monitor_png(edited, max_rows=max_rows)
    st.image(png_bytes, caption="Imagem gerada", use_container_width=True)
    st.download_button("Baixar imagem PNG", data=png_bytes, file_name="monitoramento_lh.png", mime="image/png")
