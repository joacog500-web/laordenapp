"""
Genera el reporte comparativo semanal o mensual de ventas y producción de La Orden.

Uso:
    python generar_reporte.py --tipo semanal
    python generar_reporte.py --tipo mensual

Convención de archivos (ver reportes/README.md):
    reportes/data/semanal/ventas/YYYY-MM-DD_YYYY-MM-DD.xlsx
    reportes/data/semanal/produccion/YYYY-MM-DD_YYYY-MM-DD.xlsx
    reportes/data/mensual/ventas/YYYY-MM-DD_YYYY-MM-DD.xlsx
    reportes/data/mensual/produccion/YYYY-MM-DD_YYYY-MM-DD.xlsx

El nombre del archivo es el rango de fechas cubierto por ese export de Trazal
(inicio_fin). El script no mira fechas dentro del Excel: confía en el nombre
del archivo para saber a qué período corresponde.

Salida: escribe un HTML en reportes/output/ultimo_reporte_<tipo>.html y también
lo imprime por stdout entre marcadores ---HTML_START--- / ---HTML_END--- para
que quien invoque este script pueda extraerlo y enviarlo por mail.
"""
import argparse
import os
import re
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


# ---------------------------------
# Utils (adaptado de laorden.py, sin dependencia de streamlit)
# ---------------------------------
def _parse_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def _extract_first_number(x) -> float:
    if pd.isna(x):
        return np.nan
    s = str(x)
    m = re.search(r"(-?\d+(?:[\.,]\d+)?)", s)
    if not m:
        return np.nan
    return float(m.group(1).replace(",", "."))


def _normalize_str(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)


def fmt_num(n, nd=0):
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    if nd == 0:
        return f"{n:,.0f}".replace(",", ".")
    return f"{n:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(p):
    if p is None or (isinstance(p, float) and pd.isna(p)):
        return "—"
    signo = "+" if p >= 0 else ""
    return f"{signo}{p:,.1f}%".replace(".", ",")


def pct_delta(cur, prev):
    if prev in (0, None) or (isinstance(prev, float) and pd.isna(prev)):
        return None
    return (cur - prev) / prev * 100


# ---------------------------------
# Loaders (misma lógica que el dashboard)
# ---------------------------------
def load_sales_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    expected = [
        "Expedicion", "Cliente", "Producto", "Presentacion", "Marca",
        "Unidades", "Cantidad", "Lote", "Vencimiento",
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"[{path}] Faltan columnas: {missing}")

    for c in ["Cliente", "Producto", "Presentacion", "Marca"]:
        df[c] = _normalize_str(df[c])

    df["Cantidad_num"] = df["Cantidad"].apply(_extract_first_number)
    df["Unidades"] = pd.to_numeric(df["Unidades"], errors="coerce")
    return df


def load_production_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]

    col_lut = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for src, dst in [
        ("producto", "Producto"), ("cantidad", "Cantidad"), ("total", "Total"),
        ("marca", "Marca"), ("presentacion", "Presentacion"),
        ("presentación", "Presentacion"), ("lote", "Lote"), ("vencimiento", "Vencimiento"),
    ]:
        if src in col_lut:
            rename[col_lut[src]] = dst
    df = df.rename(columns=rename)

    if "Producto" not in df.columns:
        raise ValueError(f"[{path}] Falta la columna 'Producto'")
    if "Total" not in df.columns and "Cantidad" not in df.columns:
        raise ValueError(f"[{path}] Falta la columna 'Total' o 'Cantidad'")

    df["Producto"] = _normalize_str(df["Producto"])
    base_col = "Total" if "Total" in df.columns else "Cantidad"
    df["Total_num"] = df[base_col].apply(_extract_first_number).fillna(0)

    prod_txt = df["Producto"].fillna("").str.lower()
    pres_txt = (
        df["Presentacion"].fillna("").astype(str).str.lower()
        if "Presentacion" in df.columns else pd.Series("", index=df.index)
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
    return df


# ---------------------------------
# Localización de archivos por rango de fechas en el nombre
# ---------------------------------
def list_period_files(folder):
    files = []
    if not os.path.isdir(folder):
        return files
    for fname in os.listdir(folder):
        if not fname.lower().endswith((".xlsx", ".xls")):
            continue
        stem = fname.rsplit(".", 1)[0]
        parts = stem.split("_")
        if len(parts) != 2:
            continue
        try:
            start = date.fromisoformat(parts[0])
            end = date.fromisoformat(parts[1])
        except ValueError:
            continue
        files.append({"start": start, "end": end, "path": os.path.join(folder, fname), "fname": fname})
    return sorted(files, key=lambda f: f["start"])


def pick_current(files, hoy):
    # el archivo cuyo fin sea el más reciente que ya haya cerrado (<= hoy)
    candidatos = [f for f in files if f["end"] <= hoy]
    if not candidatos:
        return None
    return candidatos[-1]


def week_ordinal_in_month(files, target_start):
    same_month = sorted(
        [f for f in files if (f["start"].year, f["start"].month) == (target_start.year, target_start.month)],
        key=lambda f: f["start"],
    )
    for idx, f in enumerate(same_month, start=1):
        if f["start"] == target_start:
            return idx
    return None


def prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def find_comparison_weekly(files, current):
    ordinal = week_ordinal_in_month(files, current["start"])
    if ordinal is None:
        return None
    py, pm = prev_month(current["start"].year, current["start"].month)
    same_month = sorted(
        [f for f in files if (f["start"].year, f["start"].month) == (py, pm)],
        key=lambda f: f["start"],
    )
    if len(same_month) >= ordinal:
        return same_month[ordinal - 1]
    return None


def find_comparison_monthly(files, current):
    py, pm = prev_month(current["start"].year, current["start"].month)
    for f in files:
        if (f["start"].year, f["start"].month) == (py, pm):
            return f
    return None


# ---------------------------------
# Métricas
# ---------------------------------
def metricas_ventas(df):
    return {
        "total_unidades": float(df["Cantidad_num"].sum()),
        "total_cajas": float(df["Unidades"].sum()),
        "clientes": int(df["Cliente"].nunique()),
        "productos": int(df["Producto"].nunique()),
        "top_clientes": (
            df.groupby("Cliente")["Cantidad_num"].sum().sort_values(ascending=False).head(5)
        ),
        "top_productos": (
            df.groupby("Producto")["Cantidad_num"].sum().sort_values(ascending=False).head(5)
        ),
    }


def metricas_produccion(df):
    por_cat = df.groupby("Categoria")["Total_num"].sum()
    return {
        "total": float(df["Total_num"].sum()),
        "ensamble": float(por_cat.get("Ensamble", 0.0)),
        "express": float(por_cat.get("Express", 0.0)),
        "emp": float(por_cat.get("Emp. Tucumanas/Salteñas", 0.0)),
        "productos": int(df["Producto"].nunique()),
        "top_productos": (
            df.groupby("Producto")["Total_num"].sum().sort_values(ascending=False).head(5)
        ),
    }


# ---------------------------------
# HTML
# ---------------------------------
def label_periodo(f, ordinal=None):
    ini, fin = f["start"], f["end"]
    txt = f"{ini.strftime('%d/%m/%Y')} al {fin.strftime('%d/%m/%Y')}"
    if ordinal:
        txt = f"Semana {ordinal} de {MESES[ini.month - 1]} {ini.year} ({txt})"
    return txt


def kpi_row(nombre, cur, prev, nd=0):
    delta_abs = None if prev is None else cur - prev
    delta_pct = None if prev is None else pct_delta(cur, prev)
    return f"""
    <tr>
      <td style="padding:6px 10px;border-bottom:1px solid #eee;">{nombre}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;">{fmt_num(cur, nd)}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#666;">{fmt_num(prev, nd) if prev is not None else '—'}</td>
      <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:{'#1a7f37' if (delta_abs or 0) >= 0 else '#c0342c'};">{fmt_pct(delta_pct) if delta_pct is not None else '—'}</td>
    </tr>"""


def top_list_html(titulo, serie_cur, serie_prev=None):
    filas = ""
    for nombre, valor in serie_cur.items():
        prev_val = None
        if serie_prev is not None and nombre in serie_prev.index:
            prev_val = float(serie_prev[nombre])
        delta_pct = pct_delta(valor, prev_val) if prev_val is not None else None
        filas += f"""
        <tr>
          <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;">{nombre}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{fmt_num(valor)}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;text-align:right;color:#888;">{fmt_pct(delta_pct) if delta_pct is not None else '—'}</td>
        </tr>"""
    return f"""
    <h3 style="margin:18px 0 6px;font-size:15px;">{titulo}</h3>
    <table style="border-collapse:collapse;width:100%;max-width:480px;font-size:13px;">
      <tr><th style="text-align:left;padding:4px 8px;">Nombre</th><th style="text-align:right;padding:4px 8px;">Cantidad</th><th style="text-align:right;padding:4px 8px;">vs. anterior</th></tr>
      {filas}
    </table>"""


def render_html(tipo, periodo_actual_label, periodo_prev_label, mv, mv_prev, mp, mp_prev, nota=None):
    titulo = "Reporte semanal" if tipo == "semanal" else "Reporte mensual"
    comparativo_titulo = periodo_prev_label or "sin datos de comparación"

    nota_html = f'<p style="color:#a15c00;background:#fff8e6;padding:8px 12px;border-radius:6px;">{nota}</p>' if nota else ""

    ventas_kpis = ""
    produccion_kpis = ""
    top_clientes_html = ""
    top_prod_ventas_html = ""
    top_prod_prod_html = ""

    if mv is not None:
        ventas_kpis = f"""
        <table style="border-collapse:collapse;width:100%;max-width:560px;font-size:13px;">
          <tr><th style="text-align:left;padding:6px 10px;">Ventas</th><th style="text-align:right;padding:6px 10px;">Actual</th><th style="text-align:right;padding:6px 10px;">Anterior</th><th style="text-align:right;padding:6px 10px;">Var. %</th></tr>
          {kpi_row("Unidades vendidas", mv["total_unidades"], mv_prev["total_unidades"] if mv_prev else None)}
          {kpi_row("Cajas / packs", mv["total_cajas"], mv_prev["total_cajas"] if mv_prev else None, nd=2)}
          {kpi_row("Clientes activos", mv["clientes"], mv_prev["clientes"] if mv_prev else None)}
          {kpi_row("Productos distintos", mv["productos"], mv_prev["productos"] if mv_prev else None)}
        </table>"""
        top_clientes_html = top_list_html(
            "Top clientes", mv["top_clientes"], mv_prev["top_clientes"] if mv_prev else None
        )
        top_prod_ventas_html = top_list_html(
            "Top productos vendidos", mv["top_productos"], mv_prev["top_productos"] if mv_prev else None
        )

    if mp is not None:
        produccion_kpis = f"""
        <table style="border-collapse:collapse;width:100%;max-width:560px;font-size:13px;">
          <tr><th style="text-align:left;padding:6px 10px;">Producción</th><th style="text-align:right;padding:6px 10px;">Actual</th><th style="text-align:right;padding:6px 10px;">Anterior</th><th style="text-align:right;padding:6px 10px;">Var. %</th></tr>
          {kpi_row("Total producido", mp["total"], mp_prev["total"] if mp_prev else None)}
          {kpi_row("Ensamble", mp["ensamble"], mp_prev["ensamble"] if mp_prev else None)}
          {kpi_row("Express", mp["express"], mp_prev["express"] if mp_prev else None)}
          {kpi_row("Emp. Tucumanas/Salteñas", mp["emp"], mp_prev["emp"] if mp_prev else None)}
          {kpi_row("Productos distintos", mp["productos"], mp_prev["productos"] if mp_prev else None)}
        </table>"""
        top_prod_prod_html = top_list_html(
            "Top productos producidos", mp["top_productos"], mp_prev["top_productos"] if mp_prev else None
        )

    return f"""<!doctype html>
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:640px;margin:0 auto;">
<h2 style="margin-bottom:2px;">📊 La Orden — {titulo}</h2>
<p style="color:#555;margin-top:0;">Período actual: <b>{periodo_actual_label}</b><br/>Comparado con: <b>{comparativo_titulo}</b></p>
{nota_html}
<h3 style="margin:18px 0 6px;">💰 Ventas</h3>
{ventas_kpis or '<p>No se subió archivo de ventas para este período.</p>'}
{top_clientes_html}
{top_prod_ventas_html}
<h3 style="margin:24px 0 6px;">🏭 Producción</h3>
{produccion_kpis or '<p>No se subió archivo de producción para este período.</p>'}
{top_prod_prod_html}
<p style="margin-top:24px;color:#999;font-size:12px;">Generado automáticamente a partir de los archivos en reportes/data/{tipo}/.</p>
</body></html>"""


# ---------------------------------
# Main
# ---------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", choices=["semanal", "mensual"], required=True)
    args = parser.parse_args()

    hoy = date.today()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ventas_files = list_period_files(os.path.join(DATA_DIR, args.tipo, "ventas"))
    prod_files = list_period_files(os.path.join(DATA_DIR, args.tipo, "produccion"))

    cur_ventas = pick_current(ventas_files, hoy)
    cur_prod = pick_current(prod_files, hoy)

    if cur_ventas is None and cur_prod is None:
        print(f"No hay archivos de {args.tipo} para procesar en reportes/data/{args.tipo}/.", file=sys.stderr)
        sys.exit(1)

    nota = None
    mv = mv_prev = mp = mp_prev = None
    periodo_actual_label = None
    periodo_prev_label = None

    if cur_ventas is not None:
        df_v = load_sales_data(cur_ventas["path"])
        mv = metricas_ventas(df_v)
        if args.tipo == "semanal":
            ordinal = week_ordinal_in_month(ventas_files, cur_ventas["start"])
            periodo_actual_label = label_periodo(cur_ventas, ordinal)
            cmp_ventas = find_comparison_weekly(ventas_files, cur_ventas)
        else:
            periodo_actual_label = f"{MESES[cur_ventas['start'].month - 1]} {cur_ventas['start'].year}"
            cmp_ventas = find_comparison_monthly(ventas_files, cur_ventas)
        if cmp_ventas is not None:
            df_v_prev = load_sales_data(cmp_ventas["path"])
            mv_prev = metricas_ventas(df_v_prev)
            periodo_prev_label = (
                label_periodo(cmp_ventas, week_ordinal_in_month(ventas_files, cmp_ventas["start"]))
                if args.tipo == "semanal"
                else f"{MESES[cmp_ventas['start'].month - 1]} {cmp_ventas['start'].year}"
            )

    if cur_prod is not None:
        df_p = load_production_data(cur_prod["path"])
        mp = metricas_produccion(df_p)
        if args.tipo == "semanal":
            ordinal_p = week_ordinal_in_month(prod_files, cur_prod["start"])
            if periodo_actual_label is None:
                periodo_actual_label = label_periodo(cur_prod, ordinal_p)
            cmp_prod = find_comparison_weekly(prod_files, cur_prod)
        else:
            if periodo_actual_label is None:
                periodo_actual_label = f"{MESES[cur_prod['start'].month - 1]} {cur_prod['start'].year}"
            cmp_prod = find_comparison_monthly(prod_files, cur_prod)
        if cmp_prod is not None:
            df_p_prev = load_production_data(cmp_prod["path"])
            mp_prev = metricas_produccion(df_p_prev)
            if periodo_prev_label is None:
                periodo_prev_label = (
                    label_periodo(cmp_prod, week_ordinal_in_month(prod_files, cmp_prod["start"]))
                    if args.tipo == "semanal"
                    else f"{MESES[cmp_prod['start'].month - 1]} {cmp_prod['start'].year}"
                )

    if periodo_prev_label is None:
        nota = "No se encontró un período equivalente anterior para comparar todavía (puede ser normal si recién estás empezando a cargar históricos)."

    html = render_html(args.tipo, periodo_actual_label, periodo_prev_label, mv, mv_prev, mp, mp_prev, nota)

    out_path = os.path.join(OUTPUT_DIR, f"ultimo_reporte_{args.tipo}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Reporte generado en: {out_path}")
    print("---HTML_START---")
    print(html)
    print("---HTML_END---")


if __name__ == "__main__":
    main()
