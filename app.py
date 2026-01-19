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
# DB
# =========================================================
DB_HOST = os.getenv("DB_HOST", "qprof_postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "qprof")
DB_USER = os.getenv("DB_USER", "qprof_user")
DB_PASS = os.getenv("DB_PASS", "qprof_pass")

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


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
    # banco guarda decimal: -0.67 = -67%
    if pd.isna(x):
        return ""
    try:
        return f"{float(x) * 100:.2f}%".replace(".", ",")
    except Exception:
        return ""


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
# KPIs (regras definidas por você)
# =========================================================
pl = safe_fetch_one(
    """
    SELECT COALESCE(SUM(vlr_aberto), 0)
    FROM cobranca_consolidada
    """,
    default=0,
    label="PL Securitizadora"
)

vop_geral = safe_fetch_one(
    """
    SELECT COALESCE(SUM(vlr_aprovado), 0)
    FROM vops
    WHERE situacao_operacao IN ('4','6','04','06')
    """,
    default=0,
    label="VOP Geral"
)

vop_mensal = safe_fetch_one(
    """
    SELECT COALESCE(SUM(vlr_aprovado), 0)
    FROM vops
    WHERE situacao_operacao IN ('4','6','04','06')
      AND date_trunc('month', dta_neg) = date_trunc('month', CURRENT_DATE)
    """,
    default=0,
    label="VOP Mensal"
)

vop_diario = safe_fetch_one(
    """
    SELECT COALESCE(SUM(vlr_aprovado), 0)
    FROM vops
    WHERE situacao_operacao IN ('4','6','04','06')
      AND dta_neg = CURRENT_DATE
    """,
    default=0,
    label="VOP Diário"
)

last_update = safe_fetch_one(
    "SELECT MAX(data_ref) FROM monitore_diario",
    default=None
)

if not last_update:
    last_update = safe_fetch_one(
        "SELECT MAX(data_ref) FROM cobranca_consolidada",
        default=None
    )


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
    st.metric("Última atualização", str(last_update) if last_update else "N/D")

st.divider()


# =========================================================
# ABAS
# =========================================================
tabs = st.tabs([
    "📌 Visão Geral",
    "🧾 Cobrança",
    "🧍 Vencidos",
    "📈 VOPs",
    "🛰️ Monitore"
])


# =========================================================
# TAB 1 - VISÃO GERAL
# =========================================================
with tabs[0]:
    st.subheader("📌 Visão Geral")

    colA, colB = st.columns([1, 1])

    with colA:
        st.markdown("### Cobrança por Situação (Top 20)")
        df_sit = safe_fetch_df("""
            SELECT
                COALESCE(situacao, 'N/I') AS situacao,
                COUNT(*) AS qtd,
                COALESCE(SUM(vlr_aberto), 0) AS vlr_aberto
            FROM cobranca_consolidada
            GROUP BY 1
            ORDER BY vlr_aberto DESC
            LIMIT 20
        """)

        if not df_sit.empty:
            df_sit["vlr_aberto"] = df_sit["vlr_aberto"].map(fmt_money_cell)

        st.dataframe(df_sit, use_container_width=True)

    with colB:
        st.markdown("### VOP por Cedente (Top 20)")
        df_vop_ced = safe_fetch_df("""
            SELECT
                COALESCE(cedente, 'N/I') AS cedente,
                COUNT(*) AS qtd,
                COALESCE(SUM(vlr_aprovado), 0) AS vlr_aprovado
            FROM vops
            WHERE situacao_operacao IN ('4','6','04','06')
            GROUP BY 1
            ORDER BY vlr_aprovado DESC
            LIMIT 20
        """)

        if not df_vop_ced.empty:
            df_vop_ced["vlr_aprovado"] = df_vop_ced["vlr_aprovado"].map(fmt_money_cell)

        st.dataframe(df_vop_ced, use_container_width=True)


# =========================================================
# TAB 2 - COBRANÇA
# =========================================================
with tabs[1]:
    st.subheader("🧾 Cobrança")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        filtro_cedente = st.text_input("Filtrar Cedente", "")
    with col2:
        filtro_sacado = st.text_input("Filtrar Sacado", "")
    with col3:
        filtro_status = st.text_input("Filtrar Status", "")

    sql_cobranca = """
        SELECT
            filial,
            cedente,
            sacado,
            situacao,
            dta_vcto,
            vlr_face,
            vlr_aberto,
            vlr_pago,
            score,
            status,
            grupo_economico,
            cnpj_cpf,
            origem_arquivo,
            data_ref
        FROM cobranca_consolidada
        WHERE 1=1
    """
    params = {}

    if filtro_cedente.strip():
        sql_cobranca += " AND cedente ILIKE :cedente"
        params["cedente"] = f"%{filtro_cedente.strip()}%"

    if filtro_sacado.strip():
        sql_cobranca += " AND sacado ILIKE :sacado"
        params["sacado"] = f"%{filtro_sacado.strip()}%"

    if filtro_status.strip():
        sql_cobranca += " AND status ILIKE :status"
        params["status"] = f"%{filtro_status.strip()}%"

    sql_cobranca += " ORDER BY dta_vcto DESC NULLS LAST LIMIT 2000"

    df_cobranca = safe_fetch_df(sql_cobranca, params=params)

    for col in ["vlr_face", "vlr_aberto", "vlr_pago"]:
        if col in df_cobranca.columns:
            df_cobranca[col] = df_cobranca[col].map(fmt_money_cell)

    st.dataframe(df_cobranca, use_container_width=True)


# =========================================================
# TAB 3 - SACADO
# =========================================================
with tabs[2]:
    st.subheader("🧍 Vencidos")

    st.caption("Se estiver 0 linhas, pode ser que o watcher ainda não carregou essa base.")

    df_sacado = safe_fetch_df("""
        SELECT
            data_geracao,
            filial,
            sacado,
            cod_sacado,
            cpf_cnpj,
            cedente,
            dta_emis,
            dta_vcto,
            vlr_face,
            vlr_aberto,
            vlr_desc,
            ocorrencias,
            vlr_ocorrencia,
            observacoes,
            grupo_economico,
            situ_rec,
            origem_arquivo
        FROM sacado_consolidado
        ORDER BY dta_vcto DESC NULLS LAST
        LIMIT 2000
    """)

    for col in ["vlr_face", "vlr_aberto", "vlr_desc", "vlr_ocorrencia"]:
        if col in df_sacado.columns:
            df_sacado[col] = df_sacado[col].map(fmt_money_cell)

    st.dataframe(df_sacado, use_container_width=True)


# =========================================================
# TAB 4 - VOPS
# =========================================================
with tabs[3]:
    st.subheader("📈 VOPs")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        filtro_cedente_vop = st.text_input("Filtrar Cedente (VOP)", "")
    with col2:
        filtro_cpf_cnpj = st.text_input("Filtrar CPF/CNPJ", "")
    with col3:
        incluir_somente_46 = st.checkbox("Somente Sit.Ope 4 e 6", value=True)

    sql_vops = """
        SELECT
            co, an, ct, filial, aditivo, fluxo_futuro, operacao,
            situacao_operacao, tipo, especie, situacao_aditivo,
            cpf_cnpj, cedente,
            rem_gestora, rem_qcert,
            vlr_face, vlr_aprovado, vlr_liquido,
            dta_neg, observacao_operacao,
            origem_arquivo
        FROM vops
        WHERE 1=1
    """
    params = {}

    if incluir_somente_46:
        sql_vops += " AND situacao_operacao IN ('4','6','04','06')"

    if filtro_cedente_vop.strip():
        sql_vops += " AND cedente ILIKE :cedente"
        params["cedente"] = f"%{filtro_cedente_vop.strip()}%"

    if filtro_cpf_cnpj.strip():
        sql_vops += " AND cpf_cnpj ILIKE :cpf"
        params["cpf"] = f"%{filtro_cpf_cnpj.strip()}%"

    sql_vops += " ORDER BY dta_neg DESC NULLS LAST LIMIT 2000"

    df_vops = safe_fetch_df(sql_vops, params=params)

    for col in ["rem_gestora", "rem_qcert", "vlr_face", "vlr_aprovado", "vlr_liquido"]:
        if col in df_vops.columns:
            df_vops[col] = df_vops[col].map(fmt_money_cell)

    st.dataframe(df_vops, use_container_width=True)


# =========================================================
# TAB 5 - MONITORE
# =========================================================
with tabs[4]:
    st.subheader("🛰️ Monitore")

    st.markdown("### Monitore Diário")

    df_mon_diario = safe_fetch_df("""
        SELECT *
        FROM monitore_diario
        ORDER BY data_ref DESC NULLS LAST
        LIMIT 2000
    """)

    if not df_mon_diario.empty:
        if "saldo_anterior" in df_mon_diario.columns:
            df_mon_diario["saldo_anterior"] = df_mon_diario["saldo_anterior"].map(fmt_money_cell)
        if "saldo_atual" in df_mon_diario.columns:
            df_mon_diario["saldo_atual"] = df_mon_diario["saldo_atual"].map(fmt_money_cell)
        if "evolucao" in df_mon_diario.columns:
            df_mon_diario["evolucao"] = df_mon_diario["evolucao"].map(fmt_money_cell)
        if "variacao" in df_mon_diario.columns:
            df_mon_diario["variacao"] = df_mon_diario["variacao"].map(fmt_pct_cell)

    st.dataframe(df_mon_diario, use_container_width=True)

    st.divider()

    st.markdown("### Monitore Serasa")

    df_mon_serasa = safe_fetch_df("""
        SELECT *
        FROM monitore_serasa
        ORDER BY data_ref DESC NULLS LAST
        LIMIT 2000
    """)

    if df_mon_serasa.empty:
        st.info("📭 Monitore Serasa ainda não possui registros.")
    else:
        if "saldo_anterior" in df_mon_serasa.columns:
            df_mon_serasa["saldo_anterior"] = df_mon_serasa["saldo_anterior"].map(fmt_money_cell)
        if "saldo_atual" in df_mon_serasa.columns:
            df_mon_serasa["saldo_atual"] = df_mon_serasa["saldo_atual"].map(fmt_money_cell)
        if "evolucao" in df_mon_serasa.columns:
            df_mon_serasa["evolucao"] = df_mon_serasa["evolucao"].map(fmt_money_cell)
        if "variacao" in df_mon_serasa.columns:
            df_mon_serasa["variacao"] = df_mon_serasa["variacao"].map(fmt_pct_cell)

        st.dataframe(df_mon_serasa, use_container_width=True)


# =========================================================
# FOOTER
# =========================================================
st.caption("QPROF • Dashboard • Streamlit")
