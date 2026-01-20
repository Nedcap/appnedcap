import os
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text


# =========================================================
# CONFIG STREAMLIT
# =========================================================
st.set_page_config(
    page_title="Ned Capital - Dashboard",
    page_icon="📊",
    layout="wide"
)

# =========================================================
# DB (Neon / Streamlit Cloud)
# =========================================================
def get_secret(key: str, default: str | None = None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


DB_HOST = get_secret("DB_HOST", "qprof_postgres")
DB_PORT = get_secret("DB_PORT", "5432")
DB_NAME = get_secret("DB_NAME", "qprof")
DB_USER = get_secret("DB_USER", "qprof_user")
DB_PASS = get_secret("DB_PASS", "qprof_pass")

# Neon requer SSL
DB_SSLMODE = get_secret("DB_SSLMODE", "require")

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?sslmode={DB_SSLMODE}"
)


@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


engine = get_engine()


def fetch_one(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def fetch_df(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def safe_fetch_one(sql: str, default=None, label: str | None = None):
    try:
        return fetch_one(sql)
    except Exception as e:
        if label:
            st.warning(f"⚠️ KPI indisponível: {label}. Motivo: {str(e)}")
        return default


def safe_fetch_df(sql: str, params: dict | None = None):
    try:
        return fetch_df(sql, params=params)
    except Exception as e:
        st.warning(f"⚠️ Consulta falhou: {str(e)}")
        return pd.DataFrame()


# =========================================================
# FORMATTERS
# =========================================================
def fmt_money(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def fmt_money_cell(x):
    if pd.isna(x):
        return ""
    try:
        return fmt_money(x)
    except Exception:
        return ""


def fmt_pct_cell(x):
    if pd.isna(x):
        return ""
    try:
        return f"{float(x) * 100:.2f}%".replace(".", ",")
    except Exception:
        return ""


def fmt_dt(dt):
    try:
        if dt is None or pd.isna(dt):
            return "N/D"
        return pd.to_datetime(dt).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(dt)


# =========================================================
# TOP BAR
# =========================================================
col_left, col_right = st.columns([4, 1])

with col_left:
    st.title("📊 Ned Capital - Dashboard")

with col_right:
    if st.button("🔄 Atualizar agora", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

st.divider()


# =========================================================
# KPIs (via vw_kpis + vw_last_update)
# =========================================================
df_kpis = safe_fetch_df("SELECT * FROM public.vw_kpis;")

pl = vop_geral = vop_mensal = vop_diario = 0
if not df_kpis.empty:
    pl = df_kpis.loc[0, "pl_securitizadora"]
    vop_geral = df_kpis.loc[0, "vop_geral"]
    vop_mensal = df_kpis.loc[0, "vop_mensal"]
    vop_diario = df_kpis.loc[0, "vop_diario"]

last_update = safe_fetch_one("SELECT last_update FROM public.vw_last_update;", default=None)


# =========================================================
# KPI CARDS
# =========================================================
k1, k2, k3, k4, k5 = st.columns([1.3, 1.3, 1.3, 1.3, 1.3])
with k1:
    st.metric("PL Securitizadora", fmt_money(pl))
with k2:
    st.metric("VOP Geral", fmt_money(vop_geral))
with k3:
    st.metric("VOP Mensal", fmt_money(vop_mensal))
with k4:
    st.metric("VOP Diário", fmt_money(vop_diario))
with k5:
    st.metric("Última atualização", fmt_dt(last_update))

st.divider()


# =========================================================
# ABAS
# =========================================================
tabs = st.tabs([
    "🏆 Top 10 Cedentes",
    "📌 Concentração Ced/Sac",
    "🏷️ Risco por Rótulo",
    "🧍 Vencidos",
    "🛰️ Monitore"
])


# =========================================================
# TAB 1 - TOP 10 CEDENTES (ranking)
# =========================================================
with tabs[0]:
    st.subheader("🏆 Top 10 Cedentes por risco (vlr_aberto)")

    df_top10 = safe_fetch_df("""
        SELECT
            cedente,
            risco_total_cedente
        FROM public.vw_top10_cedentes_risco
        ORDER BY risco_total_cedente DESC
    """)

    if df_top10.empty:
        st.info("Sem dados para exibir.")
    else:
        df_top10["risco_total_cedente"] = df_top10["risco_total_cedente"].map(fmt_money_cell)

        df_top10 = df_top10.rename(columns={
            "cedente": "Cedente",
            "risco_total_cedente": "Risco (vlr_aberto)"
        })

        st.dataframe(
            df_top10,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Cedente": st.column_config.TextColumn("Cedente", width="large"),
                "Risco (vlr_aberto)": st.column_config.TextColumn("Risco (vlr_aberto)", width="medium"),
            }
        )

        csv = df_top10.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "top10_cedentes.csv", "text/csv")


# =========================================================
# TAB 2 - CONCENTRAÇÃO (DINÂMICA COMPLETA - SEM LIMITE)
# =========================================================
with tabs[1]:
    st.subheader("📌 Concentração Cedente / Sacado")
    st.caption("Regra: sacado não pode representar 20% ou mais do vlr_aberto total do cedente.")

    df_pivot = safe_fetch_df("""
        SELECT
            cedente,
            status,
            sacado,
            valor,
            pct
        FROM public.vw_concentracao_pivot
    """)

    if df_pivot.empty:
        st.info("Sem dados para exibir.")
    else:
        df_pivot["valor"] = df_pivot["valor"].map(fmt_money_cell)
        df_pivot["pct"] = df_pivot["pct"].map(fmt_pct_cell)

        # destaca Total
        df_pivot["sacado"] = df_pivot["sacado"].apply(
            lambda x: "🧾 Total" if str(x).strip().lower() == "total" else x
        )

        # estilo Excel: repetir cedente só na primeira linha do bloco
        last = None
        ced = []
        for c in df_pivot["cedente"]:
            if c == last:
                ced.append("")
            else:
                ced.append(c)
                last = c
        df_pivot["cedente"] = ced

        df_show = df_pivot.rename(columns={
            "cedente": "Cedente",
            "status": "⚑",
            "sacado": "Sacado",
            "valor": "Valor",
            "pct": "%"
        })

        st.dataframe(
            df_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Cedente": st.column_config.TextColumn("Cedente", width="medium"),
                "⚑": st.column_config.TextColumn("⚑", width="small"),
                "Sacado": st.column_config.TextColumn("Sacado", width="large"),
                "Valor": st.column_config.TextColumn("Valor", width="medium"),
                "%": st.column_config.TextColumn("%", width="small"),
            }
        )

        csv = df_show.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "concentracao_pivot.csv", "text/csv")


# =========================================================
# TAB 3 - RISCO POR RÓTULO (DINÂMICA)
# =========================================================
with tabs[2]:
    st.subheader("🏷️ Risco por Rótulo")
    st.caption("Tabela dinâmica: Rótulo x Valor x %")

    df_rotulo = safe_fetch_df("""
        SELECT
            rotulo,
            risco_vlr_aberto,
            pct_total
        FROM public.vw_risco_por_rotulo
        ORDER BY risco_vlr_aberto DESC
    """)

    if df_rotulo.empty:
        st.info("Sem dados para exibir.")
    else:
        df_rotulo["risco_vlr_aberto"] = df_rotulo["risco_vlr_aberto"].map(fmt_money_cell)
        df_rotulo["pct_total"] = df_rotulo["pct_total"].map(fmt_pct_cell)

        df_rot_show = df_rotulo.rename(columns={
            "rotulo": "Rótulo",
            "risco_vlr_aberto": "Valor",
            "pct_total": "%"
        })

        st.dataframe(
            df_rot_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rótulo": st.column_config.TextColumn("Rótulo", width="large"),
                "Valor": st.column_config.TextColumn("Valor", width="medium"),
                "%": st.column_config.TextColumn("%", width="small"),
            }
        )

        csv = df_rot_show.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "risco_por_rotulo.csv", "text/csv")


# =========================================================
# TAB 4 - VENCIDOS
# =========================================================
with tabs[3]:
    st.subheader("🧍 Vencidos")
    st.caption("Se estiver 0 linhas, pode ser que o watcher ainda não carregou essa base.")

    df_sacado = safe_fetch_df("""
        SELECT *
        FROM public.sacado_consolidado
        ORDER BY dta_vcto DESC NULLS LAST
        LIMIT 2000
    """)

    for col in ["vlr_face", "vlr_aberto", "vlr_desc", "vlr_ocorrencia"]:
        if col in df_sacado.columns:
            df_sacado[col] = df_sacado[col].map(fmt_money_cell)

    st.dataframe(df_sacado, use_container_width=True)


# =========================================================
# TAB 5 - MONITORE
# =========================================================
with tabs[4]:
    st.subheader("🛰️ Monitore")

    df_mon = safe_fetch_df("""
        SELECT *
        FROM public.monitore_diario
        ORDER BY data_ref DESC NULLS LAST, ingested_at DESC NULLS LAST
        LIMIT 2000
    """)

    if not df_mon.empty:
        for col in ["saldo_anterior", "saldo_atual", "evolucao"]:
            if col in df_mon.columns:
                df_mon[col] = df_mon[col].map(fmt_money_cell)
        if "variacao" in df_mon.columns:
            df_mon["variacao"] = df_mon["variacao"].map(fmt_pct_cell)

    st.dataframe(df_mon, use_container_width=True)


# =========================================================
# FOOTER
# =========================================================
st.caption("NED CAPITAL • Dashboard • Streamlit")
