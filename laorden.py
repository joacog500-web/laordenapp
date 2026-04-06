import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

# ---------------------------------
# Config
# ---------------------------------
st.set_page_config(page_title="La Orden | BI", page_icon="📊", layout="wide")

# ---------------------------------
# Utils
# ---------------------------------
def _parse_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def _extract_first_number(x) -> float:
    """Extrae el primer número dentro de un string: '90.0 u', 'Caja de 30.0 u', etc."""
    if pd.isna(x):
        return np.nan
    s = str(x)
    m = re.search(r"(-?\d+(?:[\.,]\d+)?)", s)
    if not m:
        return np.nan
    return float(m.group(1).replace(",", "."))


def _normalize_str(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def fmt_num(n, nd=0):
    if pd.isna(n):
        return "—"
    if nd == 0:
        return f"{n:,.0f}".replace(",", ".")
    return f"{n:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------
# Loaders
# ---------------------------------
@st.cache_data(show_spinner=False)
def load_sales_data(source, dataset_name: str) -> pd.DataFrame:
    df = pd.read_excel(source)

    expected = [
        "Expedicion", "Cliente", "Producto", "Presentacion", "Marca",
        "Unidades", "Cantidad", "Lote", "Vencimiento"
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"[{dataset_name}] Faltan columnas: {missing}")

    for c in ["Cliente", "Producto", "Presentacion", "Marca"]:
        df[c] = _normalize_str(df[c])

    df["Expedicion_dt"] = _parse_date_series(df["Expedicion"])
    df["Vencimiento_dt"] = _parse_date_series(df["Vencimiento"])

    df["Cantidad_num"] = df["Cantidad"].apply(_extract_first_number)
    df["Unid_por_presentacion"] = df["Presentacion"].apply(_extract_first_number)
    df["Unidades"] = pd.to_numeric(df["Unidades"], errors="coerce")
    df["Cantidad_calc"] = df["Unidades"] * df["Unid_por_presentacion"]

    tol = 1e-6
    df["Consistente_Cantidad"] = np.where(
        df["Cantidad_num"].notna() & df["Cantidad_calc"].notna(),
        np.isclose(df["Cantidad_num"], df["Cantidad_calc"], atol=tol, rtol=0),
        np.nan,
    )

    today = pd.Timestamp.today().normalize()
    df["Dias_a_vencer"] = (df["Vencimiento_dt"] - today).dt.days
    df["Lote"] = pd.to_numeric(df["Lote"], errors="coerce").astype("Int64")
    df["Dataset"] = dataset_name
    return df


@st.cache_data(show_spinner=False)
def load_production_data(source, dataset_name: str) -> pd.DataFrame:
    df = pd.read_excel(source)
    df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]

    col_lut = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for src, dst in [
        ("producto", "Producto"),
        ("cantidad", "Cantidad"),
        ("total", "Total"),
        ("marca", "Marca"),
        ("presentacion", "Presentacion"),
        ("presentación", "Presentacion"),
        ("lote", "Lote"),
        ("vencimiento", "Vencimiento"),
    ]:
        if src in col_lut:
            rename[col_lut[src]] = dst
    df = df.rename(columns=rename)

    if "Producto" not in df.columns:
        raise ValueError(f"[{dataset_name}] Falta la columna 'Producto'")
    if "Total" not in df.columns and "Cantidad" not in df.columns:
        raise ValueError(f"[{dataset_name}] Falta la columna 'Total' o 'Cantidad'")

    df["Producto"] = _normalize_str(df["Producto"])
    if "Marca" in df.columns:
        df["Marca"] = _normalize_str(df["Marca"])
    if "Presentacion" in df.columns:
        df["Presentacion"] = _normalize_str(df["Presentacion"])

    base_col = "Total" if "Total" in df.columns else "Cantidad"
    df["Total_num"] = df[base_col].apply(_extract_first_number).fillna(0)

    prod_txt = df["Producto"].fillna("").str.lower()
    pres_txt = (
        df["Presentacion"].fillna("").astype(str).str.lower()
        if "Presentacion" in df.columns
        else pd.Series("", index=df.index)
    )

    es_express = (
        prod_txt.str.contains("express", na=False)
        | prod_txt.str.contains("congel", na=False)
        | pres_txt.str.contains("congel", na=False)
    )
    es_emp = (
        prod_txt.str.contains("tucuman", na=False)
        | prod_txt.str.contains("salteñ", na=False)
    ) & ~es_express

    df["Categoria"] = "Ensamble"
    df.loc[es_express, "Categoria"] = "Express"
    df.loc[es_emp, "Categoria"] = "Emp. Tucumanas/Salteñas"

    if "Vencimiento" in df.columns:
        df["Vencimiento_dt"] = _parse_date_series(df["Vencimiento"])

    df["Dataset"] = dataset_name
    return df


# ---------------------------------
# Helpers de negocio
# ---------------------------------
def build_customer_groups(df: pd.DataFrame, state_key: str = "grupos_clientes"):
    clientes_disponibles = sorted(df["Cliente"].dropna().unique().tolist())

    if state_key not in st.session_state:
        st.session_state[state_key] = {}

    st.markdown("## 👥 Grupos de clientes")
    st.caption("Agrupá clientes bajo un nombre común para analizarlos juntos.")

    with st.expander("➕ Crear / editar grupos de clientes", expanded=False):
        c1, c2 = st.columns([1, 2])
        with c1:
            nuevo_grupo = st.text_input(
                "Nombre del grupo",
                key=f"{state_key}_nombre",
                placeholder="Ej: La Reina"
            )
        with c2:
            miembros = st.multiselect(
                "Clientes del grupo",
                options=clientes_disponibles,
                key=f"{state_key}_miembros",
            )

        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Guardar grupo", key=f"{state_key}_guardar"):
                if nuevo_grupo.strip() and miembros:
                    st.session_state[state_key][nuevo_grupo.strip()] = miembros
                    st.success(f"Grupo '{nuevo_grupo.strip()}' guardado.")
                else:
                    st.warning("Ingresá un nombre y seleccioná al menos un cliente.")
        with b2:
            grupo_borrar = st.selectbox(
                "Borrar grupo",
                options=[""] + list(st.session_state[state_key].keys()),
                key=f"{state_key}_borrar_sel",
            )
            if st.button("🗑️ Borrar", key=f"{state_key}_borrar_btn") and grupo_borrar:
                del st.session_state[state_key][grupo_borrar]
                st.success(f"Grupo '{grupo_borrar}' eliminado.")

        if st.session_state[state_key]:
            st.markdown("**Grupos actuales:**")
            for gn, gm in st.session_state[state_key].items():
                st.markdown(f"- **{gn}**: {', '.join(gm)}")

    grupos = st.session_state[state_key]
    cliente_a_grupo = {}
    for gn, gm in grupos.items():
        for cli in gm:
            cliente_a_grupo[cli] = gn

    df = df.copy()
    df["Cliente_Grupo"] = df["Cliente"].map(cliente_a_grupo).fillna(df["Cliente"])

    if grupos:
        usar_grupos = st.toggle("📊 Analizar por grupos de clientes", value=True, key=f"{state_key}_toggle")
        col_cliente = "Cliente_Grupo" if usar_grupos else "Cliente"
    else:
        col_cliente = "Cliente"

    return df, col_cliente


# ---------------------------------
# UI principal
# ---------------------------------
st.title("📊 La Orden | Dashboard de Ventas + Producción")

# Tabs totalmente separadas
tab_ventas, tab_produccion = st.tabs(["💰 Ventas", "🏭 Producción"])

# ============================================================
# TAB VENTAS
# ============================================================
with tab_ventas:
    st.header("💰 Ventas")
    st.caption("Cargá uno o más archivos de ventas. El análisis principal funciona con un archivo solo; la comparación es opcional.")

    sales_uploads = st.file_uploader(
        "Subí archivos de ventas",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        key="ventas_uploader",
    )

    if not sales_uploads:
        st.info("Subí archivos de ventas para ver el análisis.")
    else:
        sales_datasets = []
        for uf in sales_uploads:
            try:
                sales_datasets.append(load_sales_data(uf, uf.name))
            except Exception as e:
                st.warning(f"❌ No pude cargar {uf.name}: {e}")

        if not sales_datasets:
            st.error("No se pudo cargar ningún archivo de ventas válido.")
        else:
            df_sales = pd.concat(sales_datasets, ignore_index=True)
            ds_opts = sorted(df_sales["Dataset"].dropna().unique())

            c1, c2 = st.columns([2, 1])
            with c1:
                dataset_principal = st.selectbox(
                    "📄 Archivo principal para el dashboard mensual",
                    ds_opts,
                    index=len(ds_opts) - 1,
                    key="ventas_dataset_principal",
                )
            with c2:
                metric_choice = st.selectbox(
                    "Métrica",
                    ["Unidades (Cantidad)", "Cajas/Packs", "Cantidad calculada"],
                    key="ventas_metric_choice",
                )

            if metric_choice == "Unidades (Cantidad)":
                metric_col = "Cantidad_num"
            elif metric_choice == "Cajas/Packs":
                metric_col = "Unidades"
            else:
                metric_col = "Cantidad_calc"

            df_mes = df_sales[df_sales["Dataset"] == dataset_principal].copy()
            df_mes, col_cliente_activa = build_customer_groups(df_mes, state_key="ventas_grupos")

            total_units = float(df_mes[metric_col].sum())
            total_boxes = float(df_mes["Unidades"].sum())
            total_clients = int(df_mes[col_cliente_activa].nunique())
            total_products = int(df_mes["Producto"].nunique())
            total_brands = int(df_mes["Marca"].nunique())
            avg_per_client = total_units / total_clients if total_clients else 0

            st.divider()
            st.subheader("📌 Resumen general del archivo")
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Vendido total", fmt_num(total_units, 0))
            k2.metric("Cajas/Packs", fmt_num(total_boxes, 2))
            k3.metric("Clientes", total_clients)
            k4.metric("Productos", total_products)
            k5.metric("Marcas", total_brands)
            k6.metric("Promedio por cliente", fmt_num(avg_per_client, 0))

            st.divider()

            left, right = st.columns(2)
            with left:
                st.markdown("### 👥 Top clientes")
                top_clientes = (
                    df_mes.groupby(col_cliente_activa, as_index=False)
                    .agg(Ventas=(metric_col, "sum"))
                    .sort_values("Ventas", ascending=False)
                    .head(15)
                    .rename(columns={col_cliente_activa: "Cliente"})
                )
                fig_clientes = px.bar(top_clientes, x="Ventas", y="Cliente", orientation="h", title="Top clientes")
                fig_clientes.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig_clientes, use_container_width=True)

            with right:
                st.markdown("### 📦 Top productos")
                top_productos = (
                    df_mes.groupby("Producto", as_index=False)
                    .agg(Ventas=(metric_col, "sum"))
                    .sort_values("Ventas", ascending=False)
                    .head(15)
                )
                fig_productos = px.bar(top_productos, x="Ventas", y="Producto", orientation="h", title="Top productos")
                fig_productos.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig_productos, use_container_width=True)

            c3, c4 = st.columns(2)
            

            

            st.divider()
            st.subheader("📊 Comparación opcional entre archivos")
            activar_cmp = st.toggle("Quiero comparar archivos", value=False, key="ventas_activar_cmp")

            if activar_cmp:
                if len(ds_opts) < 2:
                    st.info("Necesitás al menos 2 archivos para comparar.")
                else:
                    ca, cb = st.columns(2)
                    with ca:
                        cmp_a = st.selectbox("Archivo base", ds_opts, index=0, key="ventas_cmp_a")
                    with cb:
                        cmp_b = st.selectbox("Archivo a comparar", ds_opts, index=min(1, len(ds_opts)-1), key="ventas_cmp_b")

                    agrupar_por = st.radio(
                        "Comparar por",
                        ["Producto", "Cliente"],
                        horizontal=True,
                        key="ventas_cmp_agrupar"
                    )

                    if cmp_a == cmp_b:
                        st.warning("Elegí dos archivos distintos.")
                    else:
                        df_a = df_sales[df_sales["Dataset"] == cmp_a].copy()
                        df_b = df_sales[df_sales["Dataset"] == cmp_b].copy()

                        # aplicar grupos también en comparativo
                        grupos = st.session_state.get("ventas_grupos", {})
                        mapa = {cli: gn for gn, miembros in grupos.items() for cli in miembros}
                        df_a["Cliente_Grupo"] = df_a["Cliente"].map(mapa).fillna(df_a["Cliente"])
                        df_b["Cliente_Grupo"] = df_b["Cliente"].map(mapa).fillna(df_b["Cliente"])
                        group_col = "Producto" if agrupar_por == "Producto" else col_cliente_activa
                        out_col = "Producto" if agrupar_por == "Producto" else "Cliente"

                        agg_a = df_a.groupby(group_col, as_index=False).agg(Ventas_A=(metric_col, "sum"))
                        agg_b = df_b.groupby(group_col, as_index=False).agg(Ventas_B=(metric_col, "sum"))

                        cmp = pd.merge(agg_a, agg_b, on=group_col, how="outer").fillna(0)
                        cmp["Variación %"] = np.where(
                            cmp["Ventas_A"] != 0,
                            ((cmp["Ventas_B"] - cmp["Ventas_A"]) / cmp["Ventas_A"] * 100),
                            np.where(cmp["Ventas_B"] > 0, 100.0, 0.0),
                        )
                        cmp = cmp.rename(columns={group_col: out_col}).sort_values("Ventas_B", ascending=False)
                        st.dataframe(cmp, use_container_width=True, hide_index=True)

                        plot_cmp = cmp.head(15).melt(
                            id_vars=[out_col],
                            value_vars=["Ventas_A", "Ventas_B"],
                            var_name="Serie",
                            value_name="Ventas",
                        )
                        fig_cmp = px.bar(
                            plot_cmp,
                            x=out_col,
                            y="Ventas",
                            color="Serie",
                            barmode="group",
                            title=f"{cmp_a} vs {cmp_b}",
                        )
                        fig_cmp.update_layout(xaxis_tickangle=-25)
                        st.plotly_chart(fig_cmp, use_container_width=True)

# ============================================================
# TAB PRODUCCIÓN
# ============================================================
with tab_produccion:
    st.header("🏭 Producción")
    st.caption("Esta pestaña es independiente de ventas. Subí acá solo archivos de producción.")

    prod_uploads = st.file_uploader(
        "Subí archivos de producción",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        key="produccion_uploader",
    )

    if not prod_uploads:
        st.info("Subí archivos de producción para ver el análisis.")
    else:
        prod_datasets = []
        for uf in prod_uploads:
            try:
                prod_datasets.append(load_production_data(uf, uf.name))
            except Exception as e:
                st.warning(f"❌ No pude cargar {uf.name}: {e}")

        if not prod_datasets:
            st.error("No se pudo cargar ningún archivo de producción válido.")
        else:
            df_prod = pd.concat(prod_datasets, ignore_index=True)
            ds_prod_opts = sorted(df_prod["Dataset"].dropna().unique().tolist())

            ds_sel = st.multiselect(
                "📁 Archivos de producción a analizar",
                options=ds_prod_opts,
                default=ds_prod_opts,
                key="prod_ds_sel",
            )
            df_p = df_prod[df_prod["Dataset"].isin(ds_sel)].copy()

            total = float(df_p["Total_num"].sum())
            t_express = float(df_p.loc[df_p["Categoria"] == "Express", "Total_num"].sum())
            t_emp = float(df_p.loc[df_p["Categoria"] == "Emp. Tucumanas/Salteñas", "Total_num"].sum())
            t_ensam = float(df_p.loc[df_p["Categoria"] == "Ensamble", "Total_num"].sum())
            skus = int(df_p["Producto"].nunique())

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Total producido", fmt_num(total, 0))
            k2.metric("Ensamble", fmt_num(t_ensam, 0))
            k3.metric("Express", fmt_num(t_express, 0))
            k4.metric("Emp. Tuc./Salt.", fmt_num(t_emp, 0))
            k5.metric("Productos distintos", skus)

            st.divider()

            c1, c2 = st.columns(2)
            with c1:
                df_donut = pd.DataFrame({
                    "Categoría": ["Ensamble", "Express", "Emp. Tucumanas/Salteñas"],
                    "Total": [t_ensam, t_express, t_emp],
                })
                fig_donut = px.pie(df_donut, values="Total", names="Categoría", hole=0.5, title="Distribución por categoría")
                st.plotly_chart(fig_donut, use_container_width=True)

            with c2:
                top_prod = (
                    df_p.groupby("Producto", as_index=False)
                    .agg(Total=("Total_num", "sum"))
                    .sort_values("Total", ascending=False)
                    .head(15)
                )
                fig_top_prod = px.bar(top_prod, x="Total", y="Producto", orientation="h", title="Top productos producidos")
                fig_top_prod.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig_top_prod, use_container_width=True)

            st.divider()
            st.markdown("### 📋 Tabla completa")
            tabla = (
                df_p.groupby(["Producto", "Categoria"], as_index=False)
                .agg(Total=("Total_num", "sum"))
                .sort_values(["Categoria", "Total"], ascending=[True, False])
            )
            st.dataframe(tabla, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("📊 Comparación opcional de producción")
            activar_cmp_prod = st.toggle("Quiero comparar archivos de producción", value=False, key="prod_cmp_toggle")

            if activar_cmp_prod:
                if len(ds_prod_opts) < 2:
                    st.info("Necesitás al menos 2 archivos para comparar producción.")
                else:
                    p1, p2 = st.columns(2)
                    with p1:
                        prod_a = st.selectbox("Archivo base", ds_prod_opts, index=0, key="prod_cmp_a")
                    with p2:
                        prod_b = st.selectbox("Archivo a comparar", ds_prod_opts, index=min(1, len(ds_prod_opts)-1), key="prod_cmp_b")

                    agrupar_prod = st.radio(
                        "Comparar producción por",
                        ["Producto", "Categoria"],
                        horizontal=True,
                        key="prod_cmp_agrupar",
                    )

                    if prod_a == prod_b:
                        st.warning("Elegí dos archivos distintos.")
                    else:
                        pa = df_prod[df_prod["Dataset"] == prod_a].copy()
                        pb = df_prod[df_prod["Dataset"] == prod_b].copy()

                        aa = pa.groupby(agrupar_prod, as_index=False).agg(Total_A=("Total_num", "sum"))
                        bb = pb.groupby(agrupar_prod, as_index=False).agg(Total_B=("Total_num", "sum"))
                        cmp_prod = pd.merge(aa, bb, on=agrupar_prod, how="outer").fillna(0)
                        cmp_prod["Variación %"] = np.where(
                            cmp_prod["Total_A"] != 0,
                            ((cmp_prod["Total_B"] - cmp_prod["Total_A"]) / cmp_prod["Total_A"] * 100),
                            np.where(cmp_prod["Total_B"] > 0, 100.0, 0.0),
                        )
                        cmp_prod = cmp_prod.sort_values("Total_B", ascending=False)
                        st.dataframe(cmp_prod, use_container_width=True, hide_index=True)

