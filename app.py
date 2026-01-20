import os
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text


# =========================================================
# CONFIG STREAMLIT
# =========================================================
st.set_page_config(
    page_title="QPROF - Dashboard",
    page_icon="📊",
    layout="wide"
)

# =========================================================
# DB (Neon / Streamlit Cloud)
# =========================================================
def get_secret(key: str, default: str | None = None):
    """
    Prioriza st.secrets (Streamlit Cloud), se não existir usa env var.
    """
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
        # Timestamp / datetime
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
# KPIs (via VIEW: vw_kpis)
# =========================================================
df_kpis = safe_fetch_df("SELECT * FROM public.vw_kpis;")

pl = 0
vop_geral = 0
vop_mensal = 0
vop_diario = 0

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
    "📌 Visão Geral",
    "🏷️ Risco por Rótulo",
    "📌 Concentração Ced/Sac",
    "🧍 Vencidos",
    "📈 VOPs",
    "🛰️ Monitore",
    "📎 Limites"
])


# =========================================================
# TAB 1 - VISÃO GERAL
# =========================================================
with tabs[0]:
    st.subheader("📌 Visão Geral")

    colA, colB = st.columns([1, 1])

    # ---- A: Vencidos x Carteira ----
    with colA:
        st.markdown("### Resumo (Vencidos x Carteira)")

        df_resumo = safe_fetch_df("""
            SELECT 'Vencidos' AS item, COALESCE(SUM(vlr_aberto), 0) AS valor
            FROM public.sacado_consolidado
            UNION ALL
            SELECT 'Carteira' AS item, COALESCE(SUM(vlr_aberto), 0) AS valor
            FROM public.cobranca_consolidada
        """)

        if not df_resumo.empty:
            df_resumo["valor"] = df_resumo["valor"].map(fmt_money_cell)

        st.dataframe(df_resumo, use_container_width=True, hide_index=True)

    # ---- B: Top cedentes VOP (sem filtro 4 e 6 no app; o view já cuida dos KPIs, aqui é tabela livre) ----
    with colB:
        st.markdown("### VOP por Cedente (Top 20)")

        # Aqui vamos aplicar o filtro robusto igual nas views
        df_vop_ced = safe_fetch_df("""
            SELECT
                COALESCE(cedente, 'N/I') AS cedente,
                COUNT(*) AS qtd,
                COALESCE(SUM(vlr_aprovado), 0) AS vlr_aprovado
            FROM public.vops
            WHERE NULLIF(TRIM(situacao_operacao), '') IS NOT NULL
              AND LOWER(TRIM(situacao_operacao)) <> 'nan'
              AND (TRIM(situacao_operacao))::numeric IN (4, 6)
            GROUP BY 1
            ORDER BY vlr_aprovado DESC
            LIMIT 20
        """)

        if not df_vop_ced.empty:
            df_vop_ced["vlr_aprovado"] = df_vop_ced["vlr_aprovado"].map(fmt_money_cell)

        st.dataframe(df_vop_ced, use_container_width=True, hide_index=True)


# =========================================================
# TAB 2 - RISCO POR RÓTULO (TABELA DINÂMICA)
# =========================================================
with tabs[1]:
    st.subheader("🏷️ Risco por Rótulo")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        filtro_rotulo = st.text_input("Filtrar rótulo", "")
    with col2:
        top_n = st.number_input("Top N", min_value=10, max_value=500, value=50, step=10)
    with col3:
        incluir_ni = st.checkbox("Incluir N/I", value=True)

    sql_rotulo = """
        SELECT
            rotulo,
            qtd_titulos,
            risco_vlr_aberto,
            pct_total
        FROM public.vw_risco_por_rotulo
        WHERE 1=1
    """
    params = {}

    if filtro_rotulo.strip():
        sql_rotulo += " AND rotulo ILIKE :rotulo"
        params["rotulo"] = f"%{filtro_rotulo.strip()}%"

    if not incluir_ni:
        sql_rotulo += " AND rotulo <> 'N/I'"

    sql_rotulo += " ORDER BY risco_vlr_aberto DESC"
    sql_rotulo += " LIMIT :top_n"
    params["top_n"] = int(top_n)

    df_rotulo = safe_fetch_df(sql_rotulo, params=params)

    if df_rotulo.empty:
        st.info("Sem dados para exibir.")
    else:
        df_rotulo["risco_vlr_aberto"] = df_rotulo["risco_vlr_aberto"].map(fmt_money_cell)
        df_rotulo["pct_total"] = df_rotulo["pct_total"].map(fmt_pct_cell)

        st.dataframe(df_rotulo, use_container_width=True, hide_index=True)

        csv = df_rotulo.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "risco_por_rotulo.csv", "text/csv")


# =========================================================
# TAB 3 - CONCENTRAÇÃO CEDENTE / SACADO
# =========================================================
with tabs[2]:
    st.subheader("📌 Concentração Cedente / Sacado")
    st.caption("Regra: sacado não pode representar 20% ou mais do vlr_aberto total do cedente.")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        filtro_cedente = st.text_input("Filtrar Cedente (Concentração)", "")
    with col2:
        somente_alertas = st.checkbox("Somente alertas (>=20%)", value=False)
    with col3:
        top_n = st.number_input("Top N (Concentração)", min_value=50, max_value=2000, value=500, step=50)

    sql_conc = """
        SELECT
            cedente,
            sacado,
            vlr_aberto_sacado,
            vlr_aberto_cedente,
            pct_no_cedente,
            flag_ultrapassa_20
        FROM public.vw_concentracao_cedente_sacado
        WHERE 1=1
    """
    params = {}

    if filtro_cedente.strip():
        sql_conc += " AND cedente ILIKE :cedente"
        params["cedente"] = f"%{filtro_cedente.strip()}%"

    if somente_alertas:
        sql_conc += " AND flag_ultrapassa_20 = true"

    sql_conc += " ORDER BY flag_ultrapassa_20 DESC, pct_no_cedente DESC, vlr_aberto_sacado DESC"
    sql_conc += " LIMIT :top_n"
    params["top_n"] = int(top_n)

    df_conc = safe_fetch_df(sql_conc, params=params)

    if df_conc.empty:
        st.info("Sem dados para exibir.")
    else:
        df_conc["vlr_aberto_sacado"] = df_conc["vlr_aberto_sacado"].map(fmt_money_cell)
        df_conc["vlr_aberto_cedente"] = df_conc["vlr_aberto_cedente"].map(fmt_money_cell)
        df_conc["pct_no_cedente"] = df_conc["pct_no_cedente"].map(fmt_pct_cell)

        st.dataframe(df_conc, use_container_width=True, hide_index=True)

        csv = df_conc.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", csv, "concentracao_cedente_sacado.csv", "text/csv")


# =========================================================
# TAB 4 - VENCIDOS
# =========================================================
with tabs[3]:
    st.subheader("🧍 Vencidos")
    st.caption("Se estiver 0 linhas, pode ser que o watcher ainda não carregou essa base.")

    df_sacado = safe_fetch_df("""
        SELECT *
        FROM public.sacado_consolidado
        ORDER BY ingested_at DESC NULLS LAST
        LIMIT 2000
    """)

    # formatação automática se essas colunas existirem
    for col in ["vlr_face", "vlr_aberto", "vlr_desc", "vlr_ocorrencia"]:
        if col in df_sacado.columns:
            df_sacado[col] = df_sacado[col].map(fmt_money_cell)

    st.dataframe(df_sacado, use_container_width=True)


# =========================================================
# TAB 5 - VOPS
# =========================================================
with tabs[4]:
    st.subheader("📈 VOPs")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        filtro_cedente_vop = st.text_input("Filtrar Cedente (VOP)", "")
    with col2:
        filtro_cpf_cnpj = st.text_input("Filtrar CPF/CNPJ", "")
    with col3:
        incluir_somente_46 = st.checkbox("Somente Sit.Ope 4 e 6", value=True)

    sql_vops = """
        SELECT *
        FROM public.vops
        WHERE 1=1
    """
    params = {}

    # filtro robusto 4/6 (aceita 6.0 etc)
    if incluir_somente_46:
        sql_vops += """
            AND NULLIF(TRIM(situacao_operacao), '') IS NOT NULL
            AND LOWER(TRIM(situacao_operacao)) <> 'nan'
            AND (TRIM(situacao_operacao))::numeric IN (4, 6)
        """

    if filtro_cedente_vop.strip():
        sql_vops += " AND cedente ILIKE :cedente"
        params["cedente"] = f"%{filtro_cedente_vop.strip()}%"

    if filtro_cpf_cnpj.strip():
        sql_vops += " AND cpf_cnpj ILIKE :cpf"
        params["cpf"] = f"%{filtro_cpf_cnpj.strip()}%"

    sql_vops += " ORDER BY dta_neg DESC NULLS LAST"
    sql_vops += " LIMIT 2000"

    df_vops = safe_fetch_df(sql_vops, params=params)

    for col in ["rem_gestora", "rem_qcert", "vlr_face", "vlr_aprovado", "vlr_liquido"]:
        if col in df_vops.columns:
            df_vops[col] = df_vops[col].map(fmt_money_cell)

    st.dataframe(df_vops, use_container_width=True)


# =========================================================
# TAB 6 - MONITORE
# =========================================================
with tabs[5]:
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
# TAB 7 - LIMITES
# =========================================================
with tabs[6]:
    st.subheader("📎 Limites")

    df_lim = safe_fetch_df("""
        SELECT *
        FROM public.limites
        ORDER BY ingested_at DESC NULLS LAST
        LIMIT 2000
    """)

    for col in ["limite", "limite_total", "limite_disponivel", "limite_utilizado"]:
        if col in df_lim.columns:
            df_lim[col] = df_lim[col].map(fmt_money_cell)

    st.dataframe(df_lim, use_container_width=True)


# =========================================================
# FOOTER
# =========================================================
st.caption("QPROF • Dashboard • Streamlit")
