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
# TAB 1 - CONCENTRAÇÃO (TOP 10 CEDENTES + TABELAS)
# =========================================================
with tabs[0]:
    st.subheader("📌 Concentração Cedente / Sacado")
    st.caption("Regra: sacado não pode representar 20% ou mais do vlr_aberto total do cedente.")

    # ---- TOP 10 CEDENTES POR RISCO (vlr_aberto) ----
    st.markdown("### Top 10 Cedentes por risco (vlr_aberto)")

    df_top_ced = safe_fetch_df("""
        WITH base AS (
          SELECT
            COALESCE(cedente,'N/I') AS cedente,
            COALESCE(sacado,'N/I') AS sacado,
            COALESCE(vlr_aberto,0)::numeric AS vlr_aberto
          FROM public.cobranca_consolidada
        ),
        por_sacado AS (
          SELECT
            cedente,
            sacado,
            SUM(vlr_aberto) AS vlr_aberto_sacado
          FROM base
          GROUP BY 1,2
        ),
        por_cedente AS (
          SELECT
            cedente,
            SUM(vlr_aberto_sacado) AS vlr_aberto_cedente
          FROM por_sacado
          GROUP BY 1
        ),
        joined AS (
          SELECT
            s.cedente,
            s.sacado,
            s.vlr_aberto_sacado,
            c.vlr_aberto_cedente,
            CASE
              WHEN c.vlr_aberto_cedente = 0 THEN 0
              ELSE s.vlr_aberto_sacado / c.vlr_aberto_cedente
            END AS pct_no_cedente
          FROM por_sacado s
          JOIN por_cedente c USING (cedente)
        ),
        resumo AS (
          SELECT
            cedente,
            MAX(vlr_aberto_cedente) AS risco_total_cedente,
            MAX(pct_no_cedente) AS maior_pct_sacado,
            COUNT(*) AS qtd_sacados
          FROM joined
          GROUP BY 1
        )
        SELECT *
        FROM resumo
        ORDER BY risco_total_cedente DESC
        LIMIT 10
    """)

    if df_top_ced.empty:
        st.info("Sem dados na cobrança consolidada.")
    else:
        def status_emoji(pct):
            try:
                return "🔴" if float(pct) >= 0.20 else "🟢"
            except Exception:
                return "⚪"

        df_top_ced["status"] = df_top_ced["maior_pct_sacado"].apply(status_emoji)
        df_top_ced["risco_total_cedente"] = df_top_ced["risco_total_cedente"].map(fmt_money_cell)
        df_top_ced["maior_pct_sacado"] = df_top_ced["maior_pct_sacado"].map(fmt_pct_cell)

        df_top_ced_show = df_top_ced[["status", "cedente", "risco_total_cedente", "qtd_sacados", "maior_pct_sacado"]]
        st.dataframe(df_top_ced_show, use_container_width=True, hide_index=True)

    st.divider()

    # ---- TABELAS POR CEDENTE ----
    st.markdown("### Detalhamento por Cedente (Sacados)")

    if df_top_ced.empty:
        st.stop()

    cedente_escolhido = st.selectbox(
        "Selecione o cedente:",
        df_top_ced["cedente"].tolist()
    )

    df_det = safe_fetch_df("""
        SELECT
            sacado,
            vlr_aberto_sacado,
            vlr_aberto_cedente,
            pct_no_cedente,
            flag_ultrapassa_20
        FROM public.vw_concentracao_cedente_sacado
        WHERE cedente = :cedente
        ORDER BY pct_no_cedente DESC
        LIMIT 500
    """, params={"cedente": cedente_escolhido})

    if df_det.empty:
        st.info("Sem sacados para este cedente.")
    else:
        df_det["status"] = df_det["flag_ultrapassa_20"].apply(lambda x: "🔴" if x else "🟢")
        df_det["vlr_aberto_sacado"] = df_det["vlr_aberto_sacado"].map(fmt_money_cell)
        df_det["vlr_aberto_cedente"] = df_det["vlr_aberto_cedente"].map(fmt_money_cell)
        df_det["pct_no_cedente"] = df_det["pct_no_cedente"].map(fmt_pct_cell)

        df_det_show = df_det[["status", "sacado", "vlr_aberto_sacado", "pct_no_cedente"]]
        st.dataframe(df_det_show, use_container_width=True, hide_index=True)

        csv = df_det_show.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV (Cedente)", csv, "concentracao_cedente.csv", "text/csv")


# =========================================================
# TAB 2 - RISCO POR RÓTULO (DINÂMICA)
# =========================================================
with tabs[1]:
    st.subheader("🏷️ Risco por Rótulo (Dinâmica)")

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
st.caption("Ned Capital • Dashboard • Streamlit")
