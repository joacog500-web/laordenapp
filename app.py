import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
df_f = None

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

def fmt_int(n):
    if pd.isna(n):
        return "—"
    return f"{int(n):,}".replace(",", ".")

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
    """Carga y prepara Excel de ventas (tu formato clásico)."""
    df = pd.read_excel(source)

    expected = ["Expedicion","Cliente","Producto","Presentacion","Marca","Unidades","Cantidad","Lote","Vencimiento"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"[{dataset_name}] Faltan columnas: {missing}")

    for c in ["Cliente","Producto","Presentacion","Marca"]:
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
        np.nan
    )

    today = pd.Timestamp.today().normalize()
    df["Dias_a_vencer"] = (df["Vencimiento_dt"] - today).dt.days

    df["Lote"] = pd.to_numeric(df["Lote"], errors="coerce").astype("Int64")

    df["Dataset"] = dataset_name
    return df


@st.cache_data(show_spinner=False)
def load_production_data(source, dataset_name: str) -> pd.DataFrame:
    """
    Carga un Excel de producción (independiente de ventas).
    Por ahora solo exige Producto + Cantidad. Luego lo extendemos con 'componentes'.
    """
    df = pd.read_excel(source)

    required = ["Producto", "Cantidad"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"[{dataset_name}] Faltan columnas: {missing}")

    df["Producto"] = _normalize_str(df["Producto"])
    df["Cantidad_num"] = df["Cantidad"].apply(_extract_first_number)

    # Si el archivo trae fecha u otros campos, los vamos a aprovechar luego.
    df["Dataset"] = dataset_name
    return df


# ---------------------------------
# UI
# ---------------------------------
st.title("📊 La Orden | Dashboard de Ventas + Producción")

tab_ventas, tab_produccion = st.tabs(["💰 Ventas (unificado)", "🏭 Producción"])

# ============================================================
# TAB VENTAS
# ============================================================
with tab_ventas:
    sales_uploads = st.file_uploader(
        "Subí archivos de ventas",
        type=["xls", "xlsx"],
        accept_multiple_files=True
    )

    if not sales_uploads:
        st.info("Subí archivos de ventas para ver el análisis.")
        st.stop()

    sales_datasets = []
    for uf in sales_uploads:
        df_tmp = load_sales_data(uf, uf.name)
        sales_datasets.append(df_tmp)

    # ✅ CREÁS df_sales
    df_sales = pd.concat(sales_datasets, ignore_index=True)

    # ✅ CREÁS df_f
    df_f = df_sales.copy()


    if not sales_uploads:
        st.info("Subí archivos de **ventas** para ver el análisis. Producción funciona en el otro tab.")
    else:
        sales_datasets = []
        for uf in sales_uploads:
            try:
                sales_datasets.append(load_sales_data(uf, dataset_name=uf.name))
            except Exception as e:
                st.warning(f"❌ No pude cargar {uf.name}: {e}")

        if not sales_datasets:
            st.warning("No se pudo cargar ningún archivo de ventas válido.")
        else:
            df_sales = pd.concat(sales_datasets, ignore_index=True)
            


            # Selección de archivos (datasets)
            ds_opts = sorted(df_sales["Dataset"].dropna().unique())
            ds_sel = st.multiselect(
                "🗂️ Seleccioná qué archivos querés analizar",
                ds_opts,
                default=ds_opts,
                key="ventas_ds_sel",
            )
            df_f = df_sales[df_sales["Dataset"].isin(ds_sel)].copy()


            # Métrica principal de ventas
            metric_choice = st.radio(
                "Métrica principal",
                ["Unidades (Cantidad)", "Cajas/Packs", "Cantidad calculada"],
                horizontal=True,
                key="ventas_metric_choice",
            )
            if metric_choice == "Unidades (Cantidad)":
                metric_col = "Cantidad_num"
            elif metric_choice == "Cajas/Packs":
                metric_col = "Unidades"
            else:
                metric_col = "Cantidad_calc"

            # KPIs globales
            total_units = float(df_f[metric_col].sum()) if metric_col in df_f.columns else 0.0
            total_boxes = float(df_f["Unidades"].sum()) if "Unidades" in df_f.columns else 0.0
            total_clients = int(df_f["Cliente"].nunique()) if "Cliente" in df_f.columns else 0
            total_products = int(df_f["Producto"].nunique()) if "Producto" in df_f.columns else 0

            # Express (si existe lógica: "Express" en Producto)
            if "Producto" in df_f.columns:
                total_express = float(
                    df_f.loc[df_f["Producto"].str.contains("express", case=False, na=False), metric_col].sum()
                )
            else:
                total_express = 0.0

            st.markdown("## 📌 TOTAL VENTAS")
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Unidades (Cantidad)", fmt_num(total_units, 0))
            k2.metric("Cajas/Packs", fmt_num(total_boxes, 2))
            k3.metric("Clientes", total_clients)
            k4.metric("Productos", total_products)
            
            st.divider()

            # ----------------------------
            # Resumen por archivo
            # ----------------------------
            st.markdown("## Ventas por mes")
            ds_summary = (
                df_f.groupby("Dataset", as_index=False)
                    .agg(Unidades=(metric_col, "sum"))
                    .sort_values("Unidades", ascending=False)
            )
            total = float(ds_summary["Unidades"].sum()) if len(ds_summary) else 0.0
            ds_summary["% del total"] = (ds_summary["Unidades"] / total * 100) if total > 0 else 0.0

            for _, row in ds_summary.iterrows():
                c1, c2, c3 = st.columns([3, 1.5, 1.5])
                c1.markdown(f"📄 **{row['Dataset']}**")
                c2.metric("Unidades", fmt_num(row["Unidades"], 0))
                c3.metric("% del total", f"{row['% del total']:.1f}%")
                st.divider()

            

        st.header("📊 Ventas – Resumen general")
        df_v = df_f.dropna(subset=["Expedicion_dt"]).copy()
        df_v["Mes"] = df_v["Expedicion_dt"].dt.to_period("M").astype(str)

        ventas_mes = (
            df_v.groupby("Mes", as_index=False)
                .agg(Unidades=("Cantidad_num", "sum"))
                .sort_values("Mes")
        )

        import plotly.express as px

        fig_mes = px.bar(
            ventas_mes,
            x="Mes",
            y="Unidades",
            title="Ventas totales por mes"
        )
        st.plotly_chart(fig_mes, use_container_width=True)

        # ============================================================
    # 📊 VENTAS — ANÁLISIS COMPLETO (UNIFICADO, SIN TABS)
    # ============================================================
    st.divider()
    st.header("📊 Análisis completo de ventas")

    metric_options = [c for c in ["Cantidad_num", "Cantidad_calc", "Unidades"] if c in df_f.columns]

    metric_options = [c for c in ["Cantidad_num", "Cantidad_calc", "Unidades"] if c in df_f.columns]
    if not metric_options:
        st.error("No encuentro una columna numérica para medir ventas (Cantidad_num / Cantidad_calc / Unidades).")
    else:
        main_metric_col = metric_options[0]  # usa la primera disponible (normalmente Cantidad_num)

        # -----------------------------
        # 1) Rankings globales (Clientes / Productos)
        # -----------------------------



    # métrica que usás en ventas
    metric_col = "Cantidad_num" if "Cantidad_num" in df_f.columns else ("Cantidad_calc" if "Cantidad_calc" in df_f.columns else "Unidades")

    if "Dataset" not in df_f.columns or df_f["Dataset"].nunique() < 2:
        st.info("Necesitás al menos 2 archivos cargados para comparar por archivo.")
    else:
        # 1) Seleccionar cliente
        clientes = sorted(df_f["Cliente"].dropna().unique().tolist())
        cliente_sel = st.selectbox("Seleccioná cliente", clientes, key="ventas_cli_prod_arch_cliente")

        # 2) Seleccionar 2 archivos
        ds_opts = sorted(df_f["Dataset"].dropna().unique().tolist())
        c1, c2 = st.columns(2)
        with c1:
            ds_a = st.selectbox("Archivo A", ds_opts, index=max(0, len(ds_opts) - 2), key="ventas_cli_prod_arch_ds_a")
        with c2:
            ds_b = st.selectbox("Archivo B", ds_opts, index=len(ds_opts) - 1, key="ventas_cli_prod_arch_ds_b")

        if ds_a == ds_b:
            st.warning("Elegí dos archivos distintos para comparar.")
        else:
            top_n = st.slider("Top productos a comparar", 5, 40, 15, key="ventas_cli_prod_arch_top_n")

            # 3) Filtrar cliente + esos dos archivos
            df_cli = df_f[
                (df_f["Cliente"] == cliente_sel) &
                (df_f["Dataset"].isin([ds_a, ds_b]))
            ].copy()

            if df_cli.empty:
                st.info("No hay ventas para ese cliente en los archivos seleccionados.")
            else:
                # 4) Elegir productos top (en ambos archivos combinados)
                top_products = (
                    df_cli.groupby("Producto")[metric_col]
                        .sum()
                        .sort_values(ascending=False)
                        .head(top_n)
                        .index.tolist()
                )

                df_plot = (
                    df_cli[df_cli["Producto"].isin(top_products)]
                        .groupby(["Producto", "Dataset"], as_index=False)
                        .agg(Unidades=(metric_col, "sum"))
                )

                # 5) Gráfico de barras agrupado
                import plotly.express as px
                fig = px.bar(
                    df_plot,
                    x="Producto",
                    y="Unidades",
                    color="Dataset",
                    barmode="group",
                    title=f"{cliente_sel} — Producto × Archivo: {ds_a} vs {ds_b}"
                )
                fig.update_layout(
                    xaxis_title="Producto",
                    yaxis_title="Unidades",
                    xaxis_tickangle=-25
                )
                st.plotly_chart(fig, use_container_width=True)

                

        

        cA, cB = st.columns(2)
        with cA:
            top_n_cli = st.slider("Top clientes", 5, 50, 20, key="ventas_top_clientes_unificado")
            by_client = (
                df_f.groupby("Cliente")[main_metric_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(top_n_cli)
                    .reset_index()
                    .rename(columns={main_metric_col: "Unidades"})
            )
            st.markdown("### 👥 Top clientes")
            st.dataframe(by_client, use_container_width=True, hide_index=True)

        with cB:
            top_n_prod = st.slider("Top productos", 5, 50, 20, key="ventas_top_productos_unificado")
            by_prod = (
                df_f.groupby("Producto")[main_metric_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(top_n_prod)
                    .reset_index()
                    .rename(columns={main_metric_col: "Unidades"})
            )
            st.markdown("### 📦 Top productos")
            st.dataframe(by_prod, use_container_width=True, hide_index=True)

        st.divider()

        st.divider()
    st.subheader("📌 Comparativo: 2 a 5 clientes")

    # métrica que estás usando en ventas
    metric_col = "Cantidad_num" if "Cantidad_num" in df_f.columns else ("Cantidad_calc" if "Cantidad_calc" in df_f.columns else "Unidades")

    clientes = sorted(df_f["Cliente"].dropna().unique().tolist())

    clientes_sel = st.multiselect(
        "Elegí entre 2 y 5 clientes",
        options=clientes,
        default=clientes[:3] if len(clientes) >= 3 else clientes,
        key="ventas_cmp_2a5_clientes"
    )

    # Validación: entre 2 y 5
    if len(clientes_sel) < 2:
        st.info("Seleccioná al menos 2 clientes.")
    elif len(clientes_sel) > 5:
        st.warning("Seleccioná como máximo 5 clientes (para que se vea claro).")
    else:
        df_cmp = df_f[df_f["Cliente"].isin(clientes_sel)].copy()

        by_cli = (
            df_cmp.groupby("Cliente", as_index=False)
                .agg(Unidades=(metric_col, "sum"))
                .sort_values("Unidades", ascending=False)
        )

        total_sel = by_cli["Unidades"].sum()
        st.metric(f"{metric_col} (unidades) (total en selección)", f"{int(total_sel):,}".replace(",", "."))

        fig = px.bar(
            by_cli,
            x="Cliente",
            y="Unidades",
            text="Unidades",
            title=f"Comparativo de {metric_col} (unidades) (clientes seleccionados)"
        )
        fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
        fig.update_layout(yaxis_title=f"{metric_col} (unidades)", xaxis_title="Cliente")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("## 📁 Producto × Archivo (barras)")

    if "Dataset" in df_f.columns and df_f["Dataset"].nunique() >= 2:
        ds_opts = sorted(df_f["Dataset"].dropna().unique().tolist())

        c1, c2 = st.columns(2)
        with c1:
            ds_a = st.selectbox("Archivo A", ds_opts, index=max(0, len(ds_opts) - 2), key="ventas_prod_arch_ds_a")
        with c2:
            ds_b = st.selectbox("Archivo B", ds_opts, index=len(ds_opts) - 1, key="ventas_prod_arch_ds_b")

        if ds_a == ds_b:
            st.warning("Elegí dos archivos distintos para comparar.")
        else:
            top_n = st.slider("Top productos a comparar", 5, 40, 15, key="ventas_prod_arch_top_n")

            # Top productos globales (sobre ambos archivos) para que sea comparable
            df_ab = df_f[df_f["Dataset"].isin([ds_a, ds_b])].copy()

            top_products = (
                df_ab.groupby("Producto")[metric_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(top_n)
                    .index
                    .tolist()
            )

            df_plot = (
                df_ab[df_ab["Producto"].isin(top_products)]
                    .groupby(["Producto", "Dataset"], as_index=False)
                    .agg(Unidades=(metric_col, "sum"))
            )

            # Asegurar que existan las dos barras por producto (si un archivo tiene 0)
            # (Plotly ya maneja valores faltantes, pero esto deja el gráfico más estable)
            df_plot["Unidades"] = df_plot["Unidades"].fillna(0)

            import plotly.express as px
            fig = px.bar(
                df_plot,
                x="Producto",
                y="Unidades",
                color="Dataset",
                barmode="group",
                title=f"Producto × Archivo (comparación): {ds_a} vs {ds_b}"
            )

            fig.update_layout(
                xaxis_title="Producto",
                yaxis_title="Unidades",
                xaxis_tickangle=-25
            )

            st.plotly_chart(fig, use_container_width=True)

            # (opcional) tabla abajo por si querés verla también
            with st.expander("Ver tabla (pivot)"):
                pivot = df_plot.pivot_table(index="Producto", columns="Dataset", values="Unidades", aggfunc="sum", fill_value=0)
                st.dataframe(pivot, use_container_width=True)
    else:
        st.info("Cargá al menos 2 archivos para ver Producto × Archivo.")




        

    


        # -----------------------------
        # 3) Cuadros por cliente (lo más visual)
        # -----------------------------
        st.subheader("🧾 Cuadros por cliente (comparación fácil)")

        clientes = sorted(df_f["Cliente"].dropna().unique().tolist())
        # por defecto: top 2 clientes globales
        default_sel = (
            df_f.groupby("Cliente")[main_metric_col]
                .sum()
                .sort_values(ascending=False)
                .head(2)
                .index
                .tolist()
        )

        clientes_sel = st.multiselect(
            "Seleccioná clientes a comparar",
            options=clientes,
            default=default_sel if len(default_sel) else (clientes[:2] if len(clientes) >= 2 else clientes),
            key="ventas_clientes_sel_unificado"
        )

        top_n_prod_cli = st.slider("Productos por cliente (Top N)", 5, 30, 10, key="ventas_top_prod_por_cliente_unificado")

        if not clientes_sel:
            st.info("Seleccioná al menos un cliente.")
        else:
            df_sel = df_f[df_f["Cliente"].isin(clientes_sel)].copy()
            max_cols = min(len(clientes_sel), 4)
            cols = st.columns(max_cols)

            for col, cliente in zip(cols, clientes_sel[:max_cols]):
                df_cli = df_sel[df_sel["Cliente"] == cliente]

                resumen = (
                    df_cli.groupby("Producto", as_index=False)
                        .agg(Unidades=(main_metric_col, "sum"))
                        .sort_values("Unidades", ascending=False)
                        .head(top_n_prod_cli)
                )
                total_cli = df_cli[main_metric_col].sum()

                with col:
                    st.markdown(f"### {cliente}")
                    st.caption(f"Total: **{total_cli:,.0f}**".replace(",", "."))
                    st.dataframe(resumen, use_container_width=True, hide_index=True)

            if len(clientes_sel) > 4:
                st.info("Mostrando solo los primeros 4 clientes para que se vea bien.")

        st.divider()

        # -----------------------------
        # 4) (Opcional) Producto × Archivo
        # -----------------------------
        st.subheader("📁 Producto × Archivo")

        if "Dataset" in df_f.columns and df_f["Dataset"].nunique() >= 2:
            top_n_prod_arch = st.slider("Top productos a comparar (Producto × Archivo)", 5, 50, 15, key="ventas_top_prod_x_archivo_unificado")
            top_products = (
                df_f.groupby("Producto")[main_metric_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(top_n_prod_arch)
                    .index
                    .tolist()
            )
            df_cmp_p = df_f[df_f["Producto"].isin(top_products)].copy()

            pivot_prod = df_cmp_p.pivot_table(
                index="Producto",
                columns="Dataset",
                values=main_metric_col,
                aggfunc="sum",
                fill_value=0
            )
            st.dataframe(pivot_prod, use_container_width=True)
        else:
            st.info("Cargá al menos 2 archivos para ver Producto × Archivo.")


# ============================================================
# TAB PRODUCCIÓN
# ============================================================
with tab_produccion:
    st.header("🏭 Producción — Análisis completo (Congelados / Express)")

    prod_uploads = st.file_uploader(
        "Subí 1 o más archivos de PRODUCCIÓN (.xls/.xlsx)",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        key="prod_uploader_final"
    )

    if not prod_uploads:
        st.info("Subí archivos de producción para ver el análisis.")
    else:
        import re
        import numpy as np
        import pandas as pd
        import plotly.express as px

        # ---------------------------
        # Helpers
        # ---------------------------
        def _extract_first_number(x):
            """Soporta: 7423.044 | 7.423,044 | 1.200 | 1200 | etc."""
            if pd.isna(x):
                return np.nan
            s = str(x).strip()
            m = re.search(r"(-?\d+(?:[.,]\d+)*)", s)
            if not m:
                return np.nan
            num = m.group(1)

            # Caso AR: 7.423,044 -> 7423.044
            if "," in num and "." in num:
                num = num.replace(".", "").replace(",", ".")
            else:
                # Caso: 8327.088 o 1200 o 1,5
                num = num.replace(",", ".")

            try:
                return float(num)
            except:
                return np.nan

        def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
            df = df.copy()
            df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]
            return df

        def _auto_rename(df: pd.DataFrame) -> pd.DataFrame:
            """Renombra columnas comunes a estándar: Producto, Cantidad, Marca, Presentacion, Lote, Vencimiento."""
            df = df.copy()
            col_lut = {str(c).strip().lower(): c for c in df.columns}
            rename = {}

            # producto / cantidad obligatorias
            if "producto" in col_lut:
                rename[col_lut["producto"]] = "Producto"
            if "cantidad" in col_lut:
                rename[col_lut["cantidad"]] = "Cantidad"

            # opcionales
            if "marca" in col_lut:
                rename[col_lut["marca"]] = "Marca"
            if "presentacion" in col_lut:
                rename[col_lut["presentacion"]] = "Presentacion"
            if "presentación" in col_lut:
                rename[col_lut["presentación"]] = "Presentacion"
            if "lote" in col_lut:
                rename[col_lut["lote"]] = "Lote"
            if "vencimiento" in col_lut:
                rename[col_lut["vencimiento"]] = "Vencimiento"

            return df.rename(columns=rename)

        # ---------------------------
        # Carga
        # ---------------------------
        prod_datasets = []
        for uf in prod_uploads:
            try:
                df_tmp = pd.read_excel(uf)
                df_tmp = _normalize_columns(df_tmp)
                df_tmp = _auto_rename(df_tmp)
                df_tmp["Dataset"] = uf.name
                prod_datasets.append(df_tmp)
            except Exception as e:
                st.warning(f"❌ No pude cargar {uf.name}: {e}")

        if not prod_datasets:
            st.error("No se cargó ningún archivo de producción válido.")
        else:
            df_prod = pd.concat(prod_datasets, ignore_index=True)

            # Validación mínima
            missing = [c for c in ["Producto", "Cantidad"] if c not in df_prod.columns]
            if missing:
                st.error(f"Faltan columnas en Producción: {missing}")
                st.write("Columnas detectadas:", df_prod.columns.tolist())
                st.stop()

            # Normalizar textos
            df_prod["Producto"] = df_prod["Producto"].astype(str).str.strip()
            if "Marca" in df_prod.columns:
                df_prod["Marca"] = df_prod["Marca"].astype(str).str.strip()
            if "Presentacion" in df_prod.columns:
                df_prod["Presentacion"] = df_prod["Presentacion"].astype(str).str.strip()

            # Cantidad_num robusta
            df_prod["Cantidad_num"] = df_prod["Cantidad"].apply(_extract_first_number).fillna(0)

            # Congelado/Express
            prod_txt = df_prod["Producto"].fillna("").str.lower()
            pres_txt = df_prod["Presentacion"].fillna("").astype(str).str.lower() if "Presentacion" in df_prod.columns else None
            df_prod["Es_Congelado"] = (
                prod_txt.str.contains("express", na=False) |
                prod_txt.str.contains("congel", na=False) |
                (pres_txt.str.contains("congel", na=False) if isinstance(pres_txt, pd.Series) else False)
            )

            # Mes (usando Vencimiento si existe)
            if "Vencimiento" in df_prod.columns:
                df_prod["Vencimiento_dt"] = pd.to_datetime(df_prod["Vencimiento"], dayfirst=True, errors="coerce")
                df_prod["Mes"] = df_prod["Vencimiento_dt"].dt.to_period("M").astype(str)
            else:
                df_prod["Mes"] = None

            # Filtro por archivos
            ds_opts = sorted(df_prod["Dataset"].dropna().unique().tolist())
            ds_sel = st.multiselect(
                "📁 Archivos de producción a analizar",
                options=ds_opts,
                default=ds_opts,
                key="prod_ds_sel_final"
            )
            df_p = df_prod[df_prod["Dataset"].isin(ds_sel)].copy()

            # ---------------------------
            # KPIs
            # ---------------------------
            total = float(df_p["Cantidad_num"].sum())
            cong = float(df_p.loc[df_p["Es_Congelado"], "Cantidad_num"].sum())
            no_cong = total - cong
            pct_cong = (cong / total * 100) if total > 0 else 0.0
            skus = int(df_p["Producto"].nunique())

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("📦 Total producido", f"{int(total):,}".replace(",", "."))
            k2.metric("❄️ Congelados / Express", f"{int(cong):,}".replace(",", "."))
            k3.metric("📦 No congelados", f"{int(no_cong):,}".replace(",", "."))
            k4.metric("🍽 Productos distintos", skus)

            st.caption(f"❄️ % Congelado/Express sobre total: **{pct_cong:.1f}%**")

            st.divider()

            # ---------------------------
            # Congelados vs No congelados (barras)
            # ---------------------------
            st.subheader("❄️ Congelados vs No congelados")

            df_tipo = pd.DataFrame({
                "Tipo": ["Congelado/Express", "No congelado"],
                "Cantidad": [cong, no_cong]
            })
            fig_tipo = px.bar(df_tipo, x="Tipo", y="Cantidad", text="Cantidad", title="Producción por tipo")
            fig_tipo.update_traces(texttemplate="%{text:.0f}", textposition="outside")
            st.plotly_chart(fig_tipo, use_container_width=True)

            st.divider()

            

            # ---------------------------
            # Top productos (total)
            # ---------------------------
            st.subheader("🏆 Top productos producidos")

            top_n = st.slider("Top productos", 5, 30, 10, key="prod_top_n_final")

            top_prod = (
                df_p.groupby("Producto", as_index=False)
                    .agg(Cantidad=("Cantidad_num", "sum"))
                    .sort_values("Cantidad", ascending=False)
                    .head(top_n)
            )
            fig_top = px.bar(top_prod, x="Cantidad", y="Producto", orientation="h", title="Top productos (total)")
            st.plotly_chart(fig_top, use_container_width=True)

            # ---------------------------
            # Top Congelados/Express
            # ---------------------------
            st.subheader("❄️ Top productos Congelados/Express")

            df_cong = df_p[df_p["Es_Congelado"]].copy()
            if df_cong.empty:
                st.info("No hay productos Congelados/Express en estos archivos.")
            else:
                top_cong = (
                    df_cong.groupby("Producto", as_index=False)
                           .agg(Cantidad=("Cantidad_num", "sum"))
                           .sort_values("Cantidad", ascending=False)
                           .head(top_n)
                )
                fig_cong = px.bar(top_cong, x="Cantidad", y="Producto", orientation="h", title="Top Congelados/Express")
                st.plotly_chart(fig_cong, use_container_width=True)

            st.divider()