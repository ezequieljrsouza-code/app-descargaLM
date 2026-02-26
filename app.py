@st.cache_data(show_spinner=False)
def process_csv(file_bytes, today):

    cols = [
        "Destino",
        "Destino ATA",
        "Destino ATD",
        "Motorista",
        "Pacotes",
        "Veículo de carga 1"
    ]

    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(
                BytesIO(file_bytes),
                sep=sep,
                usecols=cols,
                dtype=str
            )
            if len(df.columns) > 1:
                break
        except:
            continue

    # Converter só o necessário
    df["Destino ATA"] = pd.to_datetime(df["Destino ATA"], errors="coerce", dayfirst=True)
    df["Destino ATD"] = pd.to_datetime(df["Destino ATD"], errors="coerce", dayfirst=True)
    df["Pacotes"] = pd.to_numeric(df["Pacotes"], errors="coerce").fillna(0).astype(int)

    # Filtro
    df = df[
        (df["Destino"].str.strip() == "SPA1") &
        (df["Destino ATA"].dt.date == today) &
        (df["Motorista"].str.strip() != "RODOPENHA")
    ].copy()

    grouped = (
        df.groupby("Veículo de carga 1")
          .agg(
              ATA=("Destino ATA", "min"),
              ATD=("Destino ATD", "max"),
              PACOTES=("Pacotes", "sum"),
          )
          .reset_index()
          .rename(columns={"Veículo de carga 1": "PLACA"})
    )

    grouped["SORT"] = grouped["ATA"].fillna(grouped["ATD"])
    grouped = grouped.sort_values("SORT").reset_index(drop=True)

    grouped["ORDEM"] = [f"{i}ª" for i in range(1, len(grouped)+1)]
    grouped["YMS IN"] = grouped["ATA"].dt.strftime("%H:%M:%S").fillna("")
    grouped["YMS OUT"] = grouped["ATD"].dt.strftime("%H:%M:%S").fillna("")
    grouped["DOCA"] = ""
    grouped["STATUS"] = "Aguardando Doca"

    return grouped[["ORDEM","DOCA","PLACA","YMS IN","YMS OUT","PACOTES","STATUS"]]
