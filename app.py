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
    # pool_pre_ping evita conexão morta
    return create_engine(DATABASE_URL, pool_pre_ping=True)


engine = get_engine()


def fetch_one(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def fetch_df(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def safe_fetch_one(sql: str, default=None, label: str | None = None):
    """
    Nunca deixa o app quebrar por erro de SQL/tabela ausente.
    """
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
    # banco guarda decimal: 0.20 = 20%
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
    st.title("📊 QPROF - Dashboard")

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
    "📌 Concentração Ced/Sac",
    "🏷️ Risco por Rótulo",
    "🧍 Vencidos",
    "🛰️ Monitore"
])


# =========================================================
# TAB 1 - CONCENTRAÇÃO (DINÂMICA PIVOT EXCEL)
# =========================================================
with tabs[0]:
    st.subheader("📌 Concentração Cedente / Sacado")
    st.caption("Regra: sacado não pode representar 20% ou mais do vlr_aberto total do cedente.")

    df_pivot = safe_fetch_df("""
        SELECT
            status,
            cedente,
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
        if "sacado" in df_pivot.columns:
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

        st.dataframe(df_pivot, use_container_width=True, hide_index=True)

        csv = df_pivot.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "concentracao_pivot.csv", "text/csv")


# =========================================================
# TAB 2 - RISCO POR RÓTULO (DINÂMICA)
# =========================================================
with tabs[1]:
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

        st.dataframe(df_rotulo, use_container_width=True, hide_index=True)

        csv = df_rotulo.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "risco_por_rotulo.csv", "text/csv")


# =========================================================
# TAB 3 - VENCIDOS
# =========================================================
with tabs[2]:
    st.subheader("🧍 Vencidos")
    st.caption("Se estiver 0 linhas, pode ser que o watcher ainda não carregou essa base.")

    df_sacado = safe_fetch_df("""
        SELECT *
        FROM public.sacado_consolidado
        ORDER BY dta_vcto DESC NULLS LAST
        LIMIT 2000
    """)

    # formata automaticamente se existirem as colunas
    for col in ["vlr_face", "vlr_aberto", "vlr_desc", "vlr_ocorrencia"]:
        if col in df_sacado.columns:
            df_sacado[col] = df_sacado[col].map(fmt_money_cell)

    st.dataframe(df_sacado, use_container_width=True)


# =========================================================
# TAB 4 - MONITORE
# =========================================================
with tabs[3]:
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
